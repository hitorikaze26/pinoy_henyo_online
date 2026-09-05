import random

from sqlalchemy import func

from ..extensions import db
from ..models import (
    Category,
    DeviceSession,
    Game,
    GameEvent,
    Match,
    Penalty,
    Round,
    RoundCategory,
    Score,
    Team,
    TeamMember,
    Turn,
    TurnWord,
    Word,
)
from ..utils.time import utcnow

ROUND_1 = 1
ROUND_2 = 2
ROUND_3 = 3
ROUND_NUMBERS = (ROUND_1, ROUND_2, ROUND_3)
MAX_WORDS_PER_TURN = 5
MAX_TIMER_SECONDS = 300


def _record_event(game, event_type, data=None, team_id=None, member_id=None):
    db.session.add(
        GameEvent(
            game_id=game.id,
            team_id=team_id,
            member_id=member_id,
            event_type=event_type,
            event_data=data,
        )
    )


class GameplayServiceError(Exception):
    status = 400
    code = "GAMEPLAY_SERVICE_ERROR"


class RoleInvalidError(GameplayServiceError):
    status = 400
    code = "ROLE_INVALID"


class MemberNotInTeamError(GameplayServiceError):
    status = 400
    code = "MEMBER_NOT_IN_TEAM"


class DuplicateManghuhulaError(GameplayServiceError):
    status = 409
    code = "DUPLICATE_MANGHUHULA"


class RoleLockedError(GameplayServiceError):
    status = 409
    code = "ROLE_LOCKED"


class RoundNumberInvalidError(GameplayServiceError):
    status = 400
    code = "ROUND_NUMBER_INVALID"


class TimerConfigurationError(GameplayServiceError):
    status = 400
    code = "TIMER_CONFIG_INVALID"


class RoundExistsError(GameplayServiceError):
    status = 409
    code = "ROUND_EXISTS"


class RoundNotFoundError(GameplayServiceError):
    status = 404
    code = "ROUND_NOT_FOUND"


class RoundTimerLockedError(GameplayServiceError):
    status = 409
    code = "ROUND_TIMER_LOCKED"


class NextRoundMissingError(GameplayServiceError):
    status = 409
    code = "NEXT_ROUND_MISSING"


class CategoriesRequiredError(GameplayServiceError):
    status = 400
    code = "CATEGORIES_REQUIRED"


class CategoryNotInGameError(GameplayServiceError):
    status = 400
    code = "CATEGORY_NOT_IN_GAME"


class RoundCategoryNotAllowedError(GameplayServiceError):
    status = 409
    code = "ROUND_CATEGORY_NOT_ALLOWED"


class MatchesRequiredError(GameplayServiceError):
    status = 400
    code = "MATCHES_REQUIRED"


class MatchesExistError(GameplayServiceError):
    status = 409
    code = "MATCHES_EXIST"


class TeamNotInGameError(GameplayServiceError):
    status = 400
    code = "TEAM_NOT_IN_GAME"


class DuplicateTeamInRoundError(GameplayServiceError):
    status = 400
    code = "DUPLICATE_TEAM_IN_ROUND"


class MatchNotFoundError(GameplayServiceError):
    status = 404
    code = "MATCH_NOT_FOUND"


class MatchOrderInvalidError(GameplayServiceError):
    status = 400
    code = "MATCH_ORDER_INVALID"


class MatchReorderLockedError(GameplayServiceError):
    status = 409
    code = "MATCH_REORDER_LOCKED"


class TurnParamsInvalidError(GameplayServiceError):
    status = 400
    code = "TURN_PARAMS_INVALID"


class WordNotInGameError(GameplayServiceError):
    status = 400
    code = "WORD_NOT_IN_GAME"


class WordNotInRoundError(GameplayServiceError):
    status = 409
    code = "WORD_NOT_IN_ROUND"


class WordOwnTeamError(GameplayServiceError):
    status = 409
    code = "WORD_OWN_TEAM"


class WordAlreadyAssignedError(GameplayServiceError):
    status = 409
    code = "WORD_ALREADY_ASSIGNED"


class InsufficientWordsError(GameplayServiceError):
    status = 400
    code = "INSUFFICIENT_WORDS"


