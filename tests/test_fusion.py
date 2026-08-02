"""Tests de la fusion RRF.

La fusion est la pièce qui fait cohabiter deux classements incommensurables : un cosinus borné
à [0,1] et un `ts_rank_cd` non borné. Elle ne regarde que les rangs, jamais les scores — ces
tests vérifient précisément cette propriété, car c'est elle qui justifie le choix de RRF plutôt
qu'une pondération de scores bruts.

Les résultats d'entrée sont des objets factices : la fusion ne dépend d'aucune implémentation
de recherche, seulement de la forme des résultats.
"""

from dataclasses import dataclass

from src.recherche.fusion import fusionner


@dataclass
class ResultatFactice:
    chunk_id: int
    rang: int
    score: float = 0.0
    document_id: int = 1
    titre_document: str = "Document de test"
    section: str = "§1"
    page_debut: int = 1
    page_fin: int = 1
    contenu: str = "contenu de test"


def _liste(paires: list[tuple[int, int]]) -> list[ResultatFactice]:
    """Construit une liste de résultats à partir de couples (chunk_id, rang)."""
    return [ResultatFactice(chunk_id=cid, rang=rang) for cid, rang in paires]


def test_chunk_present_dans_les_deux_listes_passe_devant():
    """Le cœur de RRF : l'accord entre les deux recherches vaut mieux qu'un bon rang isolé."""
    vectoriels = _liste([(10, 1), (20, 2)])
    lexicaux = _liste([(20, 1), (30, 2)])

    candidats = fusionner(vectoriels, lexicaux)

    # 20 est deuxième chez l'un et premier chez l'autre ; 10 est premier mais absent de l'autre.
    assert candidats[0].chunk_id == 20
    assert candidats[0].rang_vectoriel == 2
    assert candidats[0].rang_lexical == 1


def test_score_rrf_est_la_somme_des_inverses_de_rang():
    vectoriels = _liste([(10, 1)])
    lexicaux = _liste([(10, 3)])

    candidat = fusionner(vectoriels, lexicaux, k=60)[0]

    assert candidat.score_rrf == 1 / 61 + 1 / 63


def test_scores_bruts_ignores():
    """Un score vectoriel écrasant ne doit rien changer : seul le rang compte."""
    faible = [ResultatFactice(chunk_id=10, rang=2, score=0.01)]
    fort = [ResultatFactice(chunk_id=20, rang=1, score=999.0)]

    par_rang = fusionner(faible, [], k=60)[0].score_rrf
    par_rang_meilleur = fusionner(fort, [], k=60)[0].score_rrf

    assert par_rang == 1 / 62
    assert par_rang_meilleur == 1 / 61


def test_chunk_dans_une_seule_liste_conserve_un_rang_nul_dans_l_autre():
    candidats = fusionner(_liste([(10, 1)]), _liste([(20, 1)]))

    par_id = {c.chunk_id: c for c in candidats}
    assert par_id[10].rang_lexical is None
    assert par_id[20].rang_vectoriel is None


def test_rangs_finaux_contigus_et_ordonnes():
    candidats = fusionner(_liste([(10, 1), (20, 2), (30, 3)]), _liste([(30, 1)]))

    assert [c.rang for c in candidats] == [1, 2, 3]
    scores = [c.score_rrf for c in candidats]
    assert scores == sorted(scores, reverse=True)


def test_listes_vides():
    assert fusionner([], []) == []


def test_une_seule_liste_preserve_l_ordre():
    candidats = fusionner(_liste([(10, 1), (20, 2), (30, 3)]), [])
    assert [c.chunk_id for c in candidats] == [10, 20, 30]


def test_k_plus_petit_creuse_l_ecart_entre_les_premiers_rangs():
    """k amortit l'écart entre têtes de liste ; le réduire rend la fusion plus élitiste."""
    vectoriels = _liste([(10, 1), (20, 2)])

    ecart_k60 = [c.score_rrf for c in fusionner(vectoriels, [], k=60)]
    ecart_k1 = [c.score_rrf for c in fusionner(vectoriels, [], k=1)]

    assert ecart_k60[0] - ecart_k60[1] < ecart_k1[0] - ecart_k1[1]


def test_metadonnees_reprises_du_resultat_source():
    vectoriels = [
        ResultatFactice(
            chunk_id=42,
            rang=1,
            titre_document="Bâle III",
            section="Article 12",
            page_debut=34,
            page_fin=35,
            contenu="Le ratio de levier minimal est de 3 %.",
        )
    ]

    candidat = fusionner(vectoriels, [])[0]

    assert candidat.titre_document == "Bâle III"
    assert candidat.section == "Article 12"
    assert (candidat.page_debut, candidat.page_fin) == (34, 35)


def test_metadonnees_disponibles_meme_si_seul_le_lexical_a_trouve_le_chunk():
    lexicaux = [ResultatFactice(chunk_id=7, rang=1, titre_document="Notice ACPR")]

    candidat = fusionner([], lexicaux)[0]

    assert candidat.titre_document == "Notice ACPR"
