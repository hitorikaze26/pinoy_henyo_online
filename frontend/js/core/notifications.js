'use strict';
/* ============================================================
   js/core/notifications.js  —  Compatibility shim
   ─────────────────────────────────────────────────────────────
   The canonical toast implementation now lives in toast.js.
   This file exists solely for pages that still load it by name
   (index.html, settings.html).  It delegates every call to the
   ToastManager that toast.js already registered on window.Toast
   and window.showToast.

   If toast.js has not been loaded yet (should not happen in
   normal usage), it falls back to a minimal inline
   implementation so pages still work.
   ============================================================ */

if (typeof window !== 'undefined') {
  /* If Toast Manager is already registered, nothing to do —
     window.showToast and window.Notifications are already set
     by toast.js.  We just ensure Notifications.showToast
     delegates to the same manager. */
  if (window.Toast) {
    window.Notifications = {
      showToast: (msg, duration) => window.Toast.showToast(msg, duration),
    };
  } else {
    /* Fallback: toast.js not yet loaded.
       Provide a minimal inline implementation that mirrors the
       old behaviour so pages are never broken, then re-assign
       once toast.js loads (DOMContentLoaded guard below). */
    const _fallback = (() => {
      function _container() {
        let el = document.getElementById('copy-toast')
              || document.getElementById('player-toast')
              || document.getElementById('toast')
              || document.querySelector('.copy-toast')
              || document.querySelector('.player-toast');
        if (!el) {
          el = document.createElement('div');
          el.id = 'copy-toast';
          el.className = 'copy-toast';
          el.setAttribute('aria-live', 'polite');
          document.body.appendChild(el);
        }
        return el;
      }
      function showToast(msg, duration) {
        const t = _container();
        const str = String(msg || '');
        if (/<[a-z][\s\S]*>/i.test(str)) t.innerHTML = str;
        else t.textContent = str;
        t.classList.add('show');
        clearTimeout(t._t);
        t._t = setTimeout(() => t.classList.remove('show'), duration || 2400);
      }
      return { showToast };
    })();

    if (!window.showToast)    window.showToast    = _fallback.showToast;
    if (!window.Notifications) window.Notifications = _fallback;

    /* Once DOM is ready, if Toast manager loaded, upgrade the global */
    document.addEventListener('DOMContentLoaded', () => {
      if (window.Toast) {
        window.showToast    = (msg, dur) => window.Toast.showToast(msg, dur);
        window.Notifications = {
          showToast: (msg, dur) => window.Toast.showToast(msg, dur),
        };
      }
    });
  }
}
