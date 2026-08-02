# Progress — RAG réglementaire

## Session 1 — 2026-07-31

**Fait**
- Lecture du cahier des charges v1.0
- Audit de la machine : répertoire vide, Homebrew présent, Python 3.9.6, aucun runtime conteneur
- Deux arbitrages tranchés avec l'utilisateur : Docker Desktop comme runtime, mode de travail pédagogique
- Création de `task_plan.md`, `findings.md`, `progress.md`

- Python 3.11.15 installé via Homebrew, disponible sur le PATH

**En attente**
- Installation de Docker Desktop par l'utilisateur (téléchargement + mot de passe administrateur —
  je ne peux pas la faire à sa place) : `brew install --cask docker-desktop`
- Réponse de l'utilisateur sur deux points : (a) créer l'arborescence maintenant sans attendre
  Docker, (b) valider la sélection de documents du corpus avant d'écrire `download_corpus.py`

- Phase 0 close : Docker Compose v5.3.1, daemon 29.6.2, Python 3.11.15
- Socle créé : arborescence, `git init`, `.gitignore`, `pyproject.toml`, `.env.example`,
  `src/config.py`, `docker-compose.yml`, `sql/001_schema.sql`
- Base vérifiée : conteneur sain, 3 tables, pgvector 0.8.6, index HNSW + GIN + document_id
- venv Python 3.11 avec toutes les dépendances (deux incidents de compatibilité Mac Intel résolus)
- Corpus téléchargé : 11 documents, 796 pages, 83 % EN / 17 % FR
- `docs/decisions.md` ouvert avec 6 entrées

**Prochaine étape**
Jour 2 : extraction PDF (`pymupdf`) avec filtrage des en-têtes/pieds répétés, puis découpage
structuré. Contrôle obligatoire avant d'aller plus loin : inspecter 20 chunks au hasard.

## Session 2 — 2026-08-01

**Fait**
- Extraction PDF avec filtrage des bandeaux — défaut corrigé : détection par parité de page,
  les bandeaux alternent recto/verso et passaient sous le seuil global de 60 %
- Découpage structuré — 1616 chunks, médiane 315 tokens ; défaut corrigé : les intertitres
  suivis d'un sous-titre créaient des chunks de 3 tokens
- `scripts/inspecter_chunks.py` — contrôle qualité à graine fixe (livrable bloquant du jour 2)
- Chaîne de recherche complète : vectorielle, lexicale, fusion RRF, reranking, pipeline unifié
- Couche génération : prompt contraint, vérification programmatique des citations, `LLMClient`
  interchangeable Anthropic/Ollama
- API FastAPI en streaming SSE avec journalisation ; démo Streamlit ; Dockerfile ; CI GitHub Actions
- `evaluation/evaluer.py` et `evaluation/README.md` (méthode d'annotation)
- `docs/architecture.md`
- 21 tests passent, `ruff` propre sur tout le code

**Incidents résolus**
- torch 2.2.2 (dernier build macOS x86_64) incompatible NumPy 2.x → `numpy<2`
- transformers 5.x exige torch ≥ 2.4 → `transformers>=4.44,<5`
- `psycopg` ouvrait une transaction implicite : les `transaction()` par document n'étaient que
  des savepoints → `autocommit=True`

**En cours**
- Indexation des 1616 chunks (CPU, ~45-80 min estimées). Le processus lancé précède le correctif
  `autocommit`, donc la base reste à 0 jusqu'à la fin.

- 56 questions rédigées (15 factuelles, 11 définitions, 8 multi-passages, 7 références
  explicites, 15 hors-corpus) ; hors-corpus déjà annotées
- `scripts/annoter.py` écrit et testé sur son mode `--etat`

## Session 3 — 2026-08-02

**Fait**
- Indexation terminée : 11 documents, 1616 chunks vectorisés (BIS 1028, ACPR 340, EBA 248)
- Chaîne vérifiée de bout en bout sur les cinq configurations
- Latences mesurées à chaud : lexical 1 ms, hybride 222 ms, vectoriel 227 ms,
  hybride+bge **139 533 ms**, hybride+mMiniLM **9 770 ms** (p50)
- Second reranker ajouté comme configuration à part entière, décision et chiffres consignés
- 30 tests passent, `ruff` propre

**Constat qualitatif du reranking**
Sur « ratio de levier minimal », le vectoriel seul remonte en 2ᵉ position une ligne de table des
matières et en 3ᵉ un passage sur le LCR. Les deux disparaissent après reranking. Le gain existe ;
c'est son ampleur qui reste à chiffrer sur le jeu annoté.

**Bloqué sur**
- Annotation des 41 questions dans-corpus. La base est prête, l'outil est vérifié
  (`afficher_documents` et `afficher_chunks_page` testés sur données réelles). L'annotation de
  référence doit venir de l'utilisateur : l'établir à partir des seules sorties du système
  reviendrait à l'évaluer contre lui-même.

**Question ouverte pour l'évaluation**
Le seuil « < 2 s hors génération » est inatteignable avec un reranking sur 30 candidats sur ce
matériel. L'issue dépend du gain de recall mesuré — si le reranking n'apporte pas les 10 points
visés, sa latence cesse d'être un sujet.

**Tests**
21 tests unitaires (extraction, découpage, citations) — tous passants. Pas encore de test
d'intégration sur la base.

**En attente de décision**
- Commit initial non fait — à la demande de l'utilisateur.
