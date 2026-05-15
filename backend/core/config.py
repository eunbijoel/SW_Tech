"""
Central configuration — loaded once at startup.
All values sourced from environment variables / .env file.
"""
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ─────────────────────────────────────
    APP_NAME: str = "AI Prompt Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me"

    # ── API ─────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:8501"

    # ── Storage ─────────────────────────────────
    STORAGE_BASE: Path = Path("storage")
    UPLOAD_DIR: Path = Path("storage/uploads")
    RESULTS_DIR: Path = Path("storage/results")
    MAX_UPLOAD_SIZE_MB: int = 100
    ALLOWED_EXTENSIONS: str = "xlsx,xls,csv"

    # ── OpenAI ──────────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_DEFAULT_MODEL: str = "gpt-4o"
    OPENAI_MAX_TOKENS: int = 4096

    # ── Gemini ──────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_DEFAULT_MODEL: str = "gemini-1.5-pro"
    GEMINI_MAX_TOKENS: int = 4096

    # ── Ollama ──────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_DEFAULT_MODEL: str = "llama3"

    # ── GPU Server ──────────────────────────────
    GPU_SERVER_HOST: Optional[str] = None
    GPU_SERVER_PORT: int = 22
    GPU_SERVER_USER: str = "ubuntu"
    GPU_SERVER_KEY_PATH: str = "~/.ssh/gpu_server_rsa"
    GPU_API_URL: Optional[str] = None

    # ── Spark ───────────────────────────────────
    SPARK_MASTER_URL: Optional[str] = None
    SPARK_DRIVER_MEMORY: str = "4g"
    SPARK_EXECUTOR_MEMORY: str = "8g"

    # ── Logging ─────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # ── Excel Library ───────────────────────────
    EXCEL_LIBRARY_DIR: Path = Path("excel")

    @field_validator("UPLOAD_DIR", "RESULTS_DIR", "STORAGE_BASE", "EXCEL_LIBRARY_DIR", mode="before")
    @classmethod
    def make_path(cls, v: str) -> Path:
        return Path(v)

    @property
    def allowed_extensions_set(self) -> set[str]:
        return {ext.strip().lower() for ext in self.ALLOWED_EXTENSIONS.split(",")}

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    def ensure_dirs(self) -> None:
        """Create required storage directories on startup."""
        for d in [
            self.UPLOAD_DIR,
            self.RESULTS_DIR / "markdown",
            self.RESULTS_DIR / "excel",
            Path("logs"),
        ]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
