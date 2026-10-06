"""Recherche lexicale plein-texte sur le tsvector, classée par ts_rank_cd.

Complément indispensable du vectoriel : une question contenant une référence exacte
(« article 45 », « CET1 », « LCR ») doit remonter le passage qui contient littéralement
ces termes, ce que la similarité sémantique capture mal.
"""

from dataclasses import dataclass

import psycopg

from src.config import parametres


@dataclass
class Resultat:
    chunk_id: int
    document_id: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str
    score: float  # ts_rank_cd, non borné — comparable entre résultats d'une même requête
    rang: int


def rechercher(
    connexion: psycopg.Connection, question: str, top_k: int | None = None
) -> list[Resultat]:
    """Top-k lexical : les lexèmes de la question sont combinés en OU, puis classés.

    Le OU est essentiel. `websearch_to_tsquery` et `plainto_tsquery` combinent les termes en
    ET : une question de douze mots exigerait les douze lexèmes dans un même chunk, et ne
    ramènerait jamais rien. C'est le comportement attendu d'une barre de recherche où
    l'utilisateur saisit deux ou trois mots-clés, pas d'une question en langage naturel.

    En combinant en OU, tout chunk partageant au moins un lexème devient candidat, et
    `ts_rank_cd` les classe sur la densité et la proximité des termes trouvés — ce qui est
    bien le rôle attendu du volet lexical dans une recherche hybride.

    Les lexèmes sont extraits par `to_tsvector` lui-même, donc la racinisation et les mots
    vides suivent exactement la configuration de la colonne indexée. La configuration
    'french' est celle de la colonne générée — voir docs/decisions.md pour la limite assumée
    sur les documents anglais.
    """
    top_k = top_k or parametres.top_k_candidats

    lignes = connexion.execute(
        """
        SELECT c.id, c.document_id, d.titre, c.section, c.page_debut, c.page_fin,
               c.contenu, ts_rank_cd(c.tsv, requete) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id,
             to_tsquery(
                 'french',
                 array_to_string(
                     tsvector_to_array(to_tsvector('french', %s)), ' | '
                 )
             ) AS requete
        WHERE c.tsv @@ requete
        ORDER BY score DESC
        LIMIT %s
        """,
        (question.strip(), top_k),
    ).fetchall()

    return [
        Resultat(
            chunk_id=ligne[0],
            document_id=ligne[1],
            titre_document=ligne[2],
            section=ligne[3],
            page_debut=ligne[4],
            page_fin=ligne[5],
            contenu=ligne[6],
            score=float(ligne[7]),
            rang=rang,
        )
        for rang, ligne in enumerate(lignes, start=1)
    ]
