import re

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Category, DeviceSession, Game, GameEvent, Team, Word

MIN_WORDS_PER_TEAM_CATEGORY = 3
MAX_WORDS_PER_TEAM_CATEGORY = 5
MIN_WORDS_FOR_CATEGORY_READY = MIN_WORDS_PER_TEAM_CATEGORY
MAX_CATEGORY_NAME_LENGTH = 50
MAX_WORD_TEXT_LENGTH = 100

CATEGORY_NAME_PATTERN = re.compile(r"^[\w\s'()\-.,&/]+$", re.UNICODE)


class WordServiceError(Exception):
    status = 400
    code = "WORD_SERVICE_ERROR"


class CategoryNameInvalidError(WordServiceError):
    status = 400
    code = "CATEGORY_NAME_INVALID"


class DuplicateCategoryError(WordServiceError):
    status = 409
    code = "DUPLICATE_CATEGORY"


class CategoryNotFoundError(WordServiceError):
    status = 404
    code = "CATEGORY_NOT_FOUND"


class CategoryRequiredError(WordServiceError):
    status = 400
    code = "CATEGORY_REQUIRED"


class CategoryNotInGameError(WordServiceError):
    status = 400
    code = "CATEGORY_NOT_IN_GAME"


class WordNotFoundError(WordServiceError):
    status = 404
    code = "WORD_NOT_FOUND"


class WordTextInvalidError(WordServiceError):
    status = 400
    code = "WORD_TEXT_INVALID"


class TeamRequiredError(WordServiceError):
    status = 400
    code = "TEAM_REQUIRED"


class SessionRequiredError(WordServiceError):
    status = 401
    code = "SESSION_REQUIRED"


class TeamNotInGameError(WordServiceError):
    status = 400
    code = "TEAM_NOT_IN_GAME"


class SessionInvalidError(WordServiceError):
    status = 401
    code = "SESSION_INVALID"


class SessionNoTeamError(WordServiceError):
    status = 403
    code = "SESSION_NO_TEAM"


class SessionTeamMismatchError(WordServiceError):
    status = 409
    code = "SESSION_TEAM_MISMATCH"


class WordLimitExceededError(WordServiceError):
    status = 409
    code = "WORD_LIMIT_EXCEEDED"


class DuplicateWordError(WordServiceError):
    status = 409
    code = "DUPLICATE_WORD"


class WordLockedError(WordServiceError):
    status = 409
    code = "WORD_LOCKED"


class WordOwnershipError(WordServiceError):
    status = 409
    code = "WORD_OWNERSHIP"


class GameRuleError(WordServiceError):
    status = 409
    code = "GAME_RULE"


class Actor:
    def __init__(self, host=False, team=None):
        self.host = host
        self.team = team

    @property
    def team_id(self):
        if self.team is None:
            return None
        return self.team.id


def normalize_word(text):
    """Collapse whitespace and lowercase for duplicate comparison."""
    return " ".join(str(text or "").strip().split()).lower()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _validate_category_name(name):
    name = " ".join(str(name or "").strip().split())
    if not name or len(name) > MAX_CATEGORY_NAME_LENGTH:
        raise CategoryNameInvalidError(
            "Category name must be 1-{} characters and not blank.".format(
                MAX_CATEGORY_NAME_LENGTH
            )
        )
    if not CATEGORY_NAME_PATTERN.fullmatch(name):
        raise CategoryNameInvalidError(
            "Category name contains unsupported characters."
        )
    return name


def get_category(category_id):
    return db.session.get(Category, category_id)


def create_category(game, name):
    name = _validate_category_name(name)
    normalized = name.lower()
    for other in Category.query.filter_by(game_id=game.id).all():
        if other.name.lower() == normalized:
            raise DuplicateCategoryError(
                "A category with this name already exists."
            )
    category = Category(game_id=game.id, name=name)
    db.session.add(category)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise DuplicateCategoryError(
            "A category with this name already exists."
        )
    _record_event(
        game, "CATEGORY_CREATED", {"category_id": category.id, "name": name}
    )
    return category


def update_category(category, name):
    name = _validate_category_name(name)
    normalized = name.lower()
    for other in Category.query.filter(
        Category.game_id == category.game_id,
        Category.id != category.id,
    ).all():
        if other.name.lower() == normalized:
            raise DuplicateCategoryError(
                "A category with this name already exists."
            )
    category.name = name
    return category


