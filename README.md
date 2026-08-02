# Assistant documentaire RAG sur corpus réglementaire

Un assistant qui répond en langage naturel sur un corpus de textes réglementaires bancaires
(Comité de Bâle, ACPR, EBA), **en citant systématiquement ses sources**, et qui **déclare son
ignorance** plutôt que d'extrapoler quand le corpus ne contient pas la réponse.

En matière réglementaire, une réponse approximative est une réponse fausse : un ratio cité à
0,5 point près, une exigence attribuée au mauvais article, et la réponse devient dangereuse.
D'où les trois partis pris du projet — chaque affirmation renvoie au document, à l'article et à
la page ; l'abstention est un comportement attendu et mesuré ; et rien n'est affirmé sur la
qualité du système sans un chiffre issu d'un jeu d'évaluation annoté à la main.

---

## Résultats

### Latence, par configuration de recherche

Mesures à chaud, corpus de 1 616 chunks, Mac Intel **sans accélération matérielle** (CPU seul).

| Configuration | p50 | p95 | Budget < 2 s |
|---|---|---|---|
| Lexical seul | 1 ms | 5 ms | ✅ |
| Hybride (RRF) | 222 ms | 839 ms | ✅ |
| Vectoriel seul | 227 ms | 616 ms | ✅ |
| Hybride + reranking léger (mMiniLMv2, 118 M) | 9 770 ms | 9 953 ms | ❌ |
| Hybride + reranking (bge-reranker-v2-m3, 568 M) | 139 533 ms | 196 273 ms | ❌ |

Le budget de 2 secondes **n'est pas tenu** par les configurations avec reranking sur ce matériel.
Le diagnostic complet et les options envisagées sont dans
[`docs/decisions.md`](docs/decisions.md) — aucun réglage du modèle prescrit ne rentre dans le
budget, y compris en tronquant les passages à 128 tokens.

### Qualité de la récupération

> **En attente.** Les métriques de recall, de MRR et d'abstention exigent le jeu d'évaluation
> annoté. 15 des 56 questions sont annotées (les hors-corpus) ; les 41 autres demandent une
> lecture des documents sources. Le tableau ci-dessous sera rempli avec les sorties de
> `evaluation/evaluer.py`, jamais à la main.

| Configuration | R@1 | R@3 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|
| Vectoriel seul | — | — | — | — | — |
| Lexical seul | — | — | — | — | — |
| Hybride (RRF) | — | — | — | — | — |
| Hybride + reranking léger | — | — | — | — | — |
| Hybride + reranking | — | — | — | — | — |

Objectifs : recall@5 ≥ 0,80, gain du reranking ≥ +10 points, abstention correcte ≥ 0,90.

**Observation qualitative en attendant la mesure.** Sur « quel est le ratio de levier minimal
exigé ? », la recherche vectorielle seule remonte en deuxième position une ligne de table des
matières et en troisième un passage sur le LCR — deux résultats sans valeur. Après reranking,
les deux disparaissent et le bon passage passe d'un score de 0,877 à 0,995. Le gain existe ;
c'est son ampleur qui reste à chiffrer.

---

## Corpus

11 documents publics, **796 pages**, sélectionnés sur un périmètre resserré : solvabilité,
liquidité, levier, risque de crédit.

| Organisme | Documents | Chunks | Langue |
|---|---|---|---|
| BIS / Comité de Bâle | 8 | 1 028 | anglais |
| ACPR | 1 | 340 | français |
| EBA | 2 | 248 | anglais |

Les PDF **ne sont pas versionnés** : ils sont publics mais leur redistribution n'a pas lieu
d'être. `scripts/download_corpus.py` les récupère depuis leurs URL officielles et écrit un
manifeste avec le hash SHA-256 de chacun.

Le script conserve aussi la liste des documents **écartés** avec leur motif. Un corpus se
justifie autant par ce qu'il exclut que par ce qu'il contient : la notice ACPR 2023 a par exemple
été retirée parce qu'elle est le millésime précédent de la notice 2024 déjà retenue — deux
versions du même texte annuel produisent des chunks quasi identiques et des citations
contradictoires.

---

## Architecture

```
                   ┌──────────────┐
   PDF sources ──▶ │  Ingestion   │  pymupdf → découpage structuré → métadonnées
                   └──────┬───────┘
                          ▼
                   ┌──────────────┐
                   │  Embeddings  │  multilingual-e5-large (1024 dim)
                   └──────┬───────┘
                          ▼
              ┌───────────────────────┐
              │ PostgreSQL + pgvector │  vecteurs (HNSW) + tsvector (GIN)
              └───────────┬───────────┘
                          ▼
   Question ──▶ ┌──────────────────┐
                │ Recherche hybride│  ts_rank_cd + cosinus → fusion RRF
                └────────┬─────────┘
                         ▼
                ┌──────────────────┐
                │    Reranking     │  cross-encoder, top-30 → top-5
                └────────┬─────────┘
                         ▼
                ┌──────────────────┐
                │   Génération     │  LLM + prompt contraint aux sources
                └────────┬─────────┘
                         ▼
                  Réponse + citations
```

