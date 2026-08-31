'use strict';
/* ============================================================
   Core Session — thin wrapper over js/api/api.js persistence
   Provides page-safe helpers for session/context used by header,
   sidebar, and page bootstrap. Does not replace API; delegates to it.
   ============================================================ */

const Session = (() => {

  function getCtx() {
    if (typeof API !== 'undefined' && API.getSessionContext) return API.getSessionContext();
    // Fallback: raw localStorage
    try {
      const raw = localStorage.getItem('pinoy_henyo_session');
      return raw ? JSON.parse(raw) : {};
    } catch (e) { return {}; }
  }

  function isHost() {
    const c = getCtx();
    return c.role === 'host' && !!c.hostToken;
  }

  function isPlayer() {
    const c = getCtx();
    return c.role === 'team-leader' || c.role === 'team-member';
  }

  /** Fix relative hrefs for pages in pages/host/* and pages/player/* */
  function resolveFromRoot(pathFromRoot) {
    // pathFromRoot e.g., "assets/logo/logo.png" or "css/global.css"
    const d = window.location.pathname;
    const depth = (d.includes('/pages/host/') || d.includes('/pages/player/')) ? '../../' : (d.endsWith('/index.html') || d === '/' || d.endsWith('/') ? '' : './');
    // Simple: if path already starts with ../../ keep; else prefix as needed
    if (pathFromRoot.startsWith('http') || pathFromRoot.startsWith('//')) return pathFromRoot;
    if (pathFromRoot.startsWith('/')) return pathFromRoot;
    // For root page (depth 0) don't prefix; for nested pages prefix ../../
    const isNested = d.includes('/pages/');
    if (!isNested) return pathFromRoot;
    // Nested: assets/... -> ../../assets/..., css/... -> ../../css/...
    if (pathFromRoot.startsWith('assets/') || pathFromRoot.startsWith('css/') || pathFromRoot.startsWith('js/')) {
      return '../../' + pathFromRoot;
    }
    return pathFromRoot;
  }

  return { getCtx, isHost, isPlayer, resolveFromRoot };
})();

if (typeof window !== 'undefined') window.Session = Session;
