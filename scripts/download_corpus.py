#!/usr/bin/env python3
"""Télécharge le corpus réglementaire depuis les URL officielles.

Les PDF ne sont pas versionnés dans le dépôt : ils sont publics mais leur redistribution
n'a pas lieu d'être. Ce script les récupère à la source.

Usage :
    python scripts/download_corpus.py
    python scripts/download_corpus.py --organisme ACPR --force
    python scripts/download_corpus.py --lister
"""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import httpx

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PDF = RACINE / "data" / "raw"
MANIFESTE_SORTIE = RACINE / "data" / "manifeste.json"

# Certains serveurs (ACPR notamment) rejettent les clients sans user-agent.
ENTETES = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


@dataclass
class Document:
    """Un document du corpus. Le titre provient de la source officielle, pas d'une supposition."""

    nom_fichier: str
    titre: str
    url: str
    organisme: str  # BIS | ACPR | EBA
    langue: str  # en | fr
    theme: str


# Corpus : solvabilité, liquidité et risque de crédit. Toutes les URL ont été vérifiées
# par requête HTTP le 2026-07-31.
CORPUS: list[Document] = [
    # --- BIS / Comité de Bâle : fonds propres et solvabilité ---
    Document(
        "bis_bcbs189_bale3_cadre.pdf",
        "Basel III: A global regulatory framework for more resilient banks and banking systems",
        "https://www.bis.org/publ/bcbs189.pdf",
        "BIS", "en", "solvabilite",
    ),
    Document(
        "bis_d424_bale3_finalisation.pdf",
        "Basel III: Finalising post-crisis reforms",
        "https://www.bis.org/bcbs/publ/d424.pdf",
        "BIS", "en", "solvabilite",
    ),
    Document(
        "bis_d400_pilier3.pdf",
        "Pillar 3 disclosure requirements - consolidated and enhanced framework",
        "https://www.bis.org/bcbs/publ/d400.pdf",
        "BIS", "en", "publication",
    ),
    # --- BIS : liquidité ---
    Document(
        "bis_bcbs238_lcr.pdf",
        "Basel III: The Liquidity Coverage Ratio and liquidity risk monitoring tools",
        "https://www.bis.org/publ/bcbs238.pdf",
        "BIS", "en", "liquidite",
    ),
    Document(
        "bis_d295_nsfr.pdf",
        "Basel III: the net stable funding ratio",
        "https://www.bis.org/bcbs/publ/d295.pdf",
        "BIS", "en", "liquidite",
    ),
    # --- BIS : levier ---
    Document(
        "bis_bcbs270_levier.pdf",
        "Basel III leverage ratio framework and disclosure requirements",
        "https://www.bis.org/publ/bcbs270.pdf",
        "BIS", "en", "levier",
    ),
    Document(
        "bis_d365_levier_revisions.pdf",
        "Revisions to the Basel III leverage ratio framework",
        "https://www.bis.org/bcbs/publ/d365.pdf",
        "BIS", "en", "levier",
    ),
    # --- BIS : risque de marché, opérationnel, supervision ---
    Document(
        "bis_d515_risque_operationnel.pdf",
        "Revisions to the principles for the sound management of operational risk",
        "https://www.bis.org/bcbs/publ/d515.pdf",
        "BIS", "en", "risque_operationnel",
    ),
    # --- EBA : risque de crédit et processus prudentiel ---
    Document(
        "eba_gl_2020_06_octroi_credit.pdf",
        "EBA Guidelines on loan origination and monitoring (EBA/GL/2020/06)",
        "https://www.eba.europa.eu/sites/default/files/document_library/Publications/Guidelines/"
        "2020/Guidelines%20on%20loan%20origination%20and%20monitoring/884283/"
        "EBA%20GL%202020%2006%20Final%20Report%20on%20GL%20on%20loan%20origination%20and%20monitoring.pdf",
        "EBA", "en", "risque_credit",
    ),
    Document(
        "eba_gl_2016_10_icaap_ilaap.pdf",
        "EBA Guidelines on ICAAP and ILAAP information collected for SREP purposes "
        "(EBA/GL/2016/10)",
        "https://www.eba.europa.eu/sites/default/files/documents/10180/1645611/"
        "6fa080b6-059d-4b41-95c7-9c5edb8cba81/"
        "Final%20report%20on%20Guidelines%20on%20ICAAP%20ILAAP%20(EBA-GL-2016-10).pdf",
        "EBA", "en", "processus_prudentiel",
    ),
    # --- ACPR : partie francophone du corpus ---
    Document(
        "acpr_notice_2024_ratios_prudentiels.pdf",
        "Notice 2024 - Modalités de calcul et de publication des ratios prudentiels dans le cadre "
        "de la CRDIV et exigence de MREL",
        "https://acpr.banque-france.fr/system/files/2024-12/20241230_Notice_CRD4_clean.pdf",
        "ACPR", "fr", "solvabilite",
    ),
]

