'use strict';
/* ============================================================
   Core Notifications — shared toast (no duplicate per page)
   Pages previously each defined their own showToast/copy-toast.
   This core version is the canonical one; page-level wrappers
   delegate here for backward compat.
   ============================================================ */

const Notifications = (() => {

  function _container() {
    // Prefer the host dashboard / teams id, fall back to player or generic
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

  /** Unified toast — works on every page */
  function showToast(msg, duration=2400) {
    const t = _container();
    // allow HTML for pre-formatted toasts (existing callers pass "<i>…</i> Text")
    if (/<[a-z][\s\S]*>/i.test(String(msg))) t.innerHTML = String(msg);
    else t.textContent = String(msg);
    t.classList.add('show');
    clearTimeout(t._t);
    t._t = setTimeout(() => t.classList.remove('show'), duration);
  }

  // Backward compat: expose global showToast / copyText if not already present
  if (typeof window !== 'undefined' && !window.showToast) window.showToast = showToast;

  return { showToast };
})();

if (typeof window !== 'undefined') window.Notifications = Notifications;
