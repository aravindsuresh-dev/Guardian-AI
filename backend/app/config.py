"""Configuration & data-path helpers."""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"


class Settings:
    # LLM
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    azure_endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    # Convergence
    max_iterations: int = int(os.getenv("GUARDIAN_MAX_ITERATIONS", "1"))
    block_on: str = os.getenv("GUARDIAN_BLOCK_ON", "HARD").upper()

    # CORS
    cors_origins: list[str] = [
        o.strip()
        for o in os.getenv(
            "GUARDIAN_CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000",
        ).split(",")
        if o.strip()
    ]


@lru_cache
def settings() -> Settings:
    return Settings()
