'use strict';
/* ============================================================
   Pinoy Henyo Online — Global Confirmation Modal Manager
   js/core/confirm.js

   Architecture
   ─────────────────────────────────────────────────────────
   ConfirmManager
   ├── Lifecycle:  IDLE → OPENING → ACTIVE → RESOLVING → CLOSING
   ├── Queue:      one card visible at a time; extras wait in order
   ├── Dedup:      identical requestKey in queue → no second entry
   ├── Single DOM: one overlay + one card rendered at page load
   ├── Focus trap: Tab / Shift-Tab cycle within the open modal
   ├── Busy lock:  after confirm click, prevents double-execute
   ├── Escape:     cancel if not busy; no-op if busy
   ├── Backdrop:   cancel if not busy; no-op if busy
   └── Restore:    focus returns to trigger element after close

   Public API
   ─────────────────────────────────────────────────────────
   ConfirmManager.open({ title, body, confirmLabel,
                         icon, destructive, requestKey })
     → Promise<boolean>   (true = confirmed, false = cancelled)

   ConfirmManager.busy(isLoading, label)
     — lock / unlock the modal during an async operation

   ConfirmManager.close()
     — programmatic close / finally-block cleanup

   Backward-compat shims (player.js call sites unchanged)
   ─────────────────────────────────────────────────────────
   window.openConfirm(opts)    → ConfirmManager.open(opts)
   window.closeConfirm()       → ConfirmManager.close()
   window.setConfirmBusy(b,l)  → ConfirmManager.busy(b,l)
   window.resolveConfirm(val)  → ConfirmManager._resolve(val)
   ============================================================ */

