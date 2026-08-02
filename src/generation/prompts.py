"""Prompts de génération, contraints aux sources.

Quatre règles, dans cet ordre de priorité : répondre exclusivement à partir des passages fournis ;
citer la référence de chaque affirmation ; déclarer explicitement son ignorance si les passages ne
suffisent pas ; ne jamais compléter par des connaissances générales.

Le prompt ne suffit pas : la présence effective d'une citation est vérifiée dans le code
(voir `citations.py`). Un contrôle programmatique vaut mieux qu'une confiance dans le prompt.
"""

from dataclasses import dataclass

MARQUEUR_ABSTENTION = "INFORMATION_ABSENTE_DU_CORPUS"

SYSTEME = f"""Tu es un assistant documentaire sur un corpus réglementaire bancaire (Comité de \
Bâle, ACPR, EBA).

Règles absolues :

1. Réponds EXCLUSIVEMENT à partir des passages fournis ci-dessous. Tu n'as aucune autre source.
2. Cite la référence après chaque affirmation, au format [n] où n est le numéro du passage.
3. Si les passages ne contiennent pas de quoi répondre, réponds exactement \
{MARQUEUR_ABSTENTION} suivi d'une phrase expliquant ce qui manque. N'invente rien, ne devine pas.
4. N'utilise jamais tes connaissances générales pour compléter, nuancer ou contextualiser.

En matière réglementaire, une réponse approximative est une réponse fausse. Une abstention est \
toujours préférable à une extrapolation.

Réponds dans la langue de la question."""

GABARIT_UTILISATEUR = """Passages du corpus :

{passages}

---

Question : {question}"""


@dataclass
class PassageSource:
    """Passage tel qu'il est présenté au modèle, avec le numéro utilisé pour la citation."""

    numero: int
    titre_document: str
    section: str
    page_debut: int
    page_fin: int
    contenu: str

    @property
    def reference(self) -> str:
        pages = (
            f"p. {self.page_debut}"
            if self.page_debut == self.page_fin
            else f"p. {self.page_debut}-{self.page_fin}"
        )
        return f"{self.titre_document}, {self.section}, {pages}"


def formater_passages(passages: list[PassageSource]) -> str:
    return "\n\n".join(
        f"[{p.numero}] {p.reference}\n{p.contenu}" for p in passages
    )


def construire_messages(question: str, passages: list[PassageSource]) -> tuple[str, str]:
    """Retourne (système, message utilisateur)."""
    return SYSTEME, GABARIT_UTILISATEUR.format(
        passages=formater_passages(passages), question=question.strip()
    )
