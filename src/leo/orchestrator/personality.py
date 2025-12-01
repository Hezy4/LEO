"""Personality utilities: trait selection, mood effects, and filter prompt."""
from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from leo.memory.persona import MoodState, PersonaSettings, PersonaTrait

PERSONALITY_FILTER_ENABLED = os.getenv("LEO_PERSONALITY_FILTER", "1") not in {"0", "false", "False"}


def classify_interaction_effect(message: str) -> Optional[str]:
    """Heuristic classification of user tone to drive mood effects."""

    text = message.lower()
    if any(token in text for token in ["sorry", "apologize", "apologies", "my bad"]):
        return "apology_from_user"
    if any(token in text for token in ["thank you", "thanks", "appreciate", "great job", "nice work"]):
        return "friendly_user_message"
    if any(token in text for token in ["stupid", "idiot", "hate you", "useless", "terrible", "awful"]):
        return "hostile_user_message"
    return None


def select_top_traits(traits: Sequence[PersonaTrait], limit: int = 4) -> list[PersonaTrait]:
    """Select the most important traits as a simple relevance heuristic."""

    return sorted(traits, key=lambda t: t.importance, reverse=True)[:limit]


def blend_personality_vector(
    traits: Sequence[PersonaTrait],
) -> Dict[str, float]:
    """Blend trait coordinates using importance weighting to produce a base vector."""

    accum: Dict[str, float] = {}
    weight_sum: Dict[str, float] = {}
    for trait in traits:
        for axis, value in trait.coords.items():
            accum[axis] = accum.get(axis, 0.0) + value * trait.importance
            weight_sum[axis] = weight_sum.get(axis, 0.0) + trait.importance
    blended: Dict[str, float] = {}
    for axis, total in accum.items():
        denom = weight_sum.get(axis) or 1.0
        blended[axis] = total / denom
    return blended


def combine_with_mood(
    personality_vector: Mapping[str, float],
    mood: Mapping[str, float],
) -> Dict[str, float]:
    """Combine base personality with mood offsets (axes union)."""

    combined: Dict[str, float] = dict(personality_vector)
    for axis, value in mood.items():
        combined[axis] = combined.get(axis, 0.0) + value
    return combined


def _format_axes(label: str, axes: Mapping[str, float]) -> str:
    parts = [f"{axis}={round(val, 3)}" for axis, val in sorted(axes.items())]
    return f"{label}: " + (", ".join(parts) if parts else "none")


def build_personality_filter_prompt(
    user_message: str,
    neutral_response: str,
    combined_vector: Mapping[str, float],
    active_traits: Sequence[PersonaTrait],
    mood: MoodState,
) -> List[Dict[str, str]]:
    """Construct a post-processing prompt that rewrites the reply with personality."""

    trait_lines: List[str] = []
    for trait in active_traits:
        trait_lines.append(f"- {trait.name} (importance {round(trait.importance, 2)}): {trait.description}")
    trait_block = "\n".join(trait_lines) if trait_lines else "None selected."

    combined_desc = _format_axes("Personality+mood axes", combined_vector)
    mood_desc = _format_axes("Current mood", mood.values)

    system_prompt = (
        "You are LEO's personality filter. Rewrite the neutral response to reflect the personality "
        "and mood below while preserving meaning, facts, and any instructions. "
        "Do NOT alter tool call JSON or structured data. Keep speech-friendly plain sentences."
    )
    guidance = (
        f"{combined_desc}\n"
        f"{mood_desc}\n"
        f"Active traits:\n{trait_block}\n"
        "Guidelines:\n"
        "- Keep semantic content and commitments unchanged.\n"
        "- Keep any JSON/tool outputs verbatim if present.\n"
        "- Express the tone implied by the axes and traits; favor clarity over flourish.\n"
        "- Dry wit is acceptable when it does not reduce clarity."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": guidance},
        {"role": "user", "content": f"User said: {user_message}\nNeutral response: {neutral_response}\nRewrite the neutral response accordingly."},
    ]


__all__ = [
    "PERSONALITY_FILTER_ENABLED",
    "classify_interaction_effect",
    "select_top_traits",
    "blend_personality_vector",
    "combine_with_mood",
    "build_personality_filter_prompt",
]
