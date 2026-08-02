"""API HTTP : recherche, génération en streaming, journalisation.

Trois routes : `POST /questions` (réponse en flux SSE, sources dans l'événement final),
`GET /sante` (état de la base et des modèles), `GET /documents` (corpus indexé).

Chaque requête est journalisée dans la table `requetes` — c'est ce qui permet d'analyser
les échecs après coup plutôt que de les découvrir en démonstration.
"""

import json
import time
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.config import parametres
from src.generation.citations import nettoyer_abstention, verifier
from src.generation.client import construire_client
from src.generation.prompts import PassageSource
from src.recherche.pipeline import CONFIGURATIONS, Configuration, rechercher

# Chargés au démarrage : le premier appel coûte plusieurs secondes de chargement de modèles,
# on ne veut pas l'infliger à la première requête utilisateur.
_etat: dict = {}


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    _etat["llm"] = construire_client()
    yield
    _etat.clear()


application = FastAPI(
    title="Assistant documentaire réglementaire",
    description="RAG sur corpus BIS / ACPR / EBA, avec citations et abstention",
    version="1.0.0",
    lifespan=cycle_de_vie,
)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    configuration: Configuration = "hybride_rerank"
    top_k: int = Field(default=0, ge=0, le=20, description="0 = valeur configurée")


class Source(BaseModel):
    numero: int
    chunk_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    extrait: str


class Sante(BaseModel):
    statut: Literal["ok", "degrade"]
    base_accessible: bool
    nb_documents: int
    nb_chunks: int
    modele_embedding: str
    modele_reranker: str
    llm_fournisseur: str


class DocumentIndexe(BaseModel):
    id: int
    titre: str
    organisme: str | None
    langue: str | None
    nb_pages: int | None
    nb_chunks: int
    source_url: str | None


def _connexion() -> psycopg.Connection:
    return psycopg.connect(parametres.dsn)


@application.get("/sante", response_model=Sante)
def sante() -> Sante:
    try:
        with _connexion() as connexion:
            ligne = connexion.execute(
                "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)"
            ).fetchone()
        nb_documents, nb_chunks = (ligne or (0, 0))
        base_accessible = True
    except psycopg.Error:
        nb_documents = nb_chunks = 0
        base_accessible = False

    return Sante(
        # Une base vide est un service dégradé, pas un service sain : il répondrait
        # « je ne sais pas » à toutes les questions sans que rien ne semble cassé.
        statut="ok" if base_accessible and nb_chunks > 0 else "degrade",
        base_accessible=base_accessible,
        nb_documents=nb_documents,
        nb_chunks=nb_chunks,
        modele_embedding=parametres.modele_embedding,
        modele_reranker=parametres.modele_reranker,
        llm_fournisseur=parametres.llm_fournisseur,
    )


@application.get("/documents", response_model=list[DocumentIndexe])
def documents() -> list[DocumentIndexe]:
    with _connexion() as connexion:
        lignes = connexion.execute(
            """
            SELECT d.id, d.titre, d.organisme, d.langue, d.nb_pages, count(c.id), d.source_url
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.organisme, d.titre
            """
        ).fetchall()

    return [
        DocumentIndexe(
            id=ligne[0],
            titre=ligne[1],
            organisme=ligne[2],
            langue=ligne[3],
            nb_pages=ligne[4],
            nb_chunks=ligne[5],
            source_url=ligne[6],
        )
        for ligne in lignes
    ]


def _journaliser(
    question: str,
    reponse: str,
    chunks_cites: list[int],
    abstention: bool,
    latence_ms: int,
) -> None:
    """Écrit la requête au journal. Un échec de journalisation ne doit jamais casser la réponse."""
    try:
        with _connexion() as connexion:
            connexion.execute(
                """
                INSERT INTO requetes (question, reponse, chunks_cites, abstention, latence_ms)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (question, reponse, chunks_cites, abstention, latence_ms),
            )
            connexion.commit()
    except psycopg.Error:
        pass


@application.post("/questions")
async def poser_question(entree: Question) -> EventSourceResponse:
    """Répond en flux SSE.

    Trois types d'événements : `sources` (les passages retenus, envoyés d'emblée pour que
    l'interface puisse les afficher pendant la génération), `fragment` (le texte au fil de
    l'eau), `fin` (métadonnées de contrôle : citations, abstention, latences).
    """
    depart = time.perf_counter()

    with _connexion() as connexion:
        resultat = rechercher(
            connexion,
            entree.question,
            entree.configuration,
            entree.top_k or None,
        )

    if not resultat.passages:
        raise HTTPException(status_code=404, detail="Aucun passage trouvé dans le corpus indexé.")

    passages = [
        PassageSource(
            numero=index,
            titre_document=p.titre_document,
            section=p.section,
            page_debut=p.page_debut,
            page_fin=p.page_fin,
            contenu=p.contenu,
        )
        for index, p in enumerate(resultat.passages, start=1)
    ]
    latence_recherche_ms = resultat.latence_ms

    async def evenements():
        sources = [
            Source(
                numero=passage.numero,
                chunk_id=brut.chunk_id,
                titre_document=passage.titre_document,
                section=passage.section,
                page_debut=passage.page_debut,
                page_fin=passage.page_fin,
                extrait=passage.contenu[:300],
            )
            for passage, brut in zip(passages, resultat.passages, strict=True)
        ]
        yield {
            "event": "sources",
            "data": json.dumps([s.model_dump() for s in sources], ensure_ascii=False),
        }

        morceaux: list[str] = []
        for fragment in _etat["llm"].generer(entree.question, passages):
            morceaux.append(fragment)
            yield {"event": "fragment", "data": json.dumps({"texte": fragment})}

        reponse = "".join(morceaux)
        controle = verifier(reponse, nb_passages=len(passages))
        chunks_cites = [resultat.passages[n - 1].chunk_id for n in controle.numeros_cites
                        if 1 <= n <= len(resultat.passages)]
        latence_totale_ms = int((time.perf_counter() - depart) * 1000)

        _journaliser(
            entree.question,
            nettoyer_abstention(reponse),
            chunks_cites,
            controle.abstention,
            latence_totale_ms,
        )

        yield {
            "event": "fin",
            "data": json.dumps(
                {
                    "abstention": controle.abstention,
                    "chunks_cites": chunks_cites,
                    "citations_invalides": controle.numeros_invalides,
                    "suspecte": controle.suspecte,
                    "latence_recherche_ms": round(latence_recherche_ms, 1),
                    "latence_totale_ms": latence_totale_ms,
                    "configuration": resultat.configuration,
                },
                ensure_ascii=False,
            ),
        }

    return EventSourceResponse(evenements())


@application.get("/configurations")
def configurations() -> list[str]:
    """Configurations de recherche disponibles, pour la démonstration comparative."""
    return list(CONFIGURATIONS)
