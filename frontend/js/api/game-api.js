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

  // GET /api/games/<id>/leaderboard  (host only) -> { leaderboard: [...] }
  function leaderboard(gameId) {
    return API.request(`/games/${gameId}/leaderboard`, { host: true });
  }

  // GET /api/games/<id>/statistics  (host only) -> statistics object
  function statistics(gameId) {
    return API.request(`/games/${gameId}/statistics`, { host: true });
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
  };
})();

if (typeof window !== 'undefined') window.GameAPI = GameAPI;
