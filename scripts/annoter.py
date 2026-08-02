#!/usr/bin/env python3
"""Outil d'annotation du jeu d'évaluation.

Affiche pour chaque question les chunks candidats avec leur contenu, et enregistre les
identifiants que l'annotateur juge pertinents. La sauvegarde est incrémentale : on peut
s'arrêter et reprendre sans rien perdre.

Le biais à éviter : n'annoter que ce que la recherche remonte revient à évaluer le système
contre ses propres sorties. Deux commandes servent à s'en prémunir — `r` relance une recherche
avec une formulation différente, `p` liste tous les chunks d'une page lue dans le PDF. Utiliser
au moins l'une des deux dès qu'un doute existe sur l'exhaustivité des candidats.

Convention du fichier `questions.jsonl` :
    "chunks_pertinents": null   → question non encore annotée
    "chunks_pertinents": []     → annotée, hors-corpus (teste l'abstention)
    "chunks_pertinents": [142]  → annotée, chunks pertinents identifiés

Usage :
    python scripts/annoter.py
    python scripts/annoter.py --top-k 15 --depuis q012
    python scripts/annoter.py --etat
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

from src.config import parametres
from src.recherche.pipeline import rechercher

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "evaluation" / "questions.jsonl"

LARGEUR = 78
AIDE = """
Commandes :
  1,3,5   numéros des candidats pertinents (séparés par des virgules)
  0       aucun candidat pertinent — marque la question hors-corpus
  r ...   relancer la recherche avec une autre formulation
  p D N   lister tous les chunks du document D à la page N
  d       afficher les documents et leur identifiant
  v       revoir le contenu complet des candidats
  s       passer cette question sans l'annoter
  q       enregistrer et quitter
  ?       cette aide
