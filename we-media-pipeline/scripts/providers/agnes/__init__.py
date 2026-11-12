"""Agnes image provider."""
from .prompts import (CHARACTERS, DEFAULT_CHARACTER, DEFAULT_STYLE, MAX_PROMPT_CHARS,
                      MAX_SCENE_CHARS, NO_TEXT, STYLE_TEMPLATES, build_prompt)
from .provider import API_URL, DEFAULT_MODEL, default_model, draw, size_for

NAME = "agnes"

__all__ = ["NAME", "CHARACTERS", "DEFAULT_CHARACTER", "DEFAULT_STYLE", "MAX_PROMPT_CHARS",
           "MAX_SCENE_CHARS", "NO_TEXT", "STYLE_TEMPLATES", "build_prompt", "API_URL",
           "DEFAULT_MODEL", "default_model", "draw", "size_for"]
