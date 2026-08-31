'use strict';

/* ============================================================
   Turn API — /api/matches/<id>/turns, /api/turns/<id>
   ============================================================ */

const TurnAPI = (() => {
  // POST /api/matches/<match_id>/turns  { word_ids?: [], count? }  (host only)
  function createTurn(matchId, { wordIds, count } = {}) {
    const body = {};
    if (wordIds) body.word_ids = wordIds;
    if (count !== undefined && count !== null) body.count = count;
    return API.request(`/matches/${matchId}/turns`, {
      method: 'POST',
      body,
      host: true,
    });
  }

  // GET /api/matches/<match_id>/turns  -> { turns: [...] }  (host only)
  function listTurns(matchId) {
    return API.request(`/matches/${matchId}/turns`, { host: true });
  }

  // POST /api/matches/<match_id>/turn/start  (host or team session)
  // Sends whichever auth is available — host token wins if both exist.
  function startTurn(matchId) {
    const hasSession = !!API.getSessionToken();
    const hasHost    = !!API.getHostToken();
    return API.request(`/matches/${matchId}/turn/start`, {
      method:  'POST',
      host:    hasHost,
      session: !hasHost && hasSession,
    });
  }

  // GET /api/turns/<turn_id>  -> full secret payload (host) or team payload (session)
  function getTurn(turnId) {
    return API.request(`/turns/${turnId}`, { session: true });
  }

  // GET /api/turns/<turn_id>  -> full host payload (word text visible)
  function getTurnAsHost(turnId) {
    return API.request(`/turns/${turnId}`, { host: true });
  }

  // POST /api/turns/<turn_id>/correct  (host only)
  function correct(turnId) {
    return API.request(`/turns/${turnId}/correct`, { method: 'POST', host: true });
  }

  // POST /api/turns/<turn_id>/pass  (host only)
  function pass(turnId) {
    return API.request(`/turns/${turnId}/pass`, { method: 'POST', host: true });
  }

  // POST /api/turns/<turn_id>/timeout  (host only)
  function timeout(turnId) {
    return API.request(`/turns/${turnId}/timeout`, { method: 'POST', host: true });
  }

  // POST /api/turns/<turn_id>/pause  (host only)
  function pause(turnId) {
    return API.request(`/turns/${turnId}/pause`, { method: 'POST', host: true });
  }

  // POST /api/turns/<turn_id>/resume  (host only)
  function resume(turnId) {
    return API.request(`/turns/${turnId}/resume`, { method: 'POST', host: true });
  }

  // POST /api/turns/<turn_id>/time/add  { seconds }  (host only)
  function addTime(turnId, seconds) {
    return API.request(`/turns/${turnId}/time/add`, { method: 'POST', body: { seconds }, host: true });
  }

  // POST /api/turns/<turn_id>/time/remove  { seconds }  (host only)
  function removeTime(turnId, seconds) {
    return API.request(`/turns/${turnId}/time/remove`, { method: 'POST', body: { seconds }, host: true });
  }

  // POST /api/turns/<turn_id>/end  (host only)
  function end(turnId) {
    return API.request(`/turns/${turnId}/end`, { method: 'POST', host: true });
  }

  return {
    createTurn,
    listTurns,
    startTurn,
    getTurn,
    getTurnAsHost,
    correct,
    pass,
    timeout,
    pause,
    resume,
    addTime,
    removeTime,
    end,
  };
})();

if (typeof window !== 'undefined') window.TurnAPI = TurnAPI;
