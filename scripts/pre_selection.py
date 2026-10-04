#!/usr/bin/env python3
"""Pré-sélection de chunks candidats pour l'annotation, sans passer par le RAG.

L'annotation ne doit pas s'appuyer sur les sorties du système évalué, sinon le recall
mesure la cohérence du système avec lui-même. Ce script n'utilise que deux méthodes
indépendantes : la localisation par page (le champ `indice` de chaque question nomme le
document et la page du passage) et la correspondance littérale de chaîne.

Il ne décide rien : il produit une liste à valider. L'annotation reste humaine.

Usage :
    python scripts/pre_selection.py                    # toutes les questions non annotées
    python scripts/pre_selection.py --question q004
    python scripts/pre_selection.py --extrait 300
"""

import argparse
import json
import re
import sys
from pathlib import Path

import psycopg

from src.config import parametres

RACINE = Path(__file__).resolve().parent.parent
QUESTIONS = RACINE / "evaluation" / "questions.jsonl"

# Correspondance entre les abréviations employées dans le champ `indice` et les
# identifiants de documents en base.
DOCUMENTS: dict[str, int] = {
    "bcbs189": 1,
    "d424": 2,
    "d400": 3,
    "bcbs238": 4,
    "d295": 5,
    "bcbs270": 6,
    "d365": 7,
    "d515": 8,
    "eba gl 2020/06": 9,
    "eba gl 2016/10": 10,
    "acpr": 11,
}

_PAGES = re.compile(r"p\.\s?(\d+)(?:\s?-\s?(\d+))?")
_SECTIONS = re.compile(r"§\s?([\d.]+)")
# Un chiffre suivi d'un pourcentage, avec virgule ou point décimal.
_POURCENTAGES = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")


def documents_cites(indice: str) -> list[int]:
    minuscules = indice.lower()
    return sorted({id_ for cle, id_ in DOCUMENTS.items() if cle in minuscules})


def pages_citees(indice: str) -> list[int]:
    pages: set[int] = set()
    for debut, fin in _PAGES.findall(indice):
        borne_fin = int(fin) if fin else int(debut)
        pages.update(range(int(debut), borne_fin + 1))
    return sorted(pages)


def chunks_par_page(
    connexion: psycopg.Connection, documents: list[int], pages: list[int]
) -> list[tuple]:
    if not documents or not pages:
        return []
    return connexion.execute(
        """
        SELECT id, document_id, section, page_debut, page_fin, contenu
        FROM chunks
        WHERE document_id = ANY(%s)
          -- Le chevauchement doit porter sur UNE MÊME page : deux clauses ANY
          -- indépendantes seraient satisfaites par deux pages différentes et
          -- ramèneraient presque tout le document.
          AND EXISTS (
              SELECT 1 FROM unnest(%s::int[]) AS page
              WHERE page_debut <= page AND page_fin >= page
          )
        ORDER BY document_id, page_debut, id
        """,
        (documents, pages),
    ).fetchall()


def chunks_par_section(
    connexion: psycopg.Connection, documents: list[int], sections: list[str]
) -> list[tuple]:
    if not documents or not sections:
        return []
    motifs = [f"%{s}%" for s in sections]
    return connexion.execute(
        """
        SELECT id, document_id, section, page_debut, page_fin, contenu
        FROM chunks
        WHERE document_id = ANY(%s) AND section ILIKE ANY(%s)
        ORDER BY document_id, page_debut, id
        """,
        (documents, motifs),
    ).fetchall()


def chunks_par_pourcentage(
    connexion: psycopg.Connection,
    documents: list[int],
    motif: re.Pattern[str],
    limite: int = 6,
) -> list[tuple]:
    """Chunks dont le contenu contient littéralement l'un des pourcentages attendus.

    Le filtrage est fait en Python et non en SQL : dans un `LIKE`, le caractère « % » est
    un joker, de sorte qu'un motif « %3%% » signifie « contient le chiffre 3 » et ramène
    presque tout. Filtrer ici garantit aussi que la sélection et l'extrait affiché
    reposent sur exactement le même motif.
    """
    if not documents:
        return []
    lignes = connexion.execute(
        """
        SELECT id, document_id, section, page_debut, page_fin, contenu
        FROM chunks WHERE document_id = ANY(%s)
        ORDER BY document_id, page_debut, id
        """,
        (documents,),
    ).fetchall()

    retenues = [ligne for ligne in lignes if motif.search(" ".join(ligne[5].split()))]
    return retenues[:limite]


def afficher(
    lignes: list[tuple],
    titre: str,
    longueur: int,
    deja_vus: set[int],
    motif: re.Pattern[str] | None = None,
) -> None:
    """Affiche les candidats non encore vus.

    Avec `motif`, l'extrait est centré sur la correspondance au lieu de commencer au début
    du chunk : pour un seuil chiffré, c'est la phrase qui entoure le chiffre qui permet de
    trancher, pas les premiers mots du passage.
    """
    nouvelles = [ligne for ligne in lignes if ligne[0] not in deja_vus]
    if not nouvelles:
        return
    print(f"\n  — {titre} —")
    for id_, doc, section, debut, fin, contenu in nouvelles:
        deja_vus.add(id_)
        aplati = " ".join(contenu.split())
        correspondance = motif.search(aplati) if motif else None
        if correspondance:
            marge = longueur // 2
            depart = max(0, correspondance.start() - marge)
            extrait = ("…" if depart else "") + aplati[depart : depart + longueur]
        else:
            extrait = aplati[:longueur]
        print(f"    chunk {id_:4} | doc {doc:2} | {section:14} | p.{debut}-{fin}")
        print(f"      {extrait}…")


