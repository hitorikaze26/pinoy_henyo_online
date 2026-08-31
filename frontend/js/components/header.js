'use strict';
/* ============================================================
   Component Loader — header
   Loads components/header.html into #header-mount.
   Vanilla JS, no framework. Safely skips if element missing or
   content already present.
   ============================================================ */

(function loadHeader() {
  const mount = document.getElementById('header-mount');
  if (!mount || mount.innerHTML.trim()) return; // already wired or absent
  const src = Session && Session.resolveFromRoot
    ? Session.resolveFromRoot('components/header.html')
    : '../../components/header.html';
  fetch(src)
    .then(r => { if (!r.ok) throw new Error('header fetch '+r.status); return r.text(); })
    .then(html => { mount.innerHTML = html; })
    .catch(() => { /* silent fallback: page has inline nav */ });
})();
