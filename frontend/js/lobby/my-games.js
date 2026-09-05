'use strict';

/* ============================================================
   MY GAMES — lobby "Continue / Review / Delete" section
   ------------------------------------------------------------
   Lists the games created from THIS device. The source of truth
   (game ids, codes, and — critically — each game's own host token)
   is the client-side registry in api.js (localStorage
   pinoy_henyo_my_games), because the backend scopes GET
   /api/games/history to ONE host token per game. Live status is
   refreshed per game through the public status endpoint.
- Continue   -> live/active game -> host dashboard
      - View report-> completed game   -> leaderboard + statistics
      - Delete     -> terminal games only -> tick to bulk-delete, or delete
                    one from its card; both use a simple confirm modal
   Requires js/script.js (openModal/closeModal) and js/api/*.
   ============================================================ */

(function () {
  const SECTION = document.getElementById('my-games');
  const LIST    = document.getElementById('my-games-list');
  const REFRESH = document.getElementById('my-games-refresh');
  if (!SECTION || !LIST) return;

  const overlayReport = document.getElementById('modal-report-game');
  const overlayDelete = document.getElementById('modal-delete-game');

  const deleteBody = document.getElementById('modal-delete-body');
  const deleteBtn  = document.getElementById('btn-delete-confirm');
  const deleteSelectedBtn = document.getElementById('my-games-delete-selected');

  const HOST_ENTRY = 'pages/host/host_dashboard.html';

  const LIVE_STATUSES = new Set([
    'LOBBY', 'SETUP', 'READY',
    'ROUND_1', 'ROUND_2', 'TIE_BREAKER', 'PAUSED',
  ]);
  const TERMINAL_STATUSES = new Set([
    'GAME_COMPLETE', 'CANCELLED', 'EXPIRED',
  ]);

  const STATUS_LABELS = {
    LOBBY: 'Lobby',
    SETUP: 'Setup',
    READY: 'Ready',
    ROUND_1: 'Round 1',
    ROUND_2: 'Round 2',
    TIE_BREAKER: 'Tie-Breaker',
    PAUSED: 'Paused',
    GAME_COMPLETE: 'Completed',
    CANCELLED: 'Cancelled',
    EXPIRED: 'Expired',
  };

  let games = [];
  let deletePending = []; // game objects queued for deletion
  const selected = new Set(); // game ids ticked for bulk delete

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  }

  function statusLabel(s) {
    return STATUS_LABELS[s] || s || 'Unknown';
  }

  function isLive(g)  { return LIVE_STATUSES.has(g.status); }
  function isTerminal(g) { return TERMINAL_STATUSES.has(g.status); }

  /* ---------- live status refresh (public endpoint) ---------- */
  // The registry remembers status only as of last interaction; call the
  // public GET /games/<id>/status to pull the current server truth for
  // games, then persist any changes back into the registry. Runs with a
  // small worker pool so a long/slow backend can't stall the whole list.
  const STATUS_CONCURRENCY = 4;

  async function refreshStatuses(list) {
    const jobs = list.filter((g) => !TERMINAL_STATUSES.has(g.status));
    if (!jobs.length) return list;

    const changed = [];
    let idx = 0;
    async function worker() {
      while (idx < jobs.length) {
        const g = jobs[idx++];
        try {
          const fresh = await GameAPI.status(g.game_id);
          if (fresh && fresh.status) {
            const prev = g.status;
            g.status = fresh.status;
            if (fresh.current_round != null) g.current_round = fresh.current_round;
            if (fresh.ended_at) g.ended_at = fresh.ended_at;
            if (!g.created_at && fresh.created_at) g.created_at = fresh.created_at;
            if (prev !== fresh.status) changed.push(g);
          }
        } catch (e) { /* 404/network: keep the stored entry as-is */ }
      }
    }

    await Promise.all(
      Array.from({ length: Math.min(STATUS_CONCURRENCY, jobs.length) }, worker)
    );
    changed.forEach((g) => API.updateMyGame({
      game_id: g.game_id, status: g.status, ended_at: g.ended_at || undefined,
    }));
    return list;
  }

  /* ---------- spinner / message helpers ---------- */
  function setListHTML(html) {
    LIST.innerHTML = html;
  }

  function spinnerHtml() {
    return '<div class="my-games__state"><div class="my-games__spinner"></div>Loading your games…</div>';
  }

  function emptyHtml() {
    return '<div class="my-games__state">No games from this device yet. Start a game to see it here.</div>';
  }

  function errorHtml(message) {
    return `
      <div class="my-games__state">
        Could not load your games. ${esc(message)}
        <button type="button" class="btn-primary my-games__retry" id="my-games-retry">
          <i class="fa-solid fa-rotate-right"></i>
          Try Again
        </button>
      </div>`;
  }

  /* ---------- card rendering ---------- */
  function cardHtml(g) {
    const live = isLive(g);
    const terminal = isTerminal(g);
    // The card that matches the ACTIVE host session is marked so the user can
    // see which saved game the dashboard will open before they click. Merely
    // having a game in the registry never switches the session — only the
    // explicit "Continue" button does that.
    const activeGameId = API.getGameId();
    const isCurrent = activeGameId && String(activeGameId) === String(g.game_id);
    const winner = (g.winner && g.winner.team_name)
      ? g.winner.team_name
      : (g.winner_name || null);

    const continueBtn = live
      ? `<button type="button" class="my-games__act my-games__act--primary" data-act="continue" data-id="${g.game_id}" title="${isCurrent ? 'Open the dashboard for this game' : 'Switch the active host session to this game'}">
           ${isCurrent ? '<i class="fa-solid fa-door-open"></i> Open Game' : '<i class="fa-solid fa-play"></i> Continue'}
         </button>`
      : '';

    const reportBtn = (g.status === 'GAME_COMPLETE')
      ? `<button type="button" class="my-games__act" data-act="report" data-id="${g.game_id}" title="View final report">
           <i class="fa-solid fa-chart-bar"></i> Report
         </button>`
      : '';

    const deleteBtn2 = terminal
      ? `<button type="button" class="my-games__act my-games__act--danger" data-act="delete" data-id="${g.game_id}" title="Permanently delete this game">
           <i class="fa-solid fa-trash"></i>
         </button>`
      : '';

    const meta = [
      `Created ${fmtDate(g.created_at)}`,
      winner ? `Winner: ${esc(winner)}` : '',
      g.current_round ? `Round ${g.current_round}` : '',
      g.saved_at ? `Saved ${fmtDate(g.saved_at)}` : '',
    ].filter(Boolean).join(' · ');

    const check = terminal
      ? `<label class="my-games__check" title="Select for deletion">
           <input type="checkbox" data-check="${g.game_id}" aria-label="Select game ${esc(g.game_code || g.game_id)} for deletion" />
           <span class="my-games__check-box" aria-hidden="true"><i class="fa-solid fa-check"></i></span>
         </label>`
      : '';

    return `
      <article class="my-games__card${isCurrent ? ' my-games__card--current' : ''}${selected.has(String(g.game_id)) ? ' my-games__card--selected' : ''}" data-id="${g.game_id}">
        ${isCurrent ? `<div class="my-games__current-badge"><i class="fa-solid fa-circle"></i> Currently Hosting: ${esc(g.game_code || '')}</div>` : ''}
        <div class="my-games__card-main">
          <span class="my-games__card-title">
            ${check}
            <span class="my-games__code">${esc(g.game_code || '')}</span>
          </span>
          <span class="my-games__status my-games__status--${live ? 'live' : (terminal ? 'done' : 'muted')}">
            ${esc(statusLabel(g.status))}
          </span>
        </div>
        <p class="my-games__meta">${esc(meta)}</p>
        <div class="my-games__acts">
          ${continueBtn}${reportBtn}${deleteBtn2}
        </div>
      </article>`;
  }

  /* ---------- bulk delete toolbar ---------- */
  function syncBulkDeleteButton() {
    if (!deleteSelectedBtn) return;
    const anyDeletable = games.some(isTerminal);
    deleteSelectedBtn.hidden = !anyDeletable;
    const n = selected.size;
    deleteSelectedBtn.disabled = n === 0;
    deleteSelectedBtn.innerHTML = n
      ? `<i class="fa-solid fa-trash"></i> Delete (${n})`
      : '<i class="fa-solid fa-trash"></i> Delete';
  }

  function render() {
    // Selection lives across re-renders (e.g. stale ids from status refresh),
    // so drop ids that no longer exist as soon as we rebuild the list.
    selected.forEach((id) => {
      if (!games.some((g) => String(g.game_id) === String(id))) selected.delete(id);
    });
    syncBulkDeleteButton();

    if (!games.length) {
      setListHTML(emptyHtml());
      return;
    }

    // The game matching the ACTIVE host session is pinned to its own group so
    // the currently-hosted game is unmistakable. It is a display decision
    // only: nothing here switches the session — Continue (on other games) is
    // the only action that changes which game is hosted.
    const activeGameId = API.getGameId();
    const current = activeGameId
      ? games.find((g) => String(g.game_id) === String(activeGameId)) || null
      : null;
    const rest = current ? games.filter((g) => g !== current) : games;

    const groups = [];
    if (current) {
      groups.push(`<div class="my-games__group my-games__group--current">
        <h3 class="my-games__group-title"><i class="fa-solid fa-circle"></i> Currently Hosting</h3>
        ${cardHtml(current)}
      </div>`);
    }

    const live = rest.filter(isLive);
    const done = rest.filter(isTerminal);
    const other = rest.filter((g) => !isLive(g) && !isTerminal(g));

    if (live.length) {
      groups.push(`<div class="my-games__group">
        <h3 class="my-games__group-title"><i class="fa-solid fa-bolt"></i> Active Games</h3>
        ${live.map(cardHtml).join('')}
      </div>`);
    }
    if (done.length) {
      groups.push(`<div class="my-games__group">
        <h3 class="my-games__group-title"><i class="fa-solid fa-flag-checkered"></i> Finished Games</h3>
        ${done.map(cardHtml).join('')}
      </div>`);
    }
    if (other.length) {
      groups.push(`<div class="my-games__group">
        <h3 class="my-games__group-title"><i class="fa-solid fa-inbox"></i> Other</h3>
        ${other.map(cardHtml).join('')}
      </div>`);
    }
    setListHTML(groups.join(''));
  }

  /* ---------- data loading ---------- */
  async function load({ silent = false } = {}) {
    if (!silent) setListHTML(spinnerHtml());
    LIST.setAttribute('aria-busy', 'true');

    try {
      // 1. Everything this device ever created (registry entries carry the
      //    per-game host token that the server will never give back).
      const merged = new Map(
        (API.getMyGames() || []).map((g) => [String(g.game_id), Object.assign({}, g)])
      );

      // 2. Server truth for the current host token (the current game).
      if (API.getHostToken()) {
        try {
          const data = await GameAPI.history();
          ((data && data.games) || []).forEach((s) => {
            const key = String(s.game_id);
            const base = merged.get(key) || {};
            merged.set(key, Object.assign({}, base, s, {
              host_token: base.host_token || API.getHostToken(),
              saved_at: base.saved_at || null,
            }));
          });
        } catch (err) {
          // 401/403/404 just mean the current token has no matches yet; any
          // other failure should surface to the user.
          if (!(err && (err.status === 401 || err.status === 403 || err.status === 404))) {
            throw err;
          }
        }
      }

      let list = Array.from(merged.values());
      list = await refreshStatuses(list);
      list.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
      games = list;
      SECTION.hidden = false;
      render();
    } catch (err) {
      SECTION.hidden = false;
      if (err && (err.status === 401 || err.status === 403 || err.status === 404)) {
        games = [];
        render();
      } else {
        setListHTML(errorHtml((err && err.message) || 'Please try again.'));
      }
    } finally {
      LIST.setAttribute('aria-busy', 'false');
    }
  }

  /* ---------- continue ---------- */
  function continueGame(g) {
    if (!g || !g.game_id) return;
    // Every game has its OWN host token (registry). Switch the active host
    // session to this game before opening the dashboard so it reconnects to
    // the right game on restore.
    const token = g.host_token || API.getHostToken();
    if (!token) {
      if (typeof alert === 'function') alert('No host key stored for this game.');
      return;
    }
    // Dev-safe trace (never logs the token itself).
    console.log('[MY GAMES] continue → switching host session', {
      game_id: g.game_id,
      game_code: g.game_code || null,
      from_game_id: API.getGameId() || null,
      to_host_game_id: g.game_id,
    });
    API.setHostToken(token);
    API.setGameId(g.game_id);
    API.setGameCode(g.game_code || '');
    API.setHostContext({ game_id: g.game_id, game_code: g.game_code, host_session_token: token });
    window.location.href = HOST_ENTRY;
  }

  /* ---------- report modal ---------- */
  async function showReport(gameId) {
    if (!overlayReport || typeof openModal !== 'function') return;
    openModal(overlayReport);
    const tbody = document.getElementById('report-tbody');
    const winnerEl = document.getElementById('report-winner');
    const statsEl = document.getElementById('report-stats');
    const subtitle = document.getElementById('modal-report-subtitle');

    if (tbody) tbody.innerHTML = '<tr><td colspan="6">Loading…</td></tr>';
    if (statsEl) statsEl.innerHTML = '';

    let game = games.find((g) => String(g.game_id) === String(gameId)) || null;

    // leaderboard/statistics are host-only; for non-current games we need
    // THAT game's own host token. Restore the previous session afterwards.
    const priorToken = API.getHostToken();
    const reportToken = game && (game.host_token || priorToken);
    if (reportToken) API.setHostToken(reportToken);

    try {
      if (subtitle && game) subtitle.textContent = `Game ${game.game_code || ''}`;

      const [lbRes, stRes] = await Promise.all([
        GameAPI.leaderboard(gameId).catch(() => null),
        GameAPI.statistics(gameId).catch(() => null),
      ]);

      const board = (lbRes && lbRes.leaderboard) || [];
      const stats = stRes || {};

      if (winnerEl) {
        const w = stats.winning_team || (board.length ? board[0] : null);
        winnerEl.innerHTML = w
          ? `<i class="fa-solid fa-trophy"></i> Winner: <strong>${esc(w.team_name || '')}</strong>
             <span class="report-winner__pts">${Number(w.points || 0)} pts</span>`
          : '<i class="fa-solid fa-trophy"></i> No finished teams yet';
        if (w && w.team_name && game) {
          API.updateMyGame({ game_id: gameId, winner_name: w.team_name });
          game.winner_name = w.team_name;
        }
      }

      if (tbody) {
        if (!board.length) {
          tbody.innerHTML = '<tr><td colspan="6">No scores recorded.</td></tr>';
        } else {
          tbody.innerHTML = board.map((t) => `
            <tr>
              <td>${Number(t.rank) || '–'}</td>
              <td>${esc(t.team_name || '')}</td>
              <td>${Number(t.points || 0)}</td>
              <td>${Number(t.correct_words || 0)}</td>
              <td>${Number(t.passed_words || 0)}</td>
              <td>${Number(t.penalty_seconds || 0)}</td>
            </tr>`).join('');
        }
      }

      if (statsEl) {
        const fast = stats.fastest_team;
        const chips = [
          ['Teams', stats.total_teams],
          ['Words', stats.total_words],
          ['Correct', stats.total_correct_answers],
          ['Passes', stats.total_passes],
          ['Penalties', stats.total_penalties],
          ['Duration', (stats.total_game_duration_seconds != null && isFinite(stats.total_game_duration_seconds))
            ? Math.round(stats.total_game_duration_seconds / 60) + 'm' : '—'],
          ['Fastest', fast ? fast.team_name : '—'],
        ].map(([label, value]) =>
          `<span class="report-stats__chip"><span class="report-stats__label">${esc(label)}</span><strong>${esc(value == null ? '—' : value)}</strong></span>`
        ).join('');
        statsEl.innerHTML = chips || 'No statistics yet.';
      }
    } catch (e) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6">${esc((e && e.message) || 'Could not load the report.')}</td></tr>`;
    } finally {
      if (reportToken && priorToken !== reportToken) API.setHostToken(priorToken);
    }
  }

  /* ---------- delete confirm (single or bulk) ---------- */
  function describeDeletion(list) {
    if (!list.length) return;
    const codes = list
      .map((g) => String(g.game_code || g.game_id || '').trim().toUpperCase())
      .filter(Boolean);

    if (codes.length === 1) {
      deleteBody.textContent = `Delete game "${codes[0]}"?`;
      return;
    }
    deleteBody.innerHTML =
      `Delete ${list.length} games?` +
      `<span class="my-games__delete-chips" id="delete-chips">` +
      codes.map((c) => `<span class="my-games__delete-chip">${esc(c)}</span>`).join('') +
      `</span>`;
  }

  function openDeleteConfirm(list) {
    if (!overlayDelete || typeof openModal !== 'function' || !list.length) return;
    deletePending = list;
    if (deleteBody) {
      deleteBody.textContent = 'Delete this game?';
      deleteBody.innerHTML = '';
      describeDeletion(list);
    }
    openModal(overlayDelete);
  }

  async function confirmDelete() {
    const pending = deletePending.filter(Boolean);
    if (!pending.length) return;
    deleteBtn.disabled = true;
    const originalLabel = deleteBtn.innerHTML;
    deleteBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Deleting…';

    const deleteDuring = [];
    let deletedCount = 0;
    let failedCount = 0;
    let firstError = null;

    for (const g of pending) {
      // DELETE is host-only; non-current games need their own stored token.
      const priorToken = API.getHostToken();
      if (g.host_token) API.setHostToken(g.host_token);
      try {
        await API.withLoading('delete-game-' + g.game_id, () => GameAPI.deleteGame(g.game_id, { confirm: true }));
        API.removeMyGame(g.game_id);
        deleteDuring.push(g.game_id);
        deletedCount += 1;
      } catch (err) {
        failedCount += 1;
        if (!firstError) {
          firstError = (err && err.message) || 'Could not delete the game.';
        }
      } finally {
        API.setHostToken(priorToken);
      }
    }

    if (typeof closeModal === 'function' && overlayDelete) closeModal(overlayDelete);
    deleteBtn.disabled = false;
    deleteBtn.innerHTML = originalLabel;
    deletePending = [];
    deleteDuring.forEach((id) => selected.delete(String(id)));
    syncBulkDeleteButton();

    if (deletedCount && typeof showToast === 'function') {
      showToast(deletedCount === 1 ? 'Game deleted.' : `${deletedCount} games deleted.`);
    }
    if (failedCount && typeof showToast === 'function') {
      showToast(failedCount === 1 ? firstError : `${failedCount} games could not be deleted.`);
    }

    // If any deleted game was the current host game, the host session is gone.
    const currentGameId = API.getGameId();
    const currentHostGame = API.getHostGameId();
    const deletedIsCurrent = deleteDuring.some((id) =>
      String(id) === String(currentGameId) ||
      (currentHostGame && String(id) === String(currentHostGame))
    );
    if (deletedIsCurrent) {
      // clearTokens() only wipes the live session; the My Games registry
      // (separate localStorage key) keeps the other games intact.
      API.clearTokens();
      games = games.filter((x) => !deleteDuring.some((id) => String(x.game_id) === String(id)));
      SECTION.hidden = !games.length;
      render();
    } else {
      await load({ silent: true });
    }
  }

  function openDeleteModal(g) {
    openDeleteConfirm([g]);
  }

  /* ---------- wiring ---------- */
  LIST.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const id = btn.getAttribute('data-id');
    const g = games.find((x) => String(x.game_id) === String(id));
    if (!g) return;

    const act = btn.getAttribute('data-act');
    if (act === 'continue') continueGame(g);
    else if (act === 'report') showReport(g.game_id);
    else if (act === 'delete') openDeleteModal(g);
  });

  if (REFRESH) REFRESH.addEventListener('click', () => load());
  LIST.addEventListener('click', (e) => {
    if (e.target.closest && e.target.closest('#my-games-retry')) load();
  });

  // Checkbox selection for bulk delete (checkboxes only exist on terminal
  // games, so anything ticked is always deletable).
  LIST.addEventListener('change', (e) => {
    const box = e.target;
    if (!(box instanceof HTMLInputElement) || !box.matches('[data-check]')) return;
    const id = String(box.getAttribute('data-check'));
    const card = box.closest('.my-games__card');
    const game = games.find((x) => String(x.game_id) === id);
    if (!game || !isTerminal(game)) {
      box.checked = false;
      return;
    }
    if (box.checked) selected.add(id);
    else selected.delete(id);
    if (card) card.classList.toggle('my-games__card--selected', box.checked);
    syncBulkDeleteButton();
    if (typeof GameAudio === 'object' && typeof GameAudio.play === 'function') {
      GameAudio.play('click');
    }
  });

  if (deleteSelectedBtn) {
    deleteSelectedBtn.addEventListener('click', () => {
      const pending = games.filter((g) => selected.has(String(g.game_id)) && isTerminal(g));
      if (pending.length) openDeleteConfirm(pending);
    });
  }

  if (deleteBtn) deleteBtn.addEventListener('click', confirmDelete);

  const resetDelete = () => {
    deletePending = [];
  };
  ['modal-delete-close', 'modal-delete-cancel'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', () => {
      if (typeof closeModal === 'function' && overlayDelete) closeModal(overlayDelete);
      resetDelete();
    });
  });
  ['modal-report-close', 'modal-report-cancel'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', () => {
      if (typeof closeModal === 'function' && overlayReport) closeModal(overlayReport);
    });
  });

  /* ---------- bootstrap ---------- */
  if (!API.getHostToken() && !(API.getMyGames() || []).length) {
    SECTION.hidden = true;
    return;
  }
  load();
})();