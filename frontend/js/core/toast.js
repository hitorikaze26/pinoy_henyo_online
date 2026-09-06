'use strict';
/* ============================================================
   Pinoy Henyo Online — Toast Manager  (js/core/toast.js)
   Single source of truth for all in-app notifications.

   Architecture
   ─────────────────────────────────────────────────────────
   ToastManager
   ├── Queue          – ordered list of pending toasts
   ├── Active         – currently rendered items (max 3 desktop / 2 mobile)
   ├── PriorityMgr    – CRITICAL > ERROR > WARNING > CONNECTION > GAME > SUCCESS > INFO
   ├── DupDetector    – collapse identical toasts within dedup window
   ├── GroupDetector  – merge rapid same-context events
   ├── TimerManager   – per-instance timers, never cross-cancel
   ├── InteractionMgr – hover pause, touch pause, swipe-to-dismiss
   ├── Accessibility  – aria-live polite/assertive per type
   └── Renderer       – DOM factory, animation, cleanup

   Public API
   ─────────────────────────────────────────────────────────
   Toast.show({ type, title, message, icon, duration, action, priority, dedupKey, group })
   Toast.success(message, opts?)
   Toast.error(message, opts?)
   Toast.warning(message, opts?)
   Toast.info(message, opts?)
   Toast.connection(message, opts?)
   Toast.game(message, opts?)
   Toast.clear()

   Backward compatibility
   ─────────────────────────────────────────────────────────
   window.showToast(msg, duration?) is preserved as a thin wrapper.
   ============================================================ */

