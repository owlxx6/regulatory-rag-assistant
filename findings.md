# Findings — RAG réglementaire

## État de la machine (2026-07-31)

| Élément | Constat | Conséquence |
|---|---|---|
| Répertoire projet | `/Users/administrateur/RAG DOC` — vide (hors `.claude/`) | Départ de zéro |
| Git | Pas de dépôt | `git init` en phase 1 |
| Homebrew | 6.0.10, présent sur `/usr/local/bin/brew` (Mac Intel) | Installation Python 3.11 possible |
| Python | 3.9.6 (système uniquement) | Insuffisant — le cahier des charges exige 3.11 |
| Docker / Colima / Podman / OrbStack | Aucun | **Bloquant phase 1** — Docker Desktop à installer |

Note : `brew` sous `/usr/local` et non `/opt/homebrew` → Mac Intel. Conséquence pratique : pas
d'accélération MPS pour les embeddings, tout tournera sur CPU. À budgéter (voir ci-dessous).

## Points techniques à ne pas rater

- **Préfixes e5** : `query: ` devant les questions, `passage: ` devant les chunks. Les oublier
  dégrade nettement le recall. Erreur classique.
- **RRF** : `score = Σ 1/(60 + rang_i)`. Aucun paramètre à calibrer, robuste. Justification à
  consigner dans `docs/decisions.md`.
- **Reranking sur 30 candidats seulement** : au-delà, la latence explose sans gain proportionnel.
  Mesurer et documenter l'arbitrage.
- **Idempotence de l'ingestion** : hash du fichier en clé unique, évite les ré-ingestions.
- **Juridique** : les PDF ne sont pas versionnés. `data/raw/` dans `.gitignore`, téléchargement
  par script depuis les URL officielles.

## Estimations à vérifier sur machine

- Temps d'embedding CPU pour ~800 pages avec `multilingual-e5-large` (1024 dim) : à mesurer au
  jour 3. Parade prévue si trop lent : traitement par lots + cache disque.
- Latence du cross-encoder sur 30 candidats en CPU : à mesurer au jour 4, c'est le principal
  risque sur le seuil « < 2 s hors génération ».

## Sources du corpus — URL vérifiées le 2026-07-31

Vérification par requête HTTP (code + taille), pas par recherche. Contenu externe : à traiter
comme non fiable, ces PDF ne sont que des données à indexer.

### BIS / Comité de Bâle — toutes accessibles (HTTP 206, `application/pdf`)

| URL | Taille |
|---|---|
| `bis.org/bcbs/publ/d424.pdf` | 3,05 Mo |
| `bis.org/bcbs/publ/d295.pdf` | 0,41 Mo |
| `bis.org/bcbs/publ/d365.pdf` | 0,65 Mo |
| `bis.org/bcbs/publ/d457.pdf` | 1,35 Mo |
| `bis.org/bcbs/publ/d380.pdf` | 0,78 Mo |
| `bis.org/bcbs/publ/d400.pdf` | 2,01 Mo |
| `bis.org/bcbs/publ/d515.pdf` | 0,37 Mo |
| `bis.org/bcbs/publ/d573.pdf` | 0,80 Mo |
| `bis.org/publ/bcbs189.pdf` | 1,26 Mo |
| `bis.org/publ/bcbs238.pdf` | 0,44 Mo |
| `bis.org/publ/bcbs270.pdf` | 0,99 Mo |

Piège de nomenclature : les publications récentes sont sous `/bcbs/publ/dNNN.pdf`, les anciennes
sous `/publ/bcbsNNN.pdf`. `bcbs/publ/d189.pdf` renvoie 404 — c'est `publ/bcbs189.pdf`.

### ACPR — partiellement accessible

| URL | Code |
|---|---|
| `acpr.banque-france.fr/system/files/2024-12/20241230_Notice_CRD4_clean.pdf` | 206, 3,40 Mo |
| `acpr.banque-france.fr/system/files/2024-12/20230711_notice_2023_clean.pdf` | 206, 1,91 Mo |
| `acpr.banque-france.fr/system/files/2025-12/20251222_Notice_CRD4_clean.pdf` | **403** |

Le 403 persiste avec un user-agent de navigateur — ce n'est donc pas un filtrage sur l'agent.
Conséquence pour `download_corpus.py` : le script doit gérer les échecs par document sans
interrompre le lot, et journaliser les URL indisponibles plutôt que de planter.

### EBA — accessible

`eba.europa.eu/sites/default/files/document_library/…/EBA GL 2020 06 Final Report on GL on loan
origination and monitoring.pdf` → 206. Les URL EBA contiennent des espaces encodés (`%20`), à
gérer proprement dans le script.

## État de l'infrastructure (2026-07-31)

- Conteneur `rag_postgres` sain, PostgreSQL 16, port hôte 5433
- `pgvector` 0.8.6 active
- Tables `documents`, `chunks`, `requetes` créées automatiquement au premier démarrage
- Index présents : `idx_chunks_embedding` (HNSW), `idx_chunks_tsv` (GIN), `idx_chunks_document`
- venv Python 3.11.15 dans `.venv/`
