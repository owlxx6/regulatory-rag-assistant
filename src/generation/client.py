"""Client LLM interchangeable : API Anthropic ou Ollama en local.

L'interface `LLMClient` est ce qui rend la chaîne agnostique du fournisseur. On développe avec
l'API pour aller vite, et on vérifie que tout fonctionne aussi en local — argument décisif pour
les organisations soucieuses de confidentialité, qui ne peuvent pas envoyer des documents
réglementaires internes à un service tiers.

Les deux implémentations diffusent la réponse en flux (streaming) : c'est ce que l'API SSE
consomme, et cela évite de faire attendre l'utilisateur devant un écran vide pendant plusieurs
secondes de génération.
"""

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator

import anthropic
import httpx

from src.config import parametres
from src.generation.prompts import PassageSource, construire_messages

# Suffisant pour une réponse sourcée sur quelques passages. Le prompt contraint la longueur
# bien avant cette limite.
MAX_TOKENS = 2048

# Réessais sur limitation de débit : les paliers gratuits plafonnent les tokens par minute.
MAX_TENTATIVES = 10

# Plafond d'attente entre deux réessais. La limite de débit étant par minute, attendre
# plus longtemps ne sert qu'à perdre du temps sur un compteur mal interprété.
ATTENTE_MAX = 90.0


class LLMClient(ABC):
    """Interface commune. Toute la chaîne en amont ignore quel fournisseur est derrière."""

    @abstractmethod
    def generer(self, question: str, passages: list[PassageSource]) -> Iterator[str]:
        """Diffuse la réponse par fragments de texte."""

    def generer_complet(self, question: str, passages: list[PassageSource]) -> str:
        """Version bloquante, pour l'évaluation et les tests."""
        return "".join(self.generer(question, passages))


class ClientAnthropic(LLMClient):
    def __init__(self, modele: str | None = None, cle_api: str | None = None) -> None:
        self.modele = modele or parametres.llm_modele
        self._client = anthropic.Anthropic(api_key=cle_api or parametres.anthropic_api_key or None)

    def generer(self, question: str, passages: list[PassageSource]) -> Iterator[str]:
        systeme, utilisateur = construire_messages(question, passages)

        # Pas de temperature ni de top_p : les modèles Claude 5 rejettent ces paramètres
        # avec une erreur 400. Le comportement se pilote par le prompt.
        with self._client.messages.stream(
            model=self.modele,
            max_tokens=MAX_TOKENS,
            system=systeme,
            messages=[{"role": "user", "content": utilisateur}],
        ) as flux:
            yield from flux.text_stream


class ClientOllama(LLMClient):
    """Même chaîne, modèle exécuté localement. Aucune donnée ne sort de la machine."""

    def __init__(self, modele: str = "mistral", url: str | None = None) -> None:
        self.modele = modele
        self.url = (url or parametres.ollama_url).rstrip("/")

    def generer(self, question: str, passages: list[PassageSource]) -> Iterator[str]:
        systeme, utilisateur = construire_messages(question, passages)

        with httpx.stream(
            "POST",
            f"{self.url}/api/chat",
            json={
                "model": self.modele,
                "messages": [
                    {"role": "system", "content": systeme},
                    {"role": "user", "content": utilisateur},
                ],
                "stream": True,
            },
            timeout=120.0,
        ) as reponse:
            reponse.raise_for_status()
            for ligne in reponse.iter_lines():
                if not ligne:
                    continue
                fragment = json.loads(ligne)
                contenu = fragment.get("message", {}).get("content", "")
                if contenu:
                    yield contenu