def delete_category(category):
    game = category.game
    category_id, name = category.id, category.name
    db.session.delete(category)
    _record_event(
        game, "CATEGORY_DELETED", {"category_id": category_id, "name": name}
    )


def list_categories(game):
    items = []
    for category in (
        Category.query.filter_by(game_id=game.id).order_by(Category.name).all()
    ):
        word_count = _count_active_words(
            game_id=game.id, category_id=category.id
        )
        items.append(
            {
                "category_id": category.id,
                "name": category.name,
                "game_id": category.game_id,
                "word_count": word_count,
                "ready": word_count >= MIN_WORDS_FOR_CATEGORY_READY,
                "created_at": category.created_at,
            }
        )
    return items


DEFAULT_CATEGORY_NAMES = [
    "Tao / People",
    "Bagay / things / object",
    "Lugar / place",
    "Hayop / animal",
    "Pagkain / food",
    "Other",
]


def ensure_default_categories(game):
    """Create the default categories for a game that currently has none.

    Idempotent: only inserts when the game has zero categories, so it also
    upgrades pre-existing games on their first words-page load. Returns the
    full category payload list (including any newly created defaults).
    """
    if Category.query.filter_by(game_id=game.id).count() == 0:
        for name in DEFAULT_CATEGORY_NAMES:
            category = Category(game_id=game.id, name=name)
            db.session.add(category)
            try:
                db.session.flush()
            except IntegrityError:
                db.session.rollback()
                raise DuplicateCategoryError(
                    "A category with this name already exists."
                )
            _record_event(
                game,
                "CATEGORY_CREATED",
                {"category_id": category.id, "name": name},
            )
    return list_categories(game)


def category_payload(category):
    return {
        "category_id": category.id,
        "name": category.name,
        "game_id": category.game_id,
        "created_at": category.created_at,
    }


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def _validate_word_text(text):
    text = " ".join(str(text or "").strip().split())
    if not text or len(text) > MAX_WORD_TEXT_LENGTH:
        raise WordTextInvalidError(
            "Word text must be 1-{} characters and not blank.".format(
                MAX_WORD_TEXT_LENGTH
            )
        )
    return text


def _count_active_words(game_id, category_id, team_id=None):
    query = Word.query.filter(
        Word.game_id == game_id,
        Word.category_id == category_id,
        Word.status != Word.STATUS_DISABLED,
    )
    if team_id is not None:
        query = query.filter(Word.submitted_by_team_id == team_id)
    return query.count()


def _ensure_unlocked(game):
    if word_pool_locked(game):
        raise WordLockedError(
            "The word pool is locked; words can no longer be modified."
        )


def word_pool_locked(game):
    return game.status not in (Game.STATUS_LOBBY, Game.STATUS_SETUP)


def resolve_submitting_team(game, session_token=None, team_id=None):
    """Resolve the acting team for a player-initiated word operation.

    A valid, active session token is mandatory. A bare ``team_id`` sent by an
    unauthenticated client is rejected (``SESSION_REQUIRED``) to prevent
    enumerating other teams' ids. The ``team_id`` field may only be used to
    double-check the caller's own session team.
    """
    if not session_token:
        raise SessionRequiredError(
            "A team session token is required to submit or manage words."
        )
    session = DeviceSession.query.filter_by(
        game_id=game.id, session_token=session_token
    ).first()
    if session is None or session.disconnected_at is not None:
        raise SessionInvalidError(
            "The session token is invalid or inactive."
        )
    if session.team_id is None:
        raise SessionNoTeamError(
            "The session is not linked to a team."
        )
    team = session.team
    if team_id is not None and team_id != team.id:
        raise SessionTeamMismatchError(
            "The provided team does not match the active session."
        )
    return team


def resolve_team_for_host(game, team_id):
    """Resolve a team for a host-authorized word operation."""
    team = db.session.get(Team, team_id) if team_id is not None else None
    if team is None or team.game_id != game.id:
        raise TeamNotInGameError("The team does not belong to this game.")
    return team


def get_word(word_id):
    return db.session.get(Word, word_id)


