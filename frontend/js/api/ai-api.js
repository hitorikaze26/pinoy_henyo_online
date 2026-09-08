'use strict';

/* ============================================================
   AI Word Generator API — POST /api/games/<id>/ai/generate-words
   ------------------------------------------------------------
   Reaches the shared backend endpoint for AI-suggested words.
   Both auth flags are set: the endpoint accepts either a host
   token (host device) or a session token (team device).
   ============================================================ */

const AIAPI = (() => {
  // -> { category_id, category_name, language, suggestions, available_slots }
  function generateWords(gameId, { categoryId, count, language, excludeWords }) {
    return API.request(`/games/${gameId}/ai/generate-words`, {
      method: 'POST',
      body: {
        category_id: categoryId,
        count,
        language,
        exclude_words: Array.isArray(excludeWords) ? excludeWords : [],
      },
      host: true,
      session: true,
    });
  }

  return { generateWords };
})();

if (typeof window !== 'undefined') window.AIAPI = AIAPI;