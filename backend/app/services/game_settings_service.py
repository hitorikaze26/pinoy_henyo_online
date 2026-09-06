from ..extensions import db
from ..models import Game, GameEvent, GameSettings, Team
from ..utils.time import utcnow


class SettingsServiceError(Exception):
    status = 400
    code = "SETTINGS_SERVICE_ERROR"


class SettingsInvalidError(SettingsServiceError):
    status = 400
    code = "SETTINGS_INVALID"


class SettingsLockedError(SettingsServiceError):
    status = 409
    code = "SETTINGS_LOCKED"


_RULES = {
    "max_words_per_category": (
        GameSettings.ALLOWED_MAX_WORDS_PER_CATEGORY,
    ),
    "penalty_seconds": (GameSettings.ALLOWED_PENALTY_SECONDS,),
    "max_teams": (GameSettings.ALLOWED_MAX_TEAMS,),
    "max_members": (GameSettings.ALLOWED_MAX_MEMBERS,),
}

_LOCKED_FIELDS = GameSettings.LOCKED_FIELDS

_BOOL_FIELDS = (
    "allow_new_teams",
    "auto_approve_connections",
    "show_player_names",
    "show_role_labels",
    "show_scores",
    "show_qr_code",
    "show_round_category",
)


def create_defaults_for(game):
    """Insert the 1:1 settings row for a freshly created game."""
    settings = GameSettings(game_id=game.id)
    db.session.add(settings)
    return settings


def ensure_settings(game):
    """Return ``game.settings``, creating it in-transaction when missing.
    Covers legacy rows (games created before this table existed) and any
    fixture/unit path that builds a Game directly."""
    settings = game.settings
    if settings is None:
        settings = create_defaults_for(game)
        db.session.flush()
    return settings


def settings_locked(game):
    return game.status not in (Game.STATUS_LOBBY, Game.STATUS_SETUP)


def get_payload(game, include_game_id=True):
    settings = ensure_settings(game)
    data = {
        "max_words_per_category": settings.max_words_per_category,
        "penalty_seconds": settings.penalty_seconds,
        "allow_new_teams": bool(settings.allow_new_teams),
        "auto_approve_connections": bool(settings.auto_approve_connections),
        "max_teams": settings.max_teams,
        "max_members": settings.max_members,
        "show_player_names": bool(settings.show_player_names),
        "show_role_labels": bool(settings.show_role_labels),
        "show_scores": bool(settings.show_scores),
        "show_qr_code": bool(settings.show_qr_code),
        "show_round_category": bool(settings.show_round_category),
    }
    if include_game_id:
        data["game_id"] = game.id
    return data


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    raise SettingsInvalidError("Boolean settings must be true or false.")


def _coerce_int(value, allowed, field):
    if isinstance(value, bool):
        raise SettingsInvalidError(
            "{} must be one of {}.".format(
                field, ", ".join(str(a) for a in allowed)
            )
        )
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = None
    if number is None or number not in allowed:
        raise SettingsInvalidError(
            "{} must be one of {}.".format(
                field, ", ".join(str(a) for a in allowed)
            )
        )
    return number


def update_settings(game, data):
    """Apply a partial server-backed settings update.

    All fields are validated (enumerations + booleans). ``max_words_*``,
    ``max_teams`` and ``max_members`` are rejected once the game has left
    LOBBY/SETUP. The caller commits; realtime broadcast happens in the route.
    """
    if not isinstance(data, dict):
        raise SettingsInvalidError("Settings payload must be a JSON object.")
    settings = ensure_settings(game)
    use_lock_check = any(key in _LOCKED_FIELDS for key in data.keys())
    if use_lock_check and settings_locked(game):
        raise SettingsLockedError(
            "Game settings are locked once the game has started. "
            "Max words, max teams, and max members cannot be changed while "
            "the game is playing."
        )
    changes = {}
    for key, value in data.items():
        if key in _RULES:
            (allowed,) = _RULES[key]
            changes[key] = _coerce_int(value, allowed, key)
        elif key in _BOOL_FIELDS:
            changes[key] = _coerce_bool(value)
        else:
            raise SettingsInvalidError("Unknown setting {!r}.".format(key))
    for key, coerced in changes.items():
        setattr(settings, key, coerced)
    settings.updated_at = utcnow()
    return settings


def approve_pending_requests(game):
    """Atomically approve every team currently waiting on host approval.

    Called once when auto-approve is turned ON so the setting does not just
    apply to future requests; already-waiting teams connect immediately.
    Returns the list of teams whose status moved REQUESTED -> CONNECTED."""
    pending = Team.query.filter_by(
        game_id=game.id,
        connection_status=Team.CONNECTION_REQUESTED,
    ).all()
    approved = []
    for team in pending:
        team.connection_status = Team.CONNECTION_CONNECTED
        db.session.add(
            GameEvent(
                game_id=game.id,
                team_id=team.id,
                event_type="CONNECTION_APPROVED",
                event_data={"team_id": team.id, "member_id": None},
            )
        )
        approved.append(team)
    return approved