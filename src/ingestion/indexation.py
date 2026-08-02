"""Indexation du corpus : extraction → découpage → embeddings → base.

Idempotente : un document dont le hash SHA-256 est déjà en base est ignoré. Relancer le script
après un ajout au corpus n'ingère que les nouveautés ; le retrait d'un document de la base se
fait à la main, jamais automatiquement (règle du projet : tout historiser, ne rien supprimer).

Le modèle e5 impose son protocole : chaque passage est encodé préfixé de « passage: », chaque
question le sera de « query: ». L'oubli de ces préfixes est silencieux — aucun message d'erreur,
juste un recall dégradé — d'où leur centralisation ici et dans src/recherche/vectorielle.py.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from src.config import parametres
from src.ingestion.decoupage import Chunk, decouper
from src.ingestion.extraction import extraire

RACINE = Path(__file__).resolve().parent.parent.parent
MANIFESTE = RACINE / "data" / "manifeste.json"

PREFIXE_PASSAGE = "passage: "

# Taille des lots d'encodage. Sur CPU, des lots plus grands n'accélèrent pas et
# gonflent la mémoire.
TAILLE_LOT = 16


def _hash_fichier(chemin: Path) -> str:
    condensat = hashlib.sha256()
    with chemin.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1 << 20), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


def _document_deja_indexe(connexion: psycopg.Connection, hash_fichier: str) -> bool:
    resultat = connexion.execute(
        "SELECT 1 FROM documents WHERE hash_fichier = %s", (hash_fichier,)
    ).fetchone()
    return resultat is not None


def _inserer_document(connexion: psycopg.Connection, entree: dict, hash_fichier: str) -> int:
    date_pub = entree.get("date_pub")
    ligne = connexion.execute(
        """
        INSERT INTO documents
               (titre, source_url, organisme, langue, date_pub, nb_pages, hash_fichier)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            entree["titre"],
            entree["source_url"],
            entree["organisme"],
            entree["langue"],
            date.fromisoformat(date_pub) if date_pub else None,
            entree["nb_pages"],
            hash_fichier,
        ),
    ).fetchone()
    assert ligne is not None
    return ligne[0]


def _inserer_chunks(
    connexion: psycopg.Connection,
    document_id: int,
    chunks: list[Chunk],
    modele: SentenceTransformer,
) -> None:
    textes = [PREFIXE_PASSAGE + chunk.contenu for chunk in chunks]
    # normalize_embeddings=True : les vecteurs normalisés rendent la distance cosinus
    # équivalente au produit scalaire, ce qu'attend l'opérateur <=> de pgvector.
    embeddings = modele.encode(
        textes,
        batch_size=TAILLE_LOT,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    with connexion.cursor() as curseur:
        curseur.executemany(
            """
            INSERT INTO chunks
                   (document_id, section, page_debut, page_fin, contenu, nb_tokens, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    document_id,
                    chunk.section,
                    chunk.page_debut,
                    chunk.page_fin,
                    chunk.contenu,
                    chunk.nb_tokens,
                    embedding,
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ],
        )


def indexer_corpus() -> None:
    if not MANIFESTE.exists():
        raise SystemExit("Manifeste absent. Lancer d'abord : python scripts/download_corpus.py")

    entrees = json.loads(MANIFESTE.read_text(encoding="utf-8"))
    print(f"chargement du modèle {parametres.modele_embedding}…")
    modele = SentenceTransformer(parametres.modele_embedding)

    # autocommit=True : sans cela, psycopg ouvre une transaction implicite dès la première
    # requête, et les `transaction()` par document ne sont plus que des savepoints — tout ne
    # serait commité qu'à la fermeture de la connexion. Une interruption au bout d'une heure
    # d'encodage perdrait alors l'intégralité du travail.
    with psycopg.connect(parametres.dsn, autocommit=True) as connexion:
        register_vector(connexion)

        for entree in entrees:
            chemin = parametres.dossier_pdf / entree["nom_fichier"]
            if not chemin.exists():
                print(f"ABSENT   {entree['nom_fichier']} — relancer download_corpus.py")
                continue

            hash_fichier = _hash_fichier(chemin)
            if _document_deja_indexe(connexion, hash_fichier):
                print(f"déjà là  {entree['nom_fichier']}")
                continue

            print(f"ingestion {entree['nom_fichier']}")
            chunks = decouper(extraire(chemin))

            # Un document = une transaction : soit il est entièrement indexé, soit pas du tout.
            # Un échec en cours d'encodage ne laisse jamais un document à moitié présent.
            with connexion.transaction():
                document_id = _inserer_document(connexion, entree, hash_fichier)
                _inserer_chunks(connexion, document_id, chunks, modele)
            print(f"  {len(chunks)} chunks indexés")

        total = connexion.execute("SELECT count(*) FROM chunks").fetchone()
        print(f"\ntotal en base : {total[0] if total else 0} chunks")


if __name__ == "__main__":
    indexer_corpus()
