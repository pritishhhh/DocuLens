"""Configuration shared by the CLI, index builder, and serverless API."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TICKER_PATTERN = r"^[A-Z][A-Z0-9.-]{0,9}$"


def ticker_symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(TICKER_PATTERN, value):
        raise ValueError("Invalid ticker symbol")
    return value


def index_dir() -> Path:
    return Path(os.getenv("DOCULENS_INDEX_DIR", str(ROOT / "data" / "corpus")))


def api_key() -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ConfigurationError("Set GEMINI_API_KEY to enable answers.")
    return key


class ConfigurationError(RuntimeError):
    pass
