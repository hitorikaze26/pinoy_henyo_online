'use strict';

/* ============================================================
   Player — Forced Word Change Request handling
   ------------------------------------------------------------
   The host may ask a team to correct one of its submitted words.
   The backend marks the word UNDER_REVIEW and emits
   `word_change_request` to the team + game rooms. This page must
   show a NON-DISMISSIBLE modal until the team resolves it (or the
   host cancels it).

   Notes:
     - The overlay deliberately uses its own `.wcr-overlay` class so
       the global backdrop/Escape close wiring in core/modal.js
       (which targets `.modal-overlay`) can never close it.
     - The request is recovered on load and on (re)connect so a
       refresh or a network drop never silently loses a pending ask.
   ============================================================ */

(() => {
  const AllowedChars = /^[\p{L}\p{N} -]+$/u;

  const WordChange = (() => {
    let currentRequest = null;
    let submitting = false;

    const overlay = () => document.getElementById('wcr-modal');

    function gameId() {
      return (typeof API !== 'undefined' && API.getGameId()) || null;
    }

    function sessionToken() {
      return (typeof API !== 'undefined' && API.getSessionToken()) || '';
    }

    function toast(message, duration) {
      if (typeof window.showToast === 'function') {
        window.showToast(message, duration);
      }
    }

    function clearError() {
      const word = document.getElementById('wcr-word');
      const err = document.getElementById('wcr-error-word');
      if (word) word.classList.remove('error');
      if (err) err.textContent = '';
    }

    function setError(message) {
      const word = document.getElementById('wcr-word');
      const err = document.getElementById('wcr-error-word');
      if (word) word.classList.add('error');
      if (err) err.textContent = message;
    }

    function setSubmitting(flag) {
      submitting = flag;
      const btn = document.getElementById('wcr-submit');
      if (btn) {
        btn.disabled = flag;
        const label = document.getElementById('wcr-submit-label');
        if (label) label.textContent = flag ? 'Sending…' : 'Send Correction';
      }
    }

    function openFor(req) {
      if (!req || !req.id) return;
      currentRequest = req;
      const word = document.getElementById('wcr-word');
      const cat = document.getElementById('wcr-category');
      const comment = document.getElementById('wcr-comment');
      if (word) word.value = req.word_text || '';
      if (cat) cat.value = req.category_name || '';
      if (comment) comment.value = req.comment || '';
      clearError();
      const el = overlay();
      if (el) {
        el.classList.add('is-open');
        el.setAttribute('aria-hidden', 'false');
      }
      document.body.style.overflow = 'hidden';
      const input = document.getElementById('wcr-word');
      if (input) input.focus();
    }

    function close() {
      currentRequest = null;
      const el = overlay();
      if (el) {
        el.classList.remove('is-open');
        el.setAttribute('aria-hidden', 'true');
      }
      document.body.style.overflow = '';
      clearError();
      setSubmitting(false);
    }

    function matches(req) {
      return currentRequest && req && currentRequest.id === req.id;
    }

    function isMine(req) {
      return req && req.team_id != null
        && req.team_id === (typeof API !== 'undefined' && API.getTeamId());
    }

    function friendlyError(code, message) {
      const hints = {
        WORD_TEXT_INVALID: 'That word text is not allowed here.',
        DUPLICATE_WORD: 'That word already exists in this category.',
        REQUEST_NOT_PENDING: 'This request was already resolved or cancelled.',
        REQUEST_OWNERSHIP: 'Your team cannot resolve this request.',
        WORD_NOT_UNDER_REVIEW: 'This word is no longer under review.',
        GAME_FINISHED: 'The game has finished; this request can no longer be sent.',
      };
      return hints[code] || message || 'Unable to send your correction.';
    }

    async function resolveNow() {
      if (submitting || !currentRequest || !sessionToken()) return;
      const input = document.getElementById('wcr-word');
      const value = (input.value || '').trim();
      if (!value) {
        setError('Please enter the corrected word.');
        return;
      }
      if (!AllowedChars.test(value)) {
        setError('Only letters, numbers, spaces, and hyphens are allowed.');
        return;
      }
      const id = currentRequest.id;
      setSubmitting(true);
      try {
        await API.request(`/word-change-requests/${id}/resolve`, {
          method: 'POST',
          body: { word_text: value },
          session: true,
        });
        toast('Correction sent. Thank you!', 2600);
        close();
        WordChange.syncPending();
      } catch (err) {
        if (!err || !err.status) {
          setError(err && err.message ? err.message : 'Connection lost. Try again.');
        } else {
          setError(friendlyError(err.code, err.message));
        }
        setSubmitting(false);
      }
    }

    function syncPending(retries) {
      const gid = gameId();
      if (!gid || !sessionToken() || currentRequest) return;
      if ((retries || 0) > 2) return;
      API.request(`/games/${gid}/word-change-requests`, { session: true })
        .then((res) => {
          const requests = (res && Array.isArray(res.requests)) ? res.requests : [];
          if (!currentRequest && requests.length) openFor(requests[0]);
        })
        .catch(() => {
          setTimeout(() => syncPending((retries || 0) + 1), 2500);
        });
    }

    function wire() {
      const form = document.getElementById('wcr-form');
      if (form) form.addEventListener('submit', (e) => { e.preventDefault(); resolveNow(); });

      const input = document.getElementById('wcr-word');
      if (input) input.addEventListener('input', clearError);

      // Blocking backdrop/Escape are intentionally NOT wired here.
      // The requirement is that this modal has no dismiss path.
    }

    wire();

    /* ---- realtime ---- */
    const R = window.Realtime;
    if (R) {
      R.on('word_change_request', (payload) => {
        if (payload && isMine(payload) && payload.status !== 'RESOLVED'
            && payload.status !== 'CANCELLED') {
          openFor(payload);
        }
      });
      R.on('word_change_resolved', (payload) => {
        if (payload && matches(payload)) {
          close();
          WordChange.syncPending();
        }
      });
      R.on('word_change_cancelled', (payload) => {
        if (payload && matches(payload)) {
          close();
          WordChange.syncPending();
        }
      });
      R.onConnect(() => { WordChange.syncPending(0); });
      R.onReconnect(() => { WordChange.syncPending(0); });
    }

    return { openFor, close, syncPending, isMine };
  })();

  if (typeof window !== 'undefined') window.WordChange = WordChange;

  // Recover a pending request when the page (re)loads.
  WordChange.syncPending(0);
})();