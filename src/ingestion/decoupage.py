"""Découpage du texte extrait en chunks alignés sur la structure du document.

Un découpage à taille fixe coupe au milieu d'une phrase et sépare une exigence de sa condition
d'application — dans un texte réglementaire, cela produit des passages littéralement faux.
On repère donc les frontières structurelles (article, paragraphe numéroté, annexe) et on ne
subdivise que les sections trop longues, avec un chevauchement pour ne pas perdre le lien.

Le nombre de tokens est compté avec le tokenizer du modèle d'embedding lui-même : c'est la seule
mesure qui corresponde à la limite réellement subie à l'encodage.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from transformers import AutoTokenizer

from src.config import parametres
from src.ingestion.extraction import DocumentExtrait

# Motifs de frontière, du plus spécifique au plus général. Ils couvrent les trois familles
# présentes dans le corpus : articles (ACPR), sections hiérarchiques (EBA), paragraphes
# numérotés (BIS, qui numérote « 50. », « 87. » en continu sur tout le document).
MOTIFS_FRONTIERE: list[tuple[str, re.Pattern[str]]] = [
    ("article", re.compile(r"^\s*(?:Article|ARTICLE)\s+(\d+[a-z]?)\b", re.IGNORECASE)),
    ("annexe", re.compile(r"^\s*(?:Annexe|Annex)\s+([A-Z0-9]+)\b", re.IGNORECASE)),
    (
        "partie",
        re.compile(
            r"^\s*(?:Chapitre|Chapter|Partie|Part|Section|Titre|Title)\s+([IVXLC]+|\d+)\b",
            re.IGNORECASE,
        ),
    ),
    ("section", re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+\S")),
    ("paragraphe", re.compile(r"^\s*(\d{1,3})\.\s+\S")),
]

# Une frontière ne doit pas être déclenchée par une ligne de tableau ou une référence
# en milieu de phrase : on exige que la ligne soit courte ou commence bien le texte.
LONGUEUR_MAX_TITRE = 200


@dataclass
class Chunk:
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    nb_tokens: int


@dataclass
class _Ligne:
    texte: str
    page: int


@lru_cache(maxsize=2)
def _tokenizer(nom_modele: str):
    """Tokenizer du modèle d'embedding, mis en cache — son chargement coûte quelques secondes."""
    return AutoTokenizer.from_pretrained(nom_modele)


@lru_cache(maxsize=100_000)
def compter_tokens(texte: str) -> int:
    """Nombre de tokens selon le tokenizer du modèle d'embedding.

    Mis en cache : le découpage compte les mêmes lignes plusieurs fois (à l'accumulation, puis
    au calcul du chevauchement), et les lignes vides ou répétées sont nombreuses.
    """
    tokenizer = _tokenizer(parametres.modele_embedding)
    return len(tokenizer.encode(texte, add_special_tokens=False))


def _detecter_frontiere(ligne: str) -> str | None:
    """Retourne le libellé de section si la ligne ouvre une nouvelle unité, sinon None."""
    if len(ligne) > LONGUEUR_MAX_TITRE:
        return None
    for nom, motif in MOTIFS_FRONTIERE:
        correspondance = motif.match(ligne)
        if correspondance:
            reference = correspondance.group(1)
            if nom == "article":
                return f"Article {reference}"
            if nom == "annexe":
                return f"Annexe {reference}"
            if nom == "partie":
                return correspondance.group(0).strip()
            return f"§{reference}"
    return None


def _aplatir(document: DocumentExtrait) -> list[_Ligne]:
    return [
        _Ligne(texte=ligne, page=page.numero)
        for page in document.pages
        for ligne in page.texte.splitlines()
    ]


def _sections_brutes(lignes: list[_Ligne]) -> list[tuple[str, list[_Ligne]]]:
    """Regroupe les lignes en sections délimitées par les frontières structurelles."""
    sections: list[tuple[str, list[_Ligne]]] = []
    titre_courant = "préambule"
    accumulees: list[_Ligne] = []

    for ligne in lignes:
        titre = _detecter_frontiere(ligne.texte)
        if titre is None:
            accumulees.append(ligne)
            continue

        # Un intertitre immédiatement suivi de son sous-titre (« 6.2 NSFR » puis « 6.2.1 … »)
        # ouvrirait une section sans corps, qui produirait un chunk de trois tokens. On ne
        # clôt donc que si la section courante a un contenu propre ; sinon l'intertitre reste
        # en tête et on adopte le titre plus précis, ce qui préserve la hiérarchie dans le texte.
        a_du_contenu = any(suivante.texte.strip() for suivante in accumulees[1:])
        if accumulees and a_du_contenu:
            sections.append((titre_courant, accumulees))
            accumulees = [ligne]
        else:
            accumulees.append(ligne)
        titre_courant = titre

    if accumulees:
        sections.append((titre_courant, accumulees))
    return sections


