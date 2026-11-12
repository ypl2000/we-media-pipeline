"""GLM-Image (Z.AI) prompt templates.

GLM-Image is an autoregressive LLM plus a diffusion decoder, so it reads a
full art-direction brief instead of a keyword soup — unlike Agnes, a long
prompt does not make it draw badly here. But it is also very good at writing
Chinese, so the "no text" clause has to be much more explicit than for Agnes.

Same style keys as the Agnes set (xiaohei / notion / warm / minimal /
blueprint / watercolor / flat / editorial) and the same label colours, so the
overlay step behaves identically no matter which provider drew the picture.
"""

CHARACTERS = {
    "line_person": ("A single small person drawn with plain simple lines: a round head with no face "
                    "at all, thin straight arms and legs. This figure is the one performing the action."),
    "cat": ("A single small cat drawn with plain simple lines: two pointed ears, a round body, a long "
            "curved tail, no face details. This cat is the one performing the action."),
    "robot": ("A single small boxy robot drawn with plain simple lines: a square body, one short "
              "antenna on top, thin straight arms and legs, no face. This robot is the one performing "
              "the action."),
    "dot": ("A single tiny round blob with no limbs and no face. This blob is the one performing the "
            "action."),
    "none": "",
}
DEFAULT_CHARACTER = "line_person"

NO_TEXT = ("Absolutely no text anywhere in the image: no letters, no words, no numbers, no Chinese "
           "characters, no captions, no labels, no speech bubbles, no arrows carrying words, no "
           "signature, no watermark, no logo.")

STYLE_TEMPLATES = {
    "xiaohei": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a minimal black ink marker doodle on plain white paper. Loose confident "
            "single-stroke lines, uneven and casual, exactly like a quick sketch somebody drew in a "
            "notebook. Black lines only, no grey tones, no shading, no hatching, no colour, no "
            "background objects, no frame, no border. The subject sits in the middle with a lot of "
            "empty white space around it. {character} What happens: {scene}."
        ),
    },
    "notion": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a page from a tidy Notion document, drawn by hand. Thin grey pen strokes "
            "on off-white paper, simple shapes, soft muted orange and beige accents, a calm "
            "diagram-like layout with generous white space. {character} What happens: {scene}."
        ),
    },
    "warm": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a gentle flat illustration on a soft cream background. Rounded friendly "
            "shapes, a warm palette of terracotta, amber, dusty rose and olive, a light paper grain "
            "texture over everything. {character} What happens: {scene}."
        ),
    },
    "minimal": {
        "label_color": "black",
        "character": "dot",
        "prompt": (
            "Art direction: extreme minimalism. Pure white background, only a few very simple "
            "geometric shapes, one thin deep blue accent line, an enormous amount of empty space, "
            "quiet and clean. {character} What happens: {scene}."
        ),
    },
    "blueprint": {
        "label_color": "white",
        "character": "line_person",
        "prompt": (
            "Art direction: an engineering blueprint. Deep navy blue background with faint cyan grid "
            "lines, the drawing itself in white and pale cyan thin precise strokes, plain arrows and "
            "leader lines pointing at the parts. {character} What happens: {scene}."
        ),
    },
    "watercolor": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a loose soft watercolour painting on off-white textured paper. Muted teal, "
            "ochre and dusty pink washes with visible brush edges and a few pencil under-lines, airy "
            "and loose composition. {character} What happens: {scene}."
        ),
    },
    "flat": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a solid flat vector illustration on a plain background. Bold simple "
            "geometric shapes, no texture, no gradient, no shadow, a limited palette of indigo, "
            "coral, cream and charcoal. Clean editorial look. {character} What happens: {scene}."
        ),
    },
    "editorial": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Art direction: a screen-printed magazine poster. Off-white background, bold black and "
            "deep red shapes, halftone dot texture, heavy geometric forms and a strong diagonal "
            "composition. {character} What happens: {scene}."
        ),
    },
}
DEFAULT_STYLE = "xiaohei"
MAX_SCENE_CHARS = 200
MAX_PROMPT_CHARS = 2000


def build_prompt(scene: str | None, prompt: str | None, style: str = DEFAULT_STYLE,
                 character: str | None = None) -> str:
    """Style template + a one-sentence scene, or a raw prompt."""
    if scene:
        template = STYLE_TEMPLATES.get(style)
        if not template:
            raise ValueError(f"unknown style '{style}' — pick one of: {', '.join(STYLE_TEMPLATES)}")
        cast = character or template["character"]
        if cast not in CHARACTERS:
            raise ValueError(f"unknown character '{cast}' — pick one of: {', '.join(CHARACTERS)}")
        scene = scene.strip()
        if len(scene) > MAX_SCENE_CHARS:
            raise ValueError(f"scene too long ({len(scene)} chars, max {MAX_SCENE_CHARS}) — "
                             "one short sentence describing what happens")
        full = " ".join(template["prompt"].format(character=CHARACTERS[cast], scene=scene).split())
        full += " " + NO_TEXT
        if len(full) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt too long ({len(full)} chars, max {MAX_PROMPT_CHARS})")
        return full
    if not prompt:
        raise ValueError("need --scene or --prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt too long ({len(prompt)} chars, max {MAX_PROMPT_CHARS})")
    return prompt
