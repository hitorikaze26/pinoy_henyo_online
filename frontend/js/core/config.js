'use strict';
/* ============================================================
   Core Config — Pinoy Henyo Online
   ------------------------------------------------------------
   SINGLE SOURCE OF TRUTH for backend base URLs.

   The frontend can run in two topologies:

     LOCAL / MONOLITH
       Flask serves HTML + REST + Socket.IO from ONE origin
       (e.g. http://localhost:5000). The REST API is mounted at
       /api on that same origin.

     PRODUCTION (SPLIT)
       Vercel serves the static HTML/CSS/JS; the Flask backend
       runs on Render at a SEPARATE origin. The page origin
       (Vercel) must NOT be used as the backend origin.

   Resolution order (highest first):
     1. window.PINOY_CONFIG  set by js/core/runtime-config.js
        (or an inline <script> before config.js loads) with
        { apiBaseUrl, socketBaseUrl, qrBaseUrl, frontendBase }.
     2. Legacy overrides window.PINOY_API_BASE /
        window.PINOY_SOCKET_BASE (kept for compatibility).
     3. Local-environment auto-detection (localhost / 127.0.0.1 /
        ::1 / *.local) -> same-origin Flask backend.
     4. Any other (deployed) environment -> same-origin fallback
        WITH a loud console warning. Localhost is NEVER used in
        production.
   ============================================================ */
const PINOY_CONFIG = (() => {
  const injected = (typeof window !== 'undefined' && window.PINOY_CONFIG) || {};

  /* ---------- helpers ---------- */
  function pageOrigin() {
    return (window.location && window.location.origin) || '';
  }

  function hostname() {
    return ((window.location && window.location.hostname) || '').toLowerCase();
  }

  function isLocalEnvironment() {
    const h = hostname();
    if (h === '' || h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '0.0.0.0') return true;
    if (h.endsWith('.local') || h.endsWith('.localhost')) return true;
    // RFC1918 private ranges (development on a LAN).
    return /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.test(h) &&
      (h.startsWith('192.168.') || h.startsWith('10.') || /^172\.(1[6-9]|2\d|3[01])\./.test(h));
  }

  function stripTrailingSlash(value) {
    return String(value || '').trim().replace(/\/+$/, '');
  }

  /* ---------- injectable runtime values (js/core/runtime-config.js) ---------- */
  const cfgApiBase    = stripTrailingSlash(injected.apiBaseUrl   || injected.API_BASE_URL   || '');
  const cfgSocketBase = stripTrailingSlash(injected.socketBaseUrl || injected.SOCKET_BASE_URL || '');
  const cfgQrBase     = stripTrailingSlash(injected.qrBaseUrl    || injected.QR_BASE_URL    || '');
  const cfgFrontend   = stripTrailingSlash(injected.frontendBase || injected.FRONTEND_BASE  || '');

  /* ---------- API base URL ---------- */
  function resolveApiBaseUrl() {
    if (cfgApiBase) return cfgApiBase.endsWith('/api') ? cfgApiBase : cfgApiBase + '/api';
    if (window.PINOY_API_BASE) {
      const legacy = stripTrailingSlash(window.PINOY_API_BASE);
      return legacy.endsWith('/api') ? legacy : legacy + '/api';
    }
    const origin = pageOrigin();
    if (isLocalEnvironment()) {
      // Local dev: Flask serves the REST API from the same origin.
      return (origin || 'http://localhost:5000') + '/api';
    }
    // Deployed (e.g. Vercel -> Render): the page origin is the frontend, not
    // the backend. Falling back to same-origin makes a monolith deployment
    // still work, but the split topology REQUIRES an explicit apiBaseUrl.
    // Never fall back to localhost here.
    console.error(
      '[PinoyConfig] No API base URL configured. In production the frontend and ' +
      'backend are on different origins (Vercel -> Render). Set ' +
      'window.PINOY_CONFIG.apiBaseUrl in js/core/runtime-config.js before ' +
      'deploying. Falling back to same-origin "' + (origin + '/api') +
      '" — API calls will fail unless the backend is served from the same origin.'
    );
    return origin + '/api';
  }

  /* ---------- Socket.IO base URL ---------- */
  function resolveSocketBaseUrl(apiBaseUrl) {
    if (cfgSocketBase) return cfgSocketBase;
    if (window.PINOY_SOCKET_BASE) return stripTrailingSlash(window.PINOY_SOCKET_BASE);
    try { return new URL(apiBaseUrl).origin; } catch (e) { return pageOrigin() || 'http://localhost:5000'; }
  }

  const API_BASE_URL = resolveApiBaseUrl();
  const SOCKET_BASE_URL = resolveSocketBaseUrl(API_BASE_URL);
  const FRONTEND_BASE = cfgFrontend || pageOrigin() || 'http://localhost:5000';
  const QR_BASE_URL = cfgQrBase || FRONTEND_BASE;

  // Game constants (mirror backend constants)
  const MIN_CORRECT_WORDS = 3;
  const MAX_WORDS_PER_TURN = 5;
  const MAX_TIMER_SECONDS = 300;

  return {
    API_BASE_URL,
    SOCKET_BASE_URL,
    QR_BASE_URL,
    FRONTEND_BASE,
    MIN_CORRECT_WORDS,
    MAX_WORDS_PER_TURN,
    MAX_TIMER_SECONDS,
    isLocalEnvironment,
    // Legacy aliases (kept so any code referencing the old names still works).
    API_BASE: API_BASE_URL,
    SOCKET_BASE: SOCKET_BASE_URL,
    QR_BASE: QR_BASE_URL,
  };
})();

if (typeof window !== 'undefined') window.PINOY_CONFIG = PINOY_CONFIG;