const ToastManager = (() => {

  /* ============================================================
     CONSTANTS
  ============================================================ */
  const PRIORITY = {
    CRITICAL:   7,
    ERROR:      6,
    WARNING:    5,
    CONNECTION: 4,
    GAME:       3,
    SUCCESS:    2,
    INFO:       1,
  };

  // Milliseconds each type stays visible
  const DURATION = {
    success:    2800,
    info:       3200,
    warning:    4500,
    error:      5500,
    connection: 5000,
    game:       3500,
    critical:   0,    // 0 = persistent
  };

  // ARIA: which types get assertive announcements
  const ASSERTIVE_TYPES = new Set(['error', 'critical']);

  // Deduplication: same key within this window collapses → count badge
  const DEDUP_WINDOW_MS = 4000;

  // Grouping: same group key within this window → merge
  const GROUP_WINDOW_MS = 1500;

  // Max simultaneously visible toasts
  const MAX_VISIBLE_DESKTOP = 3;
  const MAX_VISIBLE_MOBILE  = 2;

  // Mobile breakpoint
  const MOBILE_BP = 640;

  // Swipe-dismiss threshold (px from original position)
  const SWIPE_THRESHOLD = 72;

  /* ============================================================
     STATE
  ============================================================ */
  let _queue   = [];          // { id, type, title, message, icon, duration, priority, dedupKey, group, action, _count, _groupIds }
  let _active  = [];          // currently rendered toast ids
  let _items   = new Map();   // id → { el, timerId, pausedAt, remaining, dedupEl, opts }
  let _dedupMap = new Map();  // dedupKey → { id, count, expireAt }
  let _groupMap = new Map();  // groupKey → { ids, expireAt, count }
  let _idCounter = 0;
  let _container = null;
  let _ariaPoliteRegion = null;
  let _ariaAssertiveRegion = null;

  /* ============================================================
     UTILS
  ============================================================ */
  function _isMobile() {
    return window.innerWidth <= MOBILE_BP;
  }

  function _maxVisible() {
    return _isMobile() ? MAX_VISIBLE_MOBILE : MAX_VISIBLE_DESKTOP;
  }

  function _nextId() {
    return ++_idCounter;
  }

  function _prefersReducedMotion() {
    return window.matchMedia &&
           window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function _esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ============================================================
     CONTAINER SETUP
  ============================================================ */
  function _ensureContainer() {
    if (_container && _container.isConnected) return _container;

    // Remove any old legacy containers so we don't duplicate
    ['copy-toast', 'player-toast', 'toast'].forEach(id => {
      const old = document.getElementById(id);
      if (old) old.remove();
    });
    document.querySelectorAll('.copy-toast, .player-toast').forEach(el => el.remove());

    _container = document.createElement('div');
    _container.id = 'ph-toast-container';
    _container.className = 'ph-toast-container';
    _container.setAttribute('aria-label', 'Notifications');
    document.body.appendChild(_container);

    // Two hidden live regions: one polite, one assertive
    _ariaPoliteRegion = document.createElement('div');
    _ariaPoliteRegion.className = 'ph-toast-aria-region sr-only';
    _ariaPoliteRegion.setAttribute('aria-live', 'polite');
    _ariaPoliteRegion.setAttribute('aria-atomic', 'true');

    _ariaAssertiveRegion = document.createElement('div');
    _ariaAssertiveRegion.className = 'ph-toast-aria-region sr-only';
    _ariaAssertiveRegion.setAttribute('aria-live', 'assertive');
    _ariaAssertiveRegion.setAttribute('aria-atomic', 'true');

    document.body.appendChild(_ariaPoliteRegion);
    document.body.appendChild(_ariaAssertiveRegion);

    return _container;
  }

  /* ============================================================
     ACCESSIBILITY ANNOUNCEMENT
  ============================================================ */
  function _announce(type, title, message) {
    const text = [title, message].filter(Boolean).join(': ');
    const region = ASSERTIVE_TYPES.has(type) ? _ariaAssertiveRegion : _ariaPoliteRegion;
    if (!region) return;
    // Clear + re-set forces screen-reader re-announcement
    region.textContent = '';
    requestAnimationFrame(() => { region.textContent = text; });
  }

  /* ============================================================
     ICON MAP
     Uses Font Awesome 6 (already loaded on every page).
  ============================================================ */
  const ICON_MAP = {
    success:    'fa-solid fa-circle-check',
    error:      'fa-solid fa-circle-xmark',
    warning:    'fa-solid fa-triangle-exclamation',
    info:       'fa-solid fa-circle-info',
    connection: 'fa-solid fa-wifi',
    game:       'fa-solid fa-gamepad',
    critical:   'fa-solid fa-circle-exclamation',
  };

  function _iconHtml(type, customIcon) {
    if (customIcon) {
      // Allow FA class string like "fa-solid fa-check"
      return `<i class="${_esc(customIcon)}" aria-hidden="true"></i>`;
    }
    const cls = ICON_MAP[type] || ICON_MAP.info;
    return `<i class="${cls}" aria-hidden="true"></i>`;
  }

  /* ============================================================
     COUNTDOWN SVG
     Animates the countdown ring. Only drawn when duration > 0
     and type is in the "show-countdown" set.
  ============================================================ */
  const COUNTDOWN_TYPES = new Set(['success', 'info', 'game', 'connection']);

  function _countdownSvg() {
    const r = 10;
    const circumference = 2 * Math.PI * r;
    return `<svg class="ph-toast__countdown" viewBox="0 0 24 24" aria-hidden="true">
      <circle class="ph-toast__countdown-track" cx="12" cy="12" r="${r}"/>
      <circle class="ph-toast__countdown-fill" cx="12" cy="12" r="${r}"
        stroke-dasharray="${circumference.toFixed(3)}"
        stroke-dashoffset="0"/>
    </svg>`;
  }

  /* ============================================================
     DOM FACTORY
  ============================================================ */
  function _buildElement(opts) {
    const {
      id, type, title, message, icon, duration, action, _count,
    } = opts;

    const showCountdown = COUNTDOWN_TYPES.has(type) && duration > 0 && !_prefersReducedMotion();
    const hasAction = action && action.label;

    const el = document.createElement('div');
    el.className = `ph-toast ph-toast--${type}`;
    el.setAttribute('role', hasAction ? 'alertdialog' : 'status');
    el.setAttribute('aria-label', [title, message].filter(Boolean).join(': '));
    el.setAttribute('tabindex', '0');
    el.dataset.id = String(id);

    // Count badge (dedup)
    const countHtml = (_count > 1)
      ? `<span class="ph-toast__count" aria-label="${_count} occurrences">${_count}</span>`
      : '';

    // Action button
    const actionHtml = hasAction
      ? `<button type="button" class="ph-toast__action" data-toast-action="${id}">${_esc(action.label)}</button>`
      : '';

    // Close button
    const closeHtml = `<button type="button" class="ph-toast__close" data-toast-close="${id}" aria-label="Dismiss notification">
      <i class="fa-solid fa-xmark" aria-hidden="true"></i>
    </button>`;

    // Title / message layout
    const titleHtml  = title   ? `<p class="ph-toast__title">${_esc(title)}</p>` : '';
    const msgHtml    = message ? `<p class="ph-toast__message">${_esc(message)}</p>` : '';
    const textHtml   = (titleHtml || msgHtml)
      ? `<div class="ph-toast__body">${titleHtml}${msgHtml}</div>`
      : '';

    el.innerHTML = `
      <span class="ph-toast__icon" aria-hidden="true">${_iconHtml(type, icon)}</span>
      ${textHtml}
      ${countHtml}
      ${showCountdown ? _countdownSvg() : ''}
      ${actionHtml}
      ${closeHtml}
    `;

    return el;
  }

  /* ============================================================
     TIMER MANAGER
     Each toast owns its own timerId — old timers can only
     affect the item they belong to, never another toast.
  ============================================================ */
  function _startTimer(id) {
    const item = _items.get(id);
    if (!item || item.opts.duration <= 0) return; // persistent
    const remaining = item.remaining != null ? item.remaining : item.opts.duration;
    if (remaining <= 0) { _dismiss(id); return; }
    item.remaining = remaining;
    item.timerStart = performance.now();

    // Start countdown animation
    if (item.el) {
      const fill = item.el.querySelector('.ph-toast__countdown-fill');
      if (fill) {
        const r = 10;
        const circumference = 2 * Math.PI * r;
        fill.style.transition = 'none';
        fill.style.strokeDashoffset = '0';
        requestAnimationFrame(() => {
          fill.style.transition = `stroke-dashoffset ${remaining}ms linear`;
          fill.style.strokeDashoffset = String(circumference);
        });
      }
    }

    item.timerId = setTimeout(() => {
      // Guard: only dismiss if this item still exists and timer hasn't been cleared
      if (!_items.has(id)) return;
      _dismiss(id);
    }, remaining);
  }

  function _pauseTimer(id) {
    const item = _items.get(id);
    if (!item || item.opts.duration <= 0 || item.paused) return;
    clearTimeout(item.timerId);
    item.timerId = null;
    const elapsed = item.timerStart != null ? (performance.now() - item.timerStart) : 0;
    item.remaining = Math.max(0, item.remaining - elapsed);
    item.paused = true;

    // Pause countdown animation
    if (item.el) {
      const fill = item.el.querySelector('.ph-toast__countdown-fill');
      if (fill) {
        const computed = window.getComputedStyle(fill);
        const currentOffset = computed.getPropertyValue('stroke-dashoffset');
        fill.style.transition = 'none';
        fill.style.strokeDashoffset = currentOffset;
      }
    }
  }

  function _resumeTimer(id) {
    const item = _items.get(id);
    if (!item || !item.paused) return;
    item.paused = false;
    _startTimer(id);
  }

  function _clearTimer(id) {
    const item = _items.get(id);
    if (!item) return;
    clearTimeout(item.timerId);
    item.timerId = null;
  }

  /* ============================================================
     SWIPE-TO-DISMISS (mobile)
  ============================================================ */
  function _bindSwipe(id, el) {
    let startX = 0;
    let startY = 0;
    let currentX = 0;
    let dragging = false;
    let dismissed = false;

    function onTouchStart(e) {
      if (e.touches.length !== 1) return;
      startX   = e.touches[0].clientX;
      startY   = e.touches[0].clientY;
      currentX = 0;
      dragging = true;
      dismissed = false;
      _pauseTimer(id);
      el.style.transition = 'none';
    }

    function onTouchMove(e) {
      if (!dragging || e.touches.length !== 1) return;
      const dx = e.touches[0].clientX - startX;
      const dy = e.touches[0].clientY - startY;
      // Only swipe horizontally; allow vertical page scroll
      if (!dismissed && Math.abs(dx) < Math.abs(dy) && Math.abs(currentX) < 8) {
        dragging = false;
        el.style.transform = '';
        _resumeTimer(id);
        return;
      }
      e.preventDefault();
      currentX = dx;
      const opacity = Math.max(0, 1 - Math.abs(dx) / (SWIPE_THRESHOLD * 2));
      el.style.transform = `translateX(${dx}px)`;
      el.style.opacity   = String(opacity);
    }

    function onTouchEnd() {
      if (!dragging) return;
      dragging = false;
      if (Math.abs(currentX) >= SWIPE_THRESHOLD) {
        dismissed = true;
        const dir = currentX > 0 ? 1 : -1;
        el.style.transition = 'transform 0.22s ease, opacity 0.22s ease';
        el.style.transform  = `translateX(${dir * 120}%)`;
        el.style.opacity    = '0';
        setTimeout(() => _dismiss(id), 230);
      } else {
        // Snap back
        el.style.transition = 'transform 0.25s cubic-bezier(0.22,1,0.36,1), opacity 0.25s ease';
        el.style.transform  = '';
        el.style.opacity    = '1';
        _resumeTimer(id);
      }
    }

    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove',  onTouchMove,  { passive: false });
    el.addEventListener('touchend',   onTouchEnd,   { passive: true });
    el.addEventListener('touchcancel',onTouchEnd,   { passive: true });
  }

  /* ============================================================
     INTERACTION BINDINGS (hover + keyboard + close + action)
  ============================================================ */
  function _bindInteraction(id, el, opts) {
    // Hover: pause timer, show close
    el.addEventListener('mouseenter', () => {
      _pauseTimer(id);
      el.classList.add('ph-toast--hovered');
    });
    el.addEventListener('mouseleave', () => {
      el.classList.remove('ph-toast--hovered');
      _resumeTimer(id);
    });

    // Focus (keyboard users): pause while focused
    el.addEventListener('focusin', () => _pauseTimer(id));
    el.addEventListener('focusout', () => _resumeTimer(id));

    // Escape to dismiss when focused
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); _dismiss(id); }
    });

    // Close button
    el.addEventListener('click', (e) => {
      const closeBtn = e.target.closest('[data-toast-close]');
      if (closeBtn) { e.stopPropagation(); _dismiss(id); return; }

      const actionBtn = e.target.closest('[data-toast-action]');
      if (actionBtn && opts.action && opts.action.handler) {
        e.stopPropagation();
        try { opts.action.handler(); } catch (_) {}
        if (opts.action.dismissOnClick !== false) _dismiss(id);
      }
    });

    // Swipe (always bind; works on touch devices)
    _bindSwipe(id, el);
  }

  /* ============================================================
     RENDER — add to DOM + animate in
  ============================================================ */
  function _render(toastOpts) {
    const container = _ensureContainer();
    const el = _buildElement(toastOpts);

    // Animate entrance
    const reduced = _prefersReducedMotion();
    if (reduced) {
      el.classList.add('ph-toast--instant');
    } else {
      el.classList.add('ph-toast--entering');
    }

    container.appendChild(el);

    const item = {
      el,
      timerId:    null,
      timerStart: null,
      remaining:  toastOpts.duration > 0 ? toastOpts.duration : null,
      paused:     false,
      opts:       toastOpts,
    };
    _items.set(toastOpts.id, item);
    _active.push(toastOpts.id);

    // Trigger enter animation on next frame
    if (!reduced) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          el.classList.remove('ph-toast--entering');
          el.classList.add('ph-toast--visible');
        });
      });
    } else {
      el.classList.add('ph-toast--visible');
    }

    // Bind interactions
    _bindInteraction(toastOpts.id, el, toastOpts);

    // Accessibility announcement
    _announce(toastOpts.type, toastOpts.title, toastOpts.message);

    // Start auto-dismiss timer
    _startTimer(toastOpts.id);
  }

  /* ============================================================
     DISMISS — animate out + remove
  ============================================================ */
  function _dismiss(id) {
    const item = _items.get(id);
    if (!item) return; // already dismissed — safe no-op
    _clearTimer(id);

    const el = item.el;
    const reduced = _prefersReducedMotion();

    if (reduced || !el) {
      _cleanup(id);
      return;
    }

    el.classList.remove('ph-toast--visible', 'ph-toast--hovered');
    el.classList.add('ph-toast--leaving');

    const onEnd = () => {
      el.removeEventListener('transitionend', onEnd);
      _cleanup(id);
    };
    el.addEventListener('transitionend', onEnd);

    // Safety fallback: if transitionend never fires (display:none, hidden tab)
    setTimeout(() => { if (_items.has(id)) _cleanup(id); }, 450);
  }

  function _cleanup(id) {
    const item = _items.get(id);
    if (!item) return;
    try { item.el.remove(); } catch (_) {}
    _items.delete(id);
    _active = _active.filter(a => a !== id);
    // Drain queue after a short delay so layout doesn't jump
    setTimeout(_drainQueue, 80);
  }

  /* ============================================================
     QUEUE DRAIN
  ============================================================ */
  function _drainQueue() {
    const max = _maxVisible();
    while (_active.length < max && _queue.length > 0) {
      // Find highest-priority item in queue
      let bestIdx = 0;
      for (let i = 1; i < _queue.length; i++) {
        if (_queue[i].priority > _queue[bestIdx].priority) bestIdx = i;
      }
      const next = _queue.splice(bestIdx, 1)[0];
      _render(next);
    }
  }

  /* ============================================================
     DEDUPLICATION
  ============================================================ */
  function _deduplicateOrCreate(opts) {
    const key = opts.dedupKey;
    if (!key) return null;

    const now = Date.now();
    const existing = _dedupMap.get(key);

    if (existing && existing.expireAt > now) {
      // Existing active toast — increment count
      const item = _items.get(existing.id);
      if (item && item.el) {
        existing.count++;
        existing.expireAt = now + DEDUP_WINDOW_MS;
        _dedupMap.set(key, existing);

        // Update the count badge in the DOM
        let badge = item.el.querySelector('.ph-toast__count');
        if (!badge && existing.count > 1) {
          badge = document.createElement('span');
          badge.className = 'ph-toast__count';
          const closeBtn = item.el.querySelector('.ph-toast__close');
          if (closeBtn) item.el.insertBefore(badge, closeBtn);
          else item.el.appendChild(badge);
        }
        if (badge) {
          badge.textContent = String(existing.count);
          badge.setAttribute('aria-label', `${existing.count} occurrences`);
          badge.classList.add('ph-toast__count--bump');
          badge.addEventListener('animationend', () => badge.classList.remove('ph-toast__count--bump'), { once: true });
        }

        // Also refresh the aria announcement with updated count
        _announce(opts.type, opts.title, `${opts.message || opts.title} (×${existing.count})`);

        // Reset timer to give user more reading time
        _clearTimer(existing.id);
        const newItem = _items.get(existing.id);
        if (newItem) newItem.remaining = opts.duration > 0 ? opts.duration : newItem.remaining;
        _startTimer(existing.id);
        return true; // deduplicated — skip creating a new toast
      }
    }

    // Also check queue for same key
    const queueIdx = _queue.findIndex(q => q.dedupKey === key);
    if (queueIdx !== -1) {
      _queue[queueIdx]._count = (_queue[queueIdx]._count || 1) + 1;
      return true;
    }

    return null;
  }

  /* ============================================================
     GROUPING
  ============================================================ */
  function _tryGroup(opts) {
    const gk = opts.group;
    if (!gk) return null;

    const now = Date.now();
    const existing = _groupMap.get(gk);
    if (!existing || existing.expireAt <= now) {
      _groupMap.set(gk, { ids: [], expireAt: now + GROUP_WINDOW_MS, count: 0, label: opts._groupLabel });
      return null; // first in group — create normally
    }

    existing.count++;
    existing.expireAt = now + GROUP_WINDOW_MS;

    // Find the first toast from this group still active
    const firstId = existing.ids.find(id => _items.has(id));
    if (firstId) {
      const firstItem = _items.get(firstId);
      if (firstItem && firstItem.el) {
        const groupCount = existing.count + 1;
        const label = opts._groupLabel || gk;
        const titleEl = firstItem.el.querySelector('.ph-toast__title');
        if (titleEl) titleEl.textContent = `${label} ×${groupCount}`;
        _announce(opts.type, `${label} ×${groupCount}`, '');
        _clearTimer(firstId);
        const gi = _items.get(firstId);
        if (gi) gi.remaining = opts.duration;
        _startTimer(firstId);
        return true; // absorbed into existing group toast
      }
    }
    return null;
  }

  /* ============================================================
     ENQUEUE
  ============================================================ */
  function _enqueue(opts) {
    _ensureContainer();

    // Normalize / default
    const type     = opts.type || 'info';
    const priority = opts.priority != null ? opts.priority : (PRIORITY[type.toUpperCase()] || PRIORITY.INFO);
    const duration = opts.duration != null ? opts.duration : (DURATION[type] != null ? DURATION[type] : DURATION.info);
    const id       = _nextId();

    const finalOpts = {
      id,
      type,
      title:    opts.title   || null,
      message:  opts.message || opts.title || null,
      icon:     opts.icon    || null,
      duration,
      priority,
      dedupKey: opts.dedupKey || null,
      group:    opts.group    || null,
      _groupLabel: opts._groupLabel || null,
      action:   opts.action  || null,
      _count:   1,
    };

    // Adjust message/title so single-string callers work
    if (finalOpts.title && !opts.message) {
      finalOpts.title   = null;
      finalOpts.message = opts.title;
    }

    // --- Deduplication check ---
    if (finalOpts.dedupKey && _deduplicateOrCreate(finalOpts)) return;

    // --- Group check ---
    if (finalOpts.group && _tryGroup(finalOpts)) return;

    // Register dedup entry
    if (finalOpts.dedupKey) {
      _dedupMap.set(finalOpts.dedupKey, {
        id:       finalOpts.id,
        count:    1,
        expireAt: Date.now() + DEDUP_WINDOW_MS,
      });
    }

    // Register group entry
    if (finalOpts.group) {
      const gk = finalOpts.group;
      const now = Date.now();
      if (!_groupMap.has(gk) || _groupMap.get(gk).expireAt <= now) {
        _groupMap.set(gk, { ids: [finalOpts.id], expireAt: now + GROUP_WINDOW_MS, count: 0, label: finalOpts._groupLabel });
      } else {
        _groupMap.get(gk).ids.push(finalOpts.id);
      }
    }

    const max = _maxVisible();
    if (_active.length < max) {
      _render(finalOpts);
    } else {
      _queue.push(finalOpts);
    }
  }

  /* ============================================================
     PUBLIC API
  ============================================================ */
  const API = {

    /** Generic show */
    show(opts) {
      if (!opts) return;
      _enqueue(typeof opts === 'string' ? { type: 'info', message: opts } : opts);
    },

    success(message, opts) {
      _enqueue({ type: 'success', message, ...opts });
    },

    error(message, opts) {
      _enqueue({ type: 'error', message, ...opts });
    },

    warning(message, opts) {
      _enqueue({ type: 'warning', message, ...opts });
    },

    info(message, opts) {
      _enqueue({ type: 'info', message, ...opts });
    },

    connection(message, opts) {
      _enqueue({ type: 'connection', message, ...opts });
    },

    game(message, opts) {
      _enqueue({ type: 'game', message, ...opts });
    },

    /** Dismiss all active toasts and clear the queue. */
    clear() {
      _queue = [];
      [..._active].forEach(id => _dismiss(id));
    },

    /**
     * Backward-compatible shim: showToast(msg, duration?)
     * Accepts the old HTML-in-message format by converting <i> icons
     * to plain text (icons render via the new type system instead).
     */
    showToast(msg, duration) {
      if (!msg) return;
      const str = String(msg);
      // Strip HTML tags from legacy HTML-formatted messages
      const plain = str.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').trim();

      // Heuristic type detection from legacy messages
      let type = 'info';
      const lower = plain.toLowerCase();
      if (/error|fail|could not|unable|invalid|danger|not allowed|locked|must be/i.test(lower)) type = 'error';
      else if (/correct|success|saved|added|updated|deleted|removed|copied|created|moved|renamed|connected/i.test(lower)) type = 'success';
      else if (/warning|unstable|caution|almost|limited/i.test(lower)) type = 'warning';
      else if (/disconnected|connection lost|realtime/i.test(lower)) type = 'connection';
      else if (/round|game|turn|started|complete|ended|over|penalty|bonus/i.test(lower)) type = 'game';

      _enqueue({
        type,
        message: plain,
        duration: duration != null ? duration : (DURATION[type] != null ? DURATION[type] : DURATION.info),
      });
    },

    // Expose DURATION constants so callers can reference them
    DURATION,
    PRIORITY,
  };

  /* ============================================================
     GLOBAL REGISTRATION
     Sets window.showToast unconditionally (replaces all page-level
     implementations with a single shim back to this manager).
  ============================================================ */
  if (typeof window !== 'undefined') {
    window.Toast = API;
    window.showToast = (msg, duration) => API.showToast(msg, duration);
    // Legacy alias
    window.Notifications = { showToast: (msg, duration) => API.showToast(msg, duration) };
  }

  // Clean up orphaned timers/elements on page unload
  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => {
      [..._active].forEach(id => _clearTimer(id));
    });
  }

  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = ToastManager;
