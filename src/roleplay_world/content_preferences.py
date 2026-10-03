"""Persisted authoring preferences, independent of browser/UI locale.

Language tags deliberately accept a bounded BCP-47 subset rather than free-form
prompt text. Missing metadata on old templates always retains Chinese behavior.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field


def normalize_language(value: str) -> str:
    parts = value.split("-")
    return "-".join([parts[0].lower(), *[
        part.title() if len(part) == 4 else part.upper() if len(part) == 2 else part.lower()
        for part in parts[1:]
    ]])


LanguageTag = Annotated[str, Field(pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$", max_length=35),
                        AfterValidator(normalize_language)]
LanguageChoice = LanguageTag | Literal["auto"]
CreationPreset = Literal["scene", "story", "adventure"]

# Presets constrain initial generation, never the editable maximum or game rules.
PRESETS = {
    "scene": {"locations": 1, "characters": 1, "clues": 0, "challenges": 0},
    "story": {"locations": 3, "characters": 2, "clues": 2, "challenges": 2},
    "adventure": {"locations": 4, "characters": 3, "clues": 3, "challenges": 2},
}


def language_prompt(language: str | None, *, source=False) -> str:
    if not language or language == "auto":
        rule = ("Preserve the main language of the supplied source documents. The adaptation brief may be in a different language."
                if source else "Use the main language of the author's creative brief.")
        return "\nContent language: " + rule + " Set content_language to its BCP-47 tag; never use 'auto' in authored content."
    return (f"\nContent language: {language}. Write all authored prose, names of new entities, dialogue, narration and "
            "suggestions in this language. Preserve existing proper names. Keep JSON keys, IDs and enum values unchanged. "
            "The language of the instructions, UI or individual player messages does not change the story's language.")


def content_language(state):
    return state["template"].get("content_language", "zh-CN")


def content_text(language, zh, en):
    """Built-in connective text; non-Chinese locales use English as fallback.

Authored prose is never translated by this helper. Model output follows the full
language tag, including languages beyond the two built-in UI catalogs.
    """
    return zh if language.lower().startswith("zh") else en
