"""Reranking des candidats fusionnés par cross-encoder.

Le bi-encodeur (e5) encode question et passage séparément : rapide, mais aveugle aux
interactions fines entre les deux textes. Le cross-encoder lit la paire (question, passage)
d'un seul tenant et produit un score de pertinence bien plus discriminant. Trop lent pour
parcourir tout le corpus, il ne voit que les 30 candidats déjà fusionnés — c'est l'étape
au plus fort gain mesurable de la chaîne, et la plus coûteuse en latence sur CPU.
"""

from dataclasses import dataclass
from functools import lru_cache

from sentence_transformers import CrossEncoder

from src.config import parametres
from src.recherche.fusion import Candidat


@dataclass
class Resultat:
    chunk_id: int
    document_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    score_reranker: float
    rang: int


@lru_cache(maxsize=2)
def _modele(nom: str) -> CrossEncoder:
    """Un cache par modèle : l'évaluation compare deux rerankers dans le même processus."""
    return CrossEncoder(nom)


def reranker(
    question: str,
    candidats: list[Candidat],
    top_k: int | None = None,
    modele: str | None = None,
) -> list[Resultat]:
    """Reclasse les candidats et n'en conserve que les meilleurs (top_k_final = 5)."""
    top_k = top_k or parametres.top_k_final
    if not candidats:
        return []

    paires = [(question, candidat.contenu) for candidat in candidats]
    scores = _modele(modele or parametres.modele_reranker).predict(paires)

    classement = sorted(zip(candidats, scores, strict=True), key=lambda paire: -float(paire[1]))

    return [
        Resultat(
            chunk_id=candidat.chunk_id,
            document_id=candidat.document_id,
            titre_document=candidat.titre_document,
            section=candidat.section,
            page_debut=candidat.page_debut,
            page_fin=candidat.page_fin,
            contenu=candidat.contenu,
            score_reranker=float(score),
            rang=rang,
        )
        for rang, (candidat, score) in enumerate(classement[:top_k], start=1)
    ]
