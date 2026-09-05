'use strict';

/* ============================================================
   Word + Category API — /api/games/<id>/words, /api/words,
   /api/games/<id>/categories, /api/categories
   ============================================================ */

const WordAPI = (() => {
  // ---------------- Categories ----------------

  // GET /api/games/<game_id>/categories  -> { categories: [...] }
  function listCategories(gameId) {
    return API.request(`/games/${gameId}/categories`);
  }

  // POST /api/games/<game_id>/categories  { name }
  function createCategory(gameId, name) {
    return API.request(`/games/${gameId}/categories`, {
      method: 'POST',
      body: { name },
      host: true,
    });
  }

  // PATCH /api/categories/<category_id>  { name }
  function updateCategory(categoryId, name) {
    return API.request(`/categories/${categoryId}`, {
      method: 'PATCH',
      body: { name },
      host: true,
    });
  }

  // DELETE /api/categories/<category_id>
  function deleteCategory(categoryId) {
    return API.request(`/categories/${categoryId}`, { method: 'DELETE', host: true });
  }

  // ---------------- Words ----------------

  // GET /api/games/<game_id>/words  -> { words: [...] }  (host only)
  function listWords(gameId) {
    return API.request(`/games/${gameId}/words`, { host: true });
  }

  // GET /api/games/<game_id>/words/my  -> own team's words (via session)
  function listMyWords(gameId) {
    return API.request(`/games/${gameId}/words/my`, { session: true });
  }

  // POST /api/games/<game_id>/words
  //   host:   { category_id, word_text, team_id }
  //   player: { category_id, word_text }  (uses X-Session-Token)
  function createWord(gameId, { categoryId, wordText, teamId, asHost = true }) {
    const body = { category_id: categoryId, word_text: wordText };
    if (teamId) body.team_id = teamId;
    return API.request(`/games/${gameId}/words`, {
      method: 'POST',
      body,
      host: asHost,
      session: !asHost,
    });
  }

  // PATCH /api/words/<word_id>  { word_text, category_id? }
  function updateWord(wordId, wordText, opts = {}) {
    const body = { word_text: wordText };
    if (opts.categoryId) body.category_id = opts.categoryId;
    return API.request(`/words/${wordId}`, {
      method: 'PATCH',
      body,
      host: opts.asHost === false ? false : true,
      session: opts.asHost === false,
    });
  }

  // DELETE /api/words/<word_id>
  function deleteWord(wordId, opts = {}) {
    return API.request(`/words/${wordId}`, {
      method: 'DELETE',
      host: opts.asHost === false ? false : true,
      session: opts.asHost === false,
    });
  }

  // POST /api/words/<word_id>/disable
  function disableWord(wordId, opts = {}) {
    return API.request(`/words/${wordId}/disable`, {
      method: 'POST',
      host: opts.asHost === false ? false : true,
      session: opts.asHost === false,
    });
  }

  return {
    listCategories,
    createCategory,
    updateCategory,
    deleteCategory,
    listWords,
    listMyWords,
    createWord,
    updateWord,
    deleteWord,
    disableWord,
  };
})();

if (typeof window !== 'undefined') window.WordAPI = WordAPI;
