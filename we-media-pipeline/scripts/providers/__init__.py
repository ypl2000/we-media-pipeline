"""Registry of image providers.

One provider = one package under this directory. Each package exposes:

    NAME                  str
    CHARACTERS            dict[str, str]     cast clauses, "" for no cast
    STYLE_TEMPLATES       dict[str, dict]    {"label_color", "character", "prompt"}
    MAX_SCENE_CHARS       int
    MAX_PROMPT_CHARS      int
    DEFAULT_STYLE         str
    build_prompt(scene, prompt, style, character) -> str
    default_model() -> str
    size_for(aspect_ratio) -> str
    draw(prompt, size, model) -> bytes

Adding a model = copy a package, edit it, add its name to PROVIDERS.
"""
import importlib

PROVIDERS = ("agnes", "glm")


def get_provider(name: str):
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider '{name}' — pick one of: {', '.join(PROVIDERS)}")
    return importlib.import_module(f"{__name__}.{name}")
