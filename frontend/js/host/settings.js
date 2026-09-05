'use strict';
/* ============================================================
   HOST SETTINGS PAGE
   ------------------------------------------------------------
   Preferences are stored device-locally in `pinoy_henyo_settings`
   and saved immediately on every control change (no giant SAVE
   button). Controls that only feel server traffic stay honest:

     A – wired live       : Pause/Resume, End, Leave, QR, Copy,
                            Audio (real GameAudio playback)
     B – local state      : Lock Game (mirrors the Teams page)
     C – UI-only future   : Player Display prefs, Auto-Approve,
                            Max teams/members, turn metrics
     D – needs backend    : none introduced here

   Turn-critical preferences (Game + Timer cards) are locked once
   the game leaves LOBBY/SETUP ("available when not running").
   ============================================================ */
(async function () {
  'use strict';

  /* ============================================================
     CONSTANTS / STORAGE
     ============================================================ */
  const STORAGE_KEY = 'pinoy_henyo_settings';
  const MAX_TURN_SECONDS = 300; // 5:00
  const TERMINAL_STATUSES = ['GAME_COMPLETE', 'CANCELLED', 'EXPIRED'];
  const RUNNING_STATUSES = ['READY', 'ROUND_1', 'ROUND_2', 'TIE_BREAKER', 'PAUSED'];
  const LOBBY_STATUSES = ['LOBBY', 'SETUP'];

  // Only files actually shipped under frontend/assets/sounds/ (local, no URLs).
  // Add future bundled tracks here; the folder is scanned for variants only.
  const MUSIC_TRACKS = ['game music.mp3'];

  const DEFAULT_SETTINGS = {
    game: { maxWordsPerTeam: 5, penaltySeconds: 3 },
    timer: { turnSeconds: 95, timerMode: 'countdown', warnSeconds: 10 },
    audio: { musicOn: true, musicVolume: 0.4, musicTrack: 'game music.mp3', sfxOn: true, sfxVolume: 0.6 },
    teams: { allowNewTeams: true, autoApprove: false, maxTeams: 8, maxMembers: 6 },
    display: { showPlayerNames: true, showRoleLabels: true, showScores: true, showQrCode: true, showRoundCategory: true },
    host: { lockGame: false },
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function deepMerge(target) {
    for (let i = 1; i < arguments.length; i++) {
      const src = arguments[i];
      if (!src || typeof src !== 'object') continue;
      Object.keys(src).forEach((k) => {
        const v = src[k];
        if (v && typeof v === 'object' && !Array.isArray(v)) {
          target[k] = deepMerge(target[k] && typeof target[k] === 'object' ? target[k] : {}, v);
        } else {
          target[k] = Array.isArray(v) ? v.slice() : v;
        }
      });
    }
    return target;
  }

  function readStored() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  const pref = deepMerge({}, DEFAULT_SETTINGS, readStored());

  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(pref)); } catch (e) { /* storage disabled */ }
  }

  function getPref(path) {
    return path.reduce((o, k) => (o == null ? undefined : o[k]), pref);
  }
  function setPref(path, value) {
    let o = pref;
    for (let i = 0; i < path.length - 1; i++) o = o[path[i]];
    o[path[path.length - 1]] = value;
  }
  function coerce(v) {
    const n = Number(v);
    return Number.isInteger(n) ? n : v;
  }

  /* ============================================================
     STATE
     ============================================================ */
  const STATE = {
    gameId: null,
    gameCode: null,
    status: null,       // raw backend status string ("" until fetched)
  };

  function isRunning(status) { return RUNNING_STATUSES.indexOf(status || '') !== -1; }
  function isLocked(status) { return status && LOBBY_STATUSES.indexOf(status) === -1 && TERMINAL_STATUSES.indexOf(status) === -1; }
  function isTerminal(status) { return TERMINAL_STATUSES.indexOf(status || '') !== -1; }

  /* ============================================================
     TOAST
     ============================================================ */
  function showToast(msg, duration) {
    const t = $('#copy-toast');
    if (!t) { return; }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._t);
    t._t = setTimeout(() => t.classList.remove('show'), duration || 2200);
  }

  let toastTimer = null;
  function noteSaved(msg) {
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => showToast(msg), 60);
  }

  /* ============================================================
     COPY
     ============================================================ */
  async function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try { await navigator.clipboard.writeText(text); return; } catch (e) { /* fall through */ }
    }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;top:0;left:0;width:2em;height:2em;opacity:0;';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    } catch (e) { /* ignored */ }
  }

  function flashIcon(el) {
    if (!el) return;
    const i = el.querySelector('i');
    if (!i) return;
    const original = i.className;
    i.className = 'fa-solid fa-check';
    setTimeout(() => { i.className = original; }, 1600);
  }

  function bindCopy(btn, textFn) {
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const text = typeof textFn === 'function' ? textFn() : textFn;
      if (!text) { showToast('No game code yet — create a game first.'); return; }
      await copyText(text);
      showToast(`Copied: ${text}`);
      flashIcon(btn);
    });
  }

  /* ============================================================
     MODALS
     ============================================================ */
  function openModal(overlay) {
    if (!overlay) return;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const first = overlay.querySelector('input, select, button:not(.dash-modal__close):not(.modal__close)');
    if (first) setTimeout(() => first.focus(), 60);
  }
  function closeModal(overlay) {
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  // Every settings modal shares the host chrome. Close/cancel buttons always
  // close their own overlay; confirm buttons run their own action handlers.
  function wireModalClosers() {
    $$('.dash-modal__close, .dash-modal__cancel').forEach((btn) => {
      btn.addEventListener('click', () => closeModal(btn.closest('.dash-modal-overlay')));
    });
  }

  /* ============================================================
     NO-SESSION STATE
     ============================================================ */
  const SESSION_ONLY_CARD_IDS = ['card-game', 'card-timer', 'card-teams', 'card-host', 'card-danger'];

  function setNoSessionState() {
    SESSION_ONLY_CARD_IDS.forEach((id) => {
      const card = document.getElementById(id);
      if (card) card.hidden = true;
    });
    const banner = $('#settings-nosession');
    if (banner) banner.hidden = false;
    setCodeDisplays('------');
    const pause = $('#btn-pause-resume');
    const end = $('#btn-end-game');
    if (pause) pause.disabled = true;
    if (end) end.disabled = true;
  }

  function setCodeDisplays(code) {
    ['game-code-display', 'settings-game-code', 'settings-qr-code-text', 'delete-game-hint'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = code;
    });
  }

  /* ============================================================
     LIVE LOCK (game + timer cards)
     ============================================================ */
  function updateLiveLock() {
    const locked = isLocked(STATE.status);
    const running = isRunning(STATE.status);

    ['game', 'timer'].forEach((key) => {
      const card = document.getElementById('card-' + key);
      const badge = document.getElementById(key + '-lock-badge');
      if (card) card.classList.toggle('is-locked', locked);
      if (badge) badge.hidden = !locked;
    });

    $$('.setting-row.is-live-config').forEach((row) => {
      row.querySelectorAll('input, select, button, .seg__btn').forEach((el) => { el.disabled = running; });
    });
  }

  /* ============================================================
     HOST CONTROLS
     ============================================================ */
  function setBtnBusy(btn, busy) {
    if (!btn) return;
    btn.classList.toggle('is-busy', busy);
    btn.disabled = busy;
  }

  function setPauseUI(paused) {
    const btn = $('#btn-pause-resume');
    if (!btn) return;
    const icon = $('#btn-pause-resume-icon');
    const label = $('#btn-pause-resume-label');
    if (icon) icon.className = paused ? 'fa-solid fa-play' : 'fa-solid fa-pause';
    if (label) label.textContent = paused ? 'Resume Game' : 'Pause Game';
  }

  function updateHostControls() {
    const status = STATE.status;
    const running = isRunning(status);
    const terminal = isTerminal(status);

    const pause = $('#btn-pause-resume');
    const end = $('#btn-end-game');

    if (pause) pause.disabled = !running || terminal;
    if (end) end.disabled = !running || terminal;

    setPauseUI(status === 'PAUSED' && running);
  }

  /* ============================================================
     ROUND NAV
     ============================================================ */
  const ROUND_MAP = { READY: 1, ROUND_1: 1, ROUND_2: 2, TIE_BREAKER: 3 };

  function setRound(status, currentRound) {
    const el = $('#round-number');
    if (!el) return;
    if (ROUND_MAP[status] != null) {
      el.textContent = String(ROUND_MAP[status]);
    } else if (currentRound != null) {
      el.textContent = String(currentRound);
    }
  }

  /* ============================================================
     STATUS
     ============================================================ */
  async function refreshStatus() {
    if (!STATE.gameId) return;
    try {
      const data = await GameAPI.status(STATE.gameId);
      STATE.status = (data && data.status) ? data.status : STATE.status;
      const code = (data && data.game_code) ? data.game_code : STATE.gameCode;
      if (code) {
        STATE.gameCode = code;
        setCodeDisplays(code);
      }
      setRound(STATE.status, data && data.current_round);
      updateLiveLock();
      updateHostControls();
    } catch (e) {
      console.warn('[settings] status refresh failed', e && e.message);
      if (window.Connect && Connect.showReconnectBanner) {
        Connect.showReconnectBanner({
          title: 'Connection lost',
          message: 'Your session could not be verified. Reconnect to your game.',
        });
        document.body.setAttribute('data-reconnect-target', '../../index.html');
      }
    }
  }

  /* ============================================================
     HOST ACTION FLOWS
     ============================================================ */
  async function runHostAction(fn, successMsg, busyBtn) {
    if (busyBtn) setBtnBusy(busyBtn, true);
    try {
      await fn();
      if (successMsg) showToast(successMsg);
      await refreshStatus();
    } catch (e) {
      console.warn('[settings] host action failed', e && e.message);
      showToast('Could not complete that action right now. Check the connection.');
    } finally {
      if (busyBtn) setBtnBusy(busyBtn, false);
    }
  }

  function onPauseResume() {
    if (!STATE.gameId || !isRunning(STATE.status)) return;
    if (STATE.status === 'PAUSED') {
      runHostAction(() => GameAPI.resume(STATE.gameId), 'Game resumed', $('#btn-pause-resume'));
      return;
    }
    openModal($('#modal-confirm-pause'));
  }
  function onConfirmPause() {
    closeModal($('#modal-confirm-pause'));
    const btn = $('#confirm-pause-btn');
    setBtnBusy(btn, true);
    runHostAction(
      () => GameAPI.pause(STATE.gameId),
      'Game paused. Everyone sees the frozen state until you resume.',
      btn
    );
  }
  function onEndGame() {
    if (!STATE.gameId || !isRunning(STATE.status)) return;
    openModal($('#modal-confirm-end'));
  }
  function onConfirmEnd() {
    closeModal($('#modal-confirm-end'));
    const btn = $('#confirm-end-btn');
    setBtnBusy(btn, true);
    runHostAction(
      () => GameAPI.end(STATE.gameId),
      'Game ended — final standings are ready on the Dashboard.',
      btn
    );
  }
  function onLeaveGame() {
    if (!STATE.gameId) return;
    openModal($('#modal-confirm-leave'));
  }
  async function onConfirmLeave() {
    closeModal($('#modal-confirm-leave'));
    const btn = $('#confirm-leave-btn');
    setBtnBusy(btn, true);
    try {
      await GameAPI.leave(STATE.gameId);
      if (API && typeof API.setGameId === 'function') API.setGameId(null);
      if (API && typeof API.setHostGameId === 'function') API.setHostGameId(null);
      showToast('You left the game. Your game stays on the server.');
      setTimeout(() => { window.location.href = '../../index.html'; }, 800);
    } catch (e) {
      console.warn('[settings] leave failed', e && e.message);
      setBtnBusy(btn, false);
      showToast('Could not leave right now. Check the connection.');
    }
  }
  function onDeleteSaved() {
    if (!STATE.gameId) return;
    const input = $('#input-delete-code');
    const err = $('#delete-error');
    if (input) input.value = '';
    if (err) err.textContent = '';
    const confirmBtn = $('#confirm-delete-btn');
    if (confirmBtn) confirmBtn.disabled = true;
    openModal($('#modal-confirm-delete'));
    if (input) setTimeout(() => input.focus(), 60);
  }
  function onDeleteInput() {
    const input = $('#input-delete-code');
    const err = $('#delete-error');
    const confirmBtn = $('#confirm-delete-btn');
    if (!input || !confirmBtn) return;
    const value = input.value.trim().toUpperCase();
    const matches = STATE.gameCode && value === STATE.gameCode.trim().toUpperCase();
    confirmBtn.disabled = !matches;
    if (err) err.textContent = value && !matches ? 'Code does not match.' : '';
  }
  async function onConfirmDelete() {
    const confirmBtn = $('#confirm-delete-btn');
    if (!confirmBtn || confirmBtn.disabled) return;
    setBtnBusy(confirmBtn, true);
    closeModal($('#modal-confirm-delete'));
    API.removeMyGame(STATE.gameId);
    if (typeof API.clearTokens === 'function') API.clearTokens();
    showToast('Saved game removed from this device.');
    setTimeout(() => { window.location.href = '../../index.html'; }, 800);
  }

  /* ============================================================
     QR
     ============================================================ */
  function renderQrPlaceholder(container, code) {
    if (!container) return;
    let seed = 0;
    for (let i = 0; i < (code || '').length; i++) seed += code.charCodeAt(i);
    const rand = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };

    container.style.cssText = 'display:grid;grid-template-columns:repeat(7,1fr);gap:2px;width:min(170px,70%);aspect-ratio:1;';
    const SIZE = 7, total = SIZE * SIZE;
    const corners = new Set([
      0, 1, 2, 7, 8, 9, 14, 15, 16,       // top-left
      4, 5, 6, 11, 12, 13, 18, 19, 20,     // top-right
      28, 29, 30, 35, 36, 37, 42, 43, 44,  // bottom-left
    ]);
    for (let i = 0; i < total; i++) {
      const filled = corners.has(i) || rand() > 0.42;
      const cell = document.createElement('div');
      cell.style.cssText = 'border-radius:2px;background:' + (filled ? '#0b1220' : '#eef2f7');
      container.appendChild(cell);
    }
  }

  function renderRealQr(container, dataUri) {
    if (!container) return;
    container.innerHTML = '';
    if (!dataUri) { renderQrPlaceholder(container, STATE.gameCode); return; }
    container.style.cssText = 'background:#fff;padding:6px;border-radius:8px;display:flex;align-items:center;justify-content:center;';
    const img = document.createElement('img');
    img.src = dataUri;
    img.alt = 'Join QR';
    img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;';
    container.appendChild(img);
  }

  async function openQrModal() {
    const overlay = $('#modal-settings-qr');
    if (!overlay) return;
    const grid = $('#settings-qr-grid');
    if (STATE.gameCode) $('#settings-qr-code-text').textContent = STATE.gameCode;
    renderQrPlaceholder(grid, STATE.gameCode);
    openModal(overlay);
    if (STATE.gameId) {
      try {
        const qr = await GameAPI.gameQr(STATE.gameId);
        const dataUri = (qr && qr.qr_image) || null;
        renderRealQr(grid, dataUri);
      } catch (e) { /* stay on placeholder */ }
    }
  }

  /* ============================================================
     AUDIO
     ============================================================ */
  function trackLabel(fileName) {
    return String(fileName).replace(/\.mp3$/i, '').replace(/-/g, ' ')
      .replace(/^\w/, (c) => c.toUpperCase());
  }

  function applyAudioToPlayer() {
    if (!window.GameAudio) return;
    const a = pref.audio;
    GameAudio.setMusicEnabled(a.musicOn);
    GameAudio.setEffectsEnabled(a.sfxOn);
    GameAudio.setVolume('music', a.musicVolume);
    GameAudio.setVolume('effects', a.sfxVolume);
    GameAudio.setMusicTrack(a.musicTrack);
  }

  function bindSlider(inputSel, valSel, onCommit) {
    const input = $(inputSel);
    const val = $(valSel);
    if (!input) return;
    const renderVal = () => { if (val) val.textContent = input.value + '%'; };
    input.addEventListener('input', renderVal);
    input.addEventListener('change', () => {
      renderVal();
      onCommit(Number(input.value));
    });
  }

  function wireAudio() {
    const a = pref.audio;
    const audio = window.GameAudio;
    if (!audio) return;

    // Track select: only bundled local files.
    const trackSel = $('#set-audio-track');
    if (trackSel) {
      MUSIC_TRACKS.forEach((t) => {
        const o = document.createElement('option');
        o.value = t;
        o.textContent = trackLabel(t);
        trackSel.appendChild(o);
      });
      trackSel.value = MUSIC_TRACKS.indexOf(a.musicTrack) !== -1 ? a.musicTrack : MUSIC_TRACKS[0];
      trackSel.addEventListener('change', () => {
        a.musicTrack = trackSel.value;
        save();
        audio.setMusicTrack(a.musicTrack);
        noteSaved('Music track updated');
      });
    }

    const musicOn = $('#set-audio-music-on');
    if (musicOn) {
      musicOn.checked = !!a.musicOn;
      musicOn.addEventListener('change', (e) => {
        a.musicOn = e.target.checked;
        save();
        audio.setMusicEnabled(a.musicOn);
        noteSaved(a.musicOn ? 'Music on' : 'Music muted');
      });
    }

    const sfxOn = $('#set-audio-sfx-on');
    if (sfxOn) {
      sfxOn.checked = !!a.sfxOn;
      sfxOn.addEventListener('change', (e) => {
        a.sfxOn = e.target.checked;
        save();
        audio.setEffectsEnabled(a.sfxOn);
        noteSaved(a.sfxOn ? 'Sound effects on' : 'Sound effects muted');
      });
    }

    const musicVol = Math.round(a.musicVolume * 100);
    const sfxVol = Math.round(a.sfxVolume * 100);
    const mVol = $('#set-audio-music-vol');
    if (mVol) {
      mVol.value = String(musicVol);
      const mv = $('#set-audio-music-vol-val');
      if (mv) mv.textContent = musicVol + '%';
      bindSlider('#set-audio-music-vol', '#set-audio-music-vol-val', (pct) => {
        a.musicVolume = Math.round(pct) / 100;
        save();
        audio.setVolume('music', a.musicVolume);
        noteSaved('Music volume updated');
      });
    }
    const sVol = $('#set-audio-sfx-vol');
    if (sVol) {
      sVol.value = String(sfxVol);
      const sv = $('#set-audio-sfx-vol-val');
      if (sv) sv.textContent = sfxVol + '%';
      bindSlider('#set-audio-sfx-vol', '#set-audio-sfx-vol-val', (pct) => {
        a.sfxVolume = Math.round(pct) / 100;
        save();
        audio.setVolume('effects', a.sfxVolume);
        noteSaved('Effects volume updated');
      });
    }

    const preview = $('#btn-audio-preview');
    if (preview) {
      preview.addEventListener('click', () => {
        if (audio.getMusicEnabled && !audio.getMusicEnabled()) {
          showToast('Background music is off — switch it on to preview.');
          return;
        }
        audio.setMusicTrack(a.musicTrack);
        showToast('Playing preview…');
      });
    }

    $$('[data-test-sound]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (audio.getEffectsEnabled && !audio.getEffectsEnabled()) {
          showToast('Sound effects are off — switch them on to test.');
          return;
        }
        audio.play(btn.dataset.testSound);
      });
    });
  }

  /* ============================================================
     TIMER
     ============================================================ */
  function fmtSeconds(s) {
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  function wireTimer() {
    const minEl = $('#set-timer-min');
    const secEl = $('#set-timer-sec');
    if (!minEl || !secEl) return;

    const paint = (total) => {
      minEl.value = String(Math.floor(total / 60));
      secEl.value = String(total % 60);
    };
    paint(pref.timer.turnSeconds);

    const readTotal = () => {
      let m = parseInt(minEl.value, 10);
      if (isNaN(m)) m = 0;
      let s = parseInt(secEl.value, 10);
      if (isNaN(s)) s = 0;
      m = Math.max(0, Math.min(5, m));
      s = Math.max(0, Math.min(59, s));
      return m * 60 + s;
    };

    const commit = () => {
      const total = readTotal();
      if (total < 1 || total > MAX_TURN_SECONDS) {
        showToast('Turn length must be between 1 second and 5:00.');
        paint(pref.timer.turnSeconds);
        return;
      }
      pref.timer.turnSeconds = total;
      save();
      noteSaved(`Turn length set to ${fmtSeconds(total)}`);
    };

    minEl.addEventListener('change', commit);
    secEl.addEventListener('change', commit);

    const setMode = (mode) => {
      pref.timer.timerMode = mode;
      save();
      ['countdown', 'countup'].forEach((m) => {
        const el = $('#set-timer-mode-' + m);
        if (el) {
          const on = m === mode;
          el.classList.toggle('seg__btn--active', on);
          el.setAttribute('aria-pressed', String(on));
        }
      });
      noteSaved('Timer direction: ' + (mode === 'countdown' ? 'Countdown' : 'Count up'));
    };

    $('#set-timer-mode-countdown').addEventListener('click', () => setMode('countdown'));
    $('#set-timer-mode-countup').addEventListener('click', () => setMode('countup'));

    $$('.timer-presets .preset-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const total = Number(btn.dataset.seconds);
        paint(total);
        pref.timer.turnSeconds = total;
        save();
        noteSaved(`Turn length set to ${fmtSeconds(total)}`);
      });
    });
  }

  /* ============================================================
     PREF CONTROLS (selects + toggles)
     ============================================================ */
  function wireSelects() {
    const bindings = [
      { sel: '#set-game-maxwords', path: ['game', 'maxWordsPerTeam'], msg: 'Game preference saved' },
      { sel: '#set-game-penalty', path: ['game', 'penaltySeconds'], msg: 'Game preference saved' },
      { sel: '#set-timer-warn', path: ['timer', 'warnSeconds'], msg: 'Timer preference saved' },
      { sel: '#set-teams-maxteams', path: ['teams', 'maxTeams'], msg: 'Team preference saved' },
      { sel: '#set-teams-maxmembers', path: ['teams', 'maxMembers'], msg: 'Team preference saved' },
    ];
    bindings.forEach((b) => {
      const el = $(b.sel);
      if (!el) return;
      el.value = String(getPref(b.path));
      el.addEventListener('change', () => {
        setPref(b.path, coerce(el.value));
        save();
        noteSaved(b.msg);
      });
    });
  }

  function wireToggles() {
    const bindings = [
      { id: 'set-teams-allow-new', path: ['teams', 'allowNewTeams'], msg: 'Team preference saved' },
      { id: 'set-teams-autoapprove', path: ['teams', 'autoApprove'], msg: 'Team preference saved' },
      { id: 'set-display-names', path: ['display', 'showPlayerNames'], msg: 'Display preference saved' },
      { id: 'set-display-roles', path: ['display', 'showRoleLabels'], msg: 'Display preference saved' },
      { id: 'set-display-scores', path: ['display', 'showScores'], msg: 'Display preference saved' },
      { id: 'set-display-qr', path: ['display', 'showQrCode'], msg: 'Display preference saved' },
      { id: 'set-display-round', path: ['display', 'showRoundCategory'], msg: 'Display preference saved' },
      { id: 'set-host-lock', path: ['host', 'lockGame'], msg: 'Lock updated' },
    ];
    bindings.forEach((b) => {
      const el = document.getElementById(b.id);
      if (!el) return;
      el.checked = !!getPref(b.path);
      el.addEventListener('change', () => {
        setPref(b.path, el.checked);
        save();
        noteSaved(b.msg);
      });
    });
  }

  /* ============================================================
     ROUND-NAV / REVEAL
     ============================================================ */
  function wireNavSkeleton() {
    bindCopy($('#btn-copy-code'), () => STATE.gameCode);
    bindCopy($('#btn-settings-copy'), () => STATE.gameCode);
    bindCopy($('#btn-settings-qr-copy'), () => STATE.gameCode);
  }

  function initReveal() {
    const els = $$('.reveal');
    if (!els.length) return;
    if (!('IntersectionObserver' in window)) {
      els.forEach((el) => el.classList.add('visible'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
    els.forEach((el) => io.observe(el));
  }

  /* ============================================================
     REALTIME (keep status honest while open)
     ============================================================ */
  function initRealtime(gameId) {
    const rt = (typeof window !== 'undefined') ? window.Realtime : null;
    if (!rt || !rt.on || !gameId) return;
    ['game_started', 'game_paused', 'game_resumed', 'game_completed', 'match_started'].forEach((evt) => {
      rt.on(evt, () => refreshStatus());
    });
    if (!rt.getSocket || !rt.getSocket()) {
      rt.connect({ mode: 'host' });
      rt.onConnect && rt.onConnect(() => refreshStatus());
      rt.onReconnect && rt.onReconnect(() => refreshStatus());
    }
  }

  /* ============================================================
     BOOTSTRAP
     ============================================================ */
  async function bootstrap() {
    const diagToken = API.getHostToken ? (API.getHostToken() ? 'present' : 'missing') : 'n/a';
    console.log('[settings] bootstrap', {
      host_token: diagToken,
      game_id: API.getGameId(),
      host_game_id: API.getHostGameId(),
      game_code: API.getGameCode(),
    });

    let gameId = API.getGameId() || API.getHostGameId();

    try {
      const r = await Connect.restoreHostSession();
      if (r.status === 'connected' && r.data && r.data.game_id) gameId = r.data.game_id;
      if (r.status === 'invalid' || r.status === 'unavailable') {
        Connect.showReconnectBanner({
          title: 'Host session not found',
          message: 'Your host session could not be restored. Reconnect to your game.',
        });
        document.body.setAttribute('data-reconnect-target', '../../index.html');
      }
    } catch (e) { /* ignore */ }

    if (!gameId) {
      console.warn('[settings] no host game session; showing "Create a game" state', { gameId });
      setNoSessionState();
      initReveal();
      return;
    }

    STATE.gameId = gameId;
    const code = API.getGameCode();
    if (code) {
      STATE.gameCode = code;
      setCodeDisplays(code);
    }

    refreshStatus();
    initRealtime(gameId);
  }

  /* ------------------------------------------------------------
     MOUNT: wire UI then bootstrap the session
     ------------------------------------------------------------ */
  wireAudio();
  wireTimer();
  wireSelects();
  wireToggles();
  wireNavSkeleton();
  wireModalClosers();

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshStatus();
  });
  window.addEventListener('focus', refreshStatus);

  $('#btn-nosession-goto').addEventListener('click', () => { window.location.href = 'host_dashboard.html'; });
  $('#btn-settings-qr').addEventListener('click', openQrModal);

  $('#btn-pause-resume').addEventListener('click', onPauseResume);
  $('#confirm-pause-btn').addEventListener('click', onConfirmPause);
  $('#btn-end-game').addEventListener('click', onEndGame);
  $('#confirm-end-btn').addEventListener('click', onConfirmEnd);
  $('#btn-leave-game').addEventListener('click', onLeaveGame);
  $('#confirm-leave-btn').addEventListener('click', onConfirmLeave);
  $('#btn-delete-saved').addEventListener('click', onDeleteSaved);
  $('#input-delete-code').addEventListener('input', onDeleteInput);
  $('#confirm-delete-btn').addEventListener('click', onConfirmDelete);

  initReveal();
  bootstrap();
})();