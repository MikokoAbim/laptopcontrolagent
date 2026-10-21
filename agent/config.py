import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder containing this `agent/` package.
ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

MODEL_NAME = os.getenv("MODEL", "deepseek/deepseek-chat-v3.1")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.6"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

# Where skills will live on disk.
SKILLS_DIR = ROOT / os.getenv("SKILLS_DIR", "skills")


def require_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing. Copy .env.example to .env and fill it in."
        )
    return OPENROUTER_API_KEY
