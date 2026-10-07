#!/usr/bin/env python3
"""Évaluation de la chaîne de récupération sur le jeu de questions annoté.

Mesure, pour chaque configuration (vectoriel, lexical, hybride, hybride+rerank) :
- recall@k pour k ∈ {1, 3, 5, 10} — proportion de questions dont au moins un chunk
  pertinent figure dans le top-k
- MRR — moyenne des inverses du rang du premier chunk pertinent
- latence médiane et p95 (hors chargement initial des modèles)

Les questions hors-corpus (chunks_pertinents vide) sont exclues des métriques de recherche :
elles mesurent l'abstention, qui relève de la couche génération (sprint 2).

Usage :
    python evaluation/evaluer.py                       # les quatre configurations
    python evaluation/evaluer.py --config hybride_rerank
    python evaluation/evaluer.py --etiquette avant_correction_tsvector
"""

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from src.config import parametres
from src.recherche.pipeline import CONFIGURATIONS, rechercher

DOSSIER = Path(__file__).resolve().parent
FICHIER_QUESTIONS = DOSSIER / "questions.jsonl"
DOSSIER_RESULTATS = DOSSIER / "resultats"

VALEURS_K = (1, 3, 5, 10)


def charger_questions() -> list[dict]:
    if not FICHIER_QUESTIONS.exists():
        print(f"Jeu de questions absent : {FICHIER_QUESTIONS}")
        print("Le constituer d'abord — voir evaluation/README.md")
        sys.exit(1)

    questions = []
    with FICHIER_QUESTIONS.open(encoding="utf-8") as fichier:
        for numero, ligne in enumerate(fichier, start=1):
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                entree = json.loads(ligne)
            except json.JSONDecodeError as erreur:
                sys.exit(f"JSON invalide ligne {numero} : {erreur}")
            for champ in ("id", "question", "chunks_pertinents", "type"):
                if champ not in entree:
                    sys.exit(f"Champ « {champ} » manquant ligne {numero} ({entree.get('id', '?')})")
            # null signifie « pas encore annotée » : l'évaluer reviendrait à compter un échec
            # de récupération là où c'est la référence qui manque.
            if entree["chunks_pertinents"] is None:
                sys.exit(
                    f"Question {entree['id']} non annotée (chunks_pertinents à null).\n"
                    "Compléter l'annotation : python scripts/annoter.py"
                )
            questions.append(entree)
    return questions


def _rechercher_resilient(
    connexion: psycopg.Connection, question: str, configuration: str, top_k: int
):
    """Recherche en retentant une fois sur perte de connexion.

    Une évaluation de la configuration bge dure plus d'une heure et demie sur CPU. Si la
    machine s'endort, Docker redémarre le conteneur PostgreSQL et la connexion meurt avec
    un `AdminShutdown` — toute l'évaluation est perdue à la dernière question. Le coût d'une
    reconnexion est négligeable devant celui d'un run perdu.

    Retourne (réponse, nouvelle_connexion) : l'appelant doit adopter la connexion retournée,
    l'ancienne pouvant avoir été remplacée.
    """
    try:
        return rechercher(connexion, question, configuration, top_k=top_k), connexion
    except psycopg.OperationalError as erreur:
        print(f"  connexion perdue ({erreur.__class__.__name__}), reconnexion…")
        try:
            connexion.close()
        except psycopg.Error:
            pass
        nouvelle = psycopg.connect(parametres.dsn)
        return rechercher(nouvelle, question, configuration, top_k=top_k), nouvelle