"""


def charger() -> list[dict]:
    if not FICHIER.exists():
        print(f"Fichier absent : {FICHIER}")
        print("Le créer d'abord avec les questions rédigées (chunks_pertinents à null).")
        sys.exit(1)
    entrees = []
    with FICHIER.open(encoding="utf-8") as fichier:
        for numero, ligne in enumerate(fichier, start=1):
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                entrees.append(json.loads(ligne))
            except json.JSONDecodeError as erreur:
                sys.exit(f"JSON invalide ligne {numero} : {erreur}")
    return entrees


def enregistrer(entrees: list[dict]) -> None:
    """Réécrit le fichier entier. Appelé après chaque question annotée."""
    with FICHIER.open("w", encoding="utf-8") as fichier:
        for entree in entrees:
            fichier.write(json.dumps(entree, ensure_ascii=False) + "\n")


def afficher_candidats(candidats: list, longueur: int) -> None:
    for numero, passage in enumerate(candidats, start=1):
        print(f"\n─── [{numero}] chunk {passage.chunk_id} — score {passage.score:.3f}")
        print(f"    {passage.titre_document[:66]}")
        print(f"    {passage.section} — p. {passage.page_debut}-{passage.page_fin}")
        contenu = passage.contenu[:longueur].replace("\n", "\n    ")
        suite = "…" if len(passage.contenu) > longueur else ""
        print(f"    {contenu}{suite}")


def afficher_documents(connexion: psycopg.Connection) -> None:
    lignes = connexion.execute(
        "SELECT id, organisme, langue, nb_pages, titre FROM documents ORDER BY id"
    ).fetchall()
    print()
    for ligne in lignes:
        print(f"  {ligne[0]:3}  {ligne[1] or '?':5} {ligne[2] or '?':3} "
              f"{ligne[3] or 0:4}p  {ligne[4][:56]}")


def afficher_chunks_page(connexion: psycopg.Connection, document_id: int, page: int) -> None:
    """Sortie de secours : liste les chunks couvrant une page lue dans le PDF."""
    lignes = connexion.execute(
        """
        SELECT id, section, page_debut, page_fin, contenu
        FROM chunks
        WHERE document_id = %s AND page_debut <= %s AND page_fin >= %s
        ORDER BY page_debut, id
        """,
        (document_id, page, page),
    ).fetchall()

    if not lignes:
        print(f"  Aucun chunk pour le document {document_id} page {page}.")
        return
    for ligne in lignes:
        print(f"\n─── chunk {ligne[0]} — {ligne[1]} — p. {ligne[2]}-{ligne[3]}")
        print("    " + ligne[4][:400].replace("\n", "\n    ") + "…")


def annoter(connexion: psycopg.Connection, entrees: list[dict], arguments) -> None:
    a_faire = [e for e in entrees if e.get("chunks_pertinents") is None]
    if arguments.depuis:
        indices = [i for i, e in enumerate(a_faire) if e["id"] == arguments.depuis]
        if not indices:
            sys.exit(f"Question introuvable parmi les non annotées : {arguments.depuis}")
        a_faire = a_faire[indices[0]:]

    if not a_faire:
        print("Toutes les questions sont annotées.")
        return

    print(f"{len(a_faire)} question(s) à annoter. `?` pour l'aide, `q` pour quitter.")

    for position, entree in enumerate(a_faire, start=1):
        question = entree["question"]
        print("\n" + "=" * LARGEUR)
        print(f"[{position}/{len(a_faire)}] {entree['id']} — type : {entree.get('type', '?')}")
        print(f"  {question}")
        print("=" * LARGEUR)

        # Configuration hybride sans reranking : à l'annotation on cherche du rappel large,
        # pas de la précision. Le reranking écarterait des candidats qu'il faut pouvoir juger.
        resultat = rechercher(connexion, question, "hybride", arguments.top_k)
        candidats = resultat.passages
        afficher_candidats(candidats, arguments.longueur)

        while True:
            try:
                saisie = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nInterrompu — les annotations déjà faites sont enregistrées.")
                return

            if not saisie:
                continue

            if saisie == "?":
                print(AIDE)
            elif saisie == "q":
                print("Enregistré.")
                return
            elif saisie == "s":
                break
            elif saisie == "d":
                afficher_documents(connexion)
            elif saisie == "v":
                afficher_candidats(candidats, 2000)
            elif saisie == "0":
                entree["chunks_pertinents"] = []
                entree["type"] = entree.get("type") or "hors_corpus"
                enregistrer(entrees)
                print("  → hors-corpus (teste l'abstention)")
                break
            elif saisie.startswith("r "):
                reformulation = saisie[2:].strip()
                if reformulation:
                    resultat = rechercher(connexion, reformulation, "hybride", arguments.top_k)
                    candidats = resultat.passages
                    print(f"\n  Recherche : « {reformulation} »")
                    afficher_candidats(candidats, arguments.longueur)
            elif saisie.startswith("p "):
                morceaux = saisie.split()
                if len(morceaux) == 3 and morceaux[1].isdigit() and morceaux[2].isdigit():
                    afficher_chunks_page(connexion, int(morceaux[1]), int(morceaux[2]))
                else:
                    print("  Format attendu : p <document_id> <page>  (voir `d`)")
            else:
                try:
                    numeros = [int(n) for n in saisie.replace(" ", "").split(",") if n]
                except ValueError:
                    print("  Saisie non reconnue. `?` pour l'aide.")
                    continue

                hors_plage = [n for n in numeros if not 1 <= n <= len(candidats)]
                if hors_plage:
                    print(f"  Numéro(s) hors de la liste affichée : {hors_plage}")
                    continue

                chunks = sorted({candidats[n - 1].chunk_id for n in numeros})
                entree["chunks_pertinents"] = chunks
                enregistrer(entrees)
                print(f"  → chunks pertinents : {chunks}")
                break


def afficher_etat(entrees: list[dict]) -> None:
    annotees = [e for e in entrees if e.get("chunks_pertinents") is not None]
    hors_corpus = [e for e in annotees if not e["chunks_pertinents"]]
    par_type: dict[str, int] = {}
    for entree in annotees:
        par_type[entree.get("type", "?")] = par_type.get(entree.get("type", "?"), 0) + 1

    print(f"\n{len(annotees)}/{len(entrees)} questions annotées")
    print(f"  dont hors-corpus : {len(hors_corpus)}")
    print("\n  répartition par type :")
    for type_question, compte in sorted(par_type.items()):
        print(f"    {compte:3}  {type_question}")

    manquants = [e["id"] for e in entrees if e.get("chunks_pertinents") is None]
    if manquants:
        apercu = ", ".join(manquants[:12])
        suite = f" … (+{len(manquants) - 12})" if len(manquants) > 12 else ""
        print(f"\n  restant à annoter : {apercu}{suite}")


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--top-k", type=int, default=12,
                           help="nombre de candidats affichés (défaut : 12)")
    analyseur.add_argument("--longueur", type=int, default=450,
                           help="caractères de contenu affichés par candidat")
    analyseur.add_argument("--depuis", help="reprendre à partir de cet identifiant de question")
    analyseur.add_argument("--etat", action="store_true",
                           help="afficher l'avancement sans rien annoter")
    arguments = analyseur.parse_args()

    entrees = charger()

    if arguments.etat:
        afficher_etat(entrees)
        return 0

    with psycopg.connect(parametres.dsn) as connexion:
        nb_chunks = connexion.execute("SELECT count(*) FROM chunks").fetchone()
        if not nb_chunks or nb_chunks[0] == 0:
            print("Base vide. Lancer d'abord : python -m src.ingestion.indexation")
            return 1
        annoter(connexion, entrees, arguments)

    afficher_etat(charger())
    return 0


if __name__ == "__main__":
    sys.exit(main())