const ConfirmManager = (() => {

  /* ─────────────────────────────────────────────
     LIFECYCLE CONSTANTS
  ───────────────────────────────────────────── */
  const STATE = { IDLE: 0, OPENING: 1, ACTIVE: 2, RESOLVING: 3, CLOSING: 4 };

  /* ─────────────────────────────────────────────
     INTERNAL STATE
  ───────────────────────────────────────────── */
  let _lifecycle  = STATE.IDLE;
  let _resolver   = null;       // Promise resolve() for the active modal
  let _busy       = false;      // true while async action is in-flight
  let _lastFocus  = null;       // element to restore focus to on close
  let _pendingLabel = '';       // confirm button label, saved before busy
  let _queue      = [];         // [{opts, resolve}] pending requests
  let _activeKey  = null;       // requestKey of the currently open modal
  let _overlay    = null;       // <div id="ph-confirm-overlay">
  let _card       = null;       // <div class="ph-confirm__card">
  let _animTimer  = null;       // closing-animation safety timeout

  /* ─────────────────────────────────────────────
     UTILS
  ───────────────────────────────────────────── */
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /* ─────────────────────────────────────────────
     DOM CREATION
     Called once at module init.  Injects the overlay
     and card into <body>.  Idempotent.
  ───────────────────────────────────────────── */
  const ICON_DEFAULTS = {
    delete:      'fa-solid fa-trash',
    remove:      'fa-solid fa-user-minus',
    leave:       'fa-solid fa-right-from-bracket',
    reset:       'fa-solid fa-rotate-left',
    end:         'fa-solid fa-flag-checkered',
    disconnect:  'fa-solid fa-plug-circle-xmark',
    warning:     'fa-solid fa-triangle-exclamation',
    default:     'fa-solid fa-circle-question',
  };

  function _iconClass(iconKey) {
    return ICON_DEFAULTS[iconKey] || iconKey || ICON_DEFAULTS.default;
  }

  function _ensureDOM() {
    if (_overlay && _overlay.isConnected) return;

    // Remove any existing instance (e.g. hot-reload)
    const old = document.getElementById('ph-confirm-overlay');
    if (old) old.remove();

    _overlay = document.createElement('div');
    _overlay.id = 'ph-confirm-overlay';
    _overlay.className = 'ph-confirm-overlay';
    _overlay.setAttribute('role', 'alertdialog');
    _overlay.setAttribute('aria-modal', 'true');
    _overlay.setAttribute('aria-hidden', 'true');
    _overlay.setAttribute('aria-labelledby', 'ph-confirm-title');
    _overlay.setAttribute('aria-describedby', 'ph-confirm-body');

    _overlay.innerHTML = `
      <div class="ph-confirm__card" id="ph-confirm-card">
        <div class="ph-confirm__icon-wrap" id="ph-confirm-icon-wrap" aria-hidden="true">
          <i id="ph-confirm-icon" class="fa-solid fa-circle-question"></i>
        </div>
        <h2 class="ph-confirm__title" id="ph-confirm-title"></h2>
        <p  class="ph-confirm__body"  id="ph-confirm-body"></p>
        <div class="ph-confirm__actions">
          <button type="button" class="ph-confirm__btn ph-confirm__btn--cancel" id="ph-confirm-cancel">
            Cancel
          </button>
          <button type="button" class="ph-confirm__btn ph-confirm__btn--action" id="ph-confirm-action">
            Confirm
          </button>
        </div>
      </div>`;

    document.body.appendChild(_overlay);
    _card = document.getElementById('ph-confirm-card');

    /* Wire events once */
    document.getElementById('ph-confirm-action').addEventListener('click', _onActionClick);
    document.getElementById('ph-confirm-cancel').addEventListener('click', () => _resolve(false));
    _overlay.addEventListener('click', _onBackdropClick);
    document.addEventListener('keydown', _onKeyDown);
  }

  /* ─────────────────────────────────────────────
     FOCUS TRAP
  ───────────────────────────────────────────── */
  function _focusableElements() {
    if (!_card) return [];
    return Array.from(
      _card.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), ' +
        'select:not([disabled]), textarea:not([disabled]), ' +
        '[tabindex]:not([tabindex="-1"]):not([disabled])'
      )
    ).filter(el => !el.closest('[hidden]'));
  }

  function _trapFocus(e) {
    if (_lifecycle !== STATE.ACTIVE) return;
    const focusable = _focusableElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  /* ─────────────────────────────────────────────
     EVENT HANDLERS
  ───────────────────────────────────────────── */
  function _onActionClick() {
    if (_lifecycle !== STATE.ACTIVE || _busy) return;
    _pendingLabel = document.getElementById('ph-confirm-action').textContent.trim();
    _resolve(true);
  }

  function _onBackdropClick(e) {
    if (e.target !== _overlay) return;
    if (_lifecycle !== STATE.ACTIVE || _busy) return;
    _resolve(false);
  }

  function _onKeyDown(e) {
    if (_lifecycle === STATE.IDLE || _lifecycle === STATE.CLOSING) return;

    if (e.key === 'Tab') {
      _trapFocus(e);
      return;
    }

    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      if (_lifecycle === STATE.ACTIVE && !_busy) _resolve(false);
    }
  }

  /* ─────────────────────────────────────────────
     POPULATE CARD
  ───────────────────────────────────────────── */
  function _populate(opts) {
    const {
      title        = 'Are you sure?',
      body         = '',
      confirmLabel = 'Confirm',
      icon         = null,
      destructive  = false,
    } = opts;

    // Icon
    const iconWrap = document.getElementById('ph-confirm-icon-wrap');
    const iconEl   = document.getElementById('ph-confirm-icon');
    iconEl.className = _iconClass(icon);
    iconWrap.className = `ph-confirm__icon-wrap${destructive ? ' ph-confirm__icon-wrap--danger' : ''}`;

    // Text
    document.getElementById('ph-confirm-title').textContent = title;
    document.getElementById('ph-confirm-body').textContent  = body;

    // Action button
    const actionBtn = document.getElementById('ph-confirm-action');
    actionBtn.textContent = confirmLabel;
    actionBtn.disabled    = false;
    actionBtn.className   = `ph-confirm__btn ph-confirm__btn--action${destructive ? ' ph-confirm__btn--danger' : ''}`;

    // Cancel button
    const cancelBtn = document.getElementById('ph-confirm-cancel');
    cancelBtn.disabled = false;
    cancelBtn.textContent = 'Cancel';

    // Card class
    _card.className = `ph-confirm__card${destructive ? ' ph-confirm__card--danger' : ''}`;
  }

  /* ─────────────────────────────────────────────
     OPEN
  ───────────────────────────────────────────── */
  function _open(opts, resolve) {
    _ensureDOM();
    _lifecycle  = STATE.OPENING;
    _resolver   = resolve;
    _busy       = false;
    _activeKey  = opts.requestKey || null;
    _lastFocus  = document.activeElement;

    _populate(opts);

    // Prevent modal.js global Escape handler from also closing this overlay
    // by marking it as handled.
    _overlay.setAttribute('aria-hidden', 'false');
    _overlay.__confirmManaged = true;

    // Suppress body scroll only once (another modal might already hold it)
    if (document.body.style.overflow !== 'hidden') {
      document.body.style.overflow = 'hidden';
    }

    const reduced = _prefersReducedMotion();
    if (!reduced) {
      _overlay.classList.add('ph-confirm-overlay--entering');
      _card.classList.add('ph-confirm__card--entering');
    }

    _overlay.classList.add('ph-confirm-overlay--open');

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!reduced) {
          _overlay.classList.remove('ph-confirm-overlay--entering');
          _card.classList.remove('ph-confirm__card--entering');
        }
        _lifecycle = STATE.ACTIVE;

        // Focus the action button by default so keyboard users can instantly press Space/Enter
        const actionBtn = document.getElementById('ph-confirm-action');
        if (actionBtn) setTimeout(() => actionBtn.focus(), 60);
      });
    });
  }

  /* ─────────────────────────────────────────────
     RESOLVE (internal — called by action/cancel/Escape/backdrop)
  ───────────────────────────────────────────── */
  function _resolve(val) {
    if (_lifecycle !== STATE.ACTIVE) return false;
    if (_busy) return false;
    if (!_resolver) return false;

    _lifecycle = STATE.RESOLVING;
    const resolver = _resolver;
    _resolver  = null;
    _activeKey = null;

    if (val === false) {
      // Cancel path: close immediately before resolving
      _doClose(() => resolver(false));
    } else {
      // Confirm path: resolve first, let caller call busy(true) + close()
      resolver(true);
    }
    return true;
  }

  /* ─────────────────────────────────────────────
     CLOSE (called by caller's finally block, or cancel path)
  ───────────────────────────────────────────── */
  function _doClose(afterClose) {
    if (_lifecycle === STATE.CLOSING || _lifecycle === STATE.IDLE) {
      if (afterClose) afterClose();
      return;
    }
    _lifecycle = STATE.CLOSING;
    _busy      = false;

    const reduced = _prefersReducedMotion();

    const finish = () => {
      clearTimeout(_animTimer);
      _overlay.classList.remove('ph-confirm-overlay--open', 'ph-confirm-overlay--leaving');
      _overlay.setAttribute('aria-hidden', 'true');

      // Restore body scroll only if no other open modal is holding it
      const otherOpen = document.querySelector(
        '.modal-overlay.open, .dash-modal-overlay.open, .ph-confirm-overlay--open'
      );
      if (!otherOpen) document.body.style.overflow = '';

      // Reset action button
      const actionBtn = document.getElementById('ph-confirm-action');
      if (actionBtn) { actionBtn.disabled = false; }
      const cancelBtn = document.getElementById('ph-confirm-cancel');
      if (cancelBtn) { cancelBtn.disabled = false; }

      _lifecycle = STATE.IDLE;

      // Restore focus
      if (_lastFocus && typeof _lastFocus.focus === 'function') {
        const saved = _lastFocus;
        _lastFocus = null;
        setTimeout(() => {
          try { saved.focus(); } catch (_) {}
        }, 30);
      }

      if (afterClose) afterClose();

      // Drain queue
      setTimeout(_drainQueue, 50);
    };

    if (reduced) {
      _overlay.classList.add('ph-confirm-overlay--leaving');
      finish();
    } else {
      _overlay.classList.add('ph-confirm-overlay--leaving');
      // Safety fallback: if transitionend never fires
      _animTimer = setTimeout(finish, 350);
      _card.addEventListener('transitionend', function handler() {
        _card.removeEventListener('transitionend', handler);
        finish();
      }, { once: true });
    }
  }

  /* ─────────────────────────────────────────────
     QUEUE DRAIN
  ───────────────────────────────────────────── */
  function _drainQueue() {
    if (_lifecycle !== STATE.IDLE) return;
    if (!_queue.length) return;
    const { opts, resolve } = _queue.shift();
    _open(opts, resolve);
  }

  /* ─────────────────────────────────────────────
     PUBLIC API
  ───────────────────────────────────────────── */
  const API = {

    /**
     * Open a confirmation modal.
     *
     * @param {object}  opts
     * @param {string}  opts.title          — modal heading
     * @param {string}  [opts.body]         — supporting description
     * @param {string}  [opts.confirmLabel] — action button text (default: 'Confirm')
     * @param {string}  [opts.icon]         — FA icon class or shorthand key
     *                                        ('delete','remove','leave','reset','end',
     *                                         'disconnect','warning') or any FA class string
     * @param {boolean} [opts.destructive]  — true = danger colours on icon + button
     * @param {string}  [opts.requestKey]   — dedup key; identical key in queue is skipped
     *
     * @returns {Promise<boolean>}  true = user confirmed, false = user cancelled
     */
    open(opts = {}) {
      return new Promise(resolve => {
        _ensureDOM();

        // Dedup: skip if same key is already active or in queue
        if (opts.requestKey) {
          if (_activeKey === opts.requestKey) { resolve(false); return; }
          if (_queue.some(q => q.opts.requestKey === opts.requestKey)) { resolve(false); return; }
        }

        if (_lifecycle === STATE.IDLE) {
          _open(opts, resolve);
        } else {
          _queue.push({ opts, resolve });
        }
      });
    },

    /**
     * Lock / unlock the modal during an async operation.
     * Call busy(true, 'Deleting…') immediately after the promise resolves true.
     * Call close() in the finally block.
     *
     * @param {boolean} isLoading
     * @param {string}  [label]   — loading text shown on the action button
     */
    busy(isLoading, label) {
      _busy = isLoading;
      _ensureDOM();
      const actionBtn = document.getElementById('ph-confirm-action');
      const cancelBtn = document.getElementById('ph-confirm-cancel');
      const closeBtn  = null; // ph-confirm has no separate ×-close button by design

      if (isLoading) {
        _overlay.classList.add('ph-confirm-overlay--busy');
        if (actionBtn) {
          actionBtn.disabled = true;
          if (label) {
            actionBtn.innerHTML =
              `<i class="fa-solid fa-spinner ph-confirm-spinner" aria-hidden="true"></i>${_esc(label)}`;
          }
        }
        if (cancelBtn) cancelBtn.disabled = true;
      } else {
        _overlay.classList.remove('ph-confirm-overlay--busy');
        if (actionBtn) {
          actionBtn.disabled    = false;
          actionBtn.textContent = _pendingLabel || 'Confirm';
        }
        if (cancelBtn) cancelBtn.disabled = false;
      }
    },

    /**
     * Close the modal and resolve any pending promise as false.
     * Safe to call from finally blocks — idempotent.
     */
    close() {
      if (_lifecycle === STATE.IDLE || _lifecycle === STATE.CLOSING) return;
      // If still resolving (confirm path, awaiting finally), just close.
      if (_lifecycle === STATE.RESOLVING || _lifecycle === STATE.ACTIVE) {
        const leftover = _resolver;
        _resolver = null;
        _activeKey = null;
        _doClose(() => { if (leftover) leftover(false); });
      }
    },

    /**
     * Internal resolve — exposed for backward-compat shim (resolveConfirm).
     * @param {boolean} val
     */
    _resolve(val) {
      return _resolve(val);
    },

    /**
     * Clear the entire queue without opening anything.
     * Useful when navigating away from a page.
     */
    clearQueue() {
      const abandoned = _queue.splice(0);
      abandoned.forEach(({ resolve }) => resolve(false));
    },
  };

  /* ─────────────────────────────────────────────
     GLOBAL REGISTRATION
     Pages that load this file before page scripts can
     call window.Confirm.open(...) or the backward-compat
     wrappers window.openConfirm(...) / window.closeConfirm()
     / window.setConfirmBusy(...) / window.resolveConfirm(...)
  ───────────────────────────────────────────── */
  if (typeof window !== 'undefined') {
    window.Confirm = API;

    /* Backward-compat: player.js calls these directly */
    window.openConfirm = (opts) => API.open(opts);
    window.closeConfirm = () => API.close();
    window.setConfirmBusy = (busy, label) => API.busy(busy, label);
    window.resolveConfirm = (val) => API._resolve(val);
  }

  /* Guard against modal.js closing the ph-confirm overlay with its own
     generic Escape handler.  modal.js checks `o.__confirmManaged` via its
     wire() loop — we add the guard attribute here so it never picks up
     our overlay. */
  if (typeof document !== 'undefined') {
    const guard = () => {
      const old = document.getElementById('ph-confirm-overlay');
      if (old) old.__confirmManaged = true;
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', guard);
    } else {
      guard();
    }
  }

  /* Clean up queue on page unload */
  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => API.clearQueue());
  }

  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = ConfirmManager;
