"""AI word-suggestion service backed by Google's Gemini API.

Additive only: this service never inserts words, changes game state, or
touches the word pool. It returns *suggestions* that the client may then
submit through the regular, authoritative word-submission endpoint
(``word_service.submit_word``), which enforces all existing rules (pool lock,
team limits, uniqueness, ownership).

Design notes
------------
* The Gemini client is created lazily on first use and reused across
  requests (module-level singleton guarded by a lock).
* ``_generate_text`` is the single I/O seam. Tests monkeypatch it so the
  service is exercised without network access or an API key.
* Output is cleaned with the same rules the word pool enforces (see
  ``word_service._validate_word_text``): alphanumerics, spaces, hyphens only,
  1..``MAX_WORD_TEXT_LENGTH`` chars. Anything else is skipped, never
  truncated — the client may still edit a suggestion before submitting.
* Results are deduplicated by normalized form, and any word already present
  in the category (DB-authoritative) or listed in the client's exclusions is
  dropped.
"""

import json
import re
import threading

from flask import current_app

from ..extensions import db
from ..models import AIGenerationLog, Word
from . import word_service

LANGUAGE_TAGALOG = "tagalog"
LANGUAGE_ENGLISH = "english"
LANGUAGE_BOTH = "both"
LANGUAGES = (LANGUAGE_TAGALOG, LANGUAGE_ENGLISH, LANGUAGE_BOTH)

_LANGUAGE_DESCRIPTIONS = {
    LANGUAGE_TAGALOG: (
        "Mostly Tagalog words (common Filipino words and short phrases), "
        "with English allowed where the Tagalog term is uncommon."
    ),
    LANGUAGE_ENGLISH: "Mostly English words (common everyday terms).",
    LANGUAGE_BOTH: (
        "A roughly even mix of Tagalog and English words — alternate rather "
        "than clustering the languages."
    ),
}


class AIServiceError(Exception):
    status = 502
    code = "AI_GENERATION_ERROR"


class AINotConfiguredError(AIServiceError):
    status = 503
    code = "AI_NOT_CONFIGURED"


class AIUnavailableError(AIServiceError):
    status = 502
    code = "AI_GENERATION_UNAVAILABLE"


class AIInvalidResponseError(AIServiceError):
    status = 502
    code = "AI_GENERATION_INVALID_RESPONSE"


# ---------------------------------------------------------------------------
# Gemini client (lazily created, reused across requests)
# ---------------------------------------------------------------------------

_gemini_client = None
_gemini_lock = threading.Lock()


def _generate_text(prompt):
    """Send ``prompt`` to Gemini and return the raw response text.

    This is the single I/O seam for the service: production talks to the real
    SDK, tests monkeypatch this function to return canned JSON.
    """
    api_key = current_app.config.get("GEMINI_API_KEY") or ""
    if not api_key:
        raise AINotConfiguredError(
            "The AI word generator is not configured. Set GEMINI_API_KEY."
        )
    global _gemini_client
    if _gemini_client is None:
        with _gemini_lock:
            if _gemini_client is None:
                import google.generativeai as genai

                genai.configure(api_key=api_key)
                _gemini_client = genai.GenerativeModel(
                    current_app.config.get("GEMINI_MODEL") or "gemini-2.0-flash"
                )
    try:
        response = _gemini_client.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json"
            ),
        )
    except Exception as exc:
        raise AIUnavailableError(
            "The AI word generator could not be reached. Try again shortly."
        ) from exc
    return response.text or ""


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------


def is_place_category(category):
    """Best-effort detection of the default "Lugar / place" category.

    Matches on the name containing "lugar" or "place" (case-insensitive).
    Words for these categories are generated as place names and the
    language preference is ignored (place names are locale-agnostic).
    """
    name = (category.name or "").lower()
    return "lugar" in name or "place" in name


def effective_language(category, language):
    return None if is_place_category(category) else (language or LANGUAGE_TAGALOG).lower()


# ---------------------------------------------------------------------------
# Suggestion generation
# ---------------------------------------------------------------------------


def available_slots(game, category, actor):
    """Remaining word slots for this actor+category, or ``None`` for the host.

    The host submits team-agnostic words, so it has no per-category cap.
    Teams are capped at ``max_words_per_category`` (default 5).
    """
    if actor.host or actor.team is None:
        return None
    used = word_service._count_active_words(
        game_id=game.id, category_id=category.id, team_id=actor.team_id
    )
    settings = game.settings
    max_words = (
        settings.max_words_per_category
        if settings is not None
        else word_service.MAX_WORDS_PER_TEAM_CATEGORY
    )
    return max(0, int(max_words) - used)


