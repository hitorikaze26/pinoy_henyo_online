'use strict';
/* ============================================================
   Component Loader — sidebar
   Loads components/sidebar.html into #sidebar-mount.
   Sidebar nav items marked active based on current path.
   ============================================================ */

(function loadSidebar() {
  const mount = document.getElementById('sidebar-mount');
  if (!mount || mount.innerHTML.trim()) return;
  const src = Session && Session.resolveFromRoot
    ? Session.resolveFromRoot('components/sidebar.html')
    : '../../components/sidebar.html';
  fetch(src)
    .then(r => { if (!r.ok) throw new Error('sidebar fetch '+r.status); return r.text(); })
    .then(html => {
      mount.innerHTML = html;
      _markActive();
    })
    .catch(() => { /* silent fallback */ });
})();

function _markActive() {
  const path = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.sidebar__nav-item[data-page]').forEach(a => {
    const page = a.getAttribute('data-page');
    const href = a.getAttribute('href');
    const target = href ? href.split('/').pop() : page;
    if (target === path || page === path.split('?')[0]) {
      a.classList.add('active');
    } else {
      a.classList.remove('active');
    }
  });
}
