"""Tests du prompt de génération et du format des références.

Ce qui est vérifié ici n'est pas le comportement du modèle — il n'est pas appelé — mais le
contrat que le prompt établit avec lui : des passages numérotés de façon contiguë à partir de 1,
une référence lisible par document, et des instructions qui interdisent explicitement le recours
aux connaissances générales. Si la numérotation dérape, les citations renvoient au mauvais
passage et le contrôle de `citations.py` valide des références fausses.
"""

from src.generation.prompts import (
    MARQUEUR_ABSTENTION,
    PassageSource,
    construire_messages,
    formater_passages,
)


def _passage(numero: int, **surcharges) -> PassageSource:
    defauts = {
        "titre_document": "Basel III: Finalising post-crisis reforms",
        "section": "Article 12",
        "page_debut": 34,
        "page_fin": 34,
        "contenu": "Le ratio de levier minimal est de 3 %.",
    }
    return PassageSource(numero=numero, **{**defauts, **surcharges})


def test_reference_page_unique():
    assert _passage(1).reference.endswith("p. 34")


def test_reference_plage_de_pages():
    """Un chunk peut chevaucher deux pages : la citation doit le refléter."""
    assert _passage(1, page_debut=34, page_fin=36).reference.endswith("p. 34-36")


def test_reference_contient_document_et_section():
    reference = _passage(1, titre_document="Notice ACPR 2024", section="§4.1").reference
    assert "Notice ACPR 2024" in reference
    assert "§4.1" in reference


def test_formatage_numerote_chaque_passage():
    rendu = formater_passages([_passage(1), _passage(2), _passage(3)])
    assert "[1]" in rendu
    assert "[2]" in rendu
    assert "[3]" in rendu


def test_formatage_conserve_le_contenu_integral():
    """Tronquer un passage dans le prompt ferait citer une source que le modèle n'a pas lue."""
    contenu = "Une exigence longue. " * 40
    rendu = formater_passages([_passage(1, contenu=contenu)])
    assert contenu.strip() in rendu


def test_messages_contiennent_la_question_et_les_passages():
    systeme, utilisateur = construire_messages(
        "Quel est le ratio de levier minimal ?", [_passage(1)]
    )
    assert "Quel est le ratio de levier minimal ?" in utilisateur
    assert "Le ratio de levier minimal est de 3 %." in utilisateur
    assert systeme


def test_question_nettoyee_des_espaces_superflus():
    _, utilisateur = construire_messages("   Quel est le NSFR ?  \n", [_passage(1)])
    assert "Quel est le NSFR ?" in utilisateur
    assert "   Quel est le NSFR ?" not in utilisateur


def test_systeme_impose_les_quatre_regles():
    systeme, _ = construire_messages("question", [_passage(1)])
    minuscules = systeme.lower()
    assert "exclusivement" in minuscules  # 1. répondre à partir des seuls passages
    assert "[n]" in minuscules  # 2. citer chaque affirmation
    assert MARQUEUR_ABSTENTION in systeme  # 3. déclarer son ignorance
    assert "connaissances générales" in minuscules  # 4. ne rien compléter


def test_systeme_demande_de_repondre_dans_la_langue_de_la_question():
    """Le corpus est bilingue : une question française ne doit pas obtenir une réponse anglaise."""
    systeme, _ = construire_messages("question", [_passage(1)])
    assert "langue de la question" in systeme.lower()


def test_aucun_passage_produit_un_prompt_valide():
    """Cas limite : la génération doit pouvoir s'abstenir plutôt que planter."""
    systeme, utilisateur = construire_messages("question sans source", [])
    assert systeme
    assert "question sans source" in utilisateur
