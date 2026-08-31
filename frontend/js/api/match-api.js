'use strict';

/* ============================================================
   Match API — /api/games/<id>/matches, /api/matches/<id>
   ============================================================ */

const MatchAPI = (() => {
  // POST /api/games/<game_id>/matches  { round_number, matches: [...] }
  //   where matches: [{ team_id, opponent_team_id, match_order? }]
  function createMatches(gameId, roundNumber, matches) {
    return API.request(`/games/${gameId}/matches`, {
      method: 'POST',
      body: { round_number: roundNumber, matches },
      host: true,
    });
  }

  // GET /api/games/<game_id>/matches  -> { matches: [...] }
  function listMatches(gameId) {
    return API.request(`/games/${gameId}/matches`, { host: true });
  }

  // PATCH /api/matches/<match_id>  { match_order }
  function reorderMatch(matchId, matchOrder) {
    return API.request(`/matches/${matchId}`, {
      method: 'PATCH',
      body: { match_order: matchOrder },
      host: true,
    });
  }

  return { createMatches, listMatches, reorderMatch };
})();

if (typeof window !== 'undefined') window.MatchAPI = MatchAPI;
