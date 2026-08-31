import secrets

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Game, GameEvent
from ..utils.codes import generate_game_code
from ..utils.time import utcnow

MAX_GAME_CODE_ATTEMPTS = 10


class GameStateError(Exception):
    pass


class GameFrozenError(Exception):
    status = 409
    code = "GAME_FROZEN"

    def __init__(self, message="This game is complete and is read-only."):
        super().__init__(message)


def assert_game_mutable(game):
    """Raise if the game is terminal (complete/cancelled/expired) and read-only."""
    if game.status in (
        Game.STATUS_GAME_COMPLETE,
        Game.STATUS_CANCELLED,
        Game.STATUS_EXPIRED,
    ):
        raise GameFrozenError()


ALLOWED_TRANSITIONS = {
    Game.STATUS_LOBBY: frozenset({Game.STATUS_READY}),
    Game.STATUS_SETUP: frozenset({Game.STATUS_READY}),
    Game.STATUS_READY: frozenset({Game.STATUS_GAME_COMPLETE}),
    Game.STATUS_ROUND_1: frozenset(
        {Game.STATUS_PAUSED, Game.STATUS_GAME_COMPLETE}
    ),
    Game.STATUS_ROUND_2: frozenset(
        {Game.STATUS_PAUSED, Game.STATUS_GAME_COMPLETE}
    ),
    Game.STATUS_TIE_BREAKER: frozenset(
        {Game.STATUS_PAUSED, Game.STATUS_GAME_COMPLETE}
    ),
    Game.STATUS_PAUSED: frozenset(
        {
            Game.STATUS_ROUND_1,
            Game.STATUS_ROUND_2,
            Game.STATUS_GAME_COMPLETE,
        }
    ),
    Game.STATUS_GAME_COMPLETE: frozenset(),
    Game.STATUS_CANCELLED: frozenset(),
    Game.STATUS_EXPIRED: frozenset(),
}


def _generate_host_token():
    return secrets.token_urlsafe(32)


def _record_event(game, event_type, data=None):
    db.session.add(
        GameEvent(game_id=game.id, event_type=event_type, event_data=data)
    )


def create_game():
    for _ in range(MAX_GAME_CODE_ATTEMPTS):
        game = Game(
            game_code=generate_game_code(),
            host_session_token=_generate_host_token(),
            status=Game.STATUS_LOBBY,
        )
        db.session.add(game)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            continue
        _record_event(game, "GAME_CREATED")
        db.session.commit()
        return game
    raise RuntimeError("Could not allocate a unique game code")


def get_game(game_id):
    return db.session.get(Game, game_id)


def get_game_by_code(game_code):
    return db.session.query(Game).filter_by(game_code=game_code).first()


def _resume_target(game):
    if game.current_round == 2:
        return Game.STATUS_ROUND_2
    return Game.STATUS_ROUND_1


def _transition(game, target, event_type, apply=None):
    allowed = ALLOWED_TRANSITIONS.get(game.status, frozenset())
    if target not in allowed:
        raise GameStateError(
            "Invalid transition: game cannot move from {!r} to {!r}.".format(
                game.status, target
            )
        )
    from_status = game.status
    game.status = target
    if apply is not None:
        apply()
    _record_event(
        game,
        event_type,
        {"from_status": from_status, "to_status": target},
    )


def start_game(game):
    def _apply():
        if game.started_at is None:
            game.started_at = utcnow()

    _transition(game, Game.STATUS_READY, "GAME_STARTED", apply=_apply)
    return _status_payload(game)


def pause_game(game):
    _transition(game, Game.STATUS_PAUSED, "GAME_PAUSED")
    return _status_payload(game)


def resume_game(game):
    _transition(game, _resume_target(game), "GAME_RESUMED")
    return _status_payload(game)


def end_game(game):
    def _apply():
        if game.ended_at is None:
            game.ended_at = utcnow()

    _transition(game, Game.STATUS_GAME_COMPLETE, "GAME_ENDED", apply=_apply)
    return _status_payload(game)


def mark_game_expired(game):
    """Set a game to the EXPIRED terminal status (host absent beyond timeout)."""
    if game.status in (
        Game.STATUS_GAME_COMPLETE,
        Game.STATUS_CANCELLED,
        Game.STATUS_EXPIRED,
    ):
        return False
    game.status = Game.STATUS_EXPIRED
    if game.ended_at is None:
        game.ended_at = utcnow()
    _record_event(game, "GAME_EXPIRED", {"from_status": game.status})
    return True


def _status_payload(game):
    return {"game_id": game.id, "status": game.status}