'use strict';

/* ============================================================
   Round API — /api/games/<id>/rounds
   ============================================================ */

const RoundAPI = (() => {
  // POST /api/games/<game_id>/rounds  { round_number, timer_seconds?, timer_mode? }
  function createRound(gameId, { roundNumber, timerSeconds, timerMode } = {}) {
    const body = { round_number: roundNumber };
    if (timerSeconds !== undefined && timerSeconds !== null) body.timer_seconds = timerSeconds;
    if (timerMode) body.timer_mode = timerMode;
    return API.request(`/games/${gameId}/rounds`, {
      method: 'POST',
      body,
      host: true,
    });
  }

  // GET /api/games/<game_id>/rounds  -> { rounds: [...] }
  function listRounds(gameId) {
    return API.request(`/games/${gameId}/rounds`, { host: true });
  }

  // POST /api/games/<game_id>/rounds/<round_number>/categories  { category_ids: [] }
  function selectRoundCategories(gameId, roundNumber, categoryIds) {
    return API.request(`/games/${gameId}/rounds/${roundNumber}/categories`, {
      method: 'POST',
      body: { category_ids: categoryIds },
      host: true,
    });
  }

  // GET /api/games/<game_id>/rounds/<round_number>/categories  -> { categories: [...] }
  function roundCategories(gameId, roundNumber) {
    return API.request(`/games/${gameId}/rounds/${roundNumber}/categories`, { host: true });
  }

  // POST /api/games/<game_id>/rounds/<round_number>/timer  { timer_seconds, timer_mode }
  function updateTimer(gameId, roundNumber, { timerSeconds, timerMode } = {}) {
    const body = {};
    if (timerSeconds !== undefined && timerSeconds !== null) body.timer_seconds = timerSeconds;
    if (timerMode) body.timer_mode = timerMode;
    return API.request(`/games/${gameId}/rounds/${roundNumber}/timer`, {
      method: 'POST',
      body,
      host: true,
    });
  }

  // POST /api/games/<game_id>/rounds/<round_number>/advance
  function advanceRound(gameId, roundNumber) {
    return API.request(`/games/${gameId}/rounds/${roundNumber}/advance`, {
      method: 'POST',
      host: true,
    });
  }

  // POST /api/games/<game_id>/rounds/<round_number>/reset
  function resetRound(gameId, roundNumber) {
    return API.request(`/games/${gameId}/rounds/${roundNumber}/reset`, {
      method: 'POST',
      host: true,
    });
  }

  return {
    createRound,
    listRounds,
    selectRoundCategories,
    roundCategories,
    updateTimer,
    advanceRound,
    resetRound,
  };
})();

if (typeof window !== 'undefined') window.RoundAPI = RoundAPI;
