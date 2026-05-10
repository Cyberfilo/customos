"""Project-wide settings loaded from config.toml + env."""
from __future__ import annotations

import os
import secrets
import tomllib
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"

LOCAL_TZ = ZoneInfo("Europe/Rome")


class Paths(BaseModel):
    data_root: Path
    raw_dir: Path
    db_path: Path
    output_dir: Path

    @classmethod
    def from_dict(cls, d: dict, root: Path) -> "Paths":
        return cls(
            data_root=root / d["data_root"],
            raw_dir=root / d["raw_dir"],
            db_path=root / d["db_path"],
            output_dir=root / d["output_dir"],
        )

    def ensure(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


class Privacy(BaseModel):
    deep_content_analysis: bool = False
    contact_hash_salt: str = ""


class ExtractCfg(BaseModel):
    lookback_days: int = 365
    include_unified_log: bool = False
    include_photos_thumbnails: bool = False


class LLMCfg(BaseModel):
    preferred: list[str] = ["anthropic", "openai"]
    anthropic_model: str = "claude-sonnet-4-5"
    openai_model: str = "gpt-5"
    max_output_tokens: int = 4000


class Settings(BaseModel):
    paths: Paths
    privacy: Privacy
    extract: ExtractCfg
    llm: LLMCfg

    def has_anthropic(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def has_openai(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def chosen_llm(self) -> str | None:
        for choice in self.llm.preferred:
            if choice == "anthropic" and self.has_anthropic():
                return "anthropic"
            if choice == "openai" and self.has_openai():
                return "openai"
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data = tomllib.loads(CONFIG_PATH.read_text())
    s = Settings(
        paths=Paths.from_dict(data["paths"], PROJECT_ROOT),
        privacy=Privacy(**data.get("privacy", {})),
        extract=ExtractCfg(**data.get("extract", {})),
        llm=LLMCfg(**data.get("llm", {})),
    )
    s.paths.ensure()
    if not s.privacy.contact_hash_salt:
        s = _bootstrap_salt(s)
    return s


def _bootstrap_salt(s: Settings) -> Settings:
    """Generate and persist a random salt the first time we run."""
    salt = secrets.token_hex(16)
    text = CONFIG_PATH.read_text()
    text = text.replace('contact_hash_salt = ""', f'contact_hash_salt = "{salt}"', 1)
    CONFIG_PATH.write_text(text)
    s.privacy.contact_hash_salt = salt
    return s