class WordLimitExceededError(GameplayServiceError):
    status = 400
    code = "WORD_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# Team roles
# ---------------------------------------------------------------------------


def get_round(game, round_number):
    return Round.query.filter_by(
        game_id=game.id, round_number=round_number
    ).first()


def list_game_rounds(game):
    return (
        Round.query.filter_by(game_id=game.id)
        .order_by(Round.round_number)
        .all()
    )


def update_round_timer(game, round_number, timer_seconds, timer_mode):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    if round_obj.started_at is not None:
        raise RoundTimerLockedError(
            "The timer cannot be changed once the round has started."
        )
    if timer_seconds is None and not timer_mode:
        raise TimerConfigurationError(
            "Provide timer_seconds and/or timer_mode."
        )
    if timer_seconds is not None:
        if (
            not isinstance(timer_seconds, int)
            or isinstance(timer_seconds, bool)
            or timer_seconds < 1
            or timer_seconds > MAX_TIMER_SECONDS
        ):
            raise TimerConfigurationError(
                "timer_seconds must be an integer between 1 and {}.".format(
                    MAX_TIMER_SECONDS
                )
            )
        round_obj.timer_seconds = timer_seconds
    if timer_mode:
        if timer_mode not in Round.TIMER_MODES:
            raise TimerConfigurationError(
                "timer_mode must be one of {}.".format(
                    ", ".join(Round.TIMER_MODES)
                )
            )
        round_obj.timer_mode = timer_mode
    _record_event(
        game,
        "ROUND_TIMER_CHANGED",
        {
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
            "timer_seconds": round_obj.timer_seconds,
            "timer_mode": round_obj.timer_mode,
        },
    )
    return round_obj


def advance_round(game, round_number):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    next_number = round_number + 1
    next_round = get_round(game, next_number)
    if next_round is None:
        raise NextRoundMissingError(
            "Round {} has not been set up yet.".format(next_number)
        )
    ensure_round_matches(game, next_round)
    if not next_round.matches:
        raise NextRoundMissingError(
            "Round {} has no matches yet.".format(next_number)
        )
    if round_obj.ended_at is None:
        round_obj.status = Round.STATUS_COMPLETED
        round_obj.ended_at = utcnow()
    for match in list(round_obj.matches):
        if match.status != Match.STATUS_COMPLETED:
            for turn in match.turns:
                if turn.status in (Turn.STATUS_ACTIVE, Turn.STATUS_PAUSED):
                    turn.status = Turn.STATUS_FAILED
                    turn.ended_at = utcnow()
            match.status = Match.STATUS_COMPLETED
            match.ended_at = utcnow()
    game.current_round = next_number
    first = (
        Match.query.filter_by(round_id=next_round.id)
        .order_by(Match.match_order)
        .first()
    )
    game.current_match_id = first.id if first is not None else None
    _record_event(
        game,
        "ROUND_ADVANCED",
        {
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
            "next_round": next_number,
        },
    )
    return next_round


def reset_round(game, round_number):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    turn_ids = [
        turn.id
        for turn in Turn.query.filter_by(round_id=round_obj.id).all()
    ]
    if turn_ids:
        TurnWord.query.filter(
            TurnWord.turn_id.in_(turn_ids)
        ).delete(synchronize_session=False)
        Penalty.query.filter(
            Penalty.turn_id.in_(turn_ids)
        ).delete(synchronize_session=False)
    Turn.query.filter_by(round_id=round_obj.id).delete(
        synchronize_session=False
    )
    Score.query.filter_by(
        game_id=game.id, round_id=round_obj.id
    ).delete(synchronize_session=False)
    for match in list(round_obj.matches):
        match.status = Match.STATUS_PENDING
        match.started_at = None
        match.ended_at = None
        match.winner_team_id = None
    round_obj.status = Round.STATUS_PENDING
    round_obj.started_at = None
    round_obj.ended_at = None
    if game.current_match_id is not None and any(
        match.id == game.current_match_id for match in round_obj.matches
    ):
        game.current_match_id = None
    _record_event(
        game,
        "ROUND_RESET",
        {
            "round_id": round_obj.id,
            "round_number": round_obj.round_number,
        },
    )
    return round_obj


