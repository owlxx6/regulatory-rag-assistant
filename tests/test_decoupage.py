"""Tests du découpage structuré.

Les deux propriétés qui comptent : aucun chunk ne dépasse la limite du modèle d'embedding,
et aucun chunk ne se réduit à un intertitre sans corps.
"""

import pytest

from src.config import parametres
from src.ingestion.decoupage import (
    _detecter_frontiere,
    _Ligne,
    _sections_brutes,
    decouper,
)
from src.ingestion.extraction import DocumentExtrait, Page


def _document(*textes_pages: str) -> DocumentExtrait:
    pages = [Page(numero=n, texte=t) for n, t in enumerate(textes_pages, start=1)]
    return DocumentExtrait(chemin=None, pages=pages, bandeaux_filtres=[])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("ligne", "attendu"),
    [
        ("Article 45 - Fonds propres", "Article 45"),
        ("ARTICLE 12", "Article 12"),
        ("Annexe B : tableau des pondérations", "Annexe B"),
        ("4.2.1 Modalités de calcul", "§4.2.1"),
        ("87.     Les banques doivent…", "§87"),
        ("Chapitre 2 — dispositions générales", "Chapitre 2"),
    ],
)
def test_frontieres_reconnues(ligne, attendu):
    assert _detecter_frontiere(ligne) == attendu


def test_ligne_ordinaire_n_est_pas_une_frontiere():
    assert _detecter_frontiere("Les établissements de crédit doivent respecter…") is None


def test_ligne_trop_longue_n_est_pas_une_frontiere():
    """Une référence en milieu de phrase ne doit pas ouvrir une section."""
    ligne = "12. " + "texte " * 100
    assert _detecter_frontiere(ligne) is None


def test_intertitre_sans_corps_ne_cree_pas_de_section_vide():
    """« 6.2 NSFR » suivi immédiatement de « 6.2.1 … » produisait un chunk de trois tokens."""
    lignes = [
        _Ligne("6.2 NSFR", 1),
        _Ligne("6.2.1 Pondérations applicables", 1),
        _Ligne("Le ratio de financement stable net est défini comme suit.", 1),
    ]
    sections = _sections_brutes(lignes)
    # Une seule section : l'intertitre reste en tête du corps de la sous-section.
    assert len(sections) == 1
    titre, contenu = sections[0]
    assert titre == "§6.2.1"
    assert any("6.2 NSFR" in ligne.texte for ligne in contenu)


def test_sections_successives_avec_corps_sont_separees():
    lignes = [
        _Ligne("Article 1", 1),
        _Ligne("Premier contenu.", 1),
        _Ligne("Article 2", 2),
        _Ligne("Second contenu.", 2),
    ]
    sections = _sections_brutes(lignes)
    assert [titre for titre, _ in sections] == ["Article 1", "Article 2"]


def test_aucun_chunk_ne_depasse_la_limite_du_modele():
    texte = "Article 1\n" + "\n".join(
        f"Phrase numéro {i} du corps réglementaire, suffisamment longue pour peser."
        for i in range(400)
    )
    chunks = decouper(_document(texte))
    assert chunks
    assert all(c.nb_tokens <= parametres.taille_chunk_max for c in chunks)


def test_les_pages_sont_conservees_dans_les_chunks():
    chunks = decouper(_document("Article 1\nContenu premier.", "Article 2\nContenu second."))
    assert all(c.page_debut >= 1 for c in chunks)
    assert max(c.page_fin for c in chunks) == 2


def test_document_vide_ne_produit_aucun_chunk():
    assert decouper(_document("", "   ")) == []