# Documents vérifiés accessibles mais écartés du corpus. Conservés ici pour la traçabilité
# du périmètre : un corpus se justifie autant par ce qu'il exclut que par ce qu'il contient.
ECARTES: list[tuple[str, str]] = [
    (
        "https://acpr.banque-france.fr/system/files/2024-12/20230711_notice_2023_clean.pdf",
        "Notice ACPR 2023 (128 p) — millésime précédent de la notice 2024 déjà retenue. Deux "
        "versions du même texte annuel produisent des chunks quasi identiques, des citations "
        "contradictoires et des faux positifs à l'évaluation.",
    ),
    (
        "https://www.bis.org/bcbs/publ/d457.pdf",
        "Minimum capital requirements for market risk (136 p) — le risque de marché sort du "
        "périmètre retenu (solvabilité, liquidité, levier, crédit).",
    ),
    (
        "https://www.bis.org/bcbs/publ/d573.pdf",
        "Core Principles for effective banking supervision (81 p) — principes de supervision "
        "généraux, peu de dispositions chiffrées exploitables en questions factuelles.",
    ),
    (
        "https://www.eba.europa.eu/sites/default/files/document_library/Publications/Guidelines/"
        "2022/EBA-GL-2022-14%20GL%20on%20IRRBB%20and%20CSRBB/1041754/"
        "Guidelines%20on%20IRRBB%20and%20CSRBB.pdf",
        "EBA Guidelines on IRRBB and CSRBB (91 p) — risque de taux du portefeuille bancaire, "
        "en marge du périmètre.",
    ),
    (
        "https://www.bis.org/bcbs/publ/d380.pdf",
        "RCAP - Assessment of Basel III risk-based capital regulations, Korea — évaluation "
        "pays, sans portée normative pour le corpus.",
    ),
]


@dataclass
class Resultat:
    """Issue du traitement d'un document."""

    document: Document
    statut: str  # telecharge | deja_present | echec
    nb_pages: int = 0
    taille_octets: int = 0
    hash_fichier: str = ""
    erreur: str = ""
    metadonnees: dict = field(default_factory=dict)


def calculer_hash(chemin: Path) -> str:
    """SHA-256 du fichier, utilisé comme clé d'idempotence à l'ingestion."""
    condensat = hashlib.sha256()
    with chemin.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1 << 20), b""):
            condensat.update(bloc)
    return condensat.hexdigest()


def inspecter_pdf(chemin: Path) -> tuple[int, dict]:
    """Retourne le nombre de pages et les métadonnées du PDF.

    Sert aussi de contrôle d'intégrité : un PDF tronqué ou une page d'erreur HTML
    déguisée en .pdf échoue ici plutôt qu'au moment de l'ingestion.
    """
    with fitz.open(chemin) as pdf:
        return pdf.page_count, dict(pdf.metadata or {})


