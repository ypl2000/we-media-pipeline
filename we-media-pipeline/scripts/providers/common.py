"""Shared helpers for the image providers. Everything provider-specific lives
in the provider's own package; config reads go through shared/config_loader."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "shared"))

from config_loader import load_project_config  # noqa: E402


def load_config() -> dict:
    return load_project_config()


def api_key(env_names: tuple, config_key: str, label: str) -> str:
    """env var first (含别名), then config.json — 统一走 config_loader。都没有则报错。"""
    for name in env_names:
        key = os.environ.get(name)
        if key:
            return key
    key = load_config().get(config_key) or ""
    if not key:
        raise RuntimeError(
            f"{label} api key not found — set env {env_names[0]} or {config_key} in config.json"
        )
    return key
