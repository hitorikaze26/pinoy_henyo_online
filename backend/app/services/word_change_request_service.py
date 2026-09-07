from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import GameEvent, Word, WordChangeRequest
from ..utils.time import utcnow
from . import word_service

REQUEST_COMMENT_MAX_LENGTH = 300


class WordChangeRequestError(Exception):
    status = 400
    code = "WORD_CHANGE_REQUEST_ERROR"


class RequestNotFoundError(WordChangeRequestError):
    status = 404
    code = "REQUEST_NOT_FOUND"


class RequestNotPendingError(WordChangeRequestError):
    status = 409
    code = "REQUEST_NOT_PENDING"


class RequestOwnershipError(WordChangeRequestError):
    status = 403
    code = "REQUEST_OWNERSHIP"


class RequestCommentRequiredError(WordChangeRequestError):
    status = 400
    code = "REQUEST_COMMENT_REQUIRED"


class RequestCommentTooLongError(WordChangeRequestError):
    status = 400
    code = "REQUEST_COMMENT_TOO_LONG"


class WordUnderReviewError(WordChangeRequestError):
    status = 409
    code = "WORD_UNDER_REVIEW"


class WordNotAvailableError(WordChangeRequestError):
    status = 409
    code = "WORD_NOT_AVAILABLE"


class WordNotUnderReviewError(WordChangeRequestError):
    status = 409
    code = "WORD_NOT_UNDER_REVIEW"


class TeamNotInGameError(WordChangeRequestError):
    status = 400
    code = "TEAM_NOT_IN_GAME"


class WordNotInGameError(WordChangeRequestError):
    status = 400
    code = "WORD_NOT_IN_GAME"


class GameFinishedError(WordChangeRequestError):
    status = 409
    code = "GAME_FINISHED"


def request_payload(req):
    word = req.target_word
    return {
        "id": req.id,
        "game_id": req.game_id,
        "team_id": req.team_id,
        "team_name": (
            req.requesting_team.team_name
            if req.requesting_team is not None
            else None
        ),
        "word_id": req.word_id,
        "word_text": word.word_text if word is not None else None,
        "category_id": word.category_id if word is not None else None,
        "category_name": (
            word.category.name
            if word is not None and word.category is not None
            else None
        ),
        "comment": req.comment,
        "status": req.status,
        "created_at": req.created_at,
        "resolved_at": req.resolved_at,
    }


def get_request(request_id):
    return db.session.get(WordChangeRequest, request_id)


def _assert_game_active(game):
    from ..models import Game

    if game.status in (
        Game.STATUS_CANCELLED,
        Game.STATUS_GAME_COMPLETE,
        Game.STATUS_EXPIRED,
    ):
        raise GameFinishedError(
            "The game has finished; word changes are no longer allowed."
        )


def _record_event(game, event_type, data=None):
    db.session.add(
        GameEvent(game_id=game.id, event_type=event_type, event_data=data)
    )


def create_request(game, team, word, comment):
    """Create a host-initiated word change request for a team.

    Places the target word ``UNDER_REVIEW`` so it is pulled out of the
    gameplay pool until the team resolves it or the host cancels it.
    """
    _assert_game_active(game)
    if not comment or not str(comment).strip():
        raise RequestCommentRequiredError(
            "A comment explaining the change is required."
        )
    comment = str(comment).strip()
    if len(comment) > REQUEST_COMMENT_MAX_LENGTH:
        raise RequestCommentTooLongError(
            "The comment must be at most {} characters.".format(
                REQUEST_COMMENT_MAX_LENGTH
            )
        )
    if word.game_id != game.id:
        raise WordNotInGameError("The word does not belong to this game.")
    if team.game_id != game.id:
        raise TeamNotInGameError("The team does not belong to this game.")
    if word.status == Word.STATUS_UNDER_REVIEW:
        raise WordUnderReviewError(
            "This word is already under review for a pending change."
        )
    if word.status != Word.STATUS_AVAILABLE:
        raise WordNotAvailableError(
            "Only available words can be put up for change."
        )
    pending = WordChangeRequest.query.filter_by(
        word_id=word.id,
        status=WordChangeRequest.STATUS_PENDING,
    ).first()
    if pending is not None:
        raise WordUnderReviewError(
            "This word is already under review for a pending change."
        )
    req = WordChangeRequest(
        game_id=game.id,
        team_id=team.id,
        word_id=word.id,
        comment=comment,
    )
    db.session.add(req)
    word.status = Word.STATUS_UNDER_REVIEW
    _record_event(
        game,
        "WORD_CHANGE_REQUESTED",
        {
            "request_id": req.id,
            "word_id": word.id,
            "category_id": word.category_id,
            "team_id": team.id,
        },
    )
    db.session.flush()
    return req


