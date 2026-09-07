'use strict';

/* ============================================================
   Host — Word Change Request widget (words page)
   ------------------------------------------------------------
   Floating action button + modal that lets the host ask a team to
   correct one of its submitted words. The request travels through
   `/word-change-requests` REST endpoints; the backend marks the
   target word UNDER_REVIEW and broadcasts realtime events so the
   affected team sees the forced modal and this page stays in sync.

   This widget intentionally uses its own `.wc-overlay` class so it
   never collides with the global `.modal-overlay` wiring.
   ============================================================ */

(() => {
  const HostRequests = (() => {
    let teams = [];
    let words = [];
    let pending = [];
    let loading = false;

    const els = {
      fab: () => document.getElementById('wc-fab'),
      badge: () => document.getElementById('wc-fab-badge'),
      overlay: () => document.getElementById('wc-modal'),
      close: () => document.getElementById('wc-close'),
      form: () => document.getElementById('wc-form'),
      team: () => document.getElementById('wc-team'),
      word: () => document.getElementById('wc-word'),
      comment: () => document.getElementById('wc-comment'),
      submit: () => document.getElementById('wc-submit'),
      errTeam: () => document.getElementById('wc-error-team'),
      errWord: () => document.getElementById('wc-error-word'),
      errComment: () => document.getElementById('wc-error-comment'),
      refresh: () => document.getElementById('wc-refresh-words'),
      pendingList: () => document.getElementById('wc-pending-list'),
      pendingEmpty: () => document.getElementById('wc-pending-empty'),
      pendingCount: () => document.getElementById('wc-pending-count'),
    };

    function gameId() {
      if (typeof API !== 'undefined') return API.getHostGameId() || API.getGameId() || null;
      return null;
    }

    function toast(message, duration) {
      if (typeof window.showToast === 'function') {
        window.showToast(message, duration);
      }
    }

    function setLoading(flag) {
      loading = flag;
      const btn = els.submit();
      if (btn) btn.disabled = flag;
    }

    /* ---------- data ---------- */
    async function fetchTeams() {
      const gid = gameId();
      if (!gid) return [];
      try {
        const res = await API.request(`/games/${gid}/teams`, { host: true });
        return (res && Array.isArray(res.teams)) ? res.teams : [];
      } catch (e) {
        return [];
      }
    }

    async function fetchWords() {
      const gid = gameId();
      if (!gid) return [];
      try {
        const res = await API.request(`/games/${gid}/words`, { host: true });
        return (res && Array.isArray(res.words)) ? res.words : [];
      } catch (e) {
        return [];
      }
    }

    async function fetchPending() {
      const gid = gameId();
      if (!gid) return [];
      try {
        const res = await API.request(`/games/${gid}/word-change-requests`, { host: true });
        const all = (res && Array.isArray(res.requests)) ? res.requests : [];
        return all.filter((r) => r && r.status === 'PENDING');
      } catch (e) {
        return [];
      }
    }

    async function resync() {
      const gid = gameId();
      if (!gid) return;
      const [nextTeams, nextWords, nextPending] = await Promise.all([
        fetchTeams(),
        fetchWords(),
        fetchPending(),
      ]);
      teams = nextTeams;
      words = nextWords;
      pending = nextPending;
      render();
    }

    /* ---------- rendering ---------- */
    function render() {
      renderPending();
      renderTeamSelect();
      refreshWordSelect();
    }

    function renderTeamSelect() {
      const select = els.team();
      if (!select) return;
      const active = select.value;
      select.innerHTML = '';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = teams.length ? 'Select a team…' : 'No teams yet';
      select.appendChild(placeholder);
      teams.forEach((t) => {
        const opt = document.createElement('option');
        opt.value = t.team_id;
        opt.textContent = t.team_name || `Team ${t.team_id}`;
        select.appendChild(opt);
      });
      if (active && teams.some((t) => String(t.team_id) === String(active))) {
        select.value = active;
      }
    }

    function selectedTeamId() {
      const select = els.team();
      if (!select) return null;
      const v = select.value;
      return v ? Number(v) : null;
    }

    function refreshWordSelect() {
      const select = els.word();
      if (!select) return;
      const teamId = selectedTeamId();
      const active = select.value;
      const available = words.filter(
        (w) => w.status === 'AVAILABLE'
          && w.submitted_by_team_id != null
          && (teamId == null || w.submitted_by_team_id === teamId)
      );
      select.innerHTML = '';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = teamId
        ? (available.length ? 'Select a word…' : 'No editable words for this team')
        : 'Select a team first…';
      select.appendChild(placeholder);
      available.forEach((w) => {
        const opt = document.createElement('option');
        opt.value = w.word_id;
        opt.textContent = `${w.word_text}${w.category_name ? ' — ' + w.category_name : ''}`;
        select.appendChild(opt);
      });
      if (active && available.some((w) => String(w.word_id) === String(active))) {
        select.value = active;
      }
    }

    function renderPending() {
      const list = els.pendingList();
      if (!list) return;
      list.innerHTML = '';
      const count = pending.length;
      const badge = els.badge();
      if (badge) {
        badge.hidden = count === 0;
        badge.textContent = String(count);
      }
      const countEl = els.pendingCount();
      if (countEl) countEl.textContent = String(count);
      if (count === 0) {
        const empty = document.createElement('li');
        empty.className = 'wc-pending__empty';
        empty.textContent = 'No pending requests.';
        list.appendChild(empty);
        return;
      }
      pending.forEach((req) => {
        const li = document.createElement('li');
        li.className = 'wc-pending__item';

        const body = document.createElement('div');
        body.className = 'wc-pending__body';
        const teamEl = document.createElement('div');
        teamEl.className = 'wc-pending__team';
        teamEl.textContent = req.team_name || 'Team';
        const wordEl = document.createElement('div');
        wordEl.className = 'wc-pending__word';
        wordEl.textContent = `“${req.word_text || ''}”`;
        const catEl = document.createElement('div');
        catEl.className = 'wc-pending__cat';
        catEl.textContent = [req.category_name, req.comment].filter(Boolean).join(' · ') || '';
        body.appendChild(teamEl);
        body.appendChild(wordEl);
        body.appendChild(catEl);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'wc-pending__cancel';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => cancelRequest(req.id, req));

        li.appendChild(body);
        li.appendChild(cancelBtn);
        list.appendChild(li);
      });
    }

    /* ---------- actions ---------- */
    async function createRequest() {
      if (loading) return;
      const gid = gameId();
      if (!gid) return;
      const teamId = selectedTeamId();
      const wordEl = els.word();
      const comment = (els.comment().value || '').trim();
      let valid = true;

      const teamIdCheck = teams.some((t) => t.team_id === teamId);
      if (!teamIdCheck) {
        els.errTeam().textContent = teamId ? 'That team is no longer available.' : 'Please select a team.';
        valid = false;
      } else {
        els.errTeam().textContent = '';
      }

      if (!wordEl.value) {
        els.errWord().textContent = 'Please select a word.';
        valid = false;
      } else {
        els.errWord().textContent = '';
      }

      if (!comment) {
        els.errComment().textContent = 'Please explain the requested change.';
        valid = false;
      } else if (comment.length > 300) {
        els.errComment().textContent = 'The comment is too long (300 max).';
        valid = false;
      } else {
        els.errComment().textContent = '';
      }

      if (!valid) return;

      setLoading(true);
      try {
        const res = await API.request(`/games/${gid}/word-change-requests`, {
          method: 'POST',
          host: true,
          body: { team_id: teamId, word_id: Number(wordEl.value), comment },
        });
        toast(`Change request sent to ${(res && res.team_name) || 'the team'}.`, 2600);
        els.comment().value = '';
        await resync();
      } catch (err) {
        wordError(err);
      } finally {
        setLoading(false);
      }
    }

    async function cancelRequest(id, req) {
      try {
        await API.request(`/word-change-requests/${id}/cancel`, {
          method: 'POST',
          host: true,
        });
        toast(`Cancelled the request for “${req.word_text || 'the word'}”.`, 2200);
        await resync();
      } catch (err) {
        if (!err || !err.status) {
          toast((err && err.message) || 'Network error. Try again.', 2600);
        } else {
          toast(err.message || 'Unable to cancel.', 2600);
        }
        await resync();
      }
    }

    function wordError(err) {
      const code = err && err.code;
      const map = {
        WORD_UNDER_REVIEW: 'That word is already under review.',
        WORD_NOT_AVAILABLE: 'Only available words can be put up for change.',
        REQUEST_COMMENT_REQUIRED: 'A comment explaining the change is required.',
        REQUEST_COMMENT_TOO_LONG: 'The comment is too long (300 max).',
        GAME_FINISHED: 'The game has finished; requests can no longer be sent.',
        UNAUTHORIZED: 'Your host session has expired. Reload this page.',
        TEAM_NOT_IN_GAME: 'That team is no longer part of this game.',
        WORD_NOT_IN_GAME: 'That word was removed from this game.',
      };
      const message = map[code] || (err && err.message);
      if (code === 'REQUEST_COMMENT_REQUIRED' || code === 'REQUEST_COMMENT_TOO_LONG') {
        els.errComment().textContent = message;
      } else if (code === 'WORD_UNDER_REVIEW' || code === 'WORD_NOT_AVAILABLE' || code === 'WORD_NOT_IN_GAME') {
        els.errWord().textContent = message;
        refreshWordSelect();
        renderPending();
      } else {
        toast(message, 3000);
      }
    }

    /* ---------- visibility ---------- */
    function open() {
      const el = els.overlay();
      if (!el) return;
      el.classList.add('is-open');
      el.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      if (!teams.length || !words.length || !pending) resync();
    }

    function close() {
      const el = els.overlay();
      if (!el) return;
      el.classList.remove('is-open');
      el.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    function wire() {
      const fab = els.fab();
      if (fab) fab.addEventListener('click', open);
      const closeBtn = els.close();
      if (closeBtn) closeBtn.addEventListener('click', close);
      const overlay = els.overlay();
      if (overlay) overlay.addEventListener('mousedown', (e) => {
        if (e.target === overlay) close();
      });

      const teamSel = els.team();
      if (teamSel) teamSel.addEventListener('change', refreshWordSelect);
      const refreshBtn = els.refresh();
      if (refreshBtn) refreshBtn.addEventListener('click', async () => {
        refreshBtn.disabled = true;
        try { await resync(); } finally { refreshBtn.disabled = false; }
      });
      const commentIn = els.comment();
      if (commentIn) commentIn.addEventListener('input', () => { els.errComment().textContent = ''; });

      const form = els.form();
      if (form) form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!e.submitter || e.submitter.type === 'submit') createRequest();
      });

      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close();
      });
    }

    wire();

    /* ---------- realtime ---------- */
    const R = window.Realtime;
    if (R) {
      ['word_change_request', 'word_change_resolved', 'word_change_cancelled', 'word_pool_updated']
        .forEach((name) => R.on(name, () => { resync(); }));
      R.onConnect(() => { resync(); });
      R.onReconnect(() => { resync(); });
    }

    return { resync, open, close };
  })();

  if (typeof window !== 'undefined') window.HostRequests = HostRequests;

  // Initial refresh + pending badge even while the widget stays closed.
  HostRequests.resync();
})();