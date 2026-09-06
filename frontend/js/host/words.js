'use strict';

/* ============================================================
   STATE — real data, populated from the backend.
============================================================ */
let CATEGORIES = [];   // Real categories, populated from the backend.
let TEAMS      = [];   // Real team names, populated from the backend.
const STATUSES = ['selected', 'available', 'used', 'passed', 'disabled'];
const HOST_TEAM_LABEL = 'Host';

// teamOf returns the display label for a word's submitting side. Host-added
// words have no owning team, so they show up under "Host".
function teamOf(w) { return w.team || HOST_TEAM_LABEL; }

let STATE = {
  locked: false,
  nextId: 1,
  pendingDeleteId: null,
  pendingEditId:   null,
  pendingDupAction: null,  // { word, category, team, round } to save after dup confirm
  search:     '',
  filterCat:  'All',
  filterTeam: 'All',
  view:       'table',      // 'table' | 'team' | 'category'
  sortCol:    'word',
  sortDir:    'asc',
  selectedIds: new Set(),
  showAssign:  false,
  categories:  [],      // real categories [{id, name}] when a game context exists

  // Real totals (updated from the backend word/category lists).
  totalWords:      0,
  totalCategories: 0,

  // Round 1 category selection. Empty array = use every category.
  round1CategoryIds: [],

  words: [],
};

// Assigned by the backend integration bootstrap so the compact Round 1 picker
// can force the word pool to refresh after a bulk category assignment.
let refreshWordPoolHook = null;

/* ============================================================
   DOM HELPERS
============================================================ */
const $  = id  => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

/* ============================================================
   TOAST — delegates to the global Toast Manager
============================================================ */
function showToast(msg) {
  if (window.Toast) window.Toast.showToast(msg);
}

