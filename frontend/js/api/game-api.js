'use strict';

/* ============================================================
   Game API — /api/games
   ============================================================ */

const GameAPI = (() => {
  function create() {
    // POST /api/games -> { game_id, game_code, host_session_token, status }
    return API.request('/games', { method: 'POST' });
  }

  function get(gameId) {
    return API.request(`/games/${gameId}`, { host: true });
  }

  function getByCode(gameCode) {
    // GET /api/games/by-code/<code> -> game_summary (public, no auth needed)
    return API.request(`/games/by-code/${encodeURIComponent(gameCode)}`);
  }

  function status(gameId) {
    return API.request(`/games/${gameId}/status`);
  }

  function start(gameId) {
    return API.request(`/games/${gameId}/start`, { method: 'POST', host: true });
  }

  function pause(gameId) {
    return API.request(`/games/${gameId}/pause`, { method: 'POST', host: true });
  }

  function resume(gameId) {
    return API.request(`/games/${gameId}/resume`, { method: 'POST', host: true });
  }

  function end(gameId) {
    return API.request(`/games/${gameId}/end`, { method: 'POST', host: true });
  }

  function readiness(gameId) {
    return API.request(`/games/${gameId}/readiness`, { host: true });
  }

  function scores(gameId) {
    return API.request(`/games/${gameId}/scores`, { host: true });
  }

  function gameQr(gameId) {
    return API.request(`/games/${gameId}/qr`, { host: true });
  }

  // GET /api/games/history  (host only) -> { games: [...] }
  function history() {
    return API.request('/games/history', { host: true });
  }

  // GET /api/games/<id>/history  (host only) -> full game history
  function gameHistory(gameId) {
    return API.request(`/games/${gameId}/history`, { host: true });
  }

  // GET /api/games/<id>/leaderboard -> { leaderboard: [...] }
  // Accessible by the host OR any connected player device (session token).
  function leaderboard(gameId) {
    return API.request(`/games/${gameId}/leaderboard`, { host: true, session: true });
  }

  // GET /api/games/<id>/statistics  (host only) -> statistics object
  function statistics(gameId) {
    return API.request(`/games/${gameId}/statistics`, { host: true });
  }

  // POST /api/games/<id>/save -> GAME_SAVED checkpoint marker
  // DB is the source of truth; this never duplicates the game.
  function save(gameId) {
    return API.request(`/games/${gameId}/save`, { method: 'POST', host: true });
  }

  // GET /api/games/<id>/state (host only) -> recoverable resume snapshot
  function state(gameId) {
    return API.request(`/games/${gameId}/state`, { host: true });
  }

  // POST /api/games/<id>/leave -> end host device session, keep game
  function leave(gameId) {
    return API.request(`/games/${gameId}/leave`, { method: 'POST', host: true });
  }

  // DELETE /api/games/<id>  (host only, terminal games only, needs confirm)
  function deleteGame(gameId, { confirm = true } = {}) {
    return API.request(`/games/${gameId}`, {
      method: 'DELETE',
      host: true,
      body: { confirm },
    });
  }

  // GET /api/games/<id>/settings (public, no secrets) -> server-backed settings
  function getSettings(gameId) {
    return API.request(`/games/${gameId}/settings`);
  }

  // PUT /api/games/<id>/settings (host only) -> persists + broadcasts settings
  function updateSettings(gameId, payload) {
    return API.request(`/games/${gameId}/settings`, {
      method: 'PUT',
      host: true,
      body: payload,
    });
  }

  return {
    create,
    get,
    getByCode,
    status,
    start,
    pause,
    resume,
    end,
    readiness,
    scores,
    gameQr,
    history,
    gameHistory,
    leaderboard,
    statistics,
    save,
    state,
    leave,
    deleteGame,
    getSettings,
    updateSettings,
  };
})();

if (typeof window !== 'undefined') window.GameAPI = GameAPI;
