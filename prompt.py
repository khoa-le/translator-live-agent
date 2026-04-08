"""
prompt.py — Translation prompt builder.

Ported from gemini-realtime-translation/prompt_context.py.
Generates system instructions for the translation LLM with domain context,
glossary injection, and language-specific notes.
"""

from typing import Optional


# Domain-specific style guides
DOMAIN_STYLES = {
    "medical": "Use precise medical terminology. Maintain clinical formality. Do not add explanations.",
    "technical": "Be precise with technical terms. Use standard industry terminology. Maintain formal register.",
    "legal": "Use formal legal language. Be precise with legal terminology. Maintain official tone.",
    "business": "Use professional business language. Be clear and direct. Maintain formal politeness.",
    "casual": "Use natural, conversational language. Adapt idioms appropriately for the target culture.",
}

# Language-specific notes
LANGUAGE_NOTES = {
    "Japanese": "Respect hierarchical relationships. Formality levels should match the original.",
    "Korean": "Honorifics are important. Match the social level of the original speech.",
    "Chinese": "Context and formality matter. Traditional vs simplified depending on audience.",
    "Vietnamese": "Use appropriate pronoun equivalents. Maintain the personal/respectful tone.",
}


def build_translation_instructions(
    source: str,
    target: str,
    domain: Optional[str] = None,
    glossary: Optional[dict[str, str]] = None,
) -> str:
    """Build system instructions for the translation agent.

    Args:
        source: Source language name (e.g. "Japanese")
        target: Target language name (e.g. "Vietnamese")
        domain: Optional domain context (medical, technical, legal, business, casual)
        glossary: Optional dict of source_term -> target_term
    """
    parts: list[str] = []

    # Role
    if source.lower() == "auto":
        parts.append(
            f"You are a professional simultaneous interpreter. "
            f"Auto-detect the source language and translate into {target}."
        )
    else:
        parts.append(
            f"You are a professional simultaneous interpreter for {source} → {target}."
        )

    # Core directive
    parts.append(
        "RULES: "
        "1) Output ONLY the translation — no commentary, no romanization, no original text. "
        "2) Translate naturally and fluently, not word-by-word. "
        "3) Preserve the speaker's tone, intent, and register. "
        "4) If the input is unclear or incomplete, translate what you can and continue."
    )

    # Domain style
    if domain and domain.lower() in DOMAIN_STYLES:
        parts.append(f"DOMAIN ({domain}): {DOMAIN_STYLES[domain.lower()]}")

    # Language notes
    for lang in (source, target):
        if lang in LANGUAGE_NOTES:
            parts.append(f"{lang}: {LANGUAGE_NOTES[lang]}")

    # Glossary
    if glossary:
        entries = ", ".join(f'{k}="{v}"' for k, v in glossary.items())
        parts.append(f"TERMINOLOGY: Always use these terms: {entries}.")

    return " ".join(parts)


def build_realtime_instructions(
    source: str,
    target: str,
    domain: Optional[str] = None,
    glossary: Optional[dict[str, str]] = None,
) -> str:
    """Build instructions for realtime (end-to-end audio) translation.

    Used with OpenAI Realtime or Gemini Live where the model handles
    audio-in → audio-out directly.
    """
    base = build_translation_instructions(source, target, domain, glossary)
    return (
        base + " "
        "BEGIN OUTPUT IMMEDIATELY. Do NOT wait for audio to finish. "
        "Translate partial sentences as you hear them, then continue. "
        "Stream naturally without awkward pauses."
    )
