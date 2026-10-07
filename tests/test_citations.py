"""Tests du contrôle programmatique des citations.

C'est le filet de sécurité derrière le prompt : le prompt demande de citer, ce code vérifie
que ça a été fait. Une réponse sans citation valide doit être marquée suspecte.
"""

from src.generation.citations import nettoyer_abstention, verifier
from src.generation.prompts import MARQUEUR_ABSTENTION, PassageSource, formater_passages


def test_reponse_avec_citation_valide():
    resultat = verifier("Le ratio de levier minimal est de 3 % [1].", nb_passages=5)
    assert resultat.numeros_cites == [1]
    assert not resultat.suspecte
    assert resultat.valide


def test_reponse_sans_citation_est_suspecte():
    resultat = verifier("Le ratio de levier minimal est de 3 %.", nb_passages=5)
    assert resultat.suspecte
    assert not resultat.valide


def test_abstention_sans_citation_n_est_pas_suspecte():
    """Une abstention n'a rien à citer — c'est justement l'absence de source qui la motive."""
    reponse = f"{MARQUEUR_ABSTENTION} Les passages ne traitent pas des taux directeurs."
    resultat = verifier(reponse, nb_passages=5)
    assert resultat.abstention
    assert not resultat.suspecte
    assert resultat.valide


def test_citation_hors_plage_est_invalide():
    """Citer [7] quand seuls 5 passages ont été fournis est une source inventée."""
    resultat = verifier("Selon l'article 429 [7], le ratio est de 3 %.", nb_passages=5)
    assert resultat.numeros_invalides == [7]
    assert not resultat.valide


def test_citations_multiples_dedupliquees_et_triees():
    resultat = verifier("Premier point [3]. Deuxième point [1]. Rappel [3].", nb_passages=5)
    assert resultat.numeros_cites == [1, 3]


def test_melange_citations_valides_et_invalides():
    resultat = verifier("Point A [2], point B [9].", nb_passages=5)
    assert resultat.numeros_invalides == [9]
    assert not resultat.suspecte  # [2] est valide, la réponse n'est pas sans source
    assert not resultat.valide  # mais [9] reste une référence inventée


def test_nettoyage_retire_le_marqueur_technique():
    reponse = f"{MARQUEUR_ABSTENTION} Le corpus ne couvre pas ce sujet."
    assert nettoyer_abstention(reponse) == "Le corpus ne couvre pas ce sujet."


def test_reference_de_passage_lisible():
    passage = PassageSource(
        numero=1,
        titre_document="Basel III: the net stable funding ratio",
        section="§12",
        page_debut=7,
        page_fin=7,
        contenu="…",
    )
    assert passage.reference == "Basel III: the net stable funding ratio, §12, p. 7"

    multipage = PassageSource(1, "Titre", "Article 5", 7, 9, "…")
    assert multipage.reference == "Titre, Article 5, p. 7-9"


def test_formatage_numerote_les_passages_pour_la_citation():
    passages = [
        PassageSource(1, "Doc A", "§1", 1, 1, "Contenu A"),
        PassageSource(2, "Doc B", "§2", 2, 2, "Contenu B"),
    ]
    rendu = formater_passages(passages)
    assert rendu.startswith("[1] Doc A, §1, p. 1\nContenu A")
    assert "[2] Doc B, §2, p. 2\nContenu B" in rendu


def test_crochets_pleine_largeur_reconnus():
    """Les modèles gpt-oss citent avec 【1】 ; refuser cette forme fausse la mesure."""
    resultat = verifier("Le coussin est fixé à 2,5 %【1】.", nb_passages=5)
    assert resultat.numeros_cites == [1]
    assert not resultat.suspecte
    assert resultat.valide


def test_crochets_mixtes_dans_une_meme_reponse():
    resultat = verifier("Premier point【2】. Second point [4].", nb_passages=5)
    assert resultat.numeros_cites == [2, 4]


def test_crochet_pleine_largeur_hors_plage_reste_invalide():
    resultat = verifier("Selon la source【9】, le ratio est de 3 %.", nb_passages=5)
    assert resultat.numeros_invalides == [9]
    assert not resultat.valide
