"""Recherche vectorielle : question → embedding préfixé « query: » → plus proches voisins HNSW."""

from dataclasses import dataclass
from functools import lru_cache

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from src.config import parametres

PREFIXE_QUESTION = "query: "


@dataclass
class Resultat:
    chunk_id: int
    document_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    score: float  # similarité cosinus, 1 = identique
    rang: int  # 1-indexé


@lru_cache(maxsize=1)
def _modele() -> SentenceTransformer:
    """Chargé une seule fois par processus : ~2 Go de poids, plusieurs secondes."""
    return SentenceTransformer(parametres.modele_embedding)


def encoder_question(question: str):
    return _modele().encode(
        PREFIXE_QUESTION + question.strip(),
        normalize_embeddings=True,
    )


def rechercher(
    connexion: psycopg.Connection, question: str, top_k: int | None = None
) -> list[Resultat]:
    """Top-k des chunks les plus proches de la question, par distance cosinus.

    La connexion est fournie par l'appelant : l'API et les scripts d'évaluation gèrent
    eux-mêmes leur cycle de vie de connexion, et l'évaluation enchaîne des dizaines de
    questions sur la même connexion.
    """
    top_k = top_k or parametres.top_k_candidats
    register_vector(connexion)
    embedding = encoder_question(question)

    lignes = connexion.execute(
        """
        SELECT c.id, c.document_id, d.titre, c.section, c.page_debut, c.page_fin,
               c.contenu, 1 - (c.embedding <=> %s) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.embedding <=> %s
        LIMIT %s
        """,
        (embedding, embedding, top_k),
    ).fetchall()

    return [
        Resultat(
            chunk_id=ligne[0],
            document_id=ligne[1],
            titre_document=ligne[2],
            section=ligne[3],
            page_debut=ligne[4],
            page_fin=ligne[5],
            contenu=ligne[6],
            score=float(ligne[7]),
            rang=rang,
        )
        for rang, ligne in enumerate(lignes, start=1)
    ]
