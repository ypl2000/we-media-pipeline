"""Agnes prompt templates.

These are tuned for Agnes (a diffusion-style image model): the prompt must stay
short, and the "no text" clause has to be in every single prompt. The style
templates live here, not in the workflow prompt, because a prompt that grows
past ~600 characters makes the model draw badly.
"""

# The recurring cast. Each one is a full clause so a style template can just
# drop it in; swap with --character to change who plays the protagonist.
CHARACTERS = {
    "line_person": ("One small simple hand-drawn human figure with a round head, no facial features, "
                    "thin limbs, performs the main action."),
    "cat": ("One small simple hand-drawn cat with pointed ears and a curved tail, no facial features, "
            "performs the main action."),
    "robot": ("One small simple hand-drawn boxy robot with an antenna and thin limbs, no facial "
              "features, performs the main action."),
    "dot": "One tiny simple dot-shaped character with no limbs, performs the main action.",
    "none": "",
}
DEFAULT_CHARACTER = "line_person"

NO_TEXT = ("Absolutely no text, no letters, no words, no numbers, no labels, "
           "no title, no signature, no watermark.")

STYLE_TEMPLATES = {
    "xiaohei": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Pure white background, minimalist black hand-drawn line art, slightly wobbly pen lines, "
            "generous white space. Sparse orange arrows. {character} Scene: {scene}."
        ),
    },
    "notion": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Off-white paper background, simple hand-drawn line illustration in thin gray pen strokes, "
            "like a Notion page doodle. Soft muted orange and beige accents. {character} Clear "
            "diagram-like layout, plenty of white space. Scene: {scene}."
        ),
    },
    "warm": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Soft cream background, gentle flat illustration with rounded shapes, warm palette of "
            "terracotta, amber, dusty rose and olive. {character} Light paper grain texture. "
            "Scene: {scene}."
        ),
    },
    "minimal": {
        "label_color": "black",
        "character": "dot",
        "prompt": (
            "Pure white background, extreme minimalism, very few simple geometric shapes, thin single "
            "accent color of deep blue, huge amount of white space. {character} Clean and quiet. "
            "Scene: {scene}."
        ),
    },
    "blueprint": {
        "label_color": "white",
        "character": "line_person",
        "prompt": (
            "Deep navy blue technical blueprint background with faint cyan grid lines, white and pale "
            "cyan schematic line drawing, thin precise strokes, plain arrows and leader lines pointing "
            "at parts. {character} Engineering diagram aesthetic. Scene: {scene}."
        ),
    },
    "watercolor": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Off-white textured paper background, loose soft watercolor wash illustration, muted teal, "
            "ochre and dusty pink washes with visible brush edges. {character} Airy and loose "
            "composition. Scene: {scene}."
        ),
    },
    "flat": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Solid flat vector illustration on a plain background, bold simple geometric shapes with no "
            "texture or gradient, limited palette of indigo, coral, cream and charcoal. {character} "
            "Clean editorial look. Scene: {scene}."
        ),
    },
    "editorial": {
        "label_color": "black",
        "character": "line_person",
        "prompt": (
            "Screen-print poster style, off-white background with bold black and deep red shapes, "
            "halftone dot texture, heavy geometric forms and a strong diagonal composition. "
            "{character} Magazine editorial feel. Scene: {scene}."
        ),
    },
}
DEFAULT_STYLE = "xiaohei"
MAX_SCENE_CHARS = 200
MAX_PROMPT_CHARS = 700


def build_prompt(scene: str | None, prompt: str | None, style: str = DEFAULT_STYLE,
                 character: str | None = None) -> str:
    """Style template + a one-sentence scene, or a raw prompt.

    `character` picks the recurring protagonist; None means the style's default.
    """
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
