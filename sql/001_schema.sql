-- Schéma du corpus réglementaire.
-- Exécuté automatiquement au premier démarrage du conteneur Postgres.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id           SERIAL PRIMARY KEY,
    titre        TEXT NOT NULL,
    source_url   TEXT,
    organisme    TEXT,              -- BIS, ACPR, EBA
    langue       TEXT,              -- fr, en
    date_pub     DATE,
    nb_pages     INT,
    hash_fichier TEXT UNIQUE        -- empêche la ré-ingestion d'un document déjà présent
);

CREATE TABLE chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INT REFERENCES documents(id) ON DELETE CASCADE,
    section      TEXT,              -- « Article 12 », « §3.4 »
    page_debut   INT,
    page_fin     INT,
    contenu      TEXT NOT NULL,
    nb_tokens    INT,
    embedding    vector(1024),
    -- Limite assumée en v1 : configuration 'french' fixe. Une colonne générée exige une
    -- fonction IMMUTABLE, ce qui interdit de choisir la configuration selon la langue du
    -- document. Le stemming français sur du texte anglais dégrade un peu le rappel lexical.
    -- Arbitrage et alternatives consignés dans docs/decisions.md.
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('french', contenu)) STORED
);

CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_tsv       ON chunks USING gin (tsv);
CREATE INDEX idx_chunks_document  ON chunks (document_id);

-- Journal des requêtes : permet d'analyser les échecs après coup et alimente la démonstration.
CREATE TABLE requetes (
    id            SERIAL PRIMARY KEY,
    question      TEXT NOT NULL,
    reponse       TEXT,
    chunks_cites  INT[],
    abstention    BOOLEAN,
    latence_ms    INT,
    horodatage    TIMESTAMPTZ DEFAULT now()
);