def resolve_request(req, team, new_text):
    """Apply the team's corrected word text and close the request.

    Only the device of the request's team may resolve. The word keeps its
    original category; standard word text/duplicate validation applies.
    """
    _assert_game_active(req.game)
    if req.status != WordChangeRequest.STATUS_PENDING:
        raise RequestNotPendingError(
            "This request is no longer pending."
        )
    if req.team_id != team.id:
        raise RequestOwnershipError(
            "Only the team that received the request can resolve it."
        )
    text = word_service.validate_word_text(new_text)
    normalized = word_service.normalize_word(text)
    word = req.target_word
    if word is None:
        raise WordNotUnderReviewError(
            "The word for this request no longer exists."
        )
    if word.status != Word.STATUS_UNDER_REVIEW:
        raise WordNotUnderReviewError(
            "This word is no longer under review."
        )
    existing = Word.query.filter(
        Word.game_id == req.game_id,
        Word.category_id == word.category_id,
        Word.normalized_word == normalized,
        Word.id != word.id,
    ).first()
    if existing is not None:
        raise word_service.DuplicateWordError(
            "Another word with the same name already exists in this category."
        )
    word.word_text = text
    word.normalized_word = normalized
    word.status = Word.STATUS_AVAILABLE
    req.status = WordChangeRequest.STATUS_RESOLVED
    req.resolved_at = utcnow()
    _record_event(
        req.game,
        "WORD_CHANGE_RESOLVED",
        {
            "request_id": req.id,
            "word_id": word.id,
            "category_id": word.category_id,
            "team_id": team.id,
        },
    )
    db.session.flush()
    return req


def cancel_request(req):
    """Cancel a pending request and return the word to the available pool."""
    _assert_game_active(req.game)
    if req.status != WordChangeRequest.STATUS_PENDING:
        raise RequestNotPendingError("This request is no longer pending.")
    req.status = WordChangeRequest.STATUS_CANCELLED
    req.resolved_at = utcnow()
    word = req.target_word
    if word is not None and word.status == Word.STATUS_UNDER_REVIEW:
        word.status = Word.STATUS_AVAILABLE
    _record_event(
        req.game,
        "WORD_CHANGE_CANCELLED",
        {
            "request_id": req.id,
            "word_id": req.word_id,
            "category_id": word.category_id if word is not None else None,
            "team_id": req.team_id,
        },
    )
    db.session.flush()
    return req


def cancel_and_detach_for_word_deleted(word):
    """Cancel pending requests targeting ``word`` and detach request history.

    Called before a word is deleted so the wishlist FK does not block the
    delete and players still holding a pending modal get notified.
    """
    pending = WordChangeRequest.query.filter_by(
        word_id=word.id,
        status=WordChangeRequest.STATUS_PENDING,
    ).all()
    for req in pending:
        req.status = WordChangeRequest.STATUS_CANCELLED
        req.resolved_at = utcnow()
    WordChangeRequest.query.filter_by(word_id=word.id).update(
        {"word_id": None}
    )
    return pending


def list_game_requests(game, team_id=None):
    query = WordChangeRequest.query.filter_by(game_id=game.id)
    if team_id is not None:
        query = query.filter_by(team_id=team_id)
    return (
        query.order_by(WordChangeRequest.id.desc())
        .options(joinedload(WordChangeRequest.target_word))
        .all()
    )


def list_team_pending(game, team):
    return (
        WordChangeRequest.query.filter_by(
            game_id=game.id,
            team_id=team.id,
            status=WordChangeRequest.STATUS_PENDING,
        )
        .order_by(WordChangeRequest.id.desc())
        .options(joinedload(WordChangeRequest.target_word))
        .all()
    )