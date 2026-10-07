"""Vérification programmatique des citations et de l'abstention.

Le prompt demande de citer ; rien ne garantit qu'il soit suivi. On vérifie donc dans le code que
la réponse contient bien au moins une référence [n] valide, et que les numéros cités
correspondent à des passages réellement fournis. Une réponse sans citation est marquée comme
suspecte dans le journal — c'est ce contrôle qui rend les hallucinations détectables plutôt que
de prétendre les supprimer.
"""

import re
from dataclasses import dataclass

from src.generation.prompts import MARQUEUR_ABSTENTION

# Les crochets pleine largeur 【 】 (U+3010/U+3011) sont acceptés au même titre que les
# crochets ASCII : les modèles de la famille gpt-oss les émettent spontanément, et refuser
# cette forme faisait compter comme « sans citation » des réponses correctement sourcées —
# un taux de citation mesuré à 0,81 au lieu de sa valeur réelle.
_CITATION = re.compile(r"[\[【](\d{1,2})[\]】]")


@dataclass
class Verification:
    abstention: bool
    numeros_cites: list[int]
    numeros_invalides: list[int]  # cités mais absents des passages fournis
    suspecte: bool  # ni abstention, ni citation valide

    @property
    def valide(self) -> bool:
        return not self.suspecte and not self.numeros_invalides


def verifier(reponse: str, nb_passages: int) -> Verification:
    """Analyse une réponse générée.

    `nb_passages` est le nombre de passages soumis au modèle : tout numéro cité au-delà est
    une référence inventée, symptôme le plus direct d'une hallucination de source.
    """
    abstention = MARQUEUR_ABSTENTION in reponse

    numeros = [int(n) for n in _CITATION.findall(reponse)]
    cites = sorted(set(numeros))
    invalides = [n for n in cites if n < 1 or n > nb_passages]
    valides = [n for n in cites if 1 <= n <= nb_passages]

    return Verification(
        abstention=abstention,
        numeros_cites=cites,
        numeros_invalides=invalides,
        # Une abstention n'a pas à citer : c'est justement l'absence de source qui la motive.
        suspecte=not abstention and not valides,
    )


def nettoyer_abstention(reponse: str) -> str:
    """Retire le marqueur technique avant affichage à l'utilisateur."""
    return reponse.replace(MARQUEUR_ABSTENTION, "").strip()
