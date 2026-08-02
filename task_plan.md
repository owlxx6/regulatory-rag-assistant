# Plan — Assistant documentaire RAG sur corpus réglementaire

**Objectif :** en 3 semaines, un RAG démontrable, **mesuré** et documenté sur un corpus réglementaire bancaire (BIS / ACPR / EBA), exploitable en entretien d'alternance.

**Règle d'arbitrage du cahier des charges :** si le temps manque, sacrifier la semaine 3 (agent), **jamais** le jour 5 (jeu d'évaluation) ni le jour 10 (documentation).

## Critères d'acceptation v1

| Critère | Seuil | Mesuré |
|---|---|---|
| Recall@5 | ≥ 0,80 | ⬜ en attente d'annotation |
| Gain reranking vs vectoriel seul | ≥ +10 pts | ⬜ en attente d'annotation |
| Abstention correcte (hors-corpus) | ≥ 0,90 | ⬜ |
| Réponses avec citation vérifiable | 100 % | ⬜ |
| Latence hors génération | < 2 s | ⚠️ **échec sur hybride+rerank** : p50 139 s. Les trois autres configurations passent (1 à 227 ms) |
| Démarrage depuis dépôt vierge | `docker compose up` + 1 cmd | ⬜ |

## Décisions prises

| Sujet | Choix | Date |
|---|---|---|
| Runtime conteneur | Docker Desktop | 2026-07-31 |
| Périmètre corpus | Large : solvabilité + liquidité + levier + crédit. Risque de marché, supervision générale et IRRBB écartés | 2026-07-31 |
| Langues | Majorité anglaise (BIS, EBA) + ACPR en français. Réel obtenu : 83 % EN / 17 % FR | 2026-07-31 |
| Mode de travail | Pédagogique — expliquer le quoi/pourquoi et **où** exécuter chaque commande | 2026-07-31 |
| Stockage | PostgreSQL 16 + pgvector (lexical + vectoriel dans un seul moteur) | 2026-07-31 |
| Génération | API Anthropic d'abord, derrière une interface `LLMClient` interchangeable avec Ollama | 2026-07-31 |

## Phase 0 — Prérequis machine `complete`

- [x] Docker Desktop installé et démarré — Compose v5.3.1, daemon 29.6.2
- [x] Python 3.11 disponible — 3.11.15 via Homebrew, sur le PATH (`/usr/local/bin/python3.11`)
- [x] Vérification finale effectuée

## Phase 1 — Socle (semaine 1, jours 1-2) `complete`

- [x] Arborescence du dépôt + `git init` + `.gitignore` (`data/raw/` exclu)
- [x] `pyproject.toml`, `.env.example`, `src/config.py` (settings Pydantic)
- [x] `docker-compose.yml` — Postgres 16 + pgvector, port hôte 5433
- [x] `sql/001_schema.sql` appliqué automatiquement — 3 tables, pgvector 0.8.6, HNSW + GIN vérifiés
- [x] `scripts/download_corpus.py` — **11 documents, 796 pages** (BIS 8, EBA 2, ACPR 1) ; manifeste
      JSON avec hash SHA-256, tolérance aux échecs, liste `ECARTES` motivée
- [x] Extraction PDF (`pymupdf`) + filtrage en-têtes/pieds répétés — détection par parité de page
      (bandeaux alternés recto/verso), 10 documents sur 11 filtrés, le 11e n'a pas de bandeau
- [x] Découpage structuré — 1616 chunks, médiane 315 tokens, max 512, 8,3 % sous 200 tokens
- [x] **Contrôle qualité effectué** : `scripts/inspecter_chunks.py`, échantillon aléatoire à graine
      fixe. Un défaut trouvé et corrigé (chunks réduits à un intertitre)

## Phase 2 — Recherche (semaine 1, jours 3-4) `in_progress`

- [x] Code d'indexation écrit — préfixes `query: ` / `passage: `, idempotence par hash SHA-256,
      une transaction par document (`autocommit=True`)
- [ ] **Indexation en cours d'exécution** — 1616 chunks sur CPU Mac Intel, ~1,6 s/chunk mesuré,
      durée estimée 45-80 min. Le processus lancé utilise le code d'avant le correctif
      `autocommit`, donc rien n'est visible en base avant la fin
