"""Point d'entrée unique de la recherche, décliné en quatre configurations mesurables.

L'évaluation compare : vectoriel seul, lexical seul, hybride (RRF), hybride + reranking.
Les quatre passent par cette fonction — même code, mêmes paramètres, seule la configuration
change. C'est la condition pour que le tableau comparatif du README compare des choses
comparables.
"""

import time
from dataclasses import dataclass
from typing import Literal

import psycopg

from src.config import parametres
from src.recherche import fusion, lexicale, reranking, vectorielle

Configuration = Literal[
    "vectoriel", "lexical", "hybride", "hybride_rerank", "hybride_rerank_leger"
]

# `hybride_rerank_leger` n'est pas une cinquième idée mais la même chaîne avec un cross-encoder
# plus petit : sur CPU, le modèle prescrit dépasse le budget de latence d'un facteur 70, et
# l'écart de qualité entre les deux doit être mesuré plutôt que supposé.
CONFIGURATIONS: tuple[Configuration, ...] = (
    "vectoriel",
    "lexical",
    "hybride",
    "hybride_rerank",
    "hybride_rerank_leger",
)


@dataclass
class Passage:
    """Résultat final, homogène quelle que soit la configuration."""

    chunk_id: int
    document_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    score: float
    rang: int


@dataclass
class Reponse:
    passages: list[Passage]
    configuration: Configuration
    latence_ms: float


def _vers_passages(resultats) -> list[Passage]:
    return [
        Passage(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            titre_document=r.titre_document,
            section=r.section,
            page_debut=r.page_debut,
            page_fin=r.page_fin,
            contenu=r.contenu,
            score=getattr(r, "score", None) or getattr(r, "score_rrf", None)
            or getattr(r, "score_reranker", 0.0),
            rang=r.rang,
        )
        for r in resultats
    ]


def rechercher(
    connexion: psycopg.Connection,
    question: str,
    configuration: Configuration = "hybride_rerank",
    top_k: int | None = None,
) -> Reponse:
    """Exécute la configuration demandée et retourne les passages avec la latence mesurée.

    `top_k` est le nombre de passages retournés (défaut : top_k_final = 5). Les étapes
    intermédiaires travaillent toujours sur top_k_candidats = 30.
    """
    top_k = top_k or parametres.top_k_final
    depart = time.perf_counter()

    if configuration == "vectoriel":
        passages = _vers_passages(vectorielle.rechercher(connexion, question)[:top_k])
    elif configuration == "lexical":
        passages = _vers_passages(lexicale.rechercher(connexion, question)[:top_k])
    elif configuration == "hybride":
        candidats = fusion.fusionner(
            vectorielle.rechercher(connexion, question),
            lexicale.rechercher(connexion, question),
        )
        passages = _vers_passages(candidats[:top_k])
    elif configuration in ("hybride_rerank", "hybride_rerank_leger"):
        modele = (
            parametres.modele_reranker
            if configuration == "hybride_rerank"
            else parametres.modele_reranker_leger
        )
        candidats = fusion.fusionner(
            vectorielle.rechercher(connexion, question),
            lexicale.rechercher(connexion, question),
        )
        passages = _vers_passages(
            reranking.reranker(
                question, candidats[: parametres.top_k_candidats], top_k, modele=modele
            )
        )
    else:
        raise ValueError(f"configuration inconnue : {configuration}")

    latence_ms = (time.perf_counter() - depart) * 1000
    return Reponse(passages=passages, configuration=configuration, latence_ms=latence_ms)
