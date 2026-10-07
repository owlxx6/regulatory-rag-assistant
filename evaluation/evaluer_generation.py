#!/usr/bin/env python3
"""Évaluation de la couche génération : abstention et traçabilité des citations.

Deux critères que la recherche seule ne peut pas mesurer :

- **Abstention.** Sur une question hors-corpus, le système doit déclarer son ignorance. C'est
  le comportement attendu en contexte réglementaire, où une réponse approximative est une
  réponse fausse. On le mesure sur les 15 questions écrites pour n'avoir aucune réponse dans
  le corpus.
- **Citation.** Toute affirmation doit renvoyer à un passage fourni. Le contrôle est
  programmatique : une réponse sans citation reconnaissable est suspecte, et un numéro
  supérieur au nombre de passages transmis est une source inventée.

Le premier compte comme un faux positif de connaissance, le second comme une faute de
traçabilité. Les deux sont rédhibitoires sur un corpus réglementaire.

Usage :
    python evaluation/evaluer_generation.py
    python evaluation/evaluer_generation.py --config hybride --limite 10
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg

from src.config import parametres
from src.generation.citations import nettoyer_abstention, verifier
from src.generation.client import construire_client
from src.generation.prompts import PassageSource
from src.recherche.pipeline import CONFIGURATIONS, rechercher

DOSSIER = Path(__file__).resolve().parent
FICHIER_QUESTIONS = DOSSIER / "questions.jsonl"
DOSSIER_RESULTATS = DOSSIER / "resultats"


def charger_questions() -> list[dict]:
    if not FICHIER_QUESTIONS.exists():
        sys.exit(f"Jeu de questions absent : {FICHIER_QUESTIONS}")
    return [
        json.loads(ligne)
        for ligne in FICHIER_QUESTIONS.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]


def traiter(connexion, client, question: dict, configuration: str) -> dict:
    """Exécute la chaîne complète sur une question et contrôle la réponse produite."""
    depart = time.perf_counter()
    resultat = rechercher(connexion, question["question"], configuration)

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

    if not passages:
        # Aucun passage : l'abstention est le seul comportement correct, et elle est
        # structurelle plutôt que décidée par le modèle.
        return {
            "id": question["id"],
            "type": question["type"],
            "abstention": True,
            "abstention_structurelle": True,
            "citations": [],
            "citations_invalides": [],
            "suspecte": False,
            "latence_ms": round((time.perf_counter() - depart) * 1000, 1),
            "reponse": "",
        }

    reponse = client.generer_complet(question["question"], passages)
    controle = verifier(reponse, nb_passages=len(passages))

    return {
        "id": question["id"],
        "type": question["type"],
        "abstention": controle.abstention,
        "abstention_structurelle": False,
        "citations": controle.numeros_cites,
        "citations_invalides": controle.numeros_invalides,
        "suspecte": controle.suspecte,
        "latence_ms": round((time.perf_counter() - depart) * 1000, 1),
        # Réponse conservée intégralement : tronquer empêche de recalculer les métriques
        # sur un run passé. Un détecteur de citations corrigé après coup doit pouvoir être
        # rejoué sur les réponses déjà obtenues, sans redépenser d'appels API.
        "reponse": nettoyer_abstention(reponse),
    }


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--config", choices=CONFIGURATIONS, default="hybride_rerank_leger")
    analyseur.add_argument("--limite", type=int, default=0,
                           help="n'évaluer que les N premières questions de chaque groupe")
    analyseur.add_argument("--etiquette", default="generation")
    arguments = analyseur.parse_args()

    questions = charger_questions()
    hors_corpus = [q for q in questions if not q["chunks_pertinents"]]
    dans_corpus = [q for q in questions if q["chunks_pertinents"]]
    if arguments.limite:
        hors_corpus = hors_corpus[: arguments.limite]
        dans_corpus = dans_corpus[: arguments.limite]

    print(f"fournisseur {parametres.llm_fournisseur} | modèle {parametres.llm_modele}")
    print(f"{len(dans_corpus)} questions dans-corpus, {len(hors_corpus)} hors-corpus\n")

    client = construire_client()
    details: list[dict] = []

    with psycopg.connect(parametres.dsn) as connexion:
        rechercher(connexion, "amorçage", arguments.config)
        for groupe, libelle in ((hors_corpus, "hors-corpus"), (dans_corpus, "dans-corpus")):
            for index, question in enumerate(groupe, start=1):
                detail = traiter(connexion, client, question, arguments.config)
                details.append(detail)
                marque = "abstention" if detail["abstention"] else (
                    f"cite {detail['citations']}" if detail["citations"] else "SANS CITATION"
                )
                print(f"  [{libelle} {index}/{len(groupe)}] {question['id']} — {marque}")

    # --- métriques ---
    hc = [d for d in details if d["type"] == "hors_corpus"]
    dc = [d for d in details if d["type"] != "hors_corpus"]

    abstentions_correctes = sum(1 for d in hc if d["abstention"])
    taux_abstention = abstentions_correctes / len(hc) if hc else 0.0

    # Une abstention sur question dans-corpus n'est pas une faute de citation : le système
    # a refusé de répondre plutôt que d'inventer. On la compte séparément.
    repondues = [d for d in dc if not d["abstention"]]
    avec_citation = sum(1 for d in repondues if d["citations"] and not d["citations_invalides"])
    taux_citation = avec_citation / len(repondues) if repondues else 0.0

    faux_positifs = [d["id"] for d in hc if not d["abstention"]]
    sans_citation = [d["id"] for d in repondues if not d["citations"]]
    citations_inventees = [d["id"] for d in repondues if d["citations_invalides"]]
    latences = sorted(d["latence_ms"] for d in details)

    print(f"\n{'=' * 64}")
    print(f"abstention correcte hors-corpus   {abstentions_correctes}/{len(hc)} "
          f"= {taux_abstention:.2f}   (seuil 0,90)")
    print(f"citation valide sur réponses      {avec_citation}/{len(repondues)} "
          f"= {taux_citation:.2f}   (seuil 1,00)")
    print(f"abstentions sur questions dans-corpus : {len(dc) - len(repondues)}/{len(dc)}")
    print(f"latence bout en bout  p50 {statistics.median(latences):.0f} ms  "
          f"p95 {latences[int(len(latences) * 0.95)]:.0f} ms")
    if faux_positifs:
        print(f"\nhors-corpus SANS abstention ({len(faux_positifs)}) : {', '.join(faux_positifs)}")
    if sans_citation:
        print(f"réponses sans citation ({len(sans_citation)}) : {', '.join(sans_citation)}")
    if citations_inventees:
        print(f"citations hors plage ({len(citations_inventees)}) : "
              f"{', '.join(citations_inventees)}")

    DOSSIER_RESULTATS.mkdir(exist_ok=True)
    sortie = DOSSIER_RESULTATS / (
        f"{datetime.now():%Y%m%d_%H%M%S}_{arguments.etiquette}.json"
    )
    sortie.write_text(
        json.dumps(
            {
                "date": datetime.now().isoformat(timespec="seconds"),
                "configuration_recherche": arguments.config,
                "fournisseur": parametres.llm_fournisseur,
                "modele": parametres.llm_modele,
                "taux_abstention_correcte": round(taux_abstention, 4),
                "taux_citation_valide": round(taux_citation, 4),
                "nb_hors_corpus": len(hc),
                "nb_dans_corpus": len(dc),
                "latence_mediane_ms": round(statistics.median(latences), 1),
                "details": details,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nrésultats écrits dans {sortie.relative_to(DOSSIER.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