def generate_suggestions(
    game, actor, category, count, language=LANGUAGE_TAGALOG, exclude_words=None
):
    """Return up to ``count`` clean, filtered word suggestions.

    Never writes to the database. ``exclude_words`` (client-supplied) and the
    category's existing words are treated as forbidden output — both via the
    prompt and deterministically after parsing.
    """
    place = is_place_category(category)
    language = effective_language(category, language)
    prompt = _build_prompt(category, place, language, count, exclude_words)
    raw = _generate_text(prompt)
    try:
        words = _parse_response(raw)
    except AIInvalidResponseError:
        # One controlled retry on malformed output; still bad -> 502.
        raw = _generate_text(prompt)
        words = _parse_response(raw)
    suggestions = _process_suggestions(words, game, category, exclude_words)
    return {
        "category_id": category.id,
        "category_name": category.name,
        "language": language if not place else None,
        "suggestions": suggestions,
        "available_slots": available_slots(game, category, actor),
    }


def _build_prompt(category, place, language, count, exclude_words):
    max_request = current_app.config.get("AI_MAX_WORDS_PER_REQUEST", 20)
    count = max(1, min(int(count), int(max_request)))
    lines = [
        'You are a helper for "Pinoy Henyo", a Filipino guessing game.',
        "A guesser may only ask YES/NO questions, so each word must be a",
        "common, well-known single word or short phrase that players can",
        "guess from clues.",
        "",
        "Category: {}".format(category.name),
    ]
    if place:
        lines.append(
            "Word type: place names — specific well-known locations, "
            "landmarks, cities and regions, or familiar types of places."
        )
    else:
        lines.append("Languages: {}".format(_LANGUAGE_DESCRIPTIONS[language]))
    lines.extend(
        [
            "Requested count: {}".format(count),
            "",
            "Rules for every word:",
            "- a common noun, object, person type, animal, food, or thing that",
            "  clearly fits the category. Nothing obscure, made-up, or",
            "  offensive; no real specific famous people; no brand names.",
            "- between 1 and {} characters.".format(word_service.MAX_WORD_TEXT_LENGTH),
            "- only letters, digits, spaces, and hyphens. No punctuation,",
            "  quotes, emojis, or accented characters.",
        ]
    )
    forbidden = [w for w in (exclude_words or []) if isinstance(w, str) and w.strip()]
    if forbidden:
        lines.extend(
            [
                "",
                "Excluded words — never output any of these or their variants:",
                ", ".join("{}".format(w) for w in forbidden[:50]),
            ]
        )
    lines.extend(
        [
            "",
            'Return ONLY valid JSON with no commentary: {"words": [ ... ]}',
            'containing exactly {} strings.'.format(count),
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Response parsing + sanitization
# ---------------------------------------------------------------------------


def _parse_response(raw):
    """Parse ``raw`` model text into a list of strings."""
    text = str(raw or "").strip()
    if not text:
        raise AIInvalidResponseError("The AI word generator returned no output.")
    # Tolerate markdown code fences around the JSON.
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise AIInvalidResponseError(
            "The AI word generator returned unparseable output."
        ) from exc
    words = payload.get("words") if isinstance(payload, dict) else None
    if not isinstance(words, list):
        raise AIInvalidResponseError(
            'The AI word generator output was missing the "words" list.'
        )
    return words


def _process_suggestions(words, game, category, exclude_words):
    """Clean, dedupe, and drop forbidden/existing words from AI output."""
    forbidden = {
        word_service.normalize_word(w)
        for w in (exclude_words or [])
        if isinstance(w, str) and w.strip()
    }
    forbidden |= {
        w.normalized_word
        for w in Word.query.filter_by(
            game_id=game.id, category_id=category.id
        ).all()
    }

    seen = set()
    result = []
    for raw in words:
        text = _clean_word(raw)
        if text is None:
            continue
        normalized = word_service.normalize_word(text)
        if normalized in forbidden or normalized in seen:
            continue
        seen.add(normalized)
        result.append(word_service._capitalize_word(text))
    return result


def _clean_word(raw):
    text = str(raw or "").strip()
    text = " ".join(text.split())
    if not text or len(text) > word_service.MAX_WORD_TEXT_LENGTH:
        return None
    if not all(char.isalnum() or char in " -" for char in text):
        return None
    return text


# ---------------------------------------------------------------------------
# Generation log (best-effort; never raises)
# ---------------------------------------------------------------------------


def log_generation(
    game,
    actor,
    category,
    requested_count,
    accepted_count,
    success,
    language=None,
    error_code=None,
):
    """Write one ai_generation_logs row. Best-effort: never raises."""
    try:
        db.session.add(
            AIGenerationLog(
                game_id=game.id,
                actor_type=(
                    AIGenerationLog.ACTOR_HOST
                    if actor.host
                    else AIGenerationLog.ACTOR_TEAM
                ),
                actor_team_id=actor.team_id,
                category_id=category.id,
                category_name=category.name,
                language=language,
                requested_count=requested_count,
                accepted_count=accepted_count,
                success=success,
                error_code=error_code,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()