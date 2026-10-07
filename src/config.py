"""Configuration centralisée, lue depuis .env puis l'environnement."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE = Path(__file__).resolve().parent.parent


class Parametres(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RACINE / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Base de données ---
    postgres_user: str = "rag"
    postgres_password: str = "rag"
    postgres_db: str = "rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # --- Modèles ---
    modele_embedding: str = "intfloat/multilingual-e5-large"
    modele_reranker: str = "BAAI/bge-reranker-v2-m3"
    # Cross-encoder multilingue nettement plus petit (~118 M paramètres contre 568 M).
    # Évalué en parallèle du précédent : sur CPU, l'écart de latence est décisif et
    # l'écart de qualité doit être chiffré plutôt que supposé.
    modele_reranker_leger: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    # --- Génération ---
    # anthropic | openai | ollama. « openai » désigne tout fournisseur exposant une API
    # compatible OpenAI (Groq, Mistral, OpenRouter, Together…), choisi par llm_base_url.
    llm_fournisseur: str = "anthropic"
    llm_modele: str = "claude-sonnet-5"
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    llm_cle_api: str = ""
    ollama_url: str = "http://localhost:11434"

    # --- Recherche ---
    # 30 candidats fusionnés soumis au reranker, 5 retenus pour la génération.
    top_k_candidats: int = 30
    top_k_final: int = 5
    rrf_k: int = 60

    # --- Découpage ---
    taille_chunk_max: int = 512
    taille_chunk_min: int = 200
    chevauchement: int = 50

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def dossier_pdf(self) -> Path:
        return RACINE / "data" / "raw"

    @property
    def dossier_cache(self) -> Path:
        return RACINE / "data" / "cache"


parametres = Parametres()
