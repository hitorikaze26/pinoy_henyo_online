from datetime import datetime

from ..extensions import db
from ..models import (
    Category,
    Game,
    GameEvent,
    Match,
    Round,
    Score,
    Team,
    TeamMember,
    Turn,
    TurnWord,
    Word,
)

# Tie-break baseline for teams with no correct word yet.
_NEVER = datetime(9999, 1, 1)


def _tz_iso(value):
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=None).isoformat()
    return value.isoformat()


def _member_payload(member):
    return {
        "member_id": member.id,
        "username": member.username,
        "device_role": member.device_role,
        "gameplay_role": member.gameplay_role,
        "is_connected": member.is_connected,
        "last_seen_at": _tz_iso(member.last_seen_at),
    }


def _team_payload(team):
    leader = team.leader
    return {
        "team_id": team.id,
        "team_code": team.team_code,
        "team_name": team.team_name,
        "status": team.status,
        "leader_member_id": leader.id if leader else None,
        "members": [_member_payload(m) for m in team.members],
    }


def _turn_payload(turn):
    words = []
    for turn_word in turn.turn_words:
        word = turn_word.word
        words.append(
            {
                "turn_word_id": turn_word.id,
                "word_id": turn_word.word_id,
                "word_text": word.word_text if word else None,
                "category_id": word.category_id if word else None,
                "submitted_by_team_id": word.submitted_by_team_id if word else None,
                "sequence": turn_word.sequence,
                "result": turn_word.result,
                "used_at": _tz_iso(turn_word.used_at),
            }
        )
    penalties = [
        {
            "penalty_id": p.id,
            "type": p.type,
            "seconds": p.seconds,
            "reason": p.reason,
            "created_at": _tz_iso(p.created_at),
        }
        for p in turn.penalties
    ]
    return {
        "turn_id": turn.id,
        "turn_order": turn.turn_order,
        "team_id": turn.team_id,
        "status": turn.status,
        "starting_seconds": turn.starting_seconds,
        "remaining_seconds": turn.remaining_seconds,
        "timer_adjustment_seconds": turn.timer_adjustment_seconds,
        "started_at": _tz_iso(turn.started_at),
        "ended_at": _tz_iso(turn.ended_at),
        "words": words,
        "penalties": penalties,
    }


def _match_payload(match):
    return {
        "match_id": match.id,
        "match_order": match.match_order,
        "team_id": match.team_id,
        "opponent_team_id": match.opponent_team_id,
        "winner_team_id": match.winner_team_id,
        "status": match.status,
        "started_at": _tz_iso(match.started_at),
        "ended_at": _tz_iso(match.ended_at),
        "turns": [_turn_payload(t) for t in match.turns],
    }


def _round_payload(round_obj):
    selected = [
        rc.category_id for rc in round_obj.selected_categories
    ]
    return {
        "round_id": round_obj.id,
        "round_number": round_obj.round_number,
        "status": round_obj.status,
        "timer_seconds": round_obj.timer_seconds,
        "timer_mode": round_obj.timer_mode,
        "started_at": _tz_iso(round_obj.started_at),
        "ended_at": _tz_iso(round_obj.ended_at),
        "selected_category_ids": selected,
        "matches": [_match_payload(m) for m in round_obj.matches],
    }


def _score_payload(score, team):
    return {
        "score_id": score.id,
        "team_id": score.team_id,
        "team_code": team.team_code if team else None,
        "team_name": team.team_name if team else None,
        "round_id": score.round_id,
        "match_id": score.match_id,
        "points": score.points,
        "correct_words": score.correct_words,
        "passed_words": score.passed_words,
        "failed_words": score.failed_words,
        "penalty_seconds": score.penalty_seconds,
        "time_bonus_seconds": score.time_bonus_seconds,
    }