def session_is_team_leader(team, session_token):
    if not session_token:
        return False
    session = DeviceSession.query.filter_by(
        session_token=session_token, disconnected_at=None
    ).first()
    if session is None or session.team_id != team.id or session.member_id is None:
        return False
    member = session.member
    return member.device_role == TeamMember.DEVICE_ROLE_TEAM_LEADER


def assign_member_role(game, team, member_id, gameplay_role):
    if game.status in (Game.STATUS_GAME_COMPLETE, Game.STATUS_CANCELLED):
        raise RoleLockedError(
            "Roles cannot be changed once the game is finished."
        )
    member = TeamMember.query.filter_by(id=member_id, team_id=team.id).first()
    if member is None:
        raise MemberNotInTeamError("The member does not belong to this team.")
    if gameplay_role is None:
        raise RoleInvalidError("A gameplay role is required.")
    if gameplay_role not in TeamMember.GAMEPLAY_ROLES:
        raise RoleInvalidError(
            "gameplay_role must be one of: {}.".format(
                ", ".join(TeamMember.GAMEPLAY_ROLES)
            )
        )
    if gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA:
        existing = TeamMember.query.filter(
            TeamMember.team_id == team.id,
            TeamMember.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA,
            TeamMember.id != member.id,
        ).first()
        if existing is not None:
            raise DuplicateManghuhulaError(
                "This team already has an active Manghuhula."
            )
    member.gameplay_role = gameplay_role
    _record_event(
        game,
        "ROLE_CHANGED",
        {
            "member_id": member.id,
            "team_id": team.id,
            "gameplay_role": gameplay_role,
        },
        team_id=team.id,
        member_id=member.id,
    )
    return member


# ---------------------------------------------------------------------------
# Rounds & category selection
# ---------------------------------------------------------------------------


def create_round(game, round_number, timer_seconds=60, timer_mode=None):
    if round_number not in ROUND_NUMBERS:
        raise RoundNumberInvalidError(
            "round_number must be 1, 2, or 3."
        )
    if get_round(game, round_number) is not None:
        raise RoundExistsError(
            "This round already exists for the game."
        )
    timer = timer_seconds if timer_seconds is not None else 60
    if not isinstance(timer, int) or timer < 1 or timer > MAX_TIMER_SECONDS:
        raise TimerConfigurationError(
            "timer_seconds must be between 1 and {}.".format(MAX_TIMER_SECONDS)
        )
    mode = timer_mode or Round.TIMER_MODE_COUNTDOWN
    if mode not in Round.TIMER_MODES:
        raise TimerConfigurationError(
            "timer_mode must be one of {}.".format(", ".join(Round.TIMER_MODES))
        )
    round_obj = Round(
        game_id=game.id,
        round_number=round_number,
        timer_seconds=timer,
        timer_mode=mode,
    )
    db.session.add(round_obj)
    return round_obj


def select_round_categories(game, round_number, category_ids):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    if round_number != ROUND_1:
        raise RoundCategoryNotAllowedError(
            "Category selection is only allowed for Round 1."
        )
    category_ids = list(dict.fromkeys(category_ids or []))
    if not category_ids:
        raise CategoriesRequiredError(
            "At least one category must be selected."
        )
    selected_ids = set(category_ids)
    categories = Category.query.filter(
        Category.game_id == game.id,
        Category.id.in_(category_ids),
    ).all()
    if len(categories) != len(category_ids):
        raise CategoryNotInGameError(
            "One or more categories do not belong to this game."
        )
    RoundCategory.query.filter_by(round_id=round_obj.id).delete()
    for category_id in category_ids:
        db.session.add(RoundCategory(round_id=round_obj.id, category_id=category_id))
    # Bulk-assign words so round membership is driven by each word's
    # `assigned_round` (per-word control). The picker is a shortcut: words in
    # the selected categories go to Round 1, everything else to Round 2.
    Word.query.filter(
        Word.game_id == game.id,
        Word.category_id.in_(selected_ids),
    ).update(
        {Word.assigned_round: ROUND_1}, synchronize_session=False
    )
    Word.query.filter(
        Word.game_id == game.id,
        ~Word.category_id.in_(selected_ids),
    ).update(
        {Word.assigned_round: ROUND_2}, synchronize_session=False
    )
    db.session.flush()
    db.session.expire_all()
    return round_obj


