"""Application settings, re-read from .env on each call so edits apply without a restart."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    ncbi_api_key: str
    http_timeout: float = 20.0
    openai_timeout: float = 120.0
    mcp_timeout: float = 90.0


def get_settings() -> Settings:
    load_dotenv(ENV_FILE, override=True)
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1").strip() or "gpt-4.1",
        ncbi_api_key=os.getenv("NCBI_API_KEY", "").strip(),
    )
