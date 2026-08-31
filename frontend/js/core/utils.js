'use strict';
/* ============================================================
   Core Utils — shared helpers (no framework)
   Used by all pages; previously duplicated across 5 JS files.
   ============================================================ */

const Utils = (() => {

  /** Escape HTML */
  function esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /** Format seconds -> M:SS */
  function formatTime(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  /** By-id helper */
  const $ = (id) => document.getElementById(id);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  /** Small delay helper */
  function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

  /** Safe JSON parse */
  function safeParse(str, fallback={}) {
    try { return JSON.parse(str); } catch (e) { return fallback; }
  }

  /** Debounce helper */
  function debounce(fn, ms=250) {
    let t; return function(...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  /** Set footer year (used by index + footer component) */
  function bindFooterYear(id='footer-year') {
    const el = document.getElementById(id);
    if (el) el.textContent = new Date().getFullYear();
  }

  return { esc, formatTime, $, $$, wait, safeParse, debounce, bindFooterYear };
})();

if (typeof window !== 'undefined') window.Utils = Utils;
