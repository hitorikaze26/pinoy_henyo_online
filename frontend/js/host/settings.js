'use strict';
/* ============================================================
   HOST SETTINGS PAGE
   ------------------------------------------------------------
   Game rules, teams & connections, and player display settings
   are SERVER-BACKED (per-game, table `game_settings`) and saved
   immediately on every change via PUT /api/games/<id>/settings.
   The server response is the source of truth: a failed update
   reverts the control and shows an error. Audio preferences stay
   device-local (`pinoy_henyo_settings.audio.*`).

   Lock behavior: max_words_per_category / max_teams / max_members
   freeze once the game leaves LOBBY/SETUP (status NOT IN
   LOBBY/SETUP). penalty_seconds, allow_new_teams,
   auto_approve_connections and the display flags stay live.
   ============================================================ */
(async function () {
  'use strict';

  /* ============================================================
     CONSTANTS / STORAGE (audio stays device-local)
     ============================================================ */
  const STORAGE_KEY = 'pinoy_henyo_settings';
  const TERMINAL_STATUSES = ['GAME_COMPLETE', 'CANCELLED', 'EXPIRED'];
  const RUNNING_STATUSES = ['READY', 'ROUND_1', 'ROUND_2', 'TIE_BREAKER', 'PAUSED'];
  const LOBBY_STATUSES = ['LOBBY', 'SETUP'];

  // Only files actually shipped under frontend/assets/sounds/ (local, no URLs).
  // Add future bundled tracks here; the folder is scanned for variants only.
  const MUSIC_TRACKS = ['game music.mp3'];

  // Legacy device-local defaults (audio is the only live section kept here).
  const DEFAULT_SETTINGS = {
    audio: { musicOn: true, musicVolume: 0.4, musicTrack: 'game music.mp3', sfxOn: true, sfxVolume: 0.6 },
  };

  // Control id -> server-backed settings key (snake_case payload).
  const CONTROL_KEYS = {
    'set-game-maxwords': 'max_words_per_category',
    'set-game-minwords': 'min_words_to_start',
    'set-game-penalty': 'penalty_seconds',
    'set-teams-allow-new': 'allow_new_teams',
    'set-teams-autoapprove': 'auto_approve_connections',
    'set-teams-maxteams': 'max_teams',
    'set-teams-maxmembers': 'max_members',
    'set-display-names': 'show_player_names',
    'set-display-roles': 'show_role_labels',
    'set-display-scores': 'show_scores',
    'set-display-qr': 'show_qr_code',
    'set-display-round': 'show_round_category',
  };
  const LOCKED_KEYS = ['max_words_per_category', 'min_words_to_start', 'max_teams', 'max_members'];

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

  /* ============================================================
     STATE
     ============================================================ */
  const STATE = {
    gameId: null,
    gameCode: null,
    status: null,       // raw backend status string ("" until fetched)
    settings: null,     // latest server-backed settings payload
    settingsLoaded: false,
  };

  function isRunning(status) { return RUNNING_STATUSES.indexOf(status || '') !== -1; }
  function isLocked(status) { return status && LOBBY_STATUSES.indexOf(status) === -1 && TERMINAL_STATUSES.indexOf(status) === -1; }
  function isTerminal(status) { return TERMINAL_STATUSES.indexOf(status || '') !== -1; }

  /* ============================================================
     TOAST — delegates to the global Toast Manager
     ============================================================ */
  function showToast(msg, duration) {
    if (window.Toast) window.Toast.showToast(msg, duration);
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

  function wireModalClosers() {
    $$('.dash-modal__close, .dash-modal__cancel').forEach((btn) => {
      btn.addEventListener('click', () => closeModal(btn.closest('.dash-modal-overlay')));
    });
  }

  /* ============================================================
     NO-SESSION STATE (audio stays visible)
     ============================================================ */
  const SESSION_ONLY_CARD_IDS = ['card-game', 'card-teams', 'card-display', 'card-danger'];

  function setNoSessionState() {
    SESSION_ONLY_CARD_IDS.forEach((id) => {
      const card = document.getElementById(id);
      if (card) card.hidden = true;
    });
    const banner = $('#settings-nosession');
    if (banner) banner.hidden = false;
    setCodeDisplays('------');
  }

  function setCodeDisplays(code) {
    ['game-code-display', 'delete-game-hint'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = code;
    });
  }

  /* ============================================================
     SERVER-BACKED CONTROL RENDERING
     ============================================================ */
  function controlOf(id) { return CONTROL_KEYS[id]; }

  function paintControl(el) {
    const key = controlOf(el && el.id);
    if (!key || !STATE.settings) return;
    if (el.type === 'checkbox') {
      el.checked = !!STATE.settings[key];
    } else {
      el.value = String(STATE.settings[key]);
    }
  }

  function paintAllControls() {
    Object.keys(CONTROL_KEYS).forEach((id) => {
      const el = document.getElementById(id);
      if (el) paintControl(el);
    });
  }

  function applySettings(payload) {
    if (!payload || typeof payload !== 'object') return;
    STATE.settings = payload;
    STATE.settingsLoaded = true;
    paintAllControls();
  }

  function setRowStatus(el, state, text) {
    const row = el.closest ? el.closest('.setting-row') : null;
    const status = row && row.querySelector('.setting-row__status');
    if (!status) return;
    status.className = 'setting-row__status' + (state ? ' setting-row__status--' + state : '');
    status.textContent = text || '';
  }

  function currentValueOf(el) {
    return el.type === 'checkbox' ? el.checked : Number(el.value);
  }

  async function saveControl(el) {
    const key = controlOf(el && el.id);
    if (!key || !STATE.gameId) return;
    const value = currentValueOf(el);
    setRowStatus(el, 'busy', 'Saving…');
    try {
      const res = await GameAPI.updateSettings(STATE.gameId, { [key]: value });
      applySettings(res);
      setRowStatus(el, 'done', 'Saved');
    } catch (e) {
      console.warn('[settings] save failed', e && e.message);
      const code = e && e.data && e.data.error && e.data.error.code;
      if (code === 'SETTINGS_LOCKED') {
        setRowStatus(el, 'error', 'Locked while playing');
        showToast('This setting locks once the game starts.');
      } else {
        setRowStatus(el, 'error', 'Not saved');
        showToast('Could not save that setting. Check the connection.');
      }
      // Server is the source of truth: revert the control to last known value.
      paintControl(el);
    }
  }

  function wireSelects() {
    const selects = $$('select');
    selects.forEach((el) => {
      if (!controlOf(el.id)) return;
      el.addEventListener('change', () => {
        const key = controlOf(el.id);
        if (LOCKED_KEYS.indexOf(key) !== -1 && isLocked(STATE.status)) return;
        saveControl(el);
      });
    });
  }

  function wireToggles() {
    $$('input[type="checkbox"]').forEach((el) => {
      if (!controlOf(el.id)) return;
      el.addEventListener('change', () => {
        if (el.id === 'set-teams-autoapprove' && el.checked && !STATE.settings.auto_approve_connections) {
          openModal($('#modal-confirm-autoapprove'));
          return;
        }
        saveControl(el);
      });
    });

    // Auto-approve confirm: apply the pending (already flipped) checkbox value.
    const confirmBtn = $('#confirm-autoapprove-btn');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', () => {
        closeModal($('#modal-confirm-autoapprove'));
        saveControl($('#set-teams-autoapprove'));
      });
    }
    // Cancel: revert the checkbox to the server value before anything saves.
    const cancelBtn = $('#cancel-confirm-autoapprove');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        paintControl($('#set-teams-autoapprove'));
      });
    }
    const closeBtn = $('#close-confirm-autoapprove');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        paintControl($('#set-teams-autoapprove'));
      });
    }
  }

  /* ============================================================
     LIVE LOCK (cap fields freeze once the game leaves LOBBY/SETUP)
     ============================================================ */
  function updateLiveLock() {
    const locked = isLocked(STATE.status);

    const gameCard = $('#card-game');
    const teamsCard = $('#card-teams');
    if (gameCard) gameCard.classList.toggle('is-locked', locked);
    if (teamsCard) teamsCard.classList.toggle('is-locked', locked);

    const gameLock = $('#game-maxwords-lock');
    if (gameLock) gameLock.hidden = !locked;
    const minWordsLock = $('#game-minwords-lock');
    if (minWordsLock) minWordsLock.hidden = !locked;
    const teamsLock = $('#teams-lock-badge');
    if (teamsLock) teamsLock.hidden = !locked;

    ['set-game-maxwords', 'set-game-minwords', 'set-teams-maxteams', 'set-teams-maxmembers'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = locked;
    });
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

  async function loadSettings() {
    if (!STATE.gameId) return;
    try {
      const res = await GameAPI.getSettings(STATE.gameId);
      applySettings(res);
    } catch (e) {
      console.warn('[settings] settings load failed', e && e.message);
    }
  }

  /* ============================================================
     DANGER ZONE FLOWS
     ============================================================ */
  function setBtnBusy(btn, busy) {
    if (!btn) return;
    btn.classList.toggle('is-busy', busy);
    btn.disabled = busy;
  }

  function onLeaveGame() {
    if (!window.HostLeaveGame) return;
    window.HostLeaveGame.confirmAndLeave();
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
      });
    }

    const musicOn = $('#set-audio-music-on');
    if (musicOn) {
      musicOn.checked = !!a.musicOn;
      musicOn.addEventListener('change', (e) => {
        a.musicOn = e.target.checked;
        save();
        audio.setMusicEnabled(a.musicOn);
      });
    }

    const sfxOn = $('#set-audio-sfx-on');
    if (sfxOn) {
      sfxOn.checked = !!a.sfxOn;
      sfxOn.addEventListener('change', (e) => {
        a.sfxOn = e.target.checked;
        save();
        audio.setEffectsEnabled(a.sfxOn);
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
     ROUND-NAV / REVEAL
     ============================================================ */
  function wireNavSkeleton() {
    bindCopy($('#btn-copy-code'), () => STATE.gameCode);
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
     REALTIME (keep settings + status honest while open)
     ============================================================ */
  function initRealtime(gameId) {
    const rt = (typeof window !== 'undefined') ? window.Realtime : null;
    if (!rt || !rt.on || !gameId) return;
    ['game_started', 'game_paused', 'game_resumed', 'game_completed', 'match_started'].forEach((evt) => {
      rt.on(evt, () => refreshStatus());
    });
    rt.on('settings_updated', (payload) => {
      applySettings(payload);
      refreshStatus();
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
    await loadSettings();
    initRealtime(gameId);
  }

  /* ------------------------------------------------------------
     MOUNT: wire UI then bootstrap the session
     ------------------------------------------------------------ */
  wireAudio();
  wireSelects();
  wireToggles();
  wireNavSkeleton();
  wireModalClosers();

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshStatus();
  });
  window.addEventListener('focus', refreshStatus);

  $('#btn-nosession-goto').addEventListener('click', () => { window.location.href = 'host_dashboard.html'; });
  $('#btn-leave-game').addEventListener('click', onLeaveGame);
  $('#btn-delete-saved').addEventListener('click', onDeleteSaved);
  $('#input-delete-code').addEventListener('input', onDeleteInput);
  $('#confirm-delete-btn').addEventListener('click', onConfirmDelete);

  initReveal();
  bootstrap();
})();