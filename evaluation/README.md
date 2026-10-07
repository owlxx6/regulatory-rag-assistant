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

## Fiabilité des runs longs

Trois précautions, chacune tirée d'un run perdu :

```bash
HF_HUB_OFFLINE=1 caffeinate -i python evaluation/evaluer.py
```

**`HF_HUB_OFFLINE=1`** force la résolution locale des modèles. Ils sont tous en cache après la
première utilisation, et interroger Hugging Face à chaque démarrage expose à des échecs
intermittents : un run a été perdu sur un `Unrecognized processing class`, alors que le cache
était complet et que le chargement direct fonctionnait. Hors ligne, le démarrage est aussi plus
rapide et surtout déterministe.

**`caffeinate -i`** empêche la mise en veille. Un run de la configuration bge dure une heure et
demie : si la machine s'endort, Docker redémarre le conteneur PostgreSQL et la connexion meurt.
`evaluer.py` se reconnecte désormais, mais mieux vaut ne pas provoquer la coupure.

**Détacher le processus** (`nohup … &`) pour un run de plus de dix minutes, sans quoi il meurt
avec le terminal qui l'a lancé.

## Lancer l'évaluation

```bash
python evaluation/evaluer.py
```

Produit un JSON horodaté dans `resultats/` et le tableau comparatif des quatre configurations.
Les JSON de résultats sont versionnés : ce sont les preuves chiffrées du README.
