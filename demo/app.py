"""Démonstration Streamlit : question, réponse en flux, sources vérifiables.

Volontairement minimale. Ce qu'elle doit montrer en trente secondes à un recruteur :
la réponse cite ses sources, chaque source renvoie au document et à la page, et le système
refuse de répondre quand le corpus ne contient pas l'information.
"""

import json

import httpx
import streamlit as st

URL_API = "http://localhost:8000"

st.set_page_config(page_title="Assistant réglementaire", page_icon="§", layout="wide")

st.title("Assistant documentaire réglementaire")
st.caption("Corpus BIS / ACPR / EBA — réponses sourcées, abstention si le corpus ne couvre pas")

with st.sidebar:
    st.subheader("Configuration de recherche")
    configuration = st.selectbox(
        "Chaîne de récupération",
        ["hybride_rerank", "hybride", "vectoriel", "lexical"],
        help="Permet de comparer les quatre configurations mesurées dans l'évaluation.",
    )

    try:
        sante = httpx.get(f"{URL_API}/sante", timeout=5.0).json()
        couleur = "🟢" if sante["statut"] == "ok" else "🟠"
        st.metric("État", f"{couleur} {sante['statut']}")
        st.write(f"{sante['nb_documents']} documents, {sante['nb_chunks']} chunks")
    except httpx.HTTPError:
        st.error("API injoignable. Lancer : `uvicorn src.api:application`")

question = st.text_input(
    "Question",
    placeholder="Quel est le ratio de levier minimal exigé ?",
)

if question:
    colonne_reponse, colonne_sources = st.columns([3, 2])
    zone_reponse = colonne_reponse.empty()
    sources_affichees = False
    texte = ""

    with httpx.stream(
        "POST",
        f"{URL_API}/questions",
        json={"question": question, "configuration": configuration},
        timeout=120.0,
    ) as flux:
        evenement = None
        for ligne in flux.iter_lines():
            if ligne.startswith("event:"):
                evenement = ligne.removeprefix("event:").strip()
            elif ligne.startswith("data:"):
                donnees = json.loads(ligne.removeprefix("data:").strip())

                if evenement == "sources" and not sources_affichees:
                    colonne_sources.subheader("Sources")
                    for source in donnees:
                        with colonne_sources.expander(
                            f"[{source['numero']}] {source['section']} — "
                            f"p. {source['page_debut']}"
                        ):
                            st.caption(source["titre_document"])
                            st.write(source["extrait"] + "…")
                    sources_affichees = True

                elif evenement == "fragment":
                    texte += donnees["texte"]
                    zone_reponse.markdown(texte)

                elif evenement == "fin":
                    if donnees["abstention"]:
                        colonne_reponse.warning(
                            "Abstention : le corpus indexé ne contient pas la réponse."
                        )
                    elif donnees["suspecte"]:
                        colonne_reponse.error(
                            "Réponse sans citation reconnaissable — marquée suspecte au journal."
                        )
                    if donnees["citations_invalides"]:
                        colonne_reponse.error(
                            f"Références inventées : {donnees['citations_invalides']}"
                        )
                    colonne_reponse.caption(
                        f"Recherche {donnees['latence_recherche_ms']:.0f} ms · "
                        f"total {donnees['latence_totale_ms']} ms · "
                        f"{donnees['configuration']}"
                    )