class ClientCompatibleOpenAI(LLMClient):
    """Tout fournisseur exposant l'API de complétion de chat d'OpenAI.

    Une seule implémentation couvre Groq, Mistral, OpenRouter, Together et les autres : ils
    partagent le même contrat HTTP et ne diffèrent que par l'URL de base et le nom du modèle.
    C'est ce qui rend la chaîne réellement agnostique du fournisseur — changer de prestataire
    ne touche que le fichier .env, jamais le code.
    """

    def __init__(
        self,
        modele: str | None = None,
        base_url: str | None = None,
        cle_api: str | None = None,
    ) -> None:
        self.modele = modele or parametres.llm_modele
        self.base_url = (base_url or parametres.llm_base_url).rstrip("/")
        self.cle_api = cle_api or parametres.llm_cle_api
        if not self.base_url:
            raise ValueError("LLM_BASE_URL est requis pour le fournisseur « openai »")

    @staticmethod
    def _duree(brut: str | None) -> float | None:
        """Convertit une durée d'en-tête en secondes : « 500ms », « 43.3s », « 7m12s », « 3 »."""
        if not brut:
            return None
        texte = brut.strip().lower()
        try:
            if texte.endswith("ms"):
                return float(texte[:-2]) / 1000
            if "m" in texte and texte.endswith("s"):  # forme « 7m12s »
                minutes, reste = texte.split("m", 1)
                return float(minutes) * 60 + float(reste.rstrip("s") or 0)
            if texte.endswith("s"):
                return float(texte[:-1])
            return float(texte)
        except ValueError:
            return None

    @classmethod
    def _attente_apres_429(cls, reponse: httpx.Response, tentative: int) -> float:
        """Durée d'attente avant réessai, bornée.

        Deux pièges, tous deux rencontrés en production.

        Le premier est de lire le mauvais compteur. `x-ratelimit-reset-requests` décompte la
        fenêtre horaire des requêtes et peut annoncer dix minutes, alors que la contrainte
        effective est le débit en tokens par minute, qui se recharge en continu — on attendait
        le remplissage du mauvais seau. On retient donc la plus courte des durées annoncées.

        Le second est de ne pas borner. La limite étant par minute, aucune attente utile ne
        dépasse une minute et demie : un plafond transforme une pause de quinze minutes en
        quelques réessais courts. Le repli exponentiel ne sert que si aucun en-tête n'est
        exploitable.
        """
        durees = [
            d
            for d in (
                cls._duree(reponse.headers.get("retry-after")),
                cls._duree(reponse.headers.get("x-ratelimit-reset-tokens")),
            )
            if d is not None and d > 0
        ]
        attente = min(durees) if durees else min(2**tentative, ATTENTE_MAX)
        # Une seconde de marge : revenir exactement à l'instant du rechargement rate un 429
        # de plus par arrondi.
        return min(attente + 1, ATTENTE_MAX)

    def generer(self, question: str, passages: list[PassageSource]) -> Iterator[str]:
        systeme, utilisateur = construire_messages(question, passages)
        corps = {
            "model": self.modele,
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "messages": [
                {"role": "system", "content": systeme},
                {"role": "user", "content": utilisateur},
            ],
        }

        for tentative in range(MAX_TENTATIVES):
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.cle_api}"},
                json=corps,
                timeout=120.0,
            ) as reponse:
                if reponse.status_code == 429 and tentative < MAX_TENTATIVES - 1:
                    reponse.read()  # libère la connexion avant d'attendre
                    attente = self._attente_apres_429(reponse, tentative)
                    print(f"    débit limité, attente de {attente:.0f} s", flush=True)
                    time.sleep(attente)
                    continue

                reponse.raise_for_status()
                for ligne in reponse.iter_lines():
                    # Flux SSE : « data: {json} », et « data: [DONE] » pour clore.
                    if not ligne.startswith("data:"):
                        continue
                    charge = ligne[5:].strip()
                    if charge == "[DONE]":
                        break
                    try:
                        fragment = json.loads(charge)
                    except json.JSONDecodeError:
                        continue
                    choix = fragment.get("choices") or [{}]
                    contenu = choix[0].get("delta", {}).get("content")
                    if contenu:
                        yield contenu
                return


def construire_client(fournisseur: str | None = None) -> LLMClient:
    """Fabrique le client correspondant au fournisseur configuré."""
    fournisseur = (fournisseur or parametres.llm_fournisseur).lower()
    if fournisseur == "anthropic":
        return ClientAnthropic()
    if fournisseur in ("openai", "compatible"):
        return ClientCompatibleOpenAI()
    if fournisseur == "ollama":
        return ClientOllama()
    raise ValueError(
        f"Fournisseur LLM inconnu : {fournisseur} (attendu : anthropic | openai | ollama)"
    )
