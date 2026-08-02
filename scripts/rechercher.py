#!/usr/bin/env python3
"""Recherche en ligne de commande, pour tester la chaîne avant l'API.

Usage :
    python scripts/rechercher.py "Quel est le ratio de levier minimal ?"
    python scripts/rechercher.py --config vectoriel "définition des fonds propres CET1"
    python scripts/rechercher.py --config hybride --top-k 10 "article 45"
"""

import argparse
import sys

import psycopg

from src.config import parametres
from src.recherche.pipeline import CONFIGURATIONS, rechercher


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("question")
    analyseur.add_argument("--config", choices=CONFIGURATIONS, default="hybride_rerank")
    analyseur.add_argument("--top-k", type=int, default=None)
    arguments = analyseur.parse_args()

    with psycopg.connect(parametres.dsn) as connexion:
        reponse = rechercher(connexion, arguments.question, arguments.config, arguments.top_k)

    print(f"\n[{reponse.configuration}] {len(reponse.passages)} passages "
          f"en {reponse.latence_ms:.0f} ms "
          "(premier appel : inclut le chargement des modèles)\n")
    for p in reponse.passages:
        print(f"[{p.rang}] score {p.score:.3f} — {p.titre_document[:58]}")
        print(f"    {p.section} — p.{p.page_debut}-{p.page_fin} — chunk {p.chunk_id}")
        print(f"    {p.contenu[:180].replace(chr(10), ' ')}…\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
