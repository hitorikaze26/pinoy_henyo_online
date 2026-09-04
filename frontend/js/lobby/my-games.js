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
     - Delete     -> terminal games only -> type-to-confirm modal
   Requires js/script.js (openModal/closeModal) and js/api/*.
   ============================================================ */

(function () {
  const SECTION = document.getElementById('my-games');
  const LIST    = document.getElementById('my-games-list');
  const REFRESH = document.getElementById('my-games-refresh');
  if (!SECTION || !LIST) return;

  const overlayReport = document.getElementById('modal-report-game');
  const overlayDelete = document.getElementById('modal-delete-game');

  const deleteInput  = document.getElementById('input-delete-code');
  const deleteHint   = document.getElementById('delete-code-hint');
  const deleteError  = document.getElementById('error-delete-code');
  const deleteBtn    = document.getElementById('btn-delete-confirm');

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
  let deleteTarget = null; // game object queued for deletion

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
  // games, then persist any changes back into the registry.
  async function refreshStatuses(list) {
    let changed = false;
    for (const g of list) {
      if (TERMINAL_STATUSES.has(g.status)) continue; // finished = finished
      try {
        const fresh = await GameAPI.status(g.game_id);
        if (fresh && fresh.status) {
          const prev = g.status;
          g.status = fresh.status;
          if (fresh.current_round != null) g.current_round = fresh.current_round;
          if (fresh.ended_at) g.ended_at = fresh.ended_at;
          if (!g.created_at && fresh.created_at) g.created_at = fresh.created_at;
          if (prev !== fresh.status) changed = true;
        }
      } catch (e) { /* 404/network: keep the stored entry as-is */ }
    }
    if (changed) {
      list.forEach((g) => API.updateMyGame({
        game_id: g.game_id, status: g.status, ended_at: g.ended_at,
      }));
    }
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
    const winner = (g.winner && g.winner.team_name)
      ? g.winner.team_name
      : (g.winner_name || null);

    const continueBtn = live
      ? `<button type="button" class="my-games__act my-games__act--primary" data-act="continue" data-id="${g.game_id}" title="Continue this game">
           <i class="fa-solid fa-play"></i> Continue
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

    return `
      <article class="my-games__card" data-id="${g.game_id}">
        <div class="my-games__card-main">
          <span class="my-games__code">${esc(g.game_code || '')}</span>
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

  function render() {
    if (!games.length) {
      setListHTML(emptyHtml());
      return;
    }
    const live = games.filter(isLive);
    const done = games.filter(isTerminal);
    const other = games.filter((g) => !isLive(g) && !isTerminal(g));

    const groups = [];
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

  /* ---------- delete modal ---------- */
  function openDeleteModal(g) {
    if (!overlayDelete || typeof openModal !== 'function') return;
    deleteTarget = g;
    if (deleteHint) deleteHint.textContent = g.game_code || '';
    if (deleteInput) { deleteInput.value = ''; deleteInput.classList.remove('error'); }
    if (deleteError) deleteError.textContent = '';
    if (deleteBtn) { deleteBtn.disabled = true; deleteBtn.innerHTML = '<i class="fa-solid fa-trash"></i> Delete Forever'; }
    openModal(overlayDelete);
  }

  function syncDeleteButton() {
    const code = (deleteInput && deleteInput.value || '').trim().toUpperCase();
    const match = deleteTarget && code === String(deleteTarget.game_code || '').toUpperCase();
    if (deleteBtn) deleteBtn.disabled = !match;
  }

  async function confirmDelete() {
    if (!deleteTarget || !deleteBtn) return;
    deleteBtn.disabled = true;
    deleteBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Deleting…';
    if (deleteError) deleteError.textContent = '';

    const g = deleteTarget;
    // DELETE is host-only; non-current games need their own stored token.
    const priorToken = API.getHostToken();
    if (g.host_token) API.setHostToken(g.host_token);
    try {
      await API.withLoading('delete-game-' + g.game_id, () => GameAPI.deleteGame(g.game_id, { confirm: true }));
      API.removeMyGame(g.game_id);
      if (typeof closeModal === 'function' && overlayDelete) closeModal(overlayDelete);
      deleteTarget = null;

      // If the deleted game was the current host game, the host session is gone.
      const currentHostGame = API.getHostGameId();
      if (currentHostGame && String(currentHostGame) === String(g.game_id)) {
        // clearTokens() only wipes the live session; the My Games registry
        // (separate localStorage key) keeps the other games intact.
        API.clearTokens();
        games = games.filter((x) => String(x.game_id) !== String(g.game_id));
        SECTION.hidden = !games.length;
        render();
      } else {
        API.setHostToken(priorToken);
        await load({ silent: true });
      }
    } catch (err) {
      deleteBtn.disabled = false;
      deleteBtn.innerHTML = '<i class="fa-solid fa-trash"></i> Delete Forever';
      const map = {
        INVALID_OPERATION: 'Only completed, cancelled, or expired games can be deleted.',
        WITH_CONFIRMATION_REQUIRED: 'Please confirm the deletion and try again.',
        GAME_FROZEN: 'This game is read-only and cannot be deleted.',
      };
      if (deleteError) {
        deleteError.textContent = map[err.code] || (err && err.message) || 'Could not delete the game.';
      }
    }
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

  if (deleteInput) {
    deleteInput.addEventListener('input', syncDeleteButton);
    deleteInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && deleteBtn && !deleteBtn.disabled) {
        e.preventDefault();
        confirmDelete();
      }
    });
  }
  if (deleteBtn) deleteBtn.addEventListener('click', confirmDelete);

  const resetDelete = () => {
    deleteTarget = null;
    if (deleteInput) deleteInput.value = '';
    if (deleteError) deleteError.textContent = '';
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