/* ============================================================
   RIPPLE
============================================================ */
function addRipple(btn, e) {
  if (!btn) return;
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x = (e.clientX - rect.left)  - size / 2;
  const y = (e.clientY - rect.top)   - size / 2;
  const r = document.createElement('span');
  r.className = 'ripple';
  r.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px;`;
  btn.querySelector('.ripple')?.remove();
  btn.appendChild(r);
  r.addEventListener('animationend', () => r.remove());
}

document.addEventListener('click', e => {
  const btn = e.target.closest(
    '.hdr-btn, .btn-confirm, .btn-danger, .btn-cancel, .bulk-btn, ' +
    '.connect-action-btn, .dash-nav__code-btn, ' +
    '.tbl-btn, .filter-pill, .view-toggle__btn'
  );
  if (btn) addRipple(btn, e);
});

/* ============================================================
   ESCAPE HTML
============================================================ */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ============================================================
   COUNT-UP ANIMATION
============================================================ */
function countUp(el, to, duration = 600) {
  if (!el) return;
  const from = parseInt(el.textContent, 10) || 0;
  if (from === to) return;
  const start = performance.now();
  const step  = now => {
    const pct = Math.min((now - start) / duration, 1);
    const val = Math.round(from + (to - from) * (1 - Math.pow(1 - pct, 3)));
    el.textContent = val;
    if (pct < 1) requestAnimationFrame(step);
    else el.textContent = to;
  };
  requestAnimationFrame(step);
}

/* ============================================================
   MODAL HELPERS
============================================================ */
function openModal(id) {
  const o = $(id);
  o.classList.add('open');
  o.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  const first = o.querySelector('input, select, button:not(.modal__close)');
  if (first) setTimeout(() => first.focus(), 60);
}

function closeModal(id) {
  const o = $(id);
  o.classList.remove('open');
  o.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

$$('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) closeModal(o.id); });
});

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  $$('.modal-overlay.open').forEach(o => closeModal(o.id));
});

// Keyboard shortcut: Ctrl+F → focus search
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    $('search-input').focus();
  }
});

/* ============================================================
   POPULATE SELECT OPTIONS (shared)
============================================================ */
function populateSelects() {
  const catSelects = ['add-category', 'edit-category'];

  catSelects.forEach(id => {
    const el = $(id);
    const cur = el.value;
    el.innerHTML = '<option value="">Select category</option>';
    CATEGORIES.forEach(c => {
      el.innerHTML += `<option value="${esc(c)}"${c===cur?' selected':''}>${esc(c)}</option>`;
    });
  });
}

/* ============================================================
   RENDER SUMMARY STATS
============================================================ */
function renderSummary() {
  countUp($('stat-total'), STATE.totalWords);
  countUp($('stat-cats'),  STATE.totalCategories);

  const r1Count = (STATE.words || []).filter(w => (w.round || 1) === 1).length;
  const r2Count = (STATE.words || []).filter(w => (w.round || 1) === 2).length;

  countUp($('stat-r1-assigned'), r1Count);
  countUp($('stat-r1-total'),    STATE.totalWords);
  countUp($('stat-r2-assigned'), r2Count);
  countUp($('stat-r2-total'),    STATE.totalWords);

  const r1Ready = STATE.totalWords > 0 && r1Count > 0;
  const r2Ready = STATE.totalWords > 0 && r2Count > 0;

  setRoundBadge('badge-r1', r1Ready);
  setRoundBadge('badge-r2', r2Ready);

  const allReady = r1Ready && r2Ready;
  const statusEl = $('overall-status');
  statusEl.className = `overall-status overall-status--${allReady ? 'ready' : 'warn'} reveal visible`;
  $('overall-icon').className = allReady ? 'fa-solid fa-circle-check' : 'fa-solid fa-triangle-exclamation';
  $('overall-text').textContent = STATE.totalWords === 0
    ? 'No words yet. Add words to get started.'
    : (allReady
        ? 'Both rounds have assigned words!'
        : 'Assign every word to Round 1 or Round 2 — use the Round 1 picker or the Round column.');
}

function setRoundBadge(id, ready) {
  const b = $(id);
  b.className = `summary-card__badge ${ready ? 'summary-card__badge--ready' : 'summary-card__badge--warn'}`;
  b.innerHTML = ready
    ? '<i class="fa-solid fa-check"></i> Ready'
    : '<i class="fa-solid fa-triangle-exclamation"></i> Incomplete';
}

/* ============================================================
   RENDER LOCK STATUS (read-only — backed by game status)
   ============================================================ */
function renderLockBar() {
  const barIcon  = $('lock-bar-icon');
  const barLabel = $('lock-bar-label');
  const statusEl = $('lock-status');
  const statusIcon = $('lock-btn-icon');
  const statusLabel = $('lock-btn-label');
  const addBtn   = $('btn-add-word');
  const addBtnEmpty = $('btn-add-word-empty');

  if (STATE.locked) {
    barIcon.className  = 'fa-solid fa-lock';
    barLabel.textContent = 'Words Locked';
    statusIcon.className  = 'fa-solid fa-lock';
    statusLabel.textContent = 'Locked';
    statusEl.classList.add('locked');
    if (addBtn)      addBtn.disabled = true;
    if (addBtnEmpty) addBtnEmpty.disabled = true;
  } else {
    barIcon.className  = 'fa-solid fa-lock-open';
    barLabel.textContent = 'Words Unlocked';
    statusIcon.className  = 'fa-solid fa-lock-open';
    statusLabel.textContent = 'Unlocked';
    statusEl.classList.remove('locked');
    if (addBtn)      addBtn.disabled = false;
    if (addBtnEmpty) addBtnEmpty.disabled = false;
  }
}

/* ============================================================
   FILTER PILLS
============================================================ */
function renderFilterPills() {
  // Category pills
  const catCounts = {};
  STATE.words.forEach(w => { catCounts[w.category] = (catCounts[w.category] || 0) + 1; });
  const catContainer = $('cat-pills');
  catContainer.innerHTML = '';

  ['All', ...CATEGORIES].forEach(cat => {
    const count   = cat === 'All' ? STATE.words.length : (catCounts[cat] || 0);
    const active  = STATE.filterCat === cat ? 'active' : '';
    const pill    = document.createElement('button');
    pill.className = `filter-pill ${active}`;
    pill.dataset.cat = cat;
    pill.setAttribute('role', 'radio');
    pill.setAttribute('aria-checked', active ? 'true' : 'false');
    pill.innerHTML = `${esc(cat)}<span class="filter-pill__count">${count}</span>`;
    pill.addEventListener('click', () => {
      STATE.filterCat = cat;
      renderFilterPills();
      renderTable();
    });
    catContainer.appendChild(pill);
  });

  // Team pills
  const teamCounts = {};
  STATE.words.forEach(w => {
    const t = teamOf(w);
    teamCounts[t] = (teamCounts[t] || 0) + 1;
  });
  const teamContainer = $('team-pills');
  teamContainer.innerHTML = '';

  const teamPillList = ['All'];
  if (!TEAMS.includes(HOST_TEAM_LABEL)) teamPillList.push(HOST_TEAM_LABEL);
  TEAMS.forEach(t => { if (!teamPillList.includes(t)) teamPillList.push(t); });

  teamPillList.forEach(team => {
    const count  = team === 'All' ? STATE.words.length : (teamCounts[team] || 0);
    const active = STATE.filterTeam === team ? 'active' : '';
    const pill   = document.createElement('button');
    pill.className = `filter-pill ${active}`;
    pill.dataset.team = team;
    pill.setAttribute('role', 'radio');
    pill.setAttribute('aria-checked', active ? 'true' : 'false');
    pill.innerHTML = `${esc(team)}<span class="filter-pill__count">${count}</span>`;
    pill.addEventListener('click', () => {
      STATE.filterTeam = team;
      renderFilterPills();
      renderTable();
    });
    teamContainer.appendChild(pill);
  });
}

/* ============================================================
   FILTERED + SORTED WORDS
============================================================ */
function getFilteredWords() {
  const q = STATE.search.trim().toLowerCase();
  return STATE.words
    .filter(w => {
      const matchSearch = !q || w.word.toLowerCase().includes(q) || w.category.toLowerCase().includes(q);
      const matchCat    = STATE.filterCat  === 'All' || w.category === STATE.filterCat;
      const matchTeam   = STATE.filterTeam === 'All' || teamOf(w) === STATE.filterTeam;
      return matchSearch && matchCat && matchTeam;
    })
    .sort((a, b) => {
      const dir = STATE.sortDir === 'asc' ? 1 : -1;
      if (STATE.sortCol === 'round') {
        return ((a.round || 1) - (b.round || 1)) * dir;
      }
      const va  = String(a[STATE.sortCol] ?? '').toLowerCase();
      const vb  = String(b[STATE.sortCol] ?? '').toLowerCase();
      return va < vb ? -dir : va > vb ? dir : 0;
    });
}

/* ============================================================
   STATUS DISPLAY HELPERS
============================================================ */
function statusLabel(s) {
  const map = { selected:'Selected', available:'Available', used:'Used', passed:'Passed', disabled:'Disabled' };
  return map[s] || s;
}

/* ============================================================
   RENDER TABLE
   ============================================================ */
function renderTable() {
  const words  = getFilteredWords();
  const tbody  = $('word-table-body');
  const empty  = $('empty-state');
  const wrap   = $('word-table-wrap');
  const allCb  = $('select-all');

  if (words.length === 0) {
    wrap.hidden  = true;
    empty.hidden = false;
    allCb.checked = false;
    return;
  }

  wrap.hidden  = false;
  empty.hidden = true;

  tbody.innerHTML = words.map((w, idx) => {
    const checked   = STATE.selectedIds.has(w.id);
    const selClass  = checked ? ' selected-row' : '';
    const delay     = `animation-delay:${idx * 0.04}s`;
    return `
      <tr class="word-row${selClass}" data-id="${w.id}" style="${delay}">
        <td>
          <label class="cb-label">
            <input type="checkbox" class="row-cb" data-id="${w.id}" ${checked ? 'checked' : ''} aria-label="Select ${esc(w.word)}" />
            <span class="cb-custom"></span>
          </label>
        </td>
        <td class="word-cell">${esc(w.word)}</td>
        <td><span class="cat-badge">${esc(w.category)}</span></td>
        <td>${esc(teamOf(w))}</td>
        <td>
          <select class="round-select dd round-select--r${w.round || 1}" data-id="${w.id}" data-current="${w.round || 1}" ${STATE.locked ? 'disabled' : ''} aria-label="Assign ${esc(w.word)} to a round">
            <option value="1" ${(w.round || 1) === 1 ? 'selected' : ''}>Round 1</option>
            <option value="2" ${(w.round || 1) === 2 ? 'selected' : ''}>Round 2</option>
          </select>
        </td>
        <td>
          <span class="status-dot status-dot--${esc(w.status)}">
            <span class="status-dot__circle"></span>
            ${esc(statusLabel(w.status))}
          </span>
        </td>
        <td>
          <div class="tbl-actions">
            <button class="tbl-btn tbl-btn--edit"   data-id="${w.id}" aria-label="Edit ${esc(w.word)}" title="Edit">
              <i class="fa-solid fa-pen"></i>
            </button>
            <button class="tbl-btn tbl-btn--delete" data-id="${w.id}" aria-label="Delete ${esc(w.word)}" title="Delete">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </td>
      </tr>`;
  }).join('');

  // Sync select-all checkbox
  allCb.checked = words.length > 0 && words.every(w => STATE.selectedIds.has(w.id));
  allCb.indeterminate = !allCb.checked && words.some(w => STATE.selectedIds.has(w.id));

  // Row checkbox events
  tbody.querySelectorAll('.row-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = +cb.dataset.id;
      cb.checked ? STATE.selectedIds.add(id) : STATE.selectedIds.delete(id);
      renderBulkBar();
      renderTable();
    });
  });

  // Edit / delete button events
  tbody.querySelectorAll('.tbl-btn--edit').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openEditWord(+btn.dataset.id); });
  });
  tbody.querySelectorAll('.tbl-btn--delete').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openDeleteWord(+btn.dataset.id); });
  });

  // Update sort header classes
  $$('.word-table th.sortable').forEach(th => {
    th.classList.remove('asc', 'desc');
    if (th.dataset.col === STATE.sortCol) th.classList.add(STATE.sortDir);
  });

  // Round assignment dropdowns
  tbody.querySelectorAll('.round-select').forEach(sel => {
    sel.addEventListener('change', async () => {
      const id = +sel.dataset.id;
      const next = parseInt(sel.value, 10);
      const w = STATE.words.find(x => x.id === id);
      if (!w) return;
      const prev = w.round || 1;
      const wrap = sel.closest('.dd') || sel;
      // Optimistic update, then persist via the API when a host context exists.
      w.round = next;
      sel.dataset.current = next;
      wrap.classList.remove('round-select--r1', 'round-select--r2');
      wrap.classList.add(`round-select--r${next}`);
      renderRoundCards();
      renderSummary();
      if (window.WordAPI && API.getGameId()) {
        try {
          await API.withLoading(`round-${id}`, () =>
            WordAPI.setWordRound(id, next)
          );
          showToast(`"${w.word}" moved to Round ${next}`);
        } catch (err) {
          console.error('[Pinoy Henyo] set word round failed', err);
          w.round = prev;
          sel.dataset.current = prev;
          sel.value = String(prev);
          wrap.classList.remove('round-select--r1', 'round-select--r2');
          wrap.classList.add(`round-select--r${prev}`);
          if (wrap.__api) wrap.__api.renderOptions();
          renderRoundCards();
          renderSummary();
          showToast(err.message || 'Could not change the round.');
        }
      } else {
        showToast(`"${w.word}" moved to Round ${next}`);
      }
    });
  });
}

/* ============================================================
   SELECT ALL
============================================================ */
$('select-all').addEventListener('change', e => {
  const words = getFilteredWords();
  if (e.target.checked) words.forEach(w => STATE.selectedIds.add(w.id));
  else                  words.forEach(w => STATE.selectedIds.delete(w.id));
  renderBulkBar();
  renderTable();
});

/* ============================================================
   SORT
============================================================ */
$$('.word-table th.sortable').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (STATE.sortCol === col) {
      STATE.sortDir = STATE.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      STATE.sortCol = col;
      STATE.sortDir = 'asc';
    }
    renderTable();
  });
});

/* ============================================================
   BULK ACTION BAR
============================================================ */
function renderBulkBar() {
  const bar   = $('bulk-bar');
  const count = STATE.selectedIds.size;
  if (count === 0) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  $('bulk-count').textContent = `${count} word${count !== 1 ? 's' : ''} selected`;
}

$('bulk-delete').addEventListener('click', async () => {
  const count = STATE.selectedIds.size;
  if (!count) return;
  if (!confirm(`Delete ${count} word${count !== 1 ? 's' : ''}? This cannot be undone.`)) return;
  const ids = [...STATE.selectedIds];

  // Real backend integration when a host game context exists.
  if (window.WordAPI && API.getGameId()) {
    const btn = $('bulk-delete');
    btn.disabled = true;
    try {
      for (const id of ids) {
        try { await WordAPI.deleteWord(id, { asHost: true }); }
        catch (e) { console.warn('[Pinoy Henyo] bulk delete word failed', id, e); }
      }
      STATE.words = STATE.words.filter(w => !ids.includes(w.id));
      STATE.totalWords = Math.max(0, STATE.totalWords - ids.length);
      STATE.selectedIds.clear();
      renderBulkBar();
      render();
      showToast(`${ids.length} word${ids.length !== 1 ? 's' : ''} deleted`);
      await refreshWordPool();
    } catch (err) {
      console.error('[Pinoy Henyo] bulk delete failed', err);
      showToast(err.message || 'Could not delete the selected words.');
    } finally {
      btn.disabled = false;
    }
    return;
  }

  STATE.words = STATE.words.filter(w => !ids.includes(w.id));
  STATE.totalWords = Math.max(0, STATE.totalWords - ids.length);
  STATE.selectedIds.clear();
  renderBulkBar();
  renderTable();
  renderFilterPills();
  showToast(`${count} word${count !== 1 ? 's' : ''} deleted`);
});

$('bulk-cancel').addEventListener('click', () => {
  STATE.selectedIds.clear();
  renderBulkBar();
  renderTable();
});

/* ============================================================
   SEARCH
============================================================ */
$('search-input').addEventListener('input', e => {
  STATE.search = e.target.value;
  $('btn-clear-search').hidden = !STATE.search;
  renderTable();
  if (STATE.view === 'team')     renderByTeam();
  if (STATE.view === 'category') renderByCategory();
});

$('btn-clear-search').addEventListener('click', () => {
  $('search-input').value = '';
  STATE.search = '';
  $('btn-clear-search').hidden = true;
  renderTable();
  renderByTeam();
  renderByCategory();
});

/* ============================================================
   VIEW TOGGLE
============================================================ */
function setView(view) {
  STATE.view = view;
  const sections = { table: 'view-table-section', team: 'view-team-section', category: 'view-category-section' };
  Object.entries(sections).forEach(([v, id]) => {
    $(id).hidden = (v !== view);
  });
  $$('.view-toggle__btn').forEach(btn => {
    btn.classList.toggle('view-toggle__btn--active', btn.dataset.view === view);
  });

  if (view === 'team')     renderByTeam();
  if (view === 'category') renderByCategory();
  if (view === 'table')    renderTable();
}

$$('.view-toggle__btn').forEach(btn => {
  btn.addEventListener('click', () => setView(btn.dataset.view));
});

/* ============================================================
   BY-TEAM VIEW
============================================================ */
function renderByTeam() {
  const container = $('by-team-content');
  const words     = getFilteredWords();

  if (words.length === 0) {
    container.innerHTML = '<p style="color:rgba(255,255,255,0.3);padding:1.5rem;text-align:center">No words match your filters.</p>';
    return;
  }

  // Group by team
  const teamMap = {};
  words.forEach(w => {
    const key = teamOf(w);
    if (!teamMap[key]) teamMap[key] = {};
    if (!teamMap[key][w.category]) teamMap[key][w.category] = [];
    teamMap[key][w.category].push(w);
  });

  container.innerHTML = Object.entries(teamMap).map(([team, catMap]) => {
    const total = Object.values(catMap).flat().length;
    const catHtml = Object.entries(catMap).map(([cat, ws]) => `
      <div class="group-cat-section">
        <p class="group-cat-label">${esc(cat)}</p>
        <div class="group-word-list">
          ${ws.map(w => `
            <div class="group-word-chip">
              ${esc(w.word)}
            </div>`).join('')}
        </div>
      </div>`).join('');

    return `
      <div class="group-section">
        <div class="group-header" data-group="${esc(team)}">
          <div class="group-header__left">
            <i class="fa-solid fa-users" style="color:var(--primary-400);font-size:0.85rem"></i>
            <span class="group-header__title">${esc(team)}</span>
            <span class="group-header__count">${total} word${total !== 1 ? 's' : ''}</span>
          </div>
          <i class="fa-solid fa-chevron-down group-header__chevron"></i>
        </div>
        <div class="group-body">${catHtml}</div>
      </div>`;
  }).join('');

  attachGroupToggle(container);
}

/* ============================================================
   BY-CATEGORY VIEW
============================================================ */
function renderByCategory() {
  const container = $('by-category-content');
  const words     = getFilteredWords();

  if (words.length === 0) {
    container.innerHTML = '<p style="color:rgba(255,255,255,0.3);padding:1.5rem;text-align:center">No words match your filters.</p>';
    return;
  }

  // Group by category
  const catMap = {};
  words.forEach(w => {
    if (!catMap[w.category]) catMap[w.category] = [];
    catMap[w.category].push(w);
  });

  container.innerHTML = Object.entries(catMap).map(([cat, ws]) => `
    <div class="group-section">
      <div class="group-header" data-group="${esc(cat)}">
        <div class="group-header__left">
          <i class="fa-solid fa-tag" style="color:var(--accent-1-400);font-size:0.85rem"></i>
          <span class="group-header__title">${esc(cat)}</span>
          <span class="group-header__count">${ws.length} word${ws.length !== 1 ? 's' : ''}</span>
        </div>
        <i class="fa-solid fa-chevron-down group-header__chevron"></i>
      </div>
      <div class="group-body">
        <div class="group-word-list">
          ${ws.map(w => `
            <div class="group-word-chip">
              ${esc(w.word)}
              <span class="group-word-chip__team">(${esc(teamOf(w))})</span>
            </div>`).join('')}
        </div>
      </div>
    </div>`).join('');

  attachGroupToggle(container);
}

/* Collapsible group headers */
function attachGroupToggle(container) {
  container.querySelectorAll('.group-header').forEach(header => {
    header.addEventListener('click', () => {
      const body = header.nextElementSibling;
      header.classList.toggle('collapsed');
      body.classList.toggle('collapsed');
    });
  });
}

/* ============================================================
   ADD WORD
============================================================ */
function openAddWord() {
  if (STATE.locked) { showToast('Words are locked.'); return; }
  $('form-add').reset();
  $('err-add-word').textContent = '';
  $('err-add-category').textContent = '';
  populateSelects();
  openModal('modal-add');
}

$('btn-add-word').addEventListener('click', openAddWord);
$('btn-add-word-empty').addEventListener('click', openAddWord);
$('close-add').addEventListener('click',  () => closeModal('modal-add'));
$('cancel-add').addEventListener('click', () => closeModal('modal-add'));

$('form-add').addEventListener('submit', e => {
  e.preventDefault();
  const wordIn = $('add-word');
  const catIn  = $('add-category');
  let valid    = true;

  if (!wordIn.value.trim()) {
    wordIn.classList.add('error');
    $('err-add-word').textContent = 'Word is required.';
    valid = false;
  } else { wordIn.classList.remove('error'); $('err-add-word').textContent = ''; }

  if (!catIn.value) {
    catIn.classList.add('error');
    $('err-add-category').textContent = 'Please select a category.';
    valid = false;
  } else { catIn.classList.remove('error'); $('err-add-category').textContent = ''; }

  if (!valid) return;

  const newWord = {
    word:     wordIn.value.trim(),
    category: catIn.value,
    team:     null,   // host-added words are stored under "Host"
    status:   'available',
    round:    parseInt($('add-round').value, 10) || 1,
  };

  // Check duplicate
  const isDup = STATE.words.some(w => w.word.toLowerCase() === newWord.word.toLowerCase());
  if (isDup) {
    STATE.pendingDupAction = newWord;
    $('dup-word-name').textContent = newWord.word;
    closeModal('modal-add');
    openModal('modal-duplicate');
    return;
  }

  commitAddWord(newWord);
});

async function commitAddWord(data) {
  // Real backend integration when a host game context exists. Host words
  // carry no team — the backend stores them without a submitting team.
  if (window.WordAPI && API.getGameId()) {
    const categoryId = window.CATEGORY_NAME_TO_ID ? window.CATEGORY_NAME_TO_ID[data.category] : null;
    const btn = $('form-add').querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Adding…';
    try {
      const created = await API.withLoading('add-word', () =>
        WordAPI.createWord(API.getGameId(), {
          categoryId, wordText: data.word, asHost: true, assignedRound: data.round || 1,
        })
      );
      if (!created.word_id) throw new Error('No word_id returned.');
      STATE.words.push({
        id: created.word_id,
        word: created.word_text,
        category: created.category_name || data.category,
        team: created.team_name || null,
        status: mapWordStatus(created.status),
        round: created.assigned_round || data.round || 1,
      });
      STATE.totalWords++;
      closeModal('modal-add');
      closeModal('modal-duplicate');
      render();
      showToast(`"${data.word}" added`);
    } catch (err) {
      console.error('[Pinoy Henyo] add word failed', err);
      if (err.code === 'DUPLICATE_SUBMIT' || err.code === 'DUPLICATE_WORD') { showToast(err.message || 'Duplicate word.'); return; }
      $('err-add-category').textContent = err.message || 'Could not add the word.';
      $('add-category').classList.add('error');
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  STATE.words.push({ id: STATE.nextId++, ...data });
  STATE.totalWords++;
  closeModal('modal-add');
  closeModal('modal-duplicate');
  render();
  showToast(`"${data.word}" added`);
}

/* ============================================================
   DUPLICATE WORD MODAL
============================================================ */
$('close-dup').addEventListener('click',     () => closeModal('modal-duplicate'));
$('btn-dup-change').addEventListener('click', () => {
  closeModal('modal-duplicate');
  openModal('modal-add');
});
$('btn-dup-keep').addEventListener('click',  () => {
  if (STATE.pendingDupAction) commitAddWord(STATE.pendingDupAction);
  STATE.pendingDupAction = null;
});

/* ============================================================
   EDIT WORD
============================================================ */
function openEditWord(id) {
  if (STATE.locked) { showToast('Words are locked.'); return; }
  const w = STATE.words.find(x => x.id === id);
  if (!w) return;
  STATE.pendingEditId = id;

  populateSelects();
  $('edit-word').value     = w.word;
  $('edit-category').value = w.category;
  $('edit-team').value     = w.team  || HOST_TEAM_LABEL;
  $('edit-subtitle').textContent = `Editing "${w.word}"` + (w.team ? ` — ${w.team}` : ` — ${HOST_TEAM_LABEL}`);

  $('err-edit-word').textContent = '';
  $('err-edit-category').textContent = '';

  openModal('modal-edit');
}

$('close-edit').addEventListener('click',  () => closeModal('modal-edit'));
$('cancel-edit').addEventListener('click', () => closeModal('modal-edit'));

$('form-edit').addEventListener('submit', async e => {
  e.preventDefault();
  const wordIn = $('edit-word');
  const catIn  = $('edit-category');
  let valid    = true;

  if (!wordIn.value.trim()) {
    wordIn.classList.add('error');
    $('err-edit-word').textContent = 'Word is required.';
    valid = false;
  } else { wordIn.classList.remove('error'); $('err-edit-word').textContent = ''; }

  if (!catIn.value) {
    catIn.classList.add('error');
    $('err-edit-category').textContent = 'Please select a category.';
    valid = false;
  } else { catIn.classList.remove('error'); $('err-edit-category').textContent = ''; }

  if (!valid) return;

  const w = STATE.words.find(x => x.id === STATE.pendingEditId);
  if (!w) return;

  // Real backend integration when a host game context exists.
  // The backend persists word text + category (PATCH /words/:id).
  if (window.WordAPI && API.getGameId()) {
    const categoryId = window.CATEGORY_NAME_TO_ID ? window.CATEGORY_NAME_TO_ID[catIn.value] : null;
    if (!categoryId) {
      $('err-edit-category').textContent = 'Please select a valid category.';
      return;
    }
    const btn = $('form-edit').querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      await API.withLoading('edit-word', () =>
        WordAPI.updateWord(w.id, wordIn.value.trim(), { asHost: true, categoryId })
      );
      w.word     = wordIn.value.trim();
      w.category = catIn.value;
      closeModal('modal-edit');
      render();
      showToast(`"${w.word}" updated`);
    } catch (err) {
      console.error('[Pinoy Henyo] edit word failed', err);
      $('err-edit-word').textContent = err.message || 'Could not update the word.';
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  w.word     = wordIn.value.trim();
  w.category = catIn.value;
  w.team     = $('edit-team').value  || null;
  w.status   = 'available';

  closeModal('modal-edit');
  render();
  showToast(`"${w.word}" updated`);
});

/* ============================================================
   DELETE WORD
============================================================ */
function openDeleteWord(id) {
  if (STATE.locked) { showToast('Words are locked.'); return; }
  const w = STATE.words.find(x => x.id === id);
  if (!w) return;
  STATE.pendingDeleteId = id;
  $('delete-word-name').textContent = w.word;
  $('delete-subtitle').textContent  = `Remove "${w.word}" from the game?`;
  openModal('modal-delete');
}

$('close-delete').addEventListener('click',     () => closeModal('modal-delete'));
$('cancel-delete').addEventListener('click',    () => closeModal('modal-delete'));
$('btn-confirm-delete').addEventListener('click', async () => {
  const w = STATE.words.find(x => x.id === STATE.pendingDeleteId);
  if (!w) return;
  const name = w.word;

  // Real backend integration when a host game context exists.
  if (window.WordAPI && API.getGameId()) {
    const btn = $('btn-confirm-delete');
    const original = btn.textContent;
    btn.disabled = true;
    try {
      await API.withLoading('delete-word', () => WordAPI.deleteWord(w.id, { asHost: true }));
      STATE.words = STATE.words.filter(x => x.id !== w.id);
      STATE.totalWords = Math.max(0, STATE.totalWords - 1);
      STATE.selectedIds.delete(w.id);
      STATE.pendingDeleteId = null;
      closeModal('modal-delete');
      render();
      showToast(`"${name}" deleted`);
    } catch (err) {
      console.error('[Pinoy Henyo] delete word failed', err);
      showToast(err.message || 'Could not delete the word.');
      closeModal('modal-delete');
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  STATE.words = STATE.words.filter(x => x.id !== STATE.pendingDeleteId);
  STATE.totalWords = Math.max(0, STATE.totalWords - 1);
  STATE.selectedIds.delete(STATE.pendingDeleteId);
  STATE.pendingDeleteId = null;
  closeModal('modal-delete');
  render();
  showToast(`"${name}" deleted`);
});

/* ============================================================
   WORD STATUS PANEL (real per-team-per-category readiness)
   ============================================================ */
$('btn-assign-words').addEventListener('click', () => {
  STATE.showAssign = true;
  $('assign-section').hidden = false;
  renderWordStatus();
  $('assign-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

$('btn-close-assign').addEventListener('click', () => {
  STATE.showAssign = false;
  $('assign-section').hidden = true;
});

function renderWordStatus() {
  const body = $('word-status-body');
  if (!body) return;

  // Group the real words by submitting team, then by category.
  const teamMap = {};
  STATE.words.forEach(w => {
    const key = teamOf(w);
    if (!teamMap[key]) teamMap[key] = {};
    if (!teamMap[key][w.category]) teamMap[key][w.category] = [];
    teamMap[key][w.category].push(w);
  });

  const teamNames = Object.keys(teamMap);
  if (teamNames.length === 0) {
    body.innerHTML = '<p style="color:rgba(255,255,255,0.35);padding:1rem">No words submitted yet. Add words to see per-team status.</p>';
    return;
  }

  body.innerHTML = teamNames.map(team => {
    const cats = teamMap[team];
    const catNames = Object.keys(cats);
    const totalCount = catNames.reduce((n, c) => n + cats[c].length, 0);
    const rows = catNames.map(cat => {
      const count = cats[cat].length;
      const cls = count >= 5 ? 'more' : (count >= 3 ? 'ok' : 'warn');
      const chip = count >= 5
        ? `<span class="ws-ready-chip more">Max 5 reached</span>`
        : `<span class="ws-ready-chip ${count >= 3 ? 'ready' : ''}">${count >= 3 ? 'Ready' : 'Need ' + (3 - count) + ' more'}</span>`;
      return `
        <div class="ws-cat">
          <span class="ws-cat__name">${esc(cat)}</span>
          <span class="ws-cat__count ${cls}">${count} / 5</span>
          ${chip}
        </div>`;
    }).join('');
    return `
      <div class="ws-team">
        <div class="ws-team__head">
          <i class="fa-solid fa-users"></i> ${esc(team)}
          <span class="ws-team__count">${totalCount} word${totalCount !== 1 ? 's' : ''}</span>
        </div>
        ${rows}
      </div>`;
  }).join('');
}

/* ============================================================
   ROUND 1 CATEGORIES
   Compact picker in the category filter row. Round 1 uses the
   selected chips (or every category when none are picked);
   Round 2 always uses all categories. Match play-slots are
   created automatically by the server when the game starts.
============================================================ */
function renderRound1Picker() {
  const pills = $('r1-pills');
  const allBtn = $('r1-pill-all');
  if (!pills) return;
  const selected = STATE.round1CategoryIds || [];
  const all = selected.length === 0 || selected.length >= STATE.categories.length;
  pills.innerHTML = STATE.categories.map(c => {
    const active = selected.includes(c.id);
    return `<button type="button" class="filter-pill ${active ? 'active' : ''}" data-cat-id="${c.id}" role="radio" aria-checked="${active}">${esc(c.name)}</button>`;
  }).join('');
  if (allBtn) {
    allBtn.classList.toggle('is-active', all);
    allBtn.setAttribute('aria-pressed', all ? 'true' : 'false');
  }
}

async function refreshRound1() {
  const gameId = API.getGameId();
  if (!gameId || !window.RoundAPI) return;
  try {
    const r = await RoundAPI.listRounds(gameId);
    const round1 = (r.rounds || []).find(x => x.round_number === 1);
    STATE.round1CategoryIds = (round1 && round1.selected_category_ids)
      ? round1.selected_category_ids.slice()
      : [];
    renderRound1Picker();
    render();
  } catch (e) {
    console.warn('[words] round 1 offline', e.message);
  }
}

let _r1Saving = false;
async function saveRound1Selection() {
  const gameId = API.getGameId();
  if (!gameId || !window.RoundAPI || _r1Saving) return;
  let ids = (STATE.round1CategoryIds || [])
    .filter(id => STATE.categories.some(c => c.id === id));
  if (!ids.length) ids = STATE.categories.map(c => c.id); // none picked => all
  if (!ids.length) { showToast('No categories yet. Add categories first.'); return; }
  _r1Saving = true;
  const allBtn = $('r1-pill-all');
  const prevText = allBtn ? allBtn.textContent : '';
  if (allBtn) { allBtn.disabled = true; allBtn.textContent = 'Saving…'; }
  try {
    let round1 = null;
    try {
      const r = await RoundAPI.listRounds(gameId);
      round1 = (r.rounds || []).find(x => x.round_number === 1);
    } catch (e) { /* ignore */ }
    if (!round1) {
      await API.withLoading('r1-create', () =>
        RoundAPI.createRound(gameId, { roundNumber: 1 })
      );
    }
    const saved = await API.withLoading('r1-cats', () =>
      RoundAPI.selectRoundCategories(gameId, 1, ids)
    );
    STATE.round1CategoryIds = ((saved && saved.selected_category_ids) || ids).slice();
    if (typeof refreshWordPoolHook === 'function') {
      try { await refreshWordPoolHook(); } catch (e) { /* ignore */ }
    }
    renderRound1Picker();
    render();
    showToast('Round 1 categories saved');
  } catch (err) {
    console.error('[words] save round 1 categories failed', err);
    showToast((err && err.message) || 'Could not save Round 1 categories.');
  } finally {
    _r1Saving = false;
    if (allBtn) { allBtn.disabled = false; allBtn.textContent = prevText; }
  }
}

const r1PillsEl = $('r1-pills');
if (r1PillsEl) {
  r1PillsEl.addEventListener('click', async e => {
    const chip = e.target.closest('.filter-pill[data-cat-id]');
    if (!chip) return;
    const id = parseInt(chip.dataset.catId, 10);
    const ids = (STATE.round1CategoryIds || []).slice();
    const i = ids.indexOf(id);
    if (i >= 0) ids.splice(i, 1); else ids.push(id);
    STATE.round1CategoryIds = ids;
    renderRound1Picker();
    await saveRound1Selection();
  });
}
const r1AllBtn = $('r1-pill-all');
if (r1AllBtn) {
  r1AllBtn.addEventListener('click', async () => {
    STATE.round1CategoryIds = [];
    renderRound1Picker();
    await saveRound1Selection();
  });
}

/* ============================================================
   NAV CODE COPY
============================================================ */
$('btn-copy-code').addEventListener('click', () => {
  const code = window.PINOY_GAME_CODE || '';
  if (navigator.clipboard) navigator.clipboard.writeText(code).catch(() => {});
  const icon = $('nav-copy-icon');
  icon.className = 'fa-solid fa-check';
  setTimeout(() => { icon.className = 'fa-regular fa-copy'; }, 1800);
  showToast(`Copied: ${code}`);
});

/* ============================================================
   SIDEBAR NAV
============================================================ */
$$('.sidebar__nav-item').forEach(item => {
  if (item.tagName === 'A' && item.href && !item.href.endsWith('#')) return; // real links navigate
  item.addEventListener('click', e => {
    e.preventDefault();
    $$('.sidebar__nav-item').forEach(i => i.classList.remove('sidebar__nav-item--active'));
    item.classList.add('sidebar__nav-item--active');
    showToast(`Coming soon: ${item.querySelector('span').textContent}`);
  });
});

/* ============================================================
   SCROLL REVEAL
============================================================ */
const revealObs = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('visible'); revealObs.unobserve(entry.target); }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -30px 0px' });
$$('.reveal').forEach(el => revealObs.observe(el));

/* ============================================================
   FULL RENDER
============================================================ */
function render() {
  renderSummary();
  renderLockBar();
  renderFilterPills();
  renderTable();
  renderRoundCards();
  if (STATE.view === 'team')     renderByTeam();
  if (STATE.view === 'category') renderByCategory();
  if (STATE.showAssign)          renderWordStatus();
}

/* ============================================================
   ROUND CARDS
   Two cards under the All Words table: one per round, listing
   every word currently assigned to it (chips + team tag).
============================================================ */
function renderRoundCards() {
  const cardsEl = $('round-cards');
  if (!cardsEl) return;
  cardsEl.hidden = !STATE.words.length;

  [1, 2].forEach(round => {
    const list  = $(`roundcard-${round}-list`);
    const count = $(`roundcard-${round}-count`);
    if (!list || !count) return;
    const words = STATE.words.filter(w => (w.round || 1) === round);
    count.textContent = String(words.length);
    if (!words.length) {
      list.innerHTML = '<span class="round-card__empty">No words yet — assign some from the table above.</span>';
      return;
    }
    list.innerHTML = words.map(w => `
      <span class="round-chip" title="${esc(w.word)} — ${esc(teamOf(w))}">
        <span class="round-chip__text">${esc(w.word)}</span>
        <span class="round-chip__team">${esc(teamOf(w))}</span>
      </span>`).join('');
  });
}

/* ============================================================
   INIT
============================================================ */
function init() {
  populateSelects();
  render();
}

init();

/* ============================================================
   BACKEND INTEGRATION (host words page)
   When a host game context exists, load real categories + words
   and route add/edit/delete through the API. Otherwise the demo
   state is preserved.
   ============================================================ */
function mapWordStatus(status) {
  if (status === 'SELECTED') return 'selected';
  if (status === 'DISABLED') return 'disabled';
  return 'available';
}

(async function bootstrapWordsIntegration() {
  const gameId = API.getGameId();
  if (!gameId) return;

  const rt = window.Realtime;

  // Host reconnect guard (parity with the dashboard + teams pages). If the
  // stored host token is stale/invalid, prompt the host to return to the lobby
  // instead of silently running in demo mode.
  try {
    const r = await Connect.restoreHostSession();
    if (r.status === 'invalid' || r.status === 'unavailable') {
      Connect.showReconnectBanner({
        title: r.status === 'invalid' ? 'Host session not found' : 'Server unreachable',
        message: r.status === 'invalid'
          ? 'Your host session could not be restored. Return to the lobby to reconnect.'
          : 'Could not reach the server. Check your connection and try again.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
    }
  } catch (e) { /* ignore */ }

  try {
    // Game code is only available from the creation response, so pull it
    // from the shared client context rather than the status endpoint.
    if (API.getGameCode()) {
      window.PINOY_GAME_CODE = API.getGameCode();
      const codeDisp = $('game-code-display');
      if (codeDisp) codeDisp.textContent = window.PINOY_GAME_CODE;
    }
  } catch (e) { /* ignore */ }

  // Populate the team filter/list from the real backend team names/ids.
  const knownTeams = (API.getKnownTeams && API.getKnownTeams()) || [];
  TEAMS = knownTeams.map(t => t.team_name || 'Team #' + t.team_id);

  // Reload the live word pool + lock state from the backend.
  async function refreshWordPool() {
    try {
      const wData = await WordAPI.listWords(gameId);
      const wordsList = (wData.words || []).map(w => ({
        id: w.word_id,
        word: w.word_text,
        category: w.category_name || 'Other',
        team: w.team_name || null,
        isHost: w.is_host === true,
        status: mapWordStatus(w.status),
        round: w.assigned_round || 1,
      }));
      STATE.words = wordsList;
      STATE.totalWords = wordsList.length;
      if (wordsList.length) {
        STATE.nextId = Math.max.apply(null, wordsList.map(w => w.id).concat(0)) + 1;
      }
      try {
        const statusData = await GameAPI.status(gameId);
        if (typeof statusData.word_pool_locked === 'boolean') {
          STATE.locked = statusData.word_pool_locked;
        }
        const roundEl = $('round-number');
        if (roundEl) roundEl.textContent = String((statusData && statusData.current_round) || 1);
      } catch (e) { /* status offline */ }
      populateSelects();
      render();
    } catch (e) { console.warn('[words] words offline', e.message); }
  }
  refreshWordPoolHook = refreshWordPool;

  // Refetch all backend-driven sections (round-1 picker and word pool).
  let refreshTimer = null;
  function refreshAll() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
      await refreshWordPool();
      await refreshRound1();
    }, 120);
  }

  // Refetch and refresh all category-derived state (selects, pills, tags,
  // name→id map, counts). Used on load and after category mutations.
  async function fetchCategories() {
    const catData = await WordAPI.listCategories(gameId);
    const cats = (catData.categories || [])
      .map(c => ({ id: c.category_id, name: c.name, word_count: c.word_count || 0 }))
      .filter(c => c.name);
    window.CATEGORY_NAME_TO_ID = {};
    cats.forEach(c => { window.CATEGORY_NAME_TO_ID[c.name] = c.id; });
    STATE.categories = cats;
    CATEGORIES.length = 0;
    cats.forEach(c => CATEGORIES.push(c.name));
    STATE.totalCategories = cats.length;
    return cats;
  }

  async function reloadCategories() {
    await fetchCategories();
    populateSelects();
    render();
    await refreshWordPool();
    await refreshRound1();
  }

  try { await fetchCategories(); }
  catch (e) { console.warn('[words] categories offline', e.message); }

  await refreshWordPool();

  // Load the Round-1 category selection into the compact picker.
  await refreshRound1();

  // ---------------- Manage Categories modal ----------------
  const manageCatsList = $('manage-cats-list');
  const newCatName = $('new-cat-name');

  async function renderManageCategories() {
    manageCatsList.innerHTML = '<p style="color:rgba(255,255,255,0.35)">Loading categories…</p>';
    try {
      const cats = await fetchCategories();
      if (!cats.length) {
        manageCatsList.innerHTML = '<p style="color:rgba(255,255,255,0.5)">No categories yet. Add one above.</p>';
        return;
      }
      manageCatsList.innerHTML = cats.map(c => `
        <div class="cat-manage-row" data-id="${c.id}">
          <span class="cat-manage-row__name">${esc(c.name)}</span>
          <span class="cat-manage-row__count">${c.word_count} word${c.word_count !== 1 ? 's' : ''}</span>
          <div class="cat-manage-row__actions">
            <button class="cat-manage-row__btn cat-manage-row__btn--rename" data-id="${c.id}" title="Rename">
              <i class="fa-solid fa-pen"></i>
            </button>
            <button class="cat-manage-row__btn cat-manage-row__btn--delete" data-id="${c.id}" data-name="${esc(c.name)}" title="Delete">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </div>`).join('');

      manageCatsList.querySelectorAll('.cat-manage-row__btn--rename').forEach(btn => {
        btn.addEventListener('click', () => startRenameCat(btn));
      });
      manageCatsList.querySelectorAll('.cat-manage-row__btn--delete').forEach(btn => {
        btn.addEventListener('click', () => deleteCatRow(btn));
      });
    } catch (e) {
      manageCatsList.innerHTML = `<p style="color:rgba(255,255,255,0.5)">${esc(e.message || 'Could not load categories.')}</p>`;
    }
  }

  async function deleteCatRow(btn) {
    if (STATE.locked) { showToast('Categories are locked once the game starts.'); return; }
    const id = parseInt(btn.dataset.id, 10);
    const name = btn.dataset.name;
    if (!confirm(`Delete category "${name}"? All of its words will also be removed.`)) return;
    btn.disabled = true;
    try {
      await API.withLoading('delete-category', () => WordAPI.deleteCategory(id));
      showToast(`Category "${name}" deleted`);
      await reloadCategories();
      await renderManageCategories();
    } catch (err) {
      console.error('[Pinoy Henyo] delete category failed', err);
      showToast(err.message || 'Could not delete the category.');
    } finally {
      btn.disabled = false;
    }
  }

  function startRenameCat(btn) {
    if (STATE.locked) { showToast('Categories are locked once the game starts.'); return; }
    const row = btn.closest('.cat-manage-row');
    const id = parseInt(btn.dataset.id, 10);
    const cur = row.querySelector('.cat-manage-row__name').textContent;
    const nameEl = row.querySelector('.cat-manage-row__name');
    nameEl.innerHTML = `<input type="text" class="form-input cat-manage-row__input" maxlength="50" value="${esc(cur)}" />`;
    const input = nameEl.querySelector('input');
    btn.outerHTML = `<span class="cat-manage-row__btn cat-manage-row__btn--save" data-id="${id}" title="Save"><i class="fa-solid fa-check"></i></span>`;
    const saveBtn = row.querySelector('.cat-manage-row__btn--save');

    const finish = async () => {
      const next = input.value.trim();
      if (!next) { nameEl.textContent = cur; return; }
      if (next === cur) { nameEl.textContent = cur; return; }
      try {
        await API.withLoading('rename-category', () => WordAPI.updateCategory(id, next));
        showToast('Category renamed');
        await reloadCategories();
        await renderManageCategories();
      } catch (err) {
        console.error('[Pinoy Henyo] rename category failed', err);
        showToast(err.message || 'Could not rename the category.');
        nameEl.textContent = cur;
        await renderManageCategories();
      }
    };

    saveBtn.addEventListener('click', finish);
    input.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') { ev.preventDefault(); finish(); }
      if (ev.key === 'Escape') { nameEl.textContent = cur; }
    });
    input.focus();
    input.select();
  }

  $('btn-manage-cats').addEventListener('click', async () => {
    openModal('modal-manage-cats');
    await renderManageCategories();
  });
  $('close-manage-cats').addEventListener('click', () => closeModal('modal-manage-cats'));
  $('close-manage-cats-2').addEventListener('click', () => closeModal('modal-manage-cats'));

  $('form-add-category').addEventListener('submit', async e => {
    e.preventDefault();
    if (STATE.locked) { showToast('Categories are locked once the game starts.'); return; }
    const name = newCatName.value.trim();
    if (!name) { $('err-new-cat').textContent = 'Category name is required.'; return; }
    $('err-new-cat').textContent = '';
    const btn = $('form-add-category').querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      await API.withLoading('create-category', () => WordAPI.createCategory(gameId, name));
      newCatName.value = '';
      showToast(`Category "${name}" added`);
      await reloadCategories();
      await renderManageCategories();
    } catch (err) {
      console.error('[Pinoy Henyo] create category failed', err);
      $('err-new-cat').textContent = err.message || 'Could not add the category.';
    } finally {
      btn.disabled = false;
    }
  });

  // Host realtime socket: keep this setup page in sync with the game
  // lifecycle so round/match/word changes made elsewhere (or by the server)
  // are reflected without a manual reload.
  if (rt) {
    const forGame = p => !!p && !!gameId && p.game_id === gameId;
    ['game_started', 'game_paused', 'game_resumed', 'game_completed',
     'round_started', 'round_completed', 'match_started'].forEach((evt) => {
      rt.on(evt, (p) => { if (forGame(p)) refreshAll(); });
    });
    if (!rt.getSocket()) {
      rt.connect({ mode: 'host' });
      rt.onConnect(() => refreshAll());
      rt.onReconnect(() => refreshAll());
    }
  }
})();