Trois choix structurants, détaillés dans [`docs/architecture.md`](docs/architecture.md) :

**Un seul moteur de stockage.** PostgreSQL porte le vectoriel (pgvector, HNSW) *et* le lexical
(`tsvector`, GIN). À quelques milliers de chunks, pgvector suffit largement, le déploiement se
réduit à un conteneur, et les métadonnées documentaires se filtrent dans la même requête que la
recherche vectorielle. Le point de bascule vers une base vectorielle dédiée se situe plutôt vers
le million de vecteurs.

**Le découpage suit la structure, pas une taille fixe.** Les frontières sont détectées par
expressions régulières sur les motifs réglementaires (`Article \d+`, `^\d+\.\d+`, `Annexe [A-Z]`,
paragraphes numérotés). Un découpage aveugle sépare une exigence de sa condition d'application —
dans un texte réglementaire, cela produit des passages littéralement faux.

**Les hallucinations sont rendues détectables, pas supprimées.** Le prompt contraint la réponse
aux passages fournis, mais un prompt ne garantit rien. Le code vérifie ensuite que la réponse
contient au moins une citation valide et qu'aucun numéro cité ne dépasse le nombre de passages
transmis — un numéro hors plage est une source inventée. Toute réponse sans citation est marquée
suspecte dans la table `requetes`.

---

## Démarrage

Prérequis : Docker et Python 3.11.

```bash
cp .env.example .env          # renseigner ANTHROPIC_API_KEY pour la génération
docker compose up -d          # PostgreSQL 16 + pgvector, schéma appliqué automatiquement
```

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/download_corpus.py && .venv/bin/python -m src.ingestion.indexation
```

L'indexation calcule 1 616 embeddings sur CPU : comptez une à deux heures sans GPU.

Puis, au choix :

```bash
.venv/bin/python scripts/rechercher.py "Quel est le ratio de levier minimal exigé ?"
.venv/bin/uvicorn src.api:application --reload
.venv/bin/streamlit run demo/app.py
```

L'API expose `POST /questions` (réponse en flux SSE, sources dans l'événement final),
`GET /sante`, `GET /documents` et `GET /configurations`.

---

## Méthode d'évaluation

**56 questions écrites à la main**, réparties en cinq types : factuelles à réponse chiffrée,
définitions, questions exigeant plusieurs passages, questions contenant une référence d'article
explicite, et 15 questions hors-corpus destinées à mesurer l'abstention.

L'annotation de référence — la liste des chunks qui contiennent réellement la réponse — est
faite par un humain qui lit les documents. Ce point n'est pas un détail de méthode : annoter à
partir des seules sorties du système reviendrait à l'évaluer contre lui-même, le recall
sortirait proche de 1,00 et ne mesurerait rien. `scripts/annoter.py` fournit deux garde-fous
contre ce biais — reformuler la recherche, et lister tous les chunks d'une page lue dans le PDF
sans passer par la recherche du tout.

```bash
.venv/bin/python scripts/annoter.py          # annoter
.venv/bin/python evaluation/evaluer.py       # mesurer les cinq configurations
```

`evaluer.py` refuse d'évaluer une question non annotée plutôt que de la compter comme un échec
de récupération. Voir [`evaluation/README.md`](evaluation/README.md).

---

## Limites connues

**Le budget de latence n'est pas tenu avec reranking.** 9,8 s avec le modèle léger, 139 s avec
le modèle prescrit, contre 2 s visées. La cause est matérielle — un cross-encoder de 568 M
paramètres sur CPU Intel — et aucun réglage ne la corrige. Les trois configurations sans
reranking tiennent le budget avec deux ordres de grandeur de marge.

**Le `tsvector` est en configuration `french` pour tout le corpus.** Une colonne générée
PostgreSQL n'accepte que des fonctions `IMMUTABLE`, ce qui interdit de choisir la configuration
selon la langue du document. Le stemming français appliqué aux 79 % de documents anglophones
dégrade le rappel lexical d'une ampleur qui reste à mesurer.

**La part francophone est de 17 %**, contre 30 % visés. L'EBA traduit ses orientations en
français : substituer une version FR à une version EN rééquilibrerait sans coût en pages.

**Périmètre volontairement restreint.** Pas d'authentification, pas de multi-utilisateurs, pas
de passage à l'échelle au-delà de quelques milliers de chunks. La v1 se juge sur la mesure, pas
sur le nombre de fonctionnalités.

## Pistes

Reranking quantifié en ONNX int8, ou réduction du nombre de candidats une fois le gain de recall
chiffré. Colonnes `tsvector` séparées par langue si la mesure confirme la dégradation. Couche
agent avec sélection automatique entre recherche documentaire et interrogation SQL — spécifiée
dans [`docs/sprints.md`](docs/sprints.md), non commencée.

---

## Stack

Python 3.11 · pymupdf · sentence-transformers (`multilingual-e5-large`, `bge-reranker-v2-m3`) ·
PostgreSQL 16 + pgvector · FastAPI + SSE · Streamlit · Docker Compose · pytest · ruff ·
GitHub Actions
