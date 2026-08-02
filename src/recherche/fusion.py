"""Fusion des listes vectorielle et lexicale par Reciprocal Rank Fusion.

RRF ne regarde que les rangs : score(chunk) = Σ 1/(k + rang_i) sur chaque liste où le chunk
apparaît. C'est ce qui la rend robuste — les scores vectoriels (cosinus, borné) et lexicaux
(ts_rank_cd, non borné) ne sont pas commensurables, et toute pondération de scores bruts
exigerait une calibration par corpus. k=60 est la valeur canonique de la littérature ;
elle amortit l'écart entre les premiers rangs sans écraser la queue de liste.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.config import parametres

# Import réservé au typage : la fusion ne manipule que des rangs et des attributs communs,
# elle n'a besoin d'aucune implémentation. L'importer à l'exécution ferait dépendre ce module
# de sentence-transformers et de torch, et le rendrait intestable en intégration continue.
if TYPE_CHECKING:
    from src.recherche import lexicale, vectorielle


@dataclass
class Candidat:
    chunk_id: int
    document_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    score_rrf: float
    rang_vectoriel: int | None  # None si absent de la liste vectorielle
    rang_lexical: int | None
    rang: int  # rang final après fusion


def fusionner(
    resultats_vectoriels: list[vectorielle.Resultat],
    resultats_lexicaux: list[lexicale.Resultat],
    k: int | None = None,
) -> list[Candidat]:
    k = k or parametres.rrf_k

    scores: dict[int, float] = {}
    rangs_vectoriels: dict[int, int] = {}
    rangs_lexicaux: dict[int, int] = {}
    details: dict[int, vectorielle.Resultat | lexicale.Resultat] = {}

    for resultat in resultats_vectoriels:
        scores[resultat.chunk_id] = scores.get(resultat.chunk_id, 0.0) + 1 / (k + resultat.rang)
        rangs_vectoriels[resultat.chunk_id] = resultat.rang
        details[resultat.chunk_id] = resultat

    for resultat in resultats_lexicaux:
        scores[resultat.chunk_id] = scores.get(resultat.chunk_id, 0.0) + 1 / (k + resultat.rang)
        rangs_lexicaux[resultat.chunk_id] = resultat.rang
        details.setdefault(resultat.chunk_id, resultat)

    classement = sorted(scores.items(), key=lambda paire: -paire[1])

    return [
        Candidat(
            chunk_id=chunk_id,
            document_id=details[chunk_id].document_id,
            titre_document=details[chunk_id].titre_document,
            section=details[chunk_id].section,
            page_debut=details[chunk_id].page_debut,
            page_fin=details[chunk_id].page_fin,
            contenu=details[chunk_id].contenu,
            score_rrf=score,
            rang_vectoriel=rangs_vectoriels.get(chunk_id),
            rang_lexical=rangs_lexicaux.get(chunk_id),
            rang=rang,
        )
        for rang, (chunk_id, score) in enumerate(classement, start=1)
    ]
