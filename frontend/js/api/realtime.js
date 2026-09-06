'use strict';

/* ============================================================
   Realtime — shared Socket.IO client (Pinoy Henyo Online)
   ------------------------------------------------------------
   Bridges the pages to the backend Socket.IO server. In local
   development the backend shares the page origin
   (http://localhost:5000). In production the Socket.IO backend is
   the Render backend, resolved from the centralized config
   (window.PINOY_CONFIG.SOCKET_BASE_URL in js/core/config.js).

   Only listens to backend events that actually exist
   (see backend/app/services/realtime.py + sockets/events.py):

     connect / disconnect (Socket.IO lifecycle)
     game_started / game_paused / game_resumed / game_completed
     round_started / round_completed
     match_started
     turn_started / turn_state / turn_completed
     word_correct / word_passed
     timer_updated / timer_paused / timer_resumed
     time_added / time_removed / penalty_applied
     team_connected / team_disconnected
     member_joined / member_left / role_updated / team_updated
     connection_requested / connection_approved
     connection_declined / connection_disconnected
     settings_updated
     error

   SECURITY: the backend broadcasts a PUBLIC payload for a turn
   (current_word_text is null, `words` carry no text) to the
   game/turn rooms. The secret word text is ONLY sent to the
   manghuhula:{team_id} room, and the host sees full word text only
   via the host-authenticated REST endpoint. This module therefore
   never fabricates secret data; consuming pages must rely on
   Realtime events for public state and on hostTurn()/manghuhula
   channels for secret word text.

   Listener registration is deduped by (event, handler) so re-wiring
   from multiple init passes never creates duplicate callbacks.
   ============================================================ */

const Realtime = (() => {
  let socket = null;
  let mode = null;

  // event name -> Set of handlers (dedupe by reference).
  const handlers = new Map();

  const LIFECYCLE = { connect: '::connect', disconnect: '::disconnect', reconnect: '::reconnect', error: '::error' };

  /* ---------- small listener registry ---------- */
  function addListener(event, handler) {
    if (typeof handler !== 'function') return;
    if (!handlers.has(event)) handlers.set(event, new Set());
    handlers.get(event).add(handler);
  }
  function removeListener(event, handler) {
    if (!handlers.has(event)) return;
    const set = handlers.get(event);
    if (handler) set.delete(handler);
    else set.clear();
  }
  function notify(event, payload) {
    const set = handlers.get(event);
    if (!set) return;
    set.forEach((fn) => { try { fn(payload); } catch (e) { /* handler error */ } });
  }

  /* ---------- origin / socket setup ---------- */
  function socketOrigin() {
    const cfg = (typeof window !== 'undefined' && window.PINOY_CONFIG) || null;
    if (cfg && cfg.SOCKET_BASE_URL) return cfg.SOCKET_BASE_URL;
    if (window.PINOY_SOCKET_BASE) return window.PINOY_SOCKET_BASE;
    try {
      const u = new URL(API.getBaseUrl());
      return u.origin;
    } catch (e) {
      return 'http://localhost:5000';
    }
  }

  // Derive the auth payload for the handshake. mode 'host' uses the
  // host session token; mode 'player' uses the device session token.
  function authPayload() {
    if (mode === 'host') {
      const token = API.getHostToken() || API.getSessionToken();
      return { token: token || '' };
    }
    return { token: API.getSessionToken() || '' };
  }

  function isReady() {
    return typeof window !== 'undefined' && typeof window.io === 'function';
  }

  // Route an incoming Socket.IO packet to its registered handlers.
  function deliver() {
    const KNOWN = new Set([
      'game_started', 'game_paused', 'game_resumed', 'game_completed',
      'round_started', 'round_completed', 'match_started',
      'turn_started', 'turn_state', 'turn_completed',
      'word_correct', 'word_passed',
      'timer_updated', 'timer_paused', 'timer_resumed',
      'time_added', 'time_removed', 'penalty_applied',
      'team_connected', 'team_disconnected',
      'member_joined', 'member_left', 'role_updated', 'team_updated',
      'connection_requested', 'connection_approved',
      'connection_declined', 'connection_disconnected',
      'settings_updated',
      'error',
    ]);
    KNOWN.forEach((name) => {
      socket.on(name, (payload) => notify(name, payload));
    });
  }

  function teardown() {
    if (!socket) return;
    socket.close();
    socket = null;
    mode = null;
    handlers.clear();
  }

  /* ---------- public connection API ---------- */
  function connect(cfg = {}) {
    if (socket) return socket;
    if (!isReady()) return null; // CDN not loaded yet -> no-op

    mode = cfg.mode === 'host' ? 'host' : 'player';

    socket = window.io(socketOrigin(), {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      auth: authPayload(),
      query: { device_id: API.getDeviceId() || '' },
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      randomizationFactor: 0.5,
      timeout: 10000,
    });

    socket.on('connect', () => notify(LIFECYCLE.connect));
    socket.on('disconnect', (reason) => notify(LIFECYCLE.disconnect, reason));
    socket.on('reconnect', (attempt) => notify(LIFECYCLE.reconnect, attempt));
    socket.on('reconnect_error', () => { /* keep trying automatically */ });
    socket.on('connect_error', (err) => notify(LIFECYCLE.error, err && err.message ? err.message : 'connect_error'));

    deliver();

    return socket;
  }

  /* ---------- lifecycle hooks ---------- */
  function onConnect(fn) { addListener(LIFECYCLE.connect, fn); }
  function onDisconnect(fn) { addListener(LIFECYCLE.disconnect, fn); }
  function onReconnect(fn) { addListener(LIFECYCLE.reconnect, fn); }

  /* ---------- event registration ---------- */
  function on(event, handler) { addListener(event, handler); }
  function off(event, handler) { removeListener(event, handler); }

  /* ---------- client -> server emits ---------- */
  function joinTurn(turnId) {
    if (!socket || !turnId) return;
    socket.emit('join_turn', turnId);
  }
  function leaveTurn(turnId) {
    if (!socket || !turnId) return;
    socket.emit('leave_turn', turnId);
  }

  function isConnected() {
    return !!socket && socket.connected;
  }
  function getSocket() {
    return socket;
  }

  // Report which backend events the frontend is *not* listening to,
  // so unsupported features are visible rather than silently ignored.
  function unsupportedReport() {
    const KNOWN = [
      'game_started', 'game_paused', 'game_resumed', 'game_completed',
      'round_started', 'round_completed', 'match_started',
      'turn_started', 'turn_state', 'turn_completed',
      'word_correct', 'word_passed',
      'timer_updated', 'timer_paused', 'timer_resumed',
      'time_added', 'time_removed', 'penalty_applied',
      'team_connected', 'team_disconnected',
      'member_joined', 'member_left', 'role_updated', 'team_updated',
      'connection_requested', 'connection_approved',
      'connection_declined', 'connection_disconnected',
      'settings_updated',
    ];
    return KNOWN.filter((name) => !(handlers.has(name) && handlers.get(name).size));
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', teardown);
  }

  return {
    connect,
    on,
    off,
    onConnect,
    onDisconnect,
    onReconnect,
    joinTurn,
    leaveTurn,
    isConnected,
    getSocket,
    unsupportedReport,
  };
})();

if (typeof window !== 'undefined') window.Realtime = Realtime;