# Sigles de 3 lettres ou plus, chiffres admis en fin (CET1, AT1, NSFR, HQLA, ICAAP, HVCRE).
_SIGLES = re.compile(r"\b([A-Z]{3,}\d?|CET ?1|AT ?1)\b")

# Sigles trop génériques pour servir d'ancre : ils apparaissent partout dans le corpus.
_SIGLES_IGNORES = frozenset({"CRR", "CRD", "ABE", "EBA", "BIS", "ACPR", "RWA", "RWAS", "III"})


def sigles_de(texte: str) -> list[str]:
    trouves = {s.replace(" ", "") for s in _SIGLES.findall(texte)}
    return sorted(trouves - _SIGLES_IGNORES)


def motif_sigles(sigles: list[str]) -> re.Pattern[str]:
    """Motif tolérant l'espace interne (« CET 1 » comme « CET1 ») et insensible à la casse."""
    alternatives = [re.escape(s).replace(r"1", r"\s?1") for s in sigles]
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)


def chunks_par_motif(
    connexion: psycopg.Connection,
    documents: list[int],
    motif: re.Pattern[str],
    limite: int = 8,
) -> list[tuple]:
    """Chunks des documents visés dont le contenu correspond au motif, filtrés en Python."""
    if not documents:
        return []
    lignes = connexion.execute(
        """
        SELECT id, document_id, section, page_debut, page_fin, contenu
        FROM chunks WHERE document_id = ANY(%s)
        ORDER BY document_id, page_debut, id
        """,
        (documents,),
    ).fetchall()
    retenues = [ligne for ligne in lignes if motif.search(" ".join(ligne[5].split()))]
    return retenues[:limite]


def motif_pourcentages(valeurs: list[str]) -> re.Pattern[str]:
    """Motif couvrant les deux écritures décimales : « 4.5% » (BIS) et « 4,5 % » (ACPR)."""
    alternatives = [
        re.escape(valeur).replace(r"\.", "[.,]").replace(",", "[.,]") for valeur in valeurs
    ]
    return re.compile(r"(?<!\d)(?:" + "|".join(alternatives) + r")\s?%")


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--question", help="ne traiter qu'un identifiant de question")
    analyseur.add_argument("--extrait", type=int, default=220,
                           help="longueur de l'extrait affiché (défaut : 220)")
    arguments = analyseur.parse_args()

    entrees = [
        json.loads(ligne)
        for ligne in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
    a_traiter = [e for e in entrees if e.get("chunks_pertinents") is None]
    if arguments.question:
        a_traiter = [e for e in a_traiter if e["id"] == arguments.question]
        if not a_traiter:
            sys.exit(f"Question introuvable parmi les non annotées : {arguments.question}")

    with psycopg.connect(parametres.dsn) as connexion:
        for entree in a_traiter:
            indice = entree.get("indice", "")
            documents = documents_cites(indice)
            pages = pages_citees(indice)
            sections = _SECTIONS.findall(indice)
            pourcentages = _POURCENTAGES.findall(indice)

            print("\n" + "=" * 86)
            print(f"{entree['id']} — {entree['type']}")
            print(f"  {entree['question']}")
            print(f"  indice : {indice or '—'}")
            print(f"  documents visés : {documents or 'aucun repéré'}")

            deja_vus: set[int] = set()
            if pages:
                afficher(chunks_par_page(connexion, documents, pages),
                         f"pages {pages}", arguments.extrait, deja_vus)
            if sections:
                afficher(chunks_par_section(connexion, documents, sections),
                         f"sections {sections}", arguments.extrait, deja_vus)
            if pourcentages:
                motif = motif_pourcentages(pourcentages)
                afficher(
                    chunks_par_pourcentage(connexion, documents, motif),
                    f"pourcentages {pourcentages}",
                    arguments.extrait,
                    deja_vus,
                    motif=motif,
                )

            # Repli quand l'indice ne nomme qu'un document : les sigles de la question
            # servent d'ancre littérale. Efficace sur les questions de définition, dont
            # la réponse contient presque toujours le sigle qu'elles interrogent.
            if not deja_vus:
                sigles = sigles_de(entree["question"])
                if sigles:
                    motif = motif_sigles(sigles)
                    afficher(
                        chunks_par_motif(connexion, documents, motif),
                        f"sigles {sigles}",
                        arguments.extrait,
                        deja_vus,
                        motif=motif,
                    )

            if not deja_vus:
                print("\n  Aucun candidat localisable par l'indice — à chercher dans le PDF,")
                print("  ou via la commande `t <expression>` de scripts/annoter.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