def game_history(game):
    """Full read-only history snapshot for a game."""
    categories = (
        Category.query.filter_by(game_id=game.id).order_by(Category.id).all()
    )
    rounds = (
        Round.query.filter_by(game_id=game.id)
        .order_by(Round.round_number, Round.id)
        .all()
    )
    scores = (
        Score.query.filter_by(game_id=game.id)
        .order_by(Score.team_id, Score.round_id, Score.match_id)
        .all()
    )
    events = (
        GameEvent.query.filter_by(game_id=game.id).order_by(GameEvent.id).all()
    )

    words_used = []
    seen_word_ids = set()
    penalties = []
    for round_obj in rounds:
        for match in round_obj.matches:
            for turn in match.turns:
                for turn_word in turn.turn_words:
                    if turn_word.word_id in seen_word_ids:
                        continue
                    seen_word_ids.add(turn_word.word_id)
                    word = turn_word.word
                    if word is not None:
                        words_used.append(
                            {
                                "word_id": word.id,
                                "word_text": word.word_text,
                                "category_id": word.category_id,
                                "status": word.status,
                            }
                        )
                for p in turn.penalties:
                    penalties.append(p)

    winner = None
    top = leaderboard(game)
    if top:
        winner = {
            "team_id": top[0]["team_id"],
            "team_code": top[0]["team_code"],
            "team_name": top[0]["team_name"],
        }

    tie_breakers = [
        {"round_id": r.id, "match_id": m.id}
        for r in rounds
        if r.round_number == 3
        for m in r.matches
    ]

    return {
        "game_id": game.id,
        "game_code": game.game_code,
        "status": game.status,
        "created_at": _tz_iso(game.created_at),
        "started_at": _tz_iso(game.started_at),
        "ended_at": _tz_iso(game.ended_at),
        "current_round": game.current_round,
        "teams": [_team_payload(t) for t in game.teams],
        "categories": [
            {"category_id": c.id, "name": c.name} for c in categories
        ],
        "words_used": words_used,
        "rounds": [_round_payload(r) for r in rounds],
        "scores": [
            _score_payload(s, db.session.get(Team, s.team_id)) for s in scores
        ],
        "penalties": [
            {
                "penalty_id": p.id,
                "turn_id": p.turn_id,
                "team_id": p.team_id,
                "type": p.type,
                "seconds": p.seconds,
                "reason": p.reason,
                "created_at": _tz_iso(p.created_at),
            }
            for p in penalties
        ],
        "events": [
            {
                "event_id": e.id,
                "event_type": e.event_type,
                "team_id": e.team_id,
                "member_id": e.member_id,
                "event_data": e.event_data,
                "created_at": _tz_iso(e.created_at),
            }
            for e in events
        ],
        "winner": winner,
        "tie_breakers": tie_breakers,
    }


def games_history_for_host(host_token):
    """History for ALL games owned by a given host session token."""
    games = (
        Game.query.filter_by(host_session_token=host_token)
        .order_by(Game.created_at.desc())
        .all()
    )
    return [game_history(g) for g in games]


def game_state(game):
    """Recoverable resume snapshot for a host returning to a paused/active game.

    The database is the source of truth: status, round, teams/members, the
    scoreboard, and the live (or most recent) match/turn are all read back from
    the DB. The timer is recomputed server-side (``turn_play_payload``) and is
    never trusted from a browser. Secrets (word text) are included because the
    host controls the game and needs the current word to restore the UI.
    """
    from ..services.turn_service import turn_play_payload

    categories = (
        Category.query.filter_by(game_id=game.id).order_by(Category.id).all()
    )
    current_round = None
    if game.current_round is not None:
        current_round = Round.query.filter_by(
            game_id=game.id, round_number=game.current_round
        ).first()
    resume_turn = None
    if game.current_match_id is not None:
        match = db.session.get(Match, game.current_match_id)
        if match is not None:
            active = next(
                (t for t in match.turns if t.status == Turn.STATUS_ACTIVE),
                None,
            )
            resumed = active if active is not None else (
                next(
                    reverted
                    for reverted in sorted(
                        match.turns, key=lambda t: t.turn_order
                    )
                )
                if match.turns
                else None
            )
            if resumed is not None:
                resume_turn = turn_play_payload(resumed)

    return {
        "game_id": game.id,
        "game_code": game.game_code,
        "status": game.status,
        "current_round": game.current_round,
        "current_match_id": game.current_match_id,
        "created_at": _tz_iso(game.created_at),
        "started_at": _tz_iso(game.started_at),
        "ended_at": _tz_iso(game.ended_at),
        "teams": [_team_payload(t) for t in game.teams],
        "categories": [
            {"category_id": c.id, "name": c.name} for c in categories
        ],
        "scoreboard": leaderboard(game),
        "round": _round_payload(current_round) if current_round else None,
        "resume_turn": resume_turn,
    }