def telecharger(client: httpx.Client, document: Document, forcer: bool) -> Resultat:
    destination = DOSSIER_PDF / document.nom_fichier

    if destination.exists() and not forcer:
        try:
            nb_pages, meta = inspecter_pdf(destination)
        except Exception as erreur:  # fichier présent mais illisible : on retélécharge
            print(f"  fichier existant illisible ({erreur}), nouveau téléchargement")
        else:
            return Resultat(
                document, "deja_present", nb_pages,
                destination.stat().st_size, calculer_hash(destination), metadonnees=meta,
            )

    try:
        reponse = client.get(document.url)
        reponse.raise_for_status()
    except httpx.HTTPError as erreur:
        # Un document indisponible ne doit pas interrompre le lot : l'ACPR renvoie
        # par exemple un 403 sur certaines notices récentes.
        return Resultat(document, "echec", erreur=str(erreur))

    contenu = reponse.content
    if not contenu.startswith(b"%PDF"):
        return Resultat(
            document, "echec",
            erreur=f"réponse non-PDF ({reponse.headers.get('content-type', 'type inconnu')})",
        )

    destination.write_bytes(contenu)

    try:
        nb_pages, meta = inspecter_pdf(destination)
    except Exception as erreur:
        destination.unlink(missing_ok=True)
        return Resultat(document, "echec", erreur=f"PDF illisible : {erreur}")

    return Resultat(
        document, "telecharge", nb_pages,
        len(contenu), calculer_hash(destination), metadonnees=meta,
    )


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--organisme", choices=["BIS", "ACPR", "EBA"],
                           help="ne traiter que les documents de cet organisme")
    analyseur.add_argument("--force", action="store_true",
                           help="retélécharger même si le fichier est déjà présent")
    analyseur.add_argument("--lister", action="store_true",
                           help="afficher le corpus sans rien télécharger")
    analyseur.add_argument("--timeout", type=float, default=60.0,
                           help="délai maximal par document, en secondes (défaut : 60)")
    arguments = analyseur.parse_args()

    documents = CORPUS
    if arguments.organisme:
        documents = [d for d in CORPUS if d.organisme == arguments.organisme]

    if arguments.lister:
        for document in documents:
            print(f"[{document.organisme:4} {document.langue}] {document.titre}")
        print(f"\n{len(documents)} documents")
        return 0

    DOSSIER_PDF.mkdir(parents=True, exist_ok=True)
    resultats: list[Resultat] = []

    with httpx.Client(headers=ENTETES, timeout=arguments.timeout, follow_redirects=True) as client:
        for index, document in enumerate(documents, start=1):
            print(f"[{index}/{len(documents)}] {document.nom_fichier}")
            resultat = telecharger(client, document, arguments.force)
            resultats.append(resultat)

            if resultat.statut == "echec":
                print(f"  ÉCHEC — {resultat.erreur}")
            else:
                mention = "déjà présent" if resultat.statut == "deja_present" else "téléchargé"
                taille_mo = resultat.taille_octets / 1_048_576
                print(f"  {mention} — {resultat.nb_pages} pages, {taille_mo:.1f} Mo")

    reussis = [r for r in resultats if r.statut != "echec"]
    echecs = [r for r in resultats if r.statut == "echec"]
    total_pages = sum(r.nb_pages for r in reussis)

    manifeste = [
        {
            "nom_fichier": r.document.nom_fichier,
            "titre": r.document.titre,
            "source_url": r.document.url,
            "organisme": r.document.organisme,
            "langue": r.document.langue,
            "theme": r.document.theme,
            "nb_pages": r.nb_pages,
            "hash_fichier": r.hash_fichier,
            "metadonnees_pdf": r.metadonnees,
        }
        for r in reussis
    ]
    MANIFESTE_SORTIE.write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n{'=' * 60}")
    print(f"{len(reussis)}/{len(documents)} documents disponibles, {total_pages} pages au total")
    repartition: dict[str, int] = {}
    for r in reussis:
        repartition[r.document.langue] = repartition.get(r.document.langue, 0) + r.nb_pages
    for langue, pages in sorted(repartition.items()):
        print(f"  {langue} : {pages} pages ({pages / total_pages:.0%})")
    print(f"manifeste écrit dans {MANIFESTE_SORTIE.relative_to(RACINE)}")

    if echecs:
        print(f"\n{len(echecs)} échec(s) :")
        for r in echecs:
            print(f"  - {r.document.nom_fichier} : {r.erreur}")

    # Le corpus visé est de 300 à 800 pages. Au-delà, l'ingestion et l'annotation
    # s'allongent sans bénéfice pour la démonstration.
    if total_pages > 800:
        print(f"\nAvertissement : {total_pages} pages, au-dessus de la cible de 800.")
    elif total_pages < 300:
        print(f"\nAvertissement : {total_pages} pages, en dessous de la cible de 300.")

    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