def list_round_categories(game, round_number):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    if round_number == ROUND_2:
        categories = (
            Category.query.filter_by(game_id=game.id)
            .order_by(Category.name)
            .all()
        )
    else:
        selected_ids = [
            rc.category_id for rc in round_obj.selected_categories
        ]
        categories = (
            Category.query.filter(Category.id.in_(selected_ids))
            .order_by(Category.name)
            .all()
        )
    return _category_payloads(categories)


def _category_payloads(categories):
    from ..services.word_service import category_payload

    return [category_payload(category) for category in categories]


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def _validate_game_team(game, team_id):
    team = db.session.get(Team, team_id) if team_id is not None else None
    if team is None or team.game_id != game.id:
        raise TeamNotInGameError("The team does not belong to this game.")
    return team


def create_round_matches(game, round_number, match_entries):
    round_obj = get_round(game, round_number)
    if round_obj is None:
        raise RoundNotFoundError("The round has not been set up yet.")
    match_entries = match_entries or []
    if not match_entries:
        raise MatchesRequiredError("At least one match entry is required.")
    existing = Match.query.filter_by(round_id=round_obj.id).count()
    if existing:
        raise MatchesExistError(
            "Matches are already defined for this round."
        )
    seen = set()
    for entry in match_entries:
        team = _validate_game_team(game, entry.get("team_id"))
        if team.id in seen:
            raise DuplicateTeamInRoundError(
                "Each team can appear at most once per round."
            )
        seen.add(team.id)
        opponent = _validate_game_team(game, entry.get("opponent_team_id"))
        if opponent is not None and opponent.id == team.id:
            raise DuplicateTeamInRoundError(
                "A team cannot play against itself."
            )
    matches = []
    for index, entry in enumerate(match_entries, start=1):
        match = Match(
            game_id=game.id,
            round_id=round_obj.id,
            match_order=index,
            team_id=entry["team_id"],
            opponent_team_id=entry.get("opponent_team_id"),
        )
        db.session.add(match)
        matches.append(match)
    return matches


def ensure_round_matches(game, round_obj):
    """Idempotently create one single-team play slot per team for a round.

    In this model a match is simply a team's turn slot (no opposing team).
    Slots are ordered by team join order and appended after any matches that
    were already defined so a manual order survives.
    """
    matched_team_ids = {
        team_id
        for (team_id,) in db.session.query(Match.team_id)
        .filter_by(round_id=round_obj.id)
        .all()
    }
    query = Team.query.filter_by(game_id=game.id)
    if matched_team_ids:
        query = query.filter(~Team.id.in_(matched_team_ids))
    missing = query.order_by(Team.id).all()
    if not missing:
        return []
    max_order = (
        db.session.query(func.max(Match.match_order))
        .filter_by(round_id=round_obj.id)
        .scalar()
    )
    max_order = max_order or 0
    matches = []
    for index, team in enumerate(missing, start=max_order + 1):
        match = Match(
            game_id=game.id,
            round_id=round_obj.id,
            match_order=index,
            team_id=team.id,
            opponent_team_id=None,
        )
        db.session.add(match)
        matches.append(match)
    return matches


def ensure_game_setup(game):
    """Create Round 1/2 and each team's play slot for both rounds.

    Runs when the host starts the game so the dashboard can immediately pick
    the playing team from the Current Turn dropdown with no manual setup.
    """
    created = {"rounds": [], "matches": []}
    for round_number in (ROUND_1, ROUND_2):
        round_obj = get_round(game, round_number)
        if round_obj is None:
            round_obj = Round(
                game_id=game.id,
                round_number=round_number,
                timer_seconds=60,
                timer_mode=Round.TIMER_MODE_COUNTDOWN,
            )
            db.session.add(round_obj)
            db.session.flush()
            created["rounds"].append(round_number)
        created["matches"].extend(ensure_round_matches(game, round_obj))
    return created


