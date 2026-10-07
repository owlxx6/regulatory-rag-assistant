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

import httpx
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


def calculer_metriques(details: list[dict]) -> dict:
    """Métriques sur les questions traitées jusqu'ici — appelée après chaque question."""
    hc = [d for d in details if d["type"] == "hors_corpus"]
    dc = [d for d in details if d["type"] != "hors_corpus"]

    # Une abstention sur question dans-corpus n'est pas une faute de citation : le système
    # a refusé de répondre plutôt que d'inventer. On la compte séparément.
    repondues = [d for d in dc if not d["abstention"]]
    citees = [d for d in repondues if d["citations"] and not d["citations_invalides"]]
    latences = sorted(d["latence_ms"] for d in details if d.get("latence_ms") is not None)

    return {
        "nb_hors_corpus": len(hc),
        "abstentions_correctes": sum(1 for d in hc if d["abstention"]),
        "taux_abstention_correcte": round(
            sum(1 for d in hc if d["abstention"]) / len(hc), 4) if hc else None,
        "nb_dans_corpus": len(dc),
        "nb_reponses_produites": len(repondues),
        "nb_citations_valides": len(citees),
        "taux_citation_valide": round(len(citees) / len(repondues), 4) if repondues else None,
        "abstentions_dans_corpus": len(dc) - len(repondues),
        "hors_corpus_sans_abstention": [d["id"] for d in hc if not d["abstention"]],
        "reponses_sans_citation": [d["id"] for d in repondues if not d["citations"]],
        "citations_hors_plage": [d["id"] for d in repondues if d["citations_invalides"]],
        "latence_mediane_ms": round(statistics.median(latences), 1) if latences else None,
    }


def ecrire(sortie: Path, details: list[dict], config: str, interruption: str | None) -> None:
    """Réécrit le fichier de résultats en entier.

    Appelée après chaque question : un run interrompu — quota journalier, coupure réseau,
    mise en veille — ne perd jamais plus que la question en cours. Deux runs ont été perdus
    en entier avant cette précaution.
    """
    sortie.write_text(
        json.dumps(
            {
                "date": datetime.now().isoformat(timespec="seconds"),
                "configuration_recherche": config,
                "fournisseur": parametres.llm_fournisseur,
                "modele": parametres.llm_modele,
                "interrompu": interruption,
                "nb_questions_traitees": len(details),
                **calculer_metriques(details),
                "details": details,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--config", choices=CONFIGURATIONS, default="hybride_rerank_leger")
    analyseur.add_argument("--limite", type=int, default=0,
                           help="n'évaluer que les N premières questions de chaque groupe")
    analyseur.add_argument("--etiquette", default="generation")
    analyseur.add_argument(
        "--reprendre", type=Path,
        help="fichier de résultats d'un run interrompu : ses questions sont conservées, "
             "seules les manquantes sont traitées",
    )
    arguments = analyseur.parse_args()

    questions = charger_questions()
    hors_corpus = [q for q in questions if not q["chunks_pertinents"]]
    dans_corpus = [q for q in questions if q["chunks_pertinents"]]
    if arguments.limite:
        hors_corpus = hors_corpus[: arguments.limite]
        dans_corpus = dans_corpus[: arguments.limite]

    details: list[dict] = []
    if arguments.reprendre:
        anterieur = json.loads(arguments.reprendre.read_text(encoding="utf-8"))
        if anterieur.get("modele") != parametres.llm_modele:
            sys.exit(
                f"Reprise refusée : le run antérieur utilisait {anterieur.get('modele')}, "
                f"la configuration actuelle {parametres.llm_modele}. Mélanger deux modèles "
                "dans une même mesure la rendrait ininterprétable."
            )
        details = anterieur["details"]
        print(f"reprise : {len(details)} questions conservées de {arguments.reprendre.name}")

    deja_faites = {d["id"] for d in details}
    print(f"fournisseur {parametres.llm_fournisseur} | modèle {parametres.llm_modele}")
    print(f"{len(dans_corpus)} questions dans-corpus, {len(hors_corpus)} hors-corpus, "
          f"{len(deja_faites)} déjà traitées\n")

    DOSSIER_RESULTATS.mkdir(exist_ok=True)
    sortie = DOSSIER_RESULTATS / f"{datetime.now():%Y%m%d_%H%M%S}_{arguments.etiquette}.json"
    client = construire_client()
    interruption: str | None = None

    with psycopg.connect(parametres.dsn) as connexion:
        rechercher(connexion, "amorçage", arguments.config)
        for groupe, libelle in ((hors_corpus, "hors-corpus"), (dans_corpus, "dans-corpus")):
            for index, question in enumerate(groupe, start=1):
                if question["id"] in deja_faites:
                    continue
                try:
                    detail = traiter(connexion, client, question, arguments.config)
                except httpx.HTTPError as erreur:
                    # HTTPError couvre à la fois les réponses en erreur (quota) et les erreurs
                    # de transport (réseau) qui auraient épuisé les réessais du client.
                    interruption = f"{question['id']} : {erreur.__class__.__name__} — {erreur}"
                    print(f"\n  INTERROMPU sur {interruption[:200]}")
                    break
                details.append(detail)
                ecrire(sortie, details, arguments.config, None)
                marque = "abstention" if detail["abstention"] else (
                    f"cite {detail['citations']}" if detail["citations"] else "SANS CITATION"
                )
                print(f"  [{libelle} {index}/{len(groupe)}] {question['id']} — {marque}",
                      flush=True)
            if interruption:
                break

    ecrire(sortie, details, arguments.config, interruption)
    m = calculer_metriques(details)

    print(f"\n{'=' * 64}")
    if interruption:
        print(f"RUN INTERROMPU — {len(details)} questions traitées, résultats partiels écrits")
        print(f"reprendre avec : --reprendre {sortie.relative_to(DOSSIER.parent)}\n")
    if m["taux_abstention_correcte"] is not None:
        print(f"abstention correcte hors-corpus   "
              f"{m['abstentions_correctes']}/{m['nb_hors_corpus']} "
              f"= {m['taux_abstention_correcte']:.2f}   (seuil 0,90)")
    if m["taux_citation_valide"] is not None:
        print(f"citation valide sur réponses      {m['nb_citations_valides']}/"
              f"{m['nb_reponses_produites']} = {m['taux_citation_valide']:.2f}   (seuil 1,00)")
    print(f"abstentions sur questions dans-corpus : {m['abstentions_dans_corpus']}/"
          f"{m['nb_dans_corpus']}")
    for cle, libelle in (
        ("hors_corpus_sans_abstention", "hors-corpus SANS abstention"),
        ("reponses_sans_citation", "réponses sans citation"),
        ("citations_hors_plage", "citations hors plage"),
    ):
        if m[cle]:
            print(f"{libelle} ({len(m[cle])}) : {', '.join(m[cle])}")
    print(f"\nrésultats écrits dans {sortie.relative_to(DOSSIER.parent)}")
    return 1 if interruption else 0


if __name__ == "__main__":
    sys.exit(main())
