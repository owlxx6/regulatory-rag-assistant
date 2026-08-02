"""Client LLM interchangeable : API Anthropic ou Ollama en local.

L'interface `LLMClient` est ce qui rend la chaîne agnostique du fournisseur. On développe avec
l'API pour aller vite, et on vérifie que tout fonctionne aussi en local — argument décisif pour
les organisations soucieuses de confidentialité, qui ne peuvent pas envoyer des documents
réglementaires internes à un service tiers.

Les deux implémentations diffusent la réponse en flux (streaming) : c'est ce que l'API SSE
consomme, et cela évite de faire attendre l'utilisateur devant un écran vide pendant plusieurs
secondes de génération.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator

import anthropic
import httpx

from src.config import parametres
from src.generation.prompts import PassageSource, construire_messages

# Suffisant pour une réponse sourcée sur quelques passages. Le prompt contraint la longueur
# bien avant cette limite.
MAX_TOKENS = 2048


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
                import json

                fragment = json.loads(ligne)
                contenu = fragment.get("message", {}).get("content", "")
                if contenu:
                    yield contenu


def construire_client(fournisseur: str | None = None) -> LLMClient:
    """Fabrique le client correspondant au fournisseur configuré."""
    fournisseur = (fournisseur or parametres.llm_fournisseur).lower()
    if fournisseur == "anthropic":
        return ClientAnthropic()
    if fournisseur == "ollama":
        return ClientOllama()
    raise ValueError(f"Fournisseur LLM inconnu : {fournisseur} (attendu : anthropic | ollama)")
