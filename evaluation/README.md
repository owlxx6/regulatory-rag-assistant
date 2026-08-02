# Jeu d'évaluation

**C'est le livrable qui distingue ce projet.** Sans lui, aucune affirmation sur la qualité de la
récupération n'est défendable.

## Constitution du jeu

40 à 60 questions écrites à la main dans `questions.jsonl`, dont environ 15 hors-corpus.
Budget : 3 à 4 heures. L'annotation de référence est faite par un humain qui lit les documents —
pas générée, sinon on évalue le système contre des suppositions.

## Format

Une question par ligne (JSONL) :

```json
{"id": "q001", "question": "Quel est le ratio de levier minimal exigé ?", "chunks_pertinents": [142, 143], "type": "factuelle"}
{"id": "q042", "question": "Quel est le taux directeur de la BCE aujourd'hui ?", "chunks_pertinents": [], "type": "hors_corpus"}
```

- `chunks_pertinents` : identifiants des chunks en base (colonne `chunks.id`) qui contiennent
  la réponse. Vide pour une question hors-corpus.
- `type` : `factuelle` | `definition` | `multi_passages` | `reference_explicite` | `hors_corpus`

## Typologie à couvrir

| Type | Exemple | Ce que ça teste |
|---|---|---|
| `factuelle` | « Quel est le ratio de levier minimal ? » | Réponse ponctuelle chiffrée |
| `definition` | « Qu'est-ce que le NSFR ? » | Rappel sémantique |
| `multi_passages` | « Quelles sont les composantes des fonds propres ? » | Couverture multi-chunks |
| `reference_explicite` | « Que dit l'article 429 ? » | Rappel lexical exact |
| `hors_corpus` | « Quel est le taux directeur de la BCE ? » | Abstention (sprint 2) |

## Aide à l'annotation

Pour trouver les identifiants de chunks pertinents pendant l'annotation :

```bash
python scripts/rechercher.py --config hybride --top-k 15 "votre question"
```

La recherche propose des candidats ; l'humain valide en lisant le contenu. Si aucun candidat ne
contient la réponse, chercher dans le document source (le PDF) puis retrouver le chunk par :

```sql
SELECT id, section, contenu FROM chunks
WHERE document_id = … AND page_debut <= … AND page_fin >= …;
```

**Attention au biais :** ne pas annoter uniquement à partir des candidats retournés par le
système qu'on évalue — on surestimerait son rappel. Pour chaque question, vérifier dans le PDF
qu'il n'existe pas d'autre passage pertinent que la recherche aurait manqué.

## Lancer l'évaluation

```bash
python evaluation/evaluer.py
```

Produit un JSON horodaté dans `resultats/` et le tableau comparatif des quatre configurations.
Les JSON de résultats sont versionnés : ce sont les preuves chiffrées du README.
