"""Tests du filtrage des en-têtes et pieds de page.

Le cas central est le bandeau alterné recto/verso : c'est le défaut qui a échappé à la première
version du filtre, parce qu'un titre courant présent une page sur deux n'atteint jamais un seuil
global de 60 %.
"""

from src.ingestion.extraction import (
    LIGNES_BORDURE,
    Page,
    _nettoyer_page,
    _normaliser,
    _reperer_bandeaux,
)


def test_normalisation_neutralise_numeros_et_espaces():
    assert _normaliser("Page 12") == _normaliser("Page 47")
    assert _normaliser("Bâle   III    reforms") == "bâle iii reforms"


def test_bandeau_present_sur_toutes_les_pages_est_repere():
    pages = [["Comité de Bâle", f"corps de la page {n}", f"{n}"] for n in range(1, 11)]
    bandeaux = _reperer_bandeaux(pages)
    assert _normaliser("Comité de Bâle") in bandeaux


def test_bandeau_alterne_recto_verso_est_repere():
    """Titre courant sur les pages impaires, numéro seul sur les paires."""
    pages = []
    for numero in range(1, 21):
        if numero % 2 == 1:
            pages.append([f"contenu {numero}", "Basel III: Finalising post-crisis reforms"])
        else:
            pages.append([f"contenu {numero}", f"{numero}"])

    bandeaux = _reperer_bandeaux(pages)
    assert _normaliser("Basel III: Finalising post-crisis reforms") in bandeaux


def test_ligne_de_contenu_frequente_mais_non_bordure_est_conservee():
    """Une phrase répétée au milieu du texte n'est pas un bandeau."""
    pages = [
        ["en-tête", "a", "b", "phrase récurrente du corps", "c", "d", "pied"]
        for _ in range(10)
    ]
    bandeaux = _reperer_bandeaux(pages)
    assert _normaliser("phrase récurrente du corps") not in bandeaux
    assert _normaliser("en-tête") in bandeaux


def test_document_trop_court_ne_declenche_aucun_filtrage():
    assert _reperer_bandeaux([["a"], ["b"]]) == set()


def test_nettoyage_retire_le_bandeau_sans_toucher_au_corps():
    lignes = ["Comité de Bâle", "premier paragraphe", "second paragraphe", "12"]
    bandeaux = {_normaliser("Comité de Bâle"), _normaliser("12")}
    resultat = _nettoyer_page(lignes, bandeaux)
    assert resultat == "premier paragraphe\nsecond paragraphe"


def test_nettoyage_ne_retire_pas_au_dela_de_la_zone_de_bordure():
    """Un bandeau situé plus loin que LIGNES_BORDURE reste en place : c'est du contenu."""
    corps = [f"paragraphe {i}" for i in range(LIGNES_BORDURE + 2)]
    lignes = [*corps, "Comité de Bâle"]
    resultat = _nettoyer_page(lignes, {_normaliser("Comité de Bâle")})
    assert "Comité de Bâle" not in resultat  # en dernière position, donc en bordure

    lignes_milieu = ["a", "Comité de Bâle", *corps, "z"]
    resultat_milieu = _nettoyer_page(lignes_milieu, {_normaliser("Comité de Bâle")})
    assert "Comité de Bâle" in resultat_milieu


def test_page_conserve_son_numero():
    page = Page(numero=34, texte="contenu")
    assert page.numero == 34
