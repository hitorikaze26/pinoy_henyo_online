'use strict';
/* ============================================================
   Core Modal — shared open/close (duplicated in 5 pages)
   Handles: open/close, focus trap stub, body scroll lock,
   backdrop click, Escape key.
   ============================================================ */

const Modal = (() => {

  function open(overlay) {
    if (!overlay) return;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const first = overlay.querySelector('input, button:not(.modal__close):not(.dash-modal__close), select, textarea, [tabindex]:not([tabindex="-1"])');
    if (first) setTimeout(() => first.focus(), 60);
  }

  function close(overlay) {
    if (!overlay) return;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    // Reset forms/errors for landing modals (existing behavior)
    const form = overlay.querySelector('form');
    if (form) {
      form.reset();
      form.querySelectorAll('.form-input').forEach(i => i.classList.remove('error'));
      form.querySelectorAll('.form-error').forEach(e => e.textContent = '');
    }
  }

  // Wire backdrop click + Escape for all current overlays (safe to call multiple times)
  function wire() {
    document.querySelectorAll('.modal-overlay, .dash-modal-overlay').forEach(o => {
      if (o.__modalWired) return;
      o.__modalWired = true;
      o.addEventListener('click', (e) => { if (e.target === o) close(o); });
    });
    if (!document.__modalEscWired) {
      document.__modalEscWired = true;
      document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('.modal-overlay.open, .dash-modal-overlay.open').forEach(o => close(o));
      });
    }
  }

  // Auto-wire on load
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
    else wire();
  }

  // Backward-compat globals used by script.js/player.js/host_dashboard.js
  if (typeof window !== 'undefined') {
    if (!window.openModal) window.openModal = open;
    if (!window.closeModal) window.closeModal = close;
  }

  return { open, close, wire };
})();

if (typeof window !== 'undefined') window.Modal = Modal;
