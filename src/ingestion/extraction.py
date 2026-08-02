"""Extraction du texte des PDF, page par page, avec filtrage des en-têtes et pieds répétés.

Les documents réglementaires répètent sur chaque page un bandeau (« Basel Committee on Banking
Supervision », un numéro de page, une date). Conservé, ce bandeau se retrouve dans chaque chunk :
il bruite les embeddings et fait remonter des passages sur des mots qui n'appartiennent pas au
fond du texte. On le détecte statistiquement plutôt que par une liste en dur, pour rester
indépendant de l'organisme émetteur.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz

# Nombre de lignes examinées en haut et en bas de chaque page.
LIGNES_BORDURE = 3

# Une ligne présente sur plus de 60 % des pages, en zone de bordure, est un bandeau.
SEUIL_REPETITION = 0.60

# Les numéros de page varient d'une page à l'autre : on les neutralise avant de comparer,
# sinon « page 12 » et « page 13 » comptent comme deux lignes distinctes.
_CHIFFRES = re.compile(r"\d+")

# Le remplissage d'espaces d'un bandeau varie avec la largeur du texte qu'il accompagne.
_ESPACES = re.compile(r"\s+")


@dataclass
class Page:
    numero: int  # 1-indexé, tel qu'affiché dans le document
    texte: str


@dataclass
class DocumentExtrait:
    chemin: Path
    pages: list[Page]
    bandeaux_filtres: list[str]

    @property
    def nb_pages(self) -> int:
        return len(self.pages)

    @property
    def texte_complet(self) -> str:
        return "\n".join(page.texte for page in self.pages)


def _normaliser(ligne: str) -> str:
    """Forme canonique d'une ligne, pour comparer des bandeaux dont seul le numéro change."""
    return _ESPACES.sub(" ", _CHIFFRES.sub("#", ligne.lower())).strip()


def _bandeaux_du_lot(pages_lignes: list[list[str]]) -> set[str]:
    """Formes normalisées présentes en bordure sur plus de 60 % des pages du lot."""
    nb_pages = len(pages_lignes)
    if nb_pages < 3:  # trop court pour que la statistique ait un sens
        return set()

    occurrences: Counter[str] = Counter()
    for lignes in pages_lignes:
        bordure = lignes[:LIGNES_BORDURE] + lignes[-LIGNES_BORDURE:]
        # set() : une ligne répétée deux fois sur la même page ne compte qu'une fois,
        # on mesure bien « sur combien de pages » et non « combien de fois ».
        for forme in {_normaliser(ligne) for ligne in bordure if ligne.strip()}:
            occurrences[forme] += 1

    seuil = nb_pages * SEUIL_REPETITION
    return {forme for forme, compte in occurrences.items() if compte > seuil}


def _reperer_bandeaux(pages_lignes: list[list[str]]) -> set[str]:
    """Repère les bandeaux, y compris ceux qui alternent entre pages paires et impaires.

    La mise en page recto/verso est la règle dans l'édition réglementaire : le BIS place le
    titre courant sur les pages impaires et le seul numéro sur les paires. Chaque forme
    n'apparaît alors que sur la moitié des pages et passe sous un seuil global de 60 %.
    On mesure donc la répétition séparément sur chaque parité, puis on réunit les résultats.
    """
    impaires = pages_lignes[::2]  # pages 1, 3, 5… en numérotation affichée
    paires = pages_lignes[1::2]
    return _bandeaux_du_lot(impaires) | _bandeaux_du_lot(paires)


def _nettoyer_page(lignes: list[str], bandeaux: set[str]) -> str:
    """Retire les bandeaux, mais seulement en bordure de page.

    Une même formule peut apparaître légitimement au milieu du texte : la restriction aux
    premières et dernières lignes évite de supprimer du contenu utile.
    """
    if not lignes:
        return ""

    debut, fin = 0, len(lignes)

    while debut < fin and (
        not lignes[debut].strip() or _normaliser(lignes[debut]) in bandeaux
    ) and debut < LIGNES_BORDURE:
        debut += 1

    while fin > debut and (
        not lignes[fin - 1].strip() or _normaliser(lignes[fin - 1]) in bandeaux
    ) and (len(lignes) - fin) < LIGNES_BORDURE:
        fin -= 1

    return "\n".join(lignes[debut:fin]).strip()


def extraire(chemin: Path) -> DocumentExtrait:
    """Extrait le texte d'un PDF en conservant la pagination.

    Le numéro de page est indispensable : c'est lui qui permet la citation
    « BIS, Bâle III, Article 12, p. 34 » attendue en sortie.
    """
    with fitz.open(chemin) as pdf:
        # sort=True réordonne les blocs selon leur position : nécessaire sur les documents
        # à deux colonnes, où l'ordre interne du PDF entrelace les colonnes.
        pages_brutes = [page.get_text("text", sort=True) for page in pdf]

    pages_lignes = [texte.splitlines() for texte in pages_brutes]
    bandeaux = _reperer_bandeaux(pages_lignes)

    pages = [
        Page(numero=index, texte=_nettoyer_page(lignes, bandeaux))
        for index, lignes in enumerate(pages_lignes, start=1)
    ]

    return DocumentExtrait(chemin=chemin, pages=pages, bandeaux_filtres=sorted(bandeaux))
