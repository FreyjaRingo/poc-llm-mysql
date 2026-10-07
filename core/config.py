"""Konfigurasi bersama. Nilai diambil dari file .env di folder utama proyek."""
import os
from pathlib import Path
from dotenv import load_dotenv

# core/config.py -> folder proyek ada satu tingkat di atas
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


# ---- Database ----
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "classicmodels")
DB_ADMIN_USER = os.getenv("DB_ADMIN_USER", "root")
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "")
DB_READER_USER = os.getenv("DB_READER_USER", "llm_reader")
DB_READER_PASSWORD = os.getenv("DB_READER_PASSWORD", "ganti_password_ini")


# ---- LLM (DeepSeek, format OpenAI) ----
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
# disabled = jawaban langsung, lebih cepat dan murah. enabled = model berpikir dulu.
LLM_THINKING = os.getenv("LLM_THINKING", "disabled").strip().lower()
_temp = os.getenv("LLM_TEMPERATURE", "0").strip()
LLM_TEMPERATURE = float(_temp) if _temp else None

# ---- Batas eksekusi ----
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))
QUERY_TIMEOUT_MS = int(os.getenv("QUERY_TIMEOUT_MS", "10000"))

# ---- Saklar eksperimen ----
INCLUDE_COLUMN_COMMENTS = _bool("INCLUDE_COLUMN_COMMENTS", "true")
INCLUDE_BUSINESS_RULES = _bool("INCLUDE_BUSINESS_RULES", "false")
SEND_ROWS_TO_LLM = _bool("SEND_ROWS_TO_LLM", "true")
ROWS_SENT_TO_LLM = int(os.getenv("ROWS_SENT_TO_LLM", "30"))

LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "logs/run_log.jsonl")
REPORT_DIR = BASE_DIR / "reports"
