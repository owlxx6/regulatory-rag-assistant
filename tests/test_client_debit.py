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