def reorder_match(match, new_order):
    if match.round.status != Round.STATUS_PENDING:
        raise MatchReorderLockedError(
            "Matches can only be reordered before the round begins."
        )
    if (
        new_order is None
        or not isinstance(new_order, int)
        or isinstance(new_order, bool)
        or new_order < 1
    ):
        raise MatchOrderInvalidError("match_order must be a positive integer.")
    old_order = match.match_order
    if old_order == new_order:
        return match
    sibling = Match.query.filter_by(
        round_id=match.round_id, match_order=new_order
    ).first()
    if sibling is not None and sibling.id != match.id:
        # Vacate one position first to avoid a unique-constraint collision.
        sibling.match_order = -1
        db.session.flush()
        match.match_order = new_order
        sibling.match_order = old_order
    else:
        match.match_order = new_order
    return match


def list_game_matches(game):
    matches = (
        Match.query.filter_by(game_id=game.id)
        .join(Round, Round.id == Match.round_id)
        .order_by(Round.round_number, Match.match_order, Match.id)
        .all()
    )
    return matches


# ---------------------------------------------------------------------------
# Word assignment
# ---------------------------------------------------------------------------


def _round_word_pool(match):
    round_obj = match.round
    query = Word.query.filter(
        Word.game_id == match.game_id,
        Word.status != Word.STATUS_DISABLED,
    )
    # Rounds 1 and 2 pull only from the words assigned to them. Tie-break and
    # any extra rounds fall back to the full pool.
    if round_obj.round_number in (ROUND_1, ROUND_2):
        query = query.filter(Word.assigned_round == round_obj.round_number)
    return [
        word
        for word in query.all()
        if word.submitted_by_team_id != match.team_id
    ]


def _used_word_ids(match):
    used = set()
    for turn in match.turns:
        for turn_word in turn.turn_words:
            used.add(turn_word.word_id)
    return used