def _subdiviser(
    titre: str, lignes: list[_Ligne], taille_max: int, chevauchement: int
) -> list[Chunk]:
    """Découpe une section trop longue, en reprenant la fin du chunk précédent.

    Le chevauchement évite qu'une exigence se retrouve séparée de la condition qui la précède
    immédiatement — cas fréquent dans les textes où un seuil chiffré suit sa définition.
    """
    chunks: list[Chunk] = []
    courant: list[_Ligne] = []
    tokens_courant = 0

    def clore() -> None:
        if not courant:
            return
        contenu = "\n".join(ligne.texte for ligne in courant).strip()
        if contenu:
            chunks.append(
                Chunk(
                    section=titre,
                    page_debut=courant[0].page,
                    page_fin=courant[-1].page,
                    contenu=contenu,
                    nb_tokens=compter_tokens(contenu),
                )
            )

    for ligne in lignes:
        tokens_ligne = compter_tokens(ligne.texte) if ligne.texte.strip() else 0

        if tokens_courant + tokens_ligne > taille_max and courant:
            clore()
            # Reprise : on garde les dernières lignes totalisant environ `chevauchement` tokens.
            reprise: list[_Ligne] = []
            total = 0
            for precedente in reversed(courant):
                cout = compter_tokens(precedente.texte) if precedente.texte.strip() else 0
                if total + cout > chevauchement:
                    break
                reprise.insert(0, precedente)
                total += cout
            courant = reprise
            tokens_courant = total

        courant.append(ligne)
        tokens_courant += tokens_ligne

    clore()
    return chunks


def decouper(document: DocumentExtrait) -> list[Chunk]:
    """Produit les chunks d'un document extrait.

    Trois étapes : regroupement par frontière structurelle, subdivision des sections trop
    longues, puis fusion des sections trop courtes. La fusion est nécessaire car une frontière
    isolée (« Article 5 » seul sur sa ligne, suivi d'un renvoi) produirait un chunk de quelques
    mots, inexploitable à la recherche et polluant pour le calcul du recall.
    """
    taille_max = parametres.taille_chunk_max
    taille_min = parametres.taille_chunk_min

    bruts: list[Chunk] = []
    for titre, lignes in _sections_brutes(_aplatir(document)):
        contenu = "\n".join(ligne.texte for ligne in lignes).strip()
        if not contenu:
            continue
        if compter_tokens(contenu) <= taille_max:
            bruts.append(
                Chunk(
                    section=titre,
                    page_debut=lignes[0].page,
                    page_fin=lignes[-1].page,
                    contenu=contenu,
                    nb_tokens=compter_tokens(contenu),
                )
            )
        else:
            bruts.extend(_subdiviser(titre, lignes, taille_max, parametres.chevauchement))

    return _fusionner_courts(bruts, taille_min, taille_max)


def _fusionner_courts(chunks: list[Chunk], taille_min: int, taille_max: int) -> list[Chunk]:
    """Fusionne un chunk trop court avec le suivant, tant que le total reste sous la limite."""
    fusionnes: list[Chunk] = []
    for chunk in chunks:
        if (
            fusionnes
            and fusionnes[-1].nb_tokens < taille_min
            and fusionnes[-1].nb_tokens + chunk.nb_tokens <= taille_max
        ):
            precedent = fusionnes[-1]
            contenu = f"{precedent.contenu}\n{chunk.contenu}"
            fusionnes[-1] = Chunk(
                # On garde le titre du premier : c'est lui qui situe le passage dans le document.
                section=precedent.section,
                page_debut=precedent.page_debut,
                page_fin=chunk.page_fin,
                contenu=contenu,
                nb_tokens=compter_tokens(contenu),
            )
        else:
            fusionnes.append(chunk)
    return fusionnes
