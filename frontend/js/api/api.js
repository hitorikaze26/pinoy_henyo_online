'use strict';

/* ============================================================
   Pinoy Henyo Online — Central API Client
   ------------------------------------------------------------
   - Fetch wrapper over the Flask REST API.
   - Manages auth tokens:
       * Host token   -> X-Host-Token
       * Session token-> X-Session-Token
   - Normalizes the backend envelope { success, data, error }.
   - Maps HTTP status codes to human-readable messages.
   - Provides loading-state helpers to prevent duplicate submits.
   ============================================================ */

const API = (() => {
  // Centralized backend config — frontend/js/core/config.js is the SINGLE
  // source of truth (window.PINOY_CONFIG.API_BASE_URL). It must load before
  // this file on every page. The legacy window.PINOY_API_BASE override and the
  // same-origin/localhost fallbacks below only apply if config.js is absent.
  const _cfg = (typeof window !== 'undefined' && window.PINOY_CONFIG) || null;
  const DEFAULT_BASE =
    (_cfg && _cfg.API_BASE_URL) ||
    (window.PINOY_API_BASE) ||
    (((window.location && window.location.origin) || 'http://localhost:5000') + '/api');

  const SERVER_ERROR = { code: 'NETWORK_ERROR', message: 'Could not reach the server. Please try again.' };

  let baseUrl = (_cfg && _cfg.API_BASE_URL) || window.PINOY_API_BASE || DEFAULT_BASE;

  /* ============================================================
     Session store.
     Persists the full connection context so that refreshing or
     re-opening a page can restore host/team/member/device identity
     and reconnect using the saved tokens.
     ------------------------------------------------------------
     Security note: tokens are stored in localStorage for cross-page
     continuity. Beware that localStorage is readable by any script
     on the origin. Prefer sessionStorage for stricter isolation, or
     memory-only storage if this app runs on a single page.
     ============================================================ */
  const STORAGE_KEY = 'pinoy_henyo_session';
  const DEVICE_KEY  = 'pinoy_henyo_device_id';
  const MY_GAMES_KEY = 'pinoy_henyo_my_games';

  // In-memory default context, seeded from shared window fields.
  const ctx = {
    role:          null,            // 'host' | 'team-leader' | 'team-member' | null
    hostToken:     null,            // X-Host-Token
    sessionToken:  null,            // X-Session-Token
    deviceId:      null,            // stable device id (persisted separately)
    memberId:      null,            // current member
    teamId:        null,
    teamCode:      null,
    teamName:      null,
    gameId:        null,
    gameCode:      null,
    username:      null,
    deviceRole:    null,            // 'TEAM_LEADER' | 'TEAM_MEMBER'
    gameplayRole:  null,            // 'MANGHUHULA' | 'TAGASAGOT' | null
    hostGameId:    null,            // game the host owns (when role=host)
    teams:         [],              // known teams [{team_id, team_name}] for setup pages
  };

  function loadLocal() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      return {};
    }
  }

  function persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        role:          ctx.role,
        hostToken:     ctx.hostToken,
        sessionToken:  ctx.sessionToken,
        memberId:      ctx.memberId,
        teamId:        ctx.teamId,
        teamCode:      ctx.teamCode,
        teamName:      ctx.teamName,
        gameId:        ctx.gameId,
        gameCode:      ctx.gameCode,
        username:      ctx.username,
        deviceRole:    ctx.deviceRole,
        gameplayRole:  ctx.gameplayRole,
        hostGameId:    ctx.hostGameId,
        teams:         ctx.teams,
      }));
    } catch (e) { /* storage disabled (private mode) */ }
  }

  function _loadDeviceId() {
    try {
      let id = localStorage.getItem(DEVICE_KEY);
      if (!id) {
        id = 'dev-' + Math.random().toString(36).slice(2, 12) + '-' + Date.now().toString(36);
        localStorage.setItem(DEVICE_KEY, id);
      }
      return id;
    } catch (e) {
      return 'dev-' + Math.random().toString(36).slice(2, 12);
    }
  }

  /* ============================================================
     My Games registry.
     ------------------------------------------------------------
     The backend scopes GET /api/games/history to a single host
     token, but every game gets its OWN host token at creation, so
     history alone can only ever list the current game. To give the
     lobby a real "games from this device" list we persist a small
     per-game registry HERE (localStorage) that records each game's
     id / code / host_token / status on this browser. The token is
     never exposed by the server for other games, so this client-side
     index is the only place it is available; live status/winner
     fields can still be refreshed from the public status endpoint.
     ============================================================ */
  function loadMyGames() {
    try {
      const raw = localStorage.getItem(MY_GAMES_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }

  function saveMyGames(list) {
    try { localStorage.setItem(MY_GAMES_KEY, JSON.stringify(list)); }
    catch (e) { /* storage disabled */ }
  }

  // Upsert a game into the registry (fields never deleted when absent).
  function recordMyGame(info) {
    if (!info || info.game_id == null) return;
    const list = loadMyGames();
    const existing = list.find((g) => String(g.game_id) === String(info.game_id));
    if (existing) {
      if (info.game_code) existing.game_code = info.game_code;
      if (info.host_token) existing.host_token = info.host_token;
      if (info.status) existing.status = info.status;
      if (info.created_at) existing.created_at = info.created_at;
      if (info.saved_at) existing.saved_at = info.saved_at;
      if (info.winner_name) existing.winner_name = info.winner_name;
    } else {
      list.push({
        game_id: info.game_id,
        game_code: info.game_code || '',
        host_token: info.host_token || ctx.hostToken,
        status: info.status || null,
        created_at: info.created_at || new Date().toISOString(),
        saved_at: info.saved_at || null,
        winner_name: info.winner_name || null,
      });
    }
    saveMyGames(list);
  }

  // Merge a partial update into an existing registry entry.
  function updateMyGame(partial) {
    if (!partial || partial.game_id == null) return;
    const list = loadMyGames();
    const match = list.find((g) => String(g.game_id) === String(partial.game_id));
    if (!match) return;
    Object.keys(partial).forEach((k) => {
      if (k !== 'game_id' && partial[k] !== undefined && partial[k] !== null) {
        match[k] = partial[k];
      }
    });
    saveMyGames(list);
  }

  function removeMyGame(gameId) {
    if (gameId == null) return;
    saveMyGames(loadMyGames().filter((g) => String(g.game_id) !== String(gameId)));
  }

  function clearMyGames() {
    try { localStorage.removeItem(MY_GAMES_KEY); } catch (e) { /* ignore */ }
  }

  /* ---------- generic get/set that keep ctx + storage in sync ---------- */
  function set(field, value) {
    ctx[field] = value === undefined ? null : value;
    // keep legacy window fields for backward-compat with existing pages
    if (field === 'gameId') window.PINOY_GAME_ID = ctx.gameId;
    if (field === 'teamId') window.PINOY_TEAM_ID = ctx.teamId;
    if (field === 'gameCode') window.PINOY_GAME_CODE = ctx.gameCode;
    persist();
  }
  function get(field) { return ctx[field]; }

  /* ============================================================
     Base URL
     ============================================================ */
  function setBaseUrl(url) {
    baseUrl = String(url || '').replace(/\/+$/, '');
  }

  function getBaseUrl() {
    return baseUrl;
  }

  /* ============================================================
     Tokens / identity (thin wrappers over the session store)
     ============================================================ */
  function setHostToken(token) { set('hostToken', token || null); }
  function getHostToken() { return ctx.hostToken; }

  function setSessionToken(token) { set('sessionToken', token || null); }
  function getSessionToken() { return ctx.sessionToken; }

  function getDeviceId() {
    if (!ctx.deviceId) set('deviceId', _loadDeviceId());
    return ctx.deviceId;
  }

  function setMemberIdentity(memberPayload, team) {
    // memberPayload: { member_id, team_id, username, device_role, gameplay_role, connection_token, is_connected }
    if (memberPayload) {
      if (memberPayload.member_id) set('memberId', memberPayload.member_id);
      if (memberPayload.team_id) set('teamId', memberPayload.team_id);
      if (memberPayload.username) set('username', memberPayload.username);
      if (memberPayload.device_role) set('deviceRole', memberPayload.device_role);
      if (memberPayload.gameplay_role !== undefined) set('gameplayRole', memberPayload.gameplay_role);
      // Preserve the 'host' role if this member is the host's own device. The
      // host creates a host-team AFTER setHostContext() flags role='host'; a
      // TEAM_LEADER identity must not downgrade the host session to 'team-leader'
      // (otherwise host pages lose their host context on restore).
      if (ctx.role === 'host') {
        // keep role = host
      } else if (memberPayload.device_role === 'TEAM_LEADER') {
        set('role', 'team-leader');
      } else if (memberPayload.device_role === 'TEAM_MEMBER') {
        set('role', 'team-member');
      }
    }
    if (team) {
      if (team.team_id) set('teamId', team.team_id);
      if (team.team_code) set('teamCode', team.team_code);
      if (team.team_name) set('teamName', team.team_name);
    }
  }

  function setHostContext(game) {
    // game: { game_id, game_code, host_session_token?, status }
    if (game) {
      if (game.game_id) { set('hostGameId', game.game_id); set('gameId', game.game_id); }
      if (game.game_code) set('gameCode', game.game_code);
      ctx.role = 'host';
    }
  }

  function clearTokens() {
    Object.keys(ctx).forEach((k) => { ctx[k] = null; });
    window.PINOY_GAME_ID = null;
    window.PINOY_TEAM_ID = null;
    window.PINOY_GAME_CODE = null;
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  }

  // Restore persisted context into memory (called once on load).
  function restoreFromStorage() {
    const data = loadLocal();
    Object.keys(ctx).forEach((k) => { ctx[k] = null; });
    if (data.role) ctx.role = data.role;
    if (data.hostToken) ctx.hostToken = data.hostToken;
    if (data.sessionToken) ctx.sessionToken = data.sessionToken;
    if (data.memberId) ctx.memberId = data.memberId;
    if (data.teamId) ctx.teamId = data.teamId;
    if (data.teamCode) ctx.teamCode = data.teamCode;
    if (data.teamName) ctx.teamName = data.teamName;
    if (data.gameId) ctx.gameId = data.gameId;
    if (data.gameCode) ctx.gameCode = data.gameCode;
    if (data.username) ctx.username = data.username;
    if (data.deviceRole) ctx.deviceRole = data.deviceRole;
    if (data.gameplayRole) ctx.gameplayRole = data.gameplayRole;
    if (data.hostGameId) ctx.hostGameId = data.hostGameId;
    ctx.teams = Array.isArray(data.teams) ? data.teams : [];
    ctx.deviceId = _loadDeviceId();
    window.PINOY_GAME_ID = ctx.gameId;
    window.PINOY_TEAM_ID = ctx.teamId;
    window.PINOY_GAME_CODE = ctx.gameCode;
  }

  /* ---------- current game context (shared across pages) ---------- */
  function getGameId() { return get('gameId'); }
  function setGameId(gameId) { set('gameId', gameId || null); }

  /* ---------- current team context (for the player side) ---------- */
  function getTeamId() { return get('teamId'); }
  function setTeamId(teamId) { set('teamId', teamId || null); }

  /* ---------- current game code (returned only at creation) ---------- */
  function getGameCode() { return get('gameCode'); }
  function setGameCode(gameCode) { set('gameCode', gameCode || null); }

  /* ---------- member / team / role identity ---------- */
  function getMemberId() { return get('memberId'); }
  function setMemberId(memberId) { set('memberId', memberId || null); }
  function getTeamCode() { return get('teamCode'); }
  function setTeamCode(teamCode) { set('teamCode', teamCode || null); }
  function getTeamName() { return get('teamName'); }
  function setTeamName(teamName) { set('teamName', teamName || null); }
  function getUsername() { return get('username'); }
  function setUsername(username) { set('username', username || null); }
  function getDeviceRole() { return get('deviceRole'); }
  function setDeviceRole(deviceRole) { set('deviceRole', deviceRole || null); }
  function getGameplayRole() { return get('gameplayRole'); }
  function setGameplayRole(gameplayRole) { set('gameplayRole', gameplayRole || null); }
  function getRole() { return get('role'); }
  function setRole(role) { set('role', role || null); }
  function getHostGameId() { return get('hostGameId'); }
  function setHostGameId(hostGameId) { set('hostGameId', hostGameId || null); }

  /* ---------- known teams (setup pages) ---------- */
  // Backend has no team-list endpoint, so the teams page records each
  // created team here (real backend id + name) for match/setup pages.
  function addKnownTeam(teamId, teamName) {
    if (!teamId) return;
    const existing = (ctx.teams || []).find((t) => t.team_id === teamId);
    if (existing) {
      if (teamName) existing.team_name = teamName;
    } else {
      ctx.teams = (ctx.teams || []).concat([{ team_id: teamId, team_name: teamName || '' }]);
    }
    persist();
  }
  function getKnownTeams() { return (ctx.teams || []).slice(); }
  function clearKnownTeams() { ctx.teams = []; persist(); }
  function getSessionContext() { return { ...ctx }; }

  /* ============================================================
     HTTP status -> friendly message
     ============================================================ */
  function messageForStatus(status, fallback) {
    const map = {
      400: 'The request was not valid. Please check your input.',
      401: 'You are not authenticated. Please reconnect or log in again.',
      403: 'You do not have permission to perform this action.',
      404: 'The requested item was not found.',
      405: 'That action is not supported here.',
      409: 'This action conflicts with the current game state.',
      422: 'The request could not be processed.',
      429: 'Too many requests. Please slow down and try again shortly.',
      500: 'An unexpected server error occurred. Please try again.',
    };
    return map[status] || fallback || 'Something went wrong. Please try again.';
  }

  /* ============================================================
     Core request
     ============================================================ */
  async function request(path, { method = 'GET', body, params, host = false, session = false } = {}) {
    let url = `${baseUrl}${path}`;
    if (params && typeof params === 'object') {
      const qs = Object.keys(params)
        .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== '')
        .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
        .join('&');
      if (qs) url += `?${qs}`;
    }

    const headers = { 'Content-Type': 'application/json' };
    if (host && ctx.hostToken) headers['X-Host-Token'] = ctx.hostToken;
    if (session && ctx.sessionToken) headers['X-Session-Token'] = ctx.sessionToken;
    // Implicit fallback: only for READ-ONLY (GET) requests, attach the host
    // token if present. This lets the host call "public" read endpoints and
    // still receive host-level data (e.g. game history, full turn payloads)
    // where the backend checks for the token. Mutating requests (POST/PUT/
    // DELETE) never leak the host token implicitly — they must opt in via
    // `host: true` — so a player action in the same browser is not
    // misclassified as a host call.
    if ((method === 'GET' || method === 'HEAD') && !host && !session && ctx.hostToken) {
      headers['X-Host-Token'] = ctx.hostToken;
    }

    let payload;
    try {
      payload = await fetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw { network: true, code: 'NETWORK_ERROR', message: SERVER_ERROR.message, status: 0 };
    }

    let json = null;
    try {
      json = await payload.json();
    } catch (e) {
      json = null;
    }

    if (!payload.ok) {
      const code = (json && json.error && json.error.code) || 'UNKNOWN_ERROR';
      const serverMsg = (json && json.error && json.error.message) || null;
      const retryAfter =
        (json && json.error && json.error.retry_after) ||
        (payload.headers && Number(payload.headers.get('Retry-After'))) ||
        0;
      let message = serverMsg || messageForStatus(payload.status, code.replace(/_/g, ' ').toLowerCase());
      if (payload.status === 429 && retryAfter > 0) {
        message = `Too many requests. Please try again in ${retryAfter}s.`;
      }
      throw {
        network: false,
        status: payload.status,
        code,
        message,
        retryAfter,
        raw: json,
      };
    }

    return json && typeof json.data !== 'undefined' ? json.data : json;
  }

  /* ============================================================
     Loading helpers (prevent duplicate submissions)
     ============================================================ */
  // Tracks in-flight operations keyed by a logical name.
  const inFlight = new Set();

  function isLoading(name) {
    return inFlight.has(name);
  }

  async function withLoading(name, fn) {
    if (inFlight.has(name)) {
      throw { code: 'DUPLICATE_SUBMIT', message: 'Please wait for the current action to finish.', status: 409 };
    }
    inFlight.add(name);
    try {
      return await fn();
    } finally {
      inFlight.delete(name);
    }
  }

  // Bind a disabled attribute to a button/input group during an operation.
  function loadingButtons(names, busy) {
    names.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = busy;
    });
  }

  // Bootstrap: restore any previously-stored identity on page load so
  // multi-page navigation keeps the host/session context alive.
  restoreFromStorage();

  return {
    setBaseUrl,
    getBaseUrl,
    setHostToken,
    getHostToken,
    setSessionToken,
    getSessionToken,
    getDeviceId,
    setMemberIdentity,
    setHostContext,
    setMemberId,
    getMemberId,
    setTeamCode,
    getTeamCode,
    setTeamName,
    getTeamName,
    setUsername,
    getUsername,
    setDeviceRole,
    getDeviceRole,
    setGameplayRole,
    getGameplayRole,
    setRole,
    getRole,
    setHostGameId,
    getHostGameId,
    addKnownTeam,
    getKnownTeams,
    clearKnownTeams,
    getSessionContext,
    clearTokens,
    restoreFromStorage,
    getGameId,
    setGameId,
    getTeamId,
    setTeamId,
    getGameCode,
    setGameCode,
    getMyGames,
    recordMyGame,
    updateMyGame,
    removeMyGame,
    clearMyGames,
    request,
    withLoading,
    isLoading,
    loadingButtons,
    messageForStatus,
  };
})();

if (typeof window !== 'undefined') {
  window.PinoyAPI = API;
}
