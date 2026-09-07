# Fix: Host dashboard GO silently flips back to START

## Confirmed root cause

`start_readiness` (`backend/app/services/display_service.py:158-171`) validates only the
GLOBAL enabled-word count (>= `min_words_to_start`). It never checks the PER-MATCH count of
words the armed team can actually play (excluding its own submitted words). Repro (armed team
submitted all 15 words -> 0 eligible for itself):

```
READY(bravo): 200 ARMED
GO(bravo):    200 COUNTDOWN     <- button shows "Starting…"
STATE(bravo): IDLE              <- worker hit InsufficientWordsError, silent reset
```

`_start_turn_for_display` (display_service.py ~:341-387) catch: rollback -> `reset_display`
(IDLE) -> log only. No socket event. Dashboard's 4s reconcile (`/display/state`) -> IDLE ->
`renderStartControl` flips back to START. The "status and matches canceled" Network entries are
the 3s `completeWatch` polls (host_dashboard.js:2304-2321), not a second bug.

## Implementation steps

### 1. gameplay_service.py — eligible-word count helper
Add after `_round_word_pool` (:688), before `_used_word_ids`:

```python
def match_eligible_word_count(match):
    used = _used_word_ids(match)
    return sum(1 for word in _round_word_pool(match) if word.id not in used)
```

Mirrors `assign_turn_words` `available` (round-scoped; excludes own-team + used words).

### 2. display_service.py — block arming an unplayable match
In `start_readiness`, after the global pool check (:167-171) and guard `match is not None and
match.game_id == game.id` is true, append an issue when `match_eligible_word_count(match) <
MAX_WORDS_PER_TURN` (5):

```
"Not enough words remain for this team's turn ({N} available — 5 needed)."
```

READY then returns 400 + checklist shows the reason BEFORE arming. GO's re-validation
re-runs `start_readiness`, so stale arms are also caught. Fix the stale docstring ("at least 25
enabled words" -> min_words setting + per-match turn words).

### 3. realtime.py — `emit_display_cancelled(game, match, reason=None)`
Add optional `reason` key to the payload (add only when present).

### 4. display_service.py — never fail silently mid-GO
- Except branch (:371-380): after `db.session.commit()`, call
  `realtime.emit_display_cancelled(game, match, reason=str(exc))`.
- `GameFrozenError` branch (:349-351): after `reset_display(game)`, emit with
  reason "The game is no longer mutable."

### 5. host_dashboard.js — surface reason + close the blind window
- `display_cancelled` handler (:2209-2214): toast `p.reason` when present, else existing message.
- Add a `turn_started` fallback handler (after :2214): if no running `turn`, `displayState` is
  COUNTDOWN/RUNNING, and `rtForThisGame(payload)` -> `hostTurn(payload.turn_id)` ->
  `setActiveTurn`, so START->Pause appears immediately from the socket instead of after the
  4s reconcile.

### 6. Tests (test_display_start.py)
- Update `test_ready_uses_configured_minimum_word_pool` final enabled set so 5 eligible words
  survive: `{5, 9, 15, 19, 25}` are team B's words (team A's own are excluded when arming
  match_a). Word order: cat0 A(0-4) B(5-9), cat1 A(10-14) B(15-19), cat2 A(20-24) B(25-29).
  Comment keeps the 2/2/1 spread.
- New `test_ready_blocks_match_without_eligible_words`: disable team B's words (indices 15+) ->
  ready(match_a) -> 400 with "Not enough words remain" in issues.
- New `test_worker_go_failure_resets_display_and_emits_cancelled`: _big_setup, disable team B
  words, force game into expired COUNTDOWN for match_a via app context, `patch`
  `display_service.realtime.emit_display_cancelled`, call `display_service._go_worker(...)` ->
  assert emit called once and display_status == IDLE.

### 7. Verify
- Run full pytest from `backend`: `venv\Scripts\python.exe -m pytest test`.
- Restart dev server on 5198; headless E2E: arm team B (all-own words) -> BLOCKED with reason;
  arm team A -> GO -> RUNNING + Pause button.