def assign_turn_words(match, word_ids=None, count=None):
    if word_ids is None and count is None:
        raise TurnParamsInvalidError(
            "Provide either word_ids or count."
        )
    used = _used_word_ids(match)
    round_obj = match.round

    if word_ids is not None:
        if not word_ids:
            raise TurnParamsInvalidError("word_ids must not be empty.")
        candidates = set()
        for word_id in word_ids:
            word = db.session.get(Word, word_id)
            if word is None or word.game_id != match.game_id:
                raise WordNotInGameError(
                    "The word does not belong to this game."
                )
            if (
                round_obj.round_number in (ROUND_1, ROUND_2)
                and word.assigned_round != round_obj.round_number
            ):
                raise WordNotInRoundError(
                    "Round {} can only use words assigned to it.".format(
                        round_obj.round_number
                    )
                )
            if word.submitted_by_team_id == match.team_id:
                raise WordOwnTeamError(
                    "A team can never receive a word it submitted itself."
                )
            if word.id in used or word.id in candidates:
                raise WordAlreadyAssignedError(
                    "A word can be assigned at most once per match."
                )
            candidates.add(word.id)
        chosen = [
            db.session.get(Word, word_id) for word_id in word_ids
        ]
    else:
        available = [
            word for word in _round_word_pool(match) if word.id not in used
        ]
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
        ):
            raise TurnParamsInvalidError("count must be a positive integer.")
        if len(available) < count:
            raise InsufficientWordsError(
                "Not enough eligible words remain for this match."
            )
        if count > MAX_WORDS_PER_TURN:
            raise WordLimitExceededError(
                "A turn can contain at most {} words.".format(
                    MAX_WORDS_PER_TURN
                )
            )
        chosen = random.sample(available, count)

    if len(chosen) > MAX_WORDS_PER_TURN:
        raise WordLimitExceededError(
            "A turn can contain at most {} words.".format(MAX_WORDS_PER_TURN)
        )

    turn_order = (
        db.session.query(db.func.max(Turn.turn_order))
        .filter_by(match_id=match.id)
        .scalar()
        or 0
    ) + 1
    turn = Turn(
        match_id=match.id,
        team_id=match.team_id,
        round_id=match.round_id,
        turn_order=turn_order,
        status=Turn.STATUS_WAITING,
    )
    db.session.add(turn)
    db.session.flush()
    for index, word in enumerate(chosen, start=1):
        db.session.add(
            TurnWord(turn_id=turn.id, word_id=word.id, sequence=index)
        )
    turn.current_word_id = chosen[0].id
    return turn


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def readiness(game):
    issues = []

    active_teams = Team.query.filter_by(
        game_id=game.id, status=Team.STATUS_ACTIVE
    ).all()
    if len(active_teams) < 2:
        issues.append("At least two active teams are required.")
    for team in active_teams:
        label = "#{} ({})".format(team.team_code, team.team_name)
        if team.leader_member_id is None:
            issues.append("Team {} has no team leader.".format(label))
        if not any(
            member.gameplay_role == TeamMember.GAMEPLAY_ROLE_MANGHUHULA
            for member in team.members
        ):
            issues.append(
                "Team {} has no Manghuhula assigned.".format(label)
            )
        if not any(
            member.gameplay_role == TeamMember.GAMEPLAY_ROLE_TAGASAGOT
            for member in team.members
        ):
            issues.append(
                "Team {} has no Tagasagot assigned.".format(label)
            )

    category_count = (
        db.session.query(Category.id)
        .join(Word, Word.category_id == Category.id)
        .filter(
            Category.game_id == game.id,
            Word.status != Word.STATUS_DISABLED,
        )
        .distinct()
        .count()
    )
    if category_count == 0:
        issues.append("No configured categories have any words.")

    rounds = (
        Round.query.filter_by(game_id=game.id)
        .order_by(Round.round_number)
        .all()
    )
    if not rounds:
        issues.append("No rounds have been set up.")
    for round_obj in rounds:
        label = "Round {}".format(round_obj.round_number)
        round_word_count = (
            Word.query.filter(
                Word.game_id == game.id,
                Word.status != Word.STATUS_DISABLED,
                Word.assigned_round == round_obj.round_number,
            ).count()
        )
        if round_word_count == 0:
            issues.append("{} has no assigned words.".format(label))
        matches = (
            Match.query.filter_by(round_id=round_obj.id)
            .order_by(Match.match_order)
            .all()
        )
        if not matches:
            issues.append("{0} has no matches.".format(label))
        for match in matches:
            match_label = "{} match #{}".format(label, match.match_order)
            assigned_words = [
                turn_word
                for turn in match.turns
                for turn_word in turn.turn_words
            ]
            if not assigned_words:
                issues.append(
                    "{} has no assigned words.".format(match_label)
                )
            for turn_word in assigned_words:
                word = turn_word.word
                if word.submitted_by_team_id == match.team_id:
                    issues.append(
                        "{} contains a word submitted by the guessing team itself.".format(
                            match_label
                        )
                    )

    return {"ready": not issues, "issues": issues}


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def round_payload(round_obj):
    return {
        "round_id": round_obj.id,
        "game_id": round_obj.game_id,
        "round_number": round_obj.round_number,
        "status": round_obj.status,
        "timer_seconds": round_obj.timer_seconds,
        "timer_mode": round_obj.timer_mode,
        "started_at": round_obj.started_at,
        "ended_at": round_obj.ended_at,
        "created_at": round_obj.created_at,
        "selected_category_ids": sorted(
            rc.category_id for rc in round_obj.selected_categories
        ),
    }


def match_payload(match):
    return {
        "match_id": match.id,
        "game_id": match.game_id,
        "round_id": match.round_id,
        "round_number": match.round.round_number,
        "match_order": match.match_order,
        "team_id": match.team_id,
        "opponent_team_id": match.opponent_team_id,
        "winner_team_id": match.winner_team_id,
        "status": match.status,
        "turn_count": len(match.turns),
    }


def turn_payload(turn):
    words = [
        {
            "word_id": turn_word.word_id,
            "word_text": turn_word.word.word_text,
            "sequence": turn_word.sequence,
            "result": turn_word.result,
        }
        for turn_word in sorted(
            turn.turn_words, key=lambda item: item.sequence
        )
    ]
    return {
        "turn_id": turn.id,
        "match_id": turn.match_id,
        "team_id": turn.team_id,
        "round_id": turn.round_id,
        "turn_order": turn.turn_order,
        "status": turn.status,
        "current_word_id": turn.current_word_id,
        "words": words,
    }