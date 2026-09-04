'use strict';

/* ============================================================
   Connect helper — QR parsing + reconnect guard
   Shared by host and player pages.
   ============================================================ */

const Connect = (() => {
  /* ---------- QR deep-link parsing ----------
     Backend QR payloads are URL deep-links (see qr_service.py):
       game: https://host/join/game/<GAME_CODE>
       team: https://host/join/team/<TEAM_CODE>?game=<GAME_CODE>
     These carry PUBLIC codes (never auth tokens). */
  function parseJoinUrl(rawUrl) {
    try {
      const u = new URL(rawUrl, window.location.origin);
      const path = u.pathname.replace(/\/+$/, '');
      const m = path.match(/\/join\/game\/([^/?#]+)$/);
      if (m) {
        return { type: 'game', gameCode: decodeURIComponent(m[1]) };
      }
      const mt = path.match(/\/join\/team\/([^/?#]+)$/);
      if (mt) {
        return {
          type: 'team',
          teamCode: decodeURIComponent(mt[1]),
          gameCode: u.searchParams.get('game') || null,
        };
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  /* ---------- Reconnect decoding (page deep-links) ----------
     The landing page / player pages may load with a deep-link that
     carries the same PUBLIC codes. Supported query shapes:
       ?code=PHABCD12            (game code, e.g. host "Share Link")
       ?game=PHABCD12            (game code)
       ?team=ABCD&?game=PHABCD12 (team code + game code) */
  function parseLocation() {
    const raw = window.location.href;
    let match = raw.match(/[?&]code=([^&]+)/);
    if (match) {
      return { type: 'game', code: decodeURIComponent(match[1]) };
    }
    match = raw.match(/[?&](game|team)=([^&]+)/);
    if (match) {
      return { type: match[1], code: decodeURIComponent(match[2]) };
    }
    return null;
  }

  /* ---------- Reconnect guard ----------
     Called on player-ish pages. Restores/re-connects a previously
     stored device session, or reports that the session is invalid and
     a (re)join is required.
     Returns a Promise resolving to:
       { status: 'connected', data }
       { status: 'no-session' }
       { status: 'invalid', error }
  */
  async function restorePlayerSession() {
    const token = API.getSessionToken();
    if (!token) return { status: 'no-session' };
    try {
      const data = await DeviceAPI.reconnect({});
      if (data && data.connected) return { status: 'connected', data: data.data };
      return { status: 'invalid', error: data.error };
    } catch (err) {
      return { status: 'invalid', error: err };
    }
  }

  /* ---------- Host reconnect guard ----------
     Verifies a stored host token against the owned game. */
  async function restoreHostSession() {
    const token = API.getHostToken();
    const gameId = API.getHostGameId() || API.getGameId();
    if (!token || !gameId) return { status: 'no-session' };
    try {
      const game = await GameAPI.get(gameId);
      return { status: 'connected', data: game };
    } catch (err) {
      // 401/403/404 => session is no longer valid (token wrong or game deleted)
      const invalidStatuses = [401, 403, 404];
      if (err && invalidStatuses.includes(err.status)) {
        API.clearTokens();
        return { status: 'invalid', error: err };
      }
      // network or 5xx => server unreachable, don't clear tokens
      return { status: 'unavailable', error: err };
    }
  }

  /* ---------- Show a lightweight reconnect/dismiss banner ---------- */
  function showReconnectBanner({ title = 'Connection lost', message = 'Your session could not be restored.' } = {}) {
    let el = document.getElementById('pinoy-reconnect-banner');
    if (!el) {
      el = document.createElement('div');
      el.id = 'pinoy-reconnect-banner';
      el.setAttribute('role', 'alert');
      el.style.cssText = [
        'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;',
        'background:rgba(20,20,30,0.96);color:#fff;border:1px solid rgba(255,255,255,0.15);',
        'border-radius:12px;padding:12px 16px;max-width:420px;width:92%;box-shadow:0 8px 30px rgba(0,0,0,0.4);',
        'font:14px/1.4 system-ui,sans-serif;display:flex;align-items:center;gap:12px;',
      ].join('');
      document.body.appendChild(el);
    }
    el.innerHTML = `
      <div style="flex:1">
        <strong style="display:block;margin-bottom:2px">${title}</strong>
        <span style="opacity:0.85">${message}</span>
      </div>
      <button id="pinoy-reconnect-cta" style="border:0;border-radius:8px;padding:8px 14px;cursor:pointer;background:#e0b54b;color:#1a1a1a;font-weight:700;white-space:nowrap">
        Reconnect
      </button>`;
    el.hidden = false;
    const cta = el.querySelector('#pinoy-reconnect-cta');
    cta.addEventListener('click', () => {
      API.clearTokens();
      el.hidden = true;
      const target = document.body.getAttribute('data-reconnect-target') || 'index.html';
      window.location.href = target;
    });
    return el;
  }

  function hideReconnectBanner() {
    const el = document.getElementById('pinoy-reconnect-banner');
    if (el) el.hidden = true;
  }

  return {
    parseJoinUrl,
    parseLocation,
    restorePlayerSession,
    restoreHostSession,
    showReconnectBanner,
    hideReconnectBanner,
  };
})();

if (typeof window !== 'undefined') window.Connect = Connect;