def evaluer_configuration(
    connexion: psycopg.Connection, questions: list[dict], configuration: str
) -> tuple[dict, psycopg.Connection]:
    """Évalue une configuration sur les questions dans-corpus.

    Retourne le rapport et la connexion à utiliser ensuite : elle peut avoir été rétablie
    en cours de route.
    """
    dans_corpus = [q for q in questions if q["chunks_pertinents"]]

    rangs_premiers: list[int | None] = []  # rang du premier chunk pertinent, None si absent
    latences: list[float] = []
    details: list[dict] = []

    for question in dans_corpus:
        pertinents = set(question["chunks_pertinents"])
        reponse, connexion = _rechercher_resilient(
            connexion, question["question"], configuration, max(VALEURS_K)
        )
        latences.append(reponse.latence_ms)

        rang_premier = next(
            (p.rang for p in reponse.passages if p.chunk_id in pertinents), None
        )
        rangs_premiers.append(rang_premier)
        details.append(
            {
                "id": question["id"],
                "type": question["type"],
                "rang_premier_pertinent": rang_premier,
                "chunks_retournes": [p.chunk_id for p in reponse.passages],
                "latence_ms": round(reponse.latence_ms, 1),
            }
        )

    nb = len(dans_corpus)
    recalls = {
        f"recall@{k}": round(
            sum(1 for rang in rangs_premiers if rang is not None and rang <= k) / nb, 4
        )
        for k in VALEURS_K
    }
    mrr = round(
        sum(1 / rang for rang in rangs_premiers if rang is not None) / nb, 4
    )
    latences_triees = sorted(latences)

    return {
        "configuration": configuration,
        "nb_questions": nb,
        **recalls,
        "mrr": mrr,
        "latence_mediane_ms": round(statistics.median(latences_triees), 1),
        "latence_p95_ms": round(latences_triees[int(len(latences_triees) * 0.95)], 1),
        "details": details,
    }, connexion


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--config", choices=CONFIGURATIONS,
                           help="n'évaluer qu'une configuration")
    analyseur.add_argument("--etiquette", default="",
                           help="suffixe du fichier de résultats, pour tracer les variantes")
    arguments = analyseur.parse_args()

    questions = charger_questions()
    nb_hors_corpus = sum(1 for q in questions if not q["chunks_pertinents"])
    print(f"{len(questions)} questions chargées, dont {nb_hors_corpus} hors-corpus "
          "(exclues des métriques de recherche)")

    configurations = [arguments.config] if arguments.config else list(CONFIGURATIONS)
    rapports = []

    with psycopg.connect(parametres.dsn) as connexion:
        # Amorçage : le premier appel charge les modèles, et ce coût ne doit pas entrer dans
        # les latences mesurées. On n'amorce que les configurations demandées — charger le
        # cross-encoder pèse plus d'une minute, inutile pour une évaluation purement lexicale.
        for configuration in configurations:
            rechercher(connexion, "amorçage des modèles", configuration)

        for configuration in configurations:
            print(f"\n=== {configuration} ===")
            rapport, connexion = evaluer_configuration(connexion, questions, configuration)
            rapports.append(rapport)
            for cle in (*[f"recall@{k}" for k in VALEURS_K], "mrr",
                        "latence_mediane_ms", "latence_p95_ms"):
                print(f"  {cle:20} {rapport[cle]}")

    DOSSIER_RESULTATS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffixe = f"_{arguments.etiquette}" if arguments.etiquette else ""
    sortie = DOSSIER_RESULTATS / f"{horodatage}{suffixe}.json"
    sortie.write_text(
        json.dumps(
            {
                "date": datetime.now().isoformat(timespec="seconds"),
                "nb_questions_total": len(questions),
                "nb_hors_corpus": nb_hors_corpus,
                "parametres": {
                    "modele_embedding": parametres.modele_embedding,
                    "modele_reranker": parametres.modele_reranker,
                    "top_k_candidats": parametres.top_k_candidats,
                    "rrf_k": parametres.rrf_k,
                },
                "rapports": rapports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nrésultats écrits dans {sortie.relative_to(DOSSIER.parent)}")

    # Tableau récapitulatif prêt à coller dans le README.
    if len(rapports) > 1:
        print("\n| Configuration | R@1 | R@3 | R@5 | R@10 | MRR | p50 ms | p95 ms |")
        print("|---|---|---|---|---|---|---|---|")
        for rapport in rapports:
            print(
                f"| {rapport['configuration']} "
                f"| {rapport['recall@1']:.2f} | {rapport['recall@3']:.2f} "
                f"| {rapport['recall@5']:.2f} | {rapport['recall@10']:.2f} "
                f"| {rapport['mrr']:.2f} "
                f"| {rapport['latence_mediane_ms']:.0f} | {rapport['latence_p95_ms']:.0f} |"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
