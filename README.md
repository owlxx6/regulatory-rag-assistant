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

Jeu de 56 questions annotées à la main, dont 15 hors-corpus. Les 41 questions dans-corpus sont
évaluées ci-dessous ; recall@k = proportion de questions dont au moins un passage pertinent
figure dans le top k.

| Configuration | R@1 | R@3 | R@5 | R@10 | MRR | p50 |
|---|---|---|---|---|---|---|
| Lexical seul | 0,098 | 0,146 | 0,195 | 0,317 | 0,146 | 17 ms |
| Hybride (RRF) | 0,195 | 0,317 | 0,366 | 0,537 | 0,289 | 221 ms |
| Vectoriel seul | 0,268 | 0,415 | 0,512 | 0,537 | 0,361 | 184 ms |
| Hybride + reranking bge (568 M) | 0,342 | 0,512 | 0,561 | 0,610 | 0,428 | 60 040 ms |
| **Hybride + reranking léger (118 M)** | **0,366** | **0,561** | **0,610** | 0,610 | **0,454** | **9 317 ms** |

**Le seuil de 0,80 au recall@5 n'est pas atteint.** Le meilleur résultat est 0,610. Les trois
constats qui expliquent cet écart valent davantage que le chiffre lui-même.

#### 1. La recherche hybride dégrade le vectoriel seul

0,366 contre 0,512 au recall@5. RRF pondère les deux listes à égalité, or le volet lexical
plafonne à 0,195 : il injecte surtout du bruit. Un mauvais résultat lexical au rang 1 reçoit
exactement le même poids qu'un bon résultat vectoriel au rang 1.

RRF suppose des récupérateurs de qualité comparable. Cette hypothèse est fausse ici, et c'est
mesurable — pas une intuition.

#### 2. L'écart entre français et anglais est de 37 points

| Langue du passage attendu | recall@5 |
|---|---|
| Français | **0,89** (8/9) |
| Anglais | **0,52** (16/31) |

Les questions sont posées en français. Le `tsvector` est en configuration `french` pour tout le
corpus, contrainte imposée par les colonnes générées de PostgreSQL (voir
[`docs/decisions.md`](docs/decisions.md)). Sur les 76 % de chunks anglophones, la recherche
lexicale ne peut structurellement rien apparier, et le vectoriel doit porter seul.

C'est la cause racine du point 1 : pour 31 des 41 questions, la liste lexicale soumise à RRF
est du bruit pur.

#### 3. Les questions factuelles sont les plus mal servies

| Type de question | recall@5 |
|---|---|
| Définition | 0,73 |
| Référence explicite | 0,71 |
| Factuelle | 0,53 |
| Multi-passages | 0,50 |

Contre-intuitif : les questions à réponse chiffrée précise devraient être les plus faciles. Elles
sont les plus dures parce que les seuils chiffrés du corpus sont énoncés dans les textes du
Comité de Bâle, en anglais. Le point 2 se propage directement ici.

#### 4. Le petit reranker bat le gros, 6,4 fois plus vite

`bge-reranker-v2-m3` est prescrit par le cahier des charges. Mesuré, il est dominé par
`mmarco-mMiniLMv2-L12`, cinq fois plus petit : 0,561 contre 0,610 de recall@5, pour 60 s contre
9,3 s de latence médiane.

L'écart de qualité ne doit pas être surinterprété — 0,610 contre 0,561, ce sont 25 questions
contre 23 sur 41, soit deux questions pour une granularité de 2,44 points. **Les deux modèles
sont indiscernables en qualité à cette taille d'échantillon.** L'écart de latence, lui, est d'un
facteur 6,4 et ne souffre aucune ambiguïté.

**Décision : le modèle léger est retenu**, et la comparaison est conservée au dépôt. Un
cross-encoder plus gros n'est pas automatiquement meilleur, en particulier sur des paires
interlingues — question française, passage anglais — où le modèle entraîné sur mMARCO semble
mieux transférer.

#### Ce que le reranking apporte

+9,8 points de recall@5 sur le vectoriel seul (0,512 → 0,610), +24,4 points sur l'hybride.

L'objectif était un gain d'au moins 10 points, et il est manqué de deux dixièmes. Cet écart
n'a pourtant aucune signification : le gain vaut 4 questions sur 41, soit 9,76 points, et les
valeurs voisines atteignables sont 7,32 points (3 questions) et 12,20 points (5 questions).
**Le seuil de +10 points n'est pas atteignable sur un jeu de 41 questions** — il tombe entre
deux valeurs possibles. Un seuil au point près exigerait environ 200 questions annotées.

Reproduire ces mesures :

```bash
python evaluation/evaluer.py                  # les cinq configurations
python evaluation/analyser.py                 # ventilation par type et par langue
```

---

### Génération : abstention et traçabilité

Mesuré via Groq, recherche en configuration hybride + reranking léger, 56 questions.

| Modèle | Abstention hors-corpus | Au moins une citation vérifiable | Aucune citation inventée |
|---|---|---|---|
| **`qwen/qwen3.8-27b`** | **1,00** (15/15) | **1,00** (35/35) | 0,97 (34/35) |
| `openai/gpt-oss-120b` | 0,93 (14/15) | ≥ 0,81 — non remesuré | — |

**Les deux critères de génération du cahier des charges sont atteints** : abstention ≥ 0,90,
et 100 % des réponses comportant au moins une citation vérifiable.

**Une référence inventée, détectée.** Sur q009, le modèle cite `[2, 4, 5, 11]` alors que seuls
cinq passages lui ont été fournis. Les citations 2, 4 et 5 sont réelles — la réponse satisfait
donc le critère du cahier — mais `[11]` n'existe pas. Le contrôle programmatique l'a signalée.
C'est le rôle qui lui était assigné : les hallucinations ne sont pas supprimées, elles sont
rendues détectables. D'où la colonne plus stricte, qui mesure ce que le critère du cahier laisse
passer.

**Deux modèles, une zone grise tranchée différemment.** q044 interroge les obligations du RGPD.
Le corpus mentionne ce règlement — les orientations EBA demandent de le respecter lors de la
collecte de données d'emprunteur — sans énoncer ce qu'il impose. `gpt-oss-120b` répond depuis
ces passages, `qwen3.8-27b` s'abstient. Mêmes passages, même prompt : c'est le modèle qui arbitre.
Qwen est aussi plus prudent sur les questions dans-corpus, avec 6 abstentions sur 41 contre 4.

**Transparence sur la mesure Qwen.** Le run a été interrompu par une coupure réseau à la
question 44, avant que l'écriture incrémentale n'existe. Les 44 premiers verdicts ont été
reconstruits depuis le journal d'exécution — produits par le même détecteur, mais sans le texte
des réponses ni les latences — puis les 12 questions restantes ont été évaluées par reprise.
Les deux fichiers sont versionnés dans `evaluation/resultats/`.

La mesure `gpt-oss-120b` n'a pas été rejouée : son taux de citation, obtenu avec un détecteur
qui ne reconnaissait pas les crochets pleine largeur `【1】`, reste un plancher, et le quota
journalier du modèle était épuisé.

**Le fournisseur est interchangeable.** La même chaîne tourne derrière l'API Anthropic, derrière
toute API compatible OpenAI (Groq, Mistral, OpenRouter), ou entièrement en local via Ollama —
auquel cas aucune donnée ne quitte la machine, ce qui est la contrainte réelle d'un établissement
soumis au secret bancaire. Le choix se fait dans `.env`, jamais dans le code.

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
