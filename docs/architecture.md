# Architecture

## Vue d'ensemble

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

## Le chemin d'une question

1. **Encodage.** La question est préfixée de `query: ` puis encodée par e5. Le préfixe n'est pas
   cosmétique : le modèle a été entraîné avec, et l'omettre dégrade le rappel sans produire la
   moindre erreur. Symétriquement, les chunks sont encodés préfixés de `passage: `.
2. **Deux recherches en parallèle conceptuel.** La vectorielle rapporte 30 candidats par distance
   cosinus sur l'index HNSW ; la lexicale 30 candidats par `ts_rank_cd` sur le `tsvector`. La
   seconde existe parce que la première échoue sur les références précises : « article 429 » est
   un motif littéral que la similarité sémantique dilue.
3. **Fusion RRF.** `score = Σ 1/(60 + rang_i)`. Les deux listes sont fusionnées sur les rangs, pas
   sur les scores — un cosinus borné à [0,1] et un `ts_rank_cd` non borné ne sont pas comparables,
   et toute pondération de scores bruts exigerait une calibration par corpus.
4. **Reranking.** Les 30 candidats fusionnés passent dans un cross-encoder qui lit la paire
   (question, passage) d'un seul tenant. C'est l'étape au plus fort gain de précision et, de très
   loin, la plus coûteuse en latence — d'où la limite à 30 candidats, et deux modèles évalués en
   parallèle plutôt qu'un seul choisi à l'aveugle (voir `docs/decisions.md`).
5. **Génération contrainte.** Les 5 passages retenus sont numérotés et injectés dans le prompt,
   qui interdit toute réponse hors de ces passages et impose une citation `[n]` par affirmation.
6. **Contrôle programmatique.** Le code vérifie que la réponse contient au moins une citation
   valide, et qu'aucun numéro cité ne dépasse le nombre de passages fournis. Une réponse sans
   citation est marquée suspecte au journal ; un numéro hors plage est une source inventée.

## Décisions structurantes

**Un seul moteur de stockage.** PostgreSQL porte le vectoriel (pgvector, index HNSW) et le lexical
(`tsvector`, index GIN). À l'échelle du projet — quelques milliers de chunks — pgvector suffit
largement et le déploiement se réduit à un conteneur. Le point de bascule vers une base vectorielle
dédiée se situe plutôt vers le million de vecteurs.

**Le découpage suit la structure, pas une taille fixe.** Les frontières sont détectées par
expressions régulières sur les motifs réglementaires (`Article \d+`, `^\d+\.\d+`, `Annexe [A-Z]`,
paragraphes numérotés). Seules les sections dépassant 512 tokens sont subdivisées, avec un
chevauchement de 50 tokens. Un découpage aveugle sépare une exigence de sa condition
d'application — dans un texte réglementaire, cela produit des passages littéralement faux.

**Le fournisseur de génération est interchangeable.** L'interface `LLMClient` isole la chaîne du
modèle. L'implémentation Anthropic sert au développement ; l'implémentation Ollama démontre que la
même chaîne tourne sans qu'aucune donnée ne quitte la machine — argument décisif pour un contexte
réglementaire.

**Tout est journalisé.** La table `requetes` conserve question, réponse, chunks cités, abstention
et latence. C'est ce qui permet d'analyser les échecs après coup au lieu de les découvrir en
démonstration.

## Modules

| Chemin | Rôle |
|---|---|
| `src/ingestion/extraction.py` | PDF → texte paginé, filtrage des bandeaux répétés |
| `src/ingestion/decoupage.py` | Texte → chunks alignés sur la structure |
| `src/ingestion/indexation.py` | Chunks → embeddings → base, idempotent par hash SHA-256 |
| `src/recherche/vectorielle.py` | Plus proches voisins HNSW, préfixe `query: ` |
| `src/recherche/lexicale.py` | `websearch_to_tsquery` + `ts_rank_cd` |
| `src/recherche/fusion.py` | Reciprocal Rank Fusion |
| `src/recherche/reranking.py` | Cross-encoder, top-30 → top-5 |
| `src/recherche/pipeline.py` | Point d'entrée unique, cinq configurations comparables |
| `src/generation/prompts.py` | Prompt contraint, format des références |
| `src/generation/citations.py` | Vérification programmatique des citations |
| `src/generation/client.py` | `LLMClient` : Anthropic ou Ollama |
| `src/api.py` | FastAPI, streaming SSE, journalisation |
| `evaluation/evaluer.py` | Métriques sur les cinq configurations |

## Contraintes de l'environnement de développement

La machine de développement est un Mac Intel. PyTorch ne publie plus de binaires macOS x86_64
au-delà de la version 2.2.2, laquelle est compilée contre NumPy 1.x — d'où les versions figées
dans `pyproject.toml`. Conséquence pratique : embeddings et reranking tournent sur CPU, sans
accélération matérielle. C'est le principal facteur de latence, et le premier chiffre à
reconsidérer sur une machine équipée d'un GPU.
