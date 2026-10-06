#!/usr/bin/env python3
"""Analyse un fichier de résultats d'évaluation : ventilation par type et par langue.

Le recall global dit si la récupération fonctionne. Il ne dit pas pourquoi elle échoue.
Ces deux ventilations le disent : l'une isole les types de questions mal servis, l'autre
mesure l'écart entre les passages français et anglais — déterminant sur un corpus bilingue
indexé avec une seule configuration de recherche plein-texte.

Usage :
    python evaluation/analyser.py                              # dernier fichier de résultats
    python evaluation/analyser.py evaluation/resultats/X.json
    python evaluation/analyser.py --k 3
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

from src.config import parametres

DOSSIER = Path(__file__).resolve().parent
QUESTIONS = DOSSIER / "questions.jsonl"


def langue_des_chunks(connexion: psycopg.Connection, chunks: list[int]) -> str:
    """Langue du passage attendu : « fr », « en », ou « mixte » si l'annotation couvre les deux."""
    langues = sorted(
        r[0]
        for r in connexion.execute(
            """
            SELECT DISTINCT d.langue FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id = ANY(%s)
            """,
            (chunks,),
        ).fetchall()
    )
    if len(langues) == 1:
        return langues[0]
    return "mixte"


def ventiler(details: list[dict], cles: dict[str, str], k: int) -> dict[str, tuple[int, int]]:
    compte: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for detail in details:
        cle = cles.get(detail["id"])
        if cle is None:
            continue
        compte[cle][1] += 1
        rang = detail["rang_premier_pertinent"]
        if rang is not None and rang <= k:
            compte[cle][0] += 1
    return {cle: (ok, total) for cle, (ok, total) in compte.items()}


def afficher(titre: str, ventilation: dict[str, tuple[int, int]], k: int) -> None:
    print(f"\n  recall@{k} par {titre} :")
    for cle, (ok, total) in sorted(ventilation.items()):
        if total:
            print(f"    {cle:22} {ok:3}/{total:<3} = {ok / total:.2f}")


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("fichier", nargs="?", help="JSON de résultats ; défaut : le plus récent")
    analyseur.add_argument("--k", type=int, default=5, help="seuil de recall analysé (défaut : 5)")
    arguments = analyseur.parse_args()

    chemin = arguments.fichier
    if not chemin:
        candidats = sorted(glob.glob(str(DOSSIER / "resultats" / "*.json")))
        if not candidats:
            sys.exit("Aucun fichier de résultats. Lancer d'abord evaluation/evaluer.py")
        chemin = candidats[-1]

    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    questions = [
        json.loads(ligne)
        for ligne in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
    types = {q["id"]: q["type"] for q in questions}
    annotations = {q["id"]: q["chunks_pertinents"] for q in questions if q["chunks_pertinents"]}

    with psycopg.connect(parametres.dsn) as connexion:
        langues = {
            qid: langue_des_chunks(connexion, chunks) for qid, chunks in annotations.items()
        }

    print(f"fichier : {Path(chemin).name}")
    for rapport in donnees["rapports"]:
        details = rapport["details"]
        print(f"\n{'=' * 62}")
        print(f"{rapport['configuration']} — recall@{arguments.k} global "
              f"{rapport.get(f'recall@{arguments.k}', '—')}")
        afficher("type de question", ventiler(details, types, arguments.k), arguments.k)
        afficher("langue du passage attendu", ventiler(details, langues, arguments.k), arguments.k)

        echecs = [d["id"] for d in details if d["rang_premier_pertinent"] is None]
        if echecs:
            print(f"\n  {len(echecs)} question(s) sans passage pertinent dans le top 10 :")
            print("    " + ", ".join(echecs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