def leaderboard(game):
    teams = (
        Team.query.filter_by(game_id=game.id, status=Team.STATUS_ACTIVE)
        .order_by(Team.id)
        .all()
    )
    if not teams:
        teams = Team.query.filter_by(game_id=game.id).order_by(Team.id).all()
    first_correct_at = {}
    correct_rows = (
        db.session.query(Turn.team_id, TurnWord.used_at)
        .join(TurnWord, TurnWord.turn_id == Turn.id)
        .join(Match, Match.id == Turn.match_id)
        .filter(
            Match.game_id == game.id,
            TurnWord.result == TurnWord.RESULT_CORRECT,
            TurnWord.used_at.isnot(None),
        )
        .order_by(TurnWord.used_at)
        .all()
    )
    for team_id, used_at in correct_rows:
        if team_id not in first_correct_at:
            first_correct_at[team_id] = used_at
    aggregate = {}
    for team in teams:
        score_rows = Score.query.filter_by(
            game_id=game.id, team_id=team.id
        ).all()
        aggregate[team.id] = {
            "team_id": team.id,
            "team_code": team.team_code,
            "team_name": team.team_name,
            "points": sum(s.points or 0 for s in score_rows),
            "correct_words": sum(s.correct_words or 0 for s in score_rows),
            "passed_words": sum(s.passed_words or 0 for s in score_rows),
            "failed_words": sum(s.failed_words or 0 for s in score_rows),
            "penalty_seconds": sum(s.penalty_seconds or 0 for s in score_rows),
            "time_bonus_seconds": sum(
                s.time_bonus_seconds or 0 for s in score_rows
            ),
            "first_correct_at": first_correct_at.get(team.id, _NEVER),
        }

    ranked = sorted(
        aggregate.values(),
        key=lambda r: (
            -r["points"],
            -r["correct_words"],
            r["first_correct_at"],
            r["penalty_seconds"],
            r["team_code"] or "",
        ),
    )
    for index, entry in enumerate(ranked, start=1):
        entry["rank"] = index
    for entry in ranked:
        entry["first_correct_at"] = _tz_iso(
            None if entry["first_correct_at"] is _NEVER else entry["first_correct_at"]
        )
    return ranked


def _penalty_count(game):
    count = 0
    rounds = Round.query.filter_by(game_id=game.id).all()
    for round_obj in rounds:
        for match in round_obj.matches:
            for turn in match.turns:
                count += len(turn.penalties)
    return count


def statistics(game):
    teams = Team.query.filter_by(game_id=game.id).all()
    word_count = Word.query.filter_by(game_id=game.id).count()
    scores = Score.query.filter_by(game_id=game.id).all()
    penalties = _penalty_count(game)

    total_correct = sum(s.correct_words or 0 for s in scores)
    total_passed = sum(s.passed_words or 0 for s in scores)
    total_penalty_seconds = sum(s.penalty_seconds or 0 for s in scores)

    duration_seconds = None
    if game.started_at is not None and game.ended_at is not None:
        start = game.started_at.replace(tzinfo=None)
        end = game.ended_at.replace(tzinfo=None)
        duration_seconds = max(0, int((end - start).total_seconds()))

    fastest_team = _fastest_team(game)

    rank = leaderboard(game)
    winning_team = rank[0] if rank else None

    return {
        "game_id": game.id,
        "total_teams": len(teams),
        "total_words": word_count,
        "total_correct_answers": total_correct,
        "total_passes": total_passed,
        "total_penalties": penalties,
        "total_game_duration_seconds": duration_seconds,
        "team_scores": rank,
        "fastest_team": fastest_team,
        "winning_team": {
            "team_id": winning_team["team_id"],
            "team_code": winning_team["team_code"],
            "team_name": winning_team["team_name"],
            "points": winning_team["points"],
        }
        if winning_team
        else None,
    }


def _fastest_team(game):
    """Team whose completed/active turns had the smallest total duration."""
    best = None
    best_seconds = None
    rounds = Round.query.filter_by(game_id=game.id).all()
    for round_obj in rounds:
        for match in round_obj.matches:
            for turn in match.turns:
                if turn.started_at is None or turn.ended_at is None:
                    continue
                start = turn.started_at.replace(tzinfo=None)
                end = turn.ended_at.replace(tzinfo=None)
                seconds = max(0, int((end - start).total_seconds()))
                if best_seconds is None or seconds < best_seconds:
                    best_seconds = seconds
                    team = db.session.get(Team, turn.team_id)
                    best = {
                        "team_id": turn.team_id,
                        "team_code": team.team_code if team else None,
                        "team_name": team.team_name if team else None,
                        "duration_seconds": seconds,
                    }
    return best
