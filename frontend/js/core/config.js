'use strict';
/* ============================================================
   Core Config — Pinoy Henyo Online
   Central base URLs + constants. Vanilla JS, no framework.
   ============================================================ */
const PINOY_CONFIG = (() => {
  const API_BASE = window.PINOY_API_BASE || 'http://localhost:5000/api';
  const SOCKET_BASE = window.PINOY_SOCKET_BASE || (() => {
    try { return new URL(API_BASE).origin; } catch (e) { return 'http://localhost:5000'; }
  })();
  const QR_BASE = 'https://pinoyhenyo.online';

  // Game constants (mirror backend constants)
  const MIN_CORRECT_WORDS = 3;
  const MAX_WORDS_PER_TURN = 5;
  const MAX_TIMER_SECONDS = 300;

  return { API_BASE, SOCKET_BASE, QR_BASE, MIN_CORRECT_WORDS, MAX_WORDS_PER_TURN, MAX_TIMER_SECONDS };
})();

if (typeof window !== 'undefined') window.PINOY_CONFIG = PINOY_CONFIG;