def submit_word(game, team, category_id, word_text, host=False):
    if category_id is None:
        raise CategoryRequiredError("A category is required.")
    category = db.session.get(Category, category_id)
    if category is None or category.game_id != game.id:
        raise CategoryNotInGameError(
            "The category does not belong to this game."
        )
    text = _validate_word_text(word_text)
    normalized = normalize_word(text)
    if team is None:
        raise TeamRequiredError("A submitting team is required.")
    _ensure_unlocked(game)

    existing = Word.query.filter_by(
        game_id=game.id,
        category_id=category.id,
        normalized_word=normalized,
    ).first()
    if existing is not None:
        raise DuplicateWordError(
            "This word has already been submitted for this category."
        )
    count = _count_active_words(
        game_id=game.id, category_id=category.id, team_id=team.id
    )
    if count >= MAX_WORDS_PER_TEAM_CATEGORY:
        raise WordLimitExceededError(
            "A team can submit at most {} words per category.".format(
                MAX_WORDS_PER_TEAM_CATEGORY
            )
        )

    word = Word(
        game_id=game.id,
        category_id=category.id,
        submitted_by_team_id=team.id,
        word_text=text,
        normalized_word=normalized,
    )
    db.session.add(word)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise DuplicateWordError(
            "This word has already been submitted for this category."
        )
    _record_event(
        game,
        "WORD_SUBMITTED",
        {
            "word_id": word.id,
            "category_id": category.id,
            "team_id": team.id,
        },
    )
    return word


def _authorize_modify(game, word, actor):
    _ensure_unlocked(game)
    if actor is None or actor.host:
        return
    if actor.team_id != word.submitted_by_team_id:
        raise WordOwnershipError(
            "A team can only modify or delete its own submitted words."
        )


def update_word(word, game, new_text, actor, category_id=None):
    _authorize_modify(game, word, actor)
    if category_id is not None:
        category = db.session.get(Category, category_id)
    else:
        category = db.session.get(Category, word.category_id)
    if category is None or category.game_id != game.id:
        raise CategoryNotInGameError(
            "The category does not belong to this game."
        )
    text = _validate_word_text(new_text)
    normalized = normalize_word(text)
    existing = Word.query.filter(
        Word.game_id == game.id,
        Word.category_id == category.id,
        Word.normalized_word == normalized,
        Word.id != word.id,
    ).first()
    if existing is not None:
        raise DuplicateWordError(
            "Another word with the same name already exists in this category."
        )
    word.word_text = text
    word.normalized_word = normalized
    if category_id is not None:
        word.category_id = category.id
    _record_event(
        game,
        "WORD_UPDATED",
        {
            "word_id": word.id,
            "category_id": word.category_id,
            "team_id": word.submitted_by_team_id,
        },
    )
    return word


def disable_word(word, game, actor):
    _authorize_modify(game, word, actor)
    word.status = Word.STATUS_DISABLED
    _record_event(
        game,
        "WORD_DISABLED",
        {
            "word_id": word.id,
            "category_id": word.category_id,
            "team_id": word.submitted_by_team_id,
        },
    )
    return word


def delete_word(word, game, actor):
    _authorize_modify(game, word, actor)
    _record_event(
        game,
        "WORD_DELETED",
        {
            "word_id": word.id,
            "category_id": word.category_id,
            "team_id": word.submitted_by_team_id,
        },
    )
    db.session.delete(word)


def list_words(game):
    words = (
        Word.query.filter_by(game_id=game.id)
        .options(joinedload(Word.category), joinedload(Word.submitting_team))
        .order_by(Word.id)
        .all()
    )
    return [word_payload(word, with_relations=True) for word in words]


def word_payload(word, with_relations=False):
    payload = {
        "word_id": word.id,
        "word_text": word.word_text,
        "normalized_word": word.normalized_word,
        "status": word.status,
        "category_id": word.category_id,
        "submitted_by_team_id": word.submitted_by_team_id,
        "game_id": word.game_id,
        "created_at": word.created_at,
        "updated_at": word.updated_at,
    }
    if with_relations:
        payload["category_name"] = (
            word.category.name if word.category is not None else None
        )
        payload["team_name"] = (
            word.submitting_team.team_name
            if word.submitting_team is not None
            else None
        )
    return payload


# ---------------------------------------------------------------------------
# Game rule: a team must never receive a word it submitted itself
# ---------------------------------------------------------------------------


def word_can_be_received(word, active_team_id):
    return word.submitted_by_team_id != active_team_id


def assert_word_assignable(word, active_team_id):
    if word.submitted_by_team_id == active_team_id:
        raise GameRuleError(
            "A team can never receive a word it submitted itself."
        )
    return True


def _record_event(game, event_type, data=None):
    db.session.add(
        GameEvent(game_id=game.id, event_type=event_type, event_data=data)
    )