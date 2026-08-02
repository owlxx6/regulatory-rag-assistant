#!/usr/bin/env python3
"""Contrôle qualité du découpage : statistiques et inspection d'un échantillon aléatoire.

Le cahier des charges pose ce contrôle comme bloquant avant l'indexation. La raison est simple :
un découpage incohérent ne se voit pas dans les métriques de recherche, il se voit dans les
chunks. Corriger après l'indexation coûte un recalcul complet des embeddings.

Usage :
    python scripts/inspecter_chunks.py --stats
    python scripts/inspecter_chunks.py --echantillon 20 --graine 42
    python scripts/inspecter_chunks.py --document bis_d295_nsfr.pdf
"""

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

from src.config import parametres
from src.ingestion.decoupage import Chunk, decouper
from src.ingestion.extraction import extraire

RACINE = Path(__file__).resolve().parent.parent
MANIFESTE = RACINE / "data" / "manifeste.json"


def charger_chunks(filtre_document: str | None) -> list[tuple[str, Chunk]]:
    """Retourne les chunks du corpus, chacun accompagné du nom de son document."""
    if not MANIFESTE.exists():
        print("Manifeste absent. Lancer d'abord : python scripts/download_corpus.py")
        sys.exit(1)

    documents = json.load(MANIFESTE.open(encoding="utf-8"))
    if filtre_document:
        documents = [d for d in documents if d["nom_fichier"] == filtre_document]
        if not documents:
            print(f"Document introuvable dans le manifeste : {filtre_document}")
            sys.exit(1)

    resultat: list[tuple[str, Chunk]] = []
    for entree in documents:
        chemin = parametres.dossier_pdf / entree["nom_fichier"]
        print(f"  découpage de {entree['nom_fichier']}…", file=sys.stderr)
        extrait = extraire(chemin)
        for chunk in decouper(extrait):
            resultat.append((entree["nom_fichier"], chunk))
    return resultat


def afficher_stats(chunks: list[tuple[str, Chunk]]) -> None:
    tailles = sorted(chunk.nb_tokens for _, chunk in chunks)
    if not tailles:
        print("Aucun chunk produit.")
        return

    sous_min = sum(1 for t in tailles if t < parametres.taille_chunk_min)
    sur_max = sum(1 for t in tailles if t > parametres.taille_chunk_max)

    print(f"\n{'=' * 62}")
    print(f"{len(chunks)} chunks au total")
    print(f"  min      {tailles[0]:5} tokens")
    print(f"  médiane  {statistics.median(tailles):5.0f} tokens")
    print(f"  moyenne  {statistics.mean(tailles):5.0f} tokens")
    print(f"  p95      {tailles[int(len(tailles) * 0.95)]:5} tokens")
    print(f"  max      {tailles[-1]:5} tokens")
    print(
        f"\n  sous {parametres.taille_chunk_min} tokens : {sous_min} "
        f"({sous_min / len(tailles):.1%})"
    )
    print(
        f"  au-dessus de {parametres.taille_chunk_max} : {sur_max} "
        f"({sur_max / len(tailles):.1%})"
    )

    par_document: dict[str, int] = {}
    for nom, _ in chunks:
        par_document[nom] = par_document.get(nom, 0) + 1
    print("\n  répartition par document :")
    for nom, compte in sorted(par_document.items(), key=lambda x: -x[1]):
        print(f"    {compte:5}  {nom}")

    sans_section = sum(1 for _, c in chunks if c.section == "préambule")
    print(f"\n  chunks sans section identifiée : {sans_section} ({sans_section / len(chunks):.1%})")


def afficher_echantillon(chunks: list[tuple[str, Chunk]], taille: int, graine: int) -> None:
    """Affiche des chunks au hasard, à graine fixe pour que le contrôle soit rejouable."""
    random.seed(graine)
    echantillon = random.sample(chunks, min(taille, len(chunks)))

    for index, (nom, chunk) in enumerate(echantillon, start=1):
        print(f"\n{'─' * 62}")
        print(
            f"[{index}/{len(echantillon)}] {nom} — {chunk.section} — "
            f"p.{chunk.page_debut}-{chunk.page_fin} — {chunk.nb_tokens} tokens"
        )
        print(f"{'─' * 62}")
        print(chunk.contenu)


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--echantillon", type=int, default=0,
                           help="nombre de chunks à afficher au hasard")
    analyseur.add_argument("--graine", type=int, default=42,
                           help="graine du tirage, pour rejouer le même échantillon")
    analyseur.add_argument("--document", help="restreindre à un seul fichier du corpus")
    analyseur.add_argument("--stats", action="store_true", help="afficher les statistiques")
    arguments = analyseur.parse_args()

    if not arguments.stats and not arguments.echantillon:
        arguments.stats = True

    chunks = charger_chunks(arguments.document)

    if arguments.stats:
        afficher_stats(chunks)
    if arguments.echantillon:
        afficher_echantillon(chunks, arguments.echantillon, arguments.graine)

    return 0


if __name__ == "__main__":
    sys.exit(main())
