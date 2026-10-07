"""Tests du calcul d'attente après une réponse 429.

Deux défauts rencontrés en production sont couverts ici : lire le compteur de la fenêtre
horaire des requêtes au lieu de celui du débit en tokens, ce qui faisait attendre quinze
minutes au lieu de quelques secondes ; et ne pas borner l'attente, ce qui transformait un
mauvais en-tête en run bloqué.
"""

import httpx

from src.generation.client import ATTENTE_MAX
from src.generation.client import ClientCompatibleOpenAI as Client


def test_conversion_des_formats_de_duree():
    assert Client._duree("500ms") == 0.5
    assert Client._duree("43.3s") == 43.3
    assert Client._duree("7m12s") == 432.0
    assert Client._duree("3") == 3.0
    assert Client._duree(None) is None
    assert Client._duree("bientôt") is None


def test_retient_la_plus_courte_duree_annoncee():
    """Le compteur de tokens se recharge en continu ; celui des requêtes couvre une heure."""
    reponse = httpx.Response(
        429,
        headers={"retry-after": "60", "x-ratelimit-reset-tokens": "4s"},
    )
    assert Client._attente_apres_429(reponse, 0) == 5.0  # 4 s + 1 s de marge


def test_ignore_le_compteur_de_requetes():
    """x-ratelimit-reset-requests annonçait 10 minutes : il ne doit pas être lu."""
    reponse = httpx.Response(
        429,
        headers={"x-ratelimit-reset-requests": "15m32s", "x-ratelimit-reset-tokens": "2s"},
    )
    assert Client._attente_apres_429(reponse, 0) == 3.0


def test_attente_bornee():
    reponse = httpx.Response(429, headers={"retry-after": "3600"})
    assert Client._attente_apres_429(reponse, 0) == ATTENTE_MAX


def test_repli_exponentiel_sans_entete_exploitable():
    reponse = httpx.Response(429)
    assert Client._attente_apres_429(reponse, 0) == 2.0
    assert Client._attente_apres_429(reponse, 3) == 9.0
    assert Client._attente_apres_429(reponse, 20) == ATTENTE_MAX


def test_duree_nulle_ou_negative_ignoree():
    """Un compteur déjà épuisé ne doit pas produire une attente de zéro seconde."""
    reponse = httpx.Response(429, headers={"x-ratelimit-reset-tokens": "0s"})
    assert Client._attente_apres_429(reponse, 2) == 5.0  # repli : 2**2 + 1


# --- Résilience de la boucle de génération, sans réseau ---------------------------------

import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402

from src.generation import client as module_client  # noqa: E402
from src.generation.prompts import PassageSource  # noqa: E402

PASSAGES = [
    PassageSource(numero=1, titre_document="Doc", section="§1", page_debut=1, page_fin=1,
                  contenu="Le ratio de levier minimal est de 3 %.")
]


_REQUETE = httpx.Request("POST", "https://exemple.test/v1/chat/completions")


def _sse(*fragments: str) -> bytes:
    lignes = [
        "data: " + json.dumps({"choices": [{"delta": {"content": f}}]}) + "\n\n"
        for f in fragments
    ]
    return ("".join(lignes) + "data: [DONE]\n\n").encode()


def _reponse(statut: int, **kwargs) -> httpx.Response:
    """Réponse rattachée à une requête : raise_for_status l'exige."""
    return httpx.Response(statut, request=_REQUETE, **kwargs)


class _FluxCoupe(httpx.SyncByteStream):
    """Flux qui émet un fragment puis perd la connexion."""

    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Le ratio"}}]}\n\n'
        raise httpx.ReadError("connexion perdue en cours de flux")


def _installer(monkeypatch, scenarios: list) -> list:
    """Remplace httpx.stream par une suite de scénarios ; retourne le compteur d'appels."""
    appels: list[int] = []

    @contextmanager
    def faux_stream(*_args, **_kwargs):
        appels.append(1)
        scenario = scenarios.pop(0)
        if isinstance(scenario, Exception):
            raise scenario
        yield scenario

    monkeypatch.setattr(module_client.httpx, "stream", faux_stream)
    monkeypatch.setattr(module_client.time, "sleep", lambda _s: None)
    return appels


def _client() -> Client:
    return Client(modele="test", base_url="https://exemple.test/v1", cle_api="x")


def test_reessai_apres_coupure_reseau(monkeypatch):
    """Un échec DNS transitoire ne doit pas tuer la génération."""
    appels = _installer(monkeypatch, [
        httpx.ConnectError("nodename nor servname provided"),
        _reponse(200, content=_sse("Le ratio est de 3 %", " [1].")),
    ])
    assert _client().generer_complet("question", PASSAGES) == "Le ratio est de 3 % [1]."
    assert len(appels) == 2


def test_pas_de_reessai_apres_emission_partielle(monkeypatch):
    """Relancer après des fragments déjà émis dupliquerait le début de la réponse."""
    appels = _installer(monkeypatch, [
        _reponse(200, stream=_FluxCoupe()),
        _reponse(200, content=_sse("ne doit jamais être lu")),
    ])
    with pytest.raises(httpx.ReadError):
        _client().generer_complet("question", PASSAGES)
    assert len(appels) == 1


def test_reessai_apres_429(monkeypatch):
    appels = _installer(monkeypatch, [
        _reponse(429, headers={"x-ratelimit-reset-tokens": "2s"}),
        _reponse(200, content=_sse("Réponse [1].")),
    ])
    assert _client().generer_complet("question", PASSAGES) == "Réponse [1]."
    assert len(appels) == 2


def test_abandon_apres_epuisement_des_tentatives(monkeypatch):
    scenarios = [httpx.ConnectError("réseau absent")] * module_client.MAX_TENTATIVES
    appels = _installer(monkeypatch, list(scenarios))
    with pytest.raises(httpx.ConnectError):
        _client().generer_complet("question", PASSAGES)
    assert len(appels) == module_client.MAX_TENTATIVES