- [x] Recherche vectorielle (`vectorielle.py`), lexicale (`lexicale.py`), fusion RRF k=60
      (`fusion.py`), reranking top-30 → top-5 (`reranking.py`)
- [x] `pipeline.py` — point d'entrée unique, quatre configurations comparables
- [x] `scripts/rechercher.py` — CLI de test
- [x] **Indexation terminée** — 11 documents, 1616 chunks, tous vectorisés (BIS 1028, ACPR 340,
      EBA 248). Durée réelle très supérieure à l'estimation : le log montre un effondrement du
      débit d'un facteur 20 en cours de route (machine en veille ou fortement contrainte)
- [x] Vérification de bout en bout : les quatre configurations répondent, le reranking écarte
      bien une table des matières et un passage hors sujet que le vectoriel seul remontait
- [x] Latences mesurées — voir le tableau des critères ci-dessus et `docs/decisions.md`
- [ ] **Arbitrage à trancher sur la latence du reranking**

## Phase 3 — Évaluation (semaine 1, jour 5) `in_progress` **BLOQUANTE**

- [x] 56 questions rédigées, ancrées sur des passages réels du corpus (seuils chiffrés repérés
      par expression régulière dans les PDF)
- [x] 15 questions hors-corpus annotées (`chunks_pertinents: []`) — annotation triviale, pas de
      vérification documentaire nécessaire
- [x] `scripts/annoter.py` — outil d'annotation avec sauvegarde incrémentale, commande `r` pour
      reformuler et `p` pour lister les chunks d'une page (garde-fous anti-biais)
- [ ] **41 questions à annoter par l'utilisateur** — nécessite la base indexée
- [x] `evaluation/evaluer.py` — recall@{1,3,5,10}, MRR, latence p50/p95 ; refuse d'évaluer une
      question non annotée plutôt que de la compter comme un échec de récupération
- [ ] Tableau comparatif : vectoriel seul / lexical seul / hybride / hybride+rerank
- [ ] Aucun développement de la semaine 2 sans ces mesures

## Phase 4 — Produit (semaine 2, jours 6-9) `pending`

- [ ] `LLMClient` (API Anthropic | Ollama), prompt contraint, abstention
- [ ] Contrôle programmatique de la présence de citations
- [ ] API FastAPI + SSE : `POST /questions`, `GET /sante`, `GET /documents`
- [ ] Journalisation dans `requetes`
- [ ] Démo Streamlit avec affichage des sources
- [ ] `pytest`, `ruff`, GitHub Actions, Dockerfile applicatif

## Phase 5 — Documentation (semaine 2, jour 10) `pending` **BLOQUANTE**

- [ ] README dans l'ordre imposé (§11 du cahier des charges) — résultats chiffrés en haut
- [ ] `docs/architecture.md`, `docs/decisions.md` (alimenté en continu depuis le jour 1)
- [ ] Capture/GIF de démonstration
- [ ] Test de démarrage depuis un clone vierge

## Phase 6 — Agent v2 (semaine 3) `pending` — sacrifiable

- [ ] Base d'exemple : portefeuille de crédit synthétique
- [ ] Outil `requete_sql` en lecture seule + garde-fous sur le SQL généré
- [ ] Boucle d'agent, sélection entre `recherche_documentaire` et `requete_sql`
- [ ] Évaluation sur 15 questions mixtes, mise à jour du README

## Erreurs rencontrées

| Erreur | Tentative | Résolution |
|---|---|---|
| `Failed to initialize NumPy: _ARRAY_API not found` puis `NameError: torch` | 1 | Mac Intel : torch s'arrête à 2.2.2 sur macOS x86_64, binaire compilé contre NumPy 1.x → `numpy<2` épinglé |
| `NameError: name 'torch' is not defined` dans `transformers/integrations/tensor_parallel.py` | 2 | transformers 5.x exige torch ≥ 2.4 → `transformers>=4.44,<5` (résolu en 4.57.6) |
| ACPR `20251222_Notice_CRD4_clean.pdf` → HTTP 403, y compris avec user-agent navigateur | 1 | Document écarté du corpus ; `download_corpus.py` doit tolérer les échecs par document |
