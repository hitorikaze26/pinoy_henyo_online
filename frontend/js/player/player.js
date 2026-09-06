'use strict';

/* ============================================================
   DEFAULT CATEGORIES (overwritten by real backend categories)
============================================================ */
const CATEGORIES = ['Tao / Person', 'Bagay / Object', 'Hayop / Animal', 'Pagkain / Food', 'Lugar / Place'];

let STATE = {
  teamName:      '',
  teamCode:      '',
  gameCode:      '',
  isConnected:   false,
  hostConnected: false,
  connectionStatus: 'NOT_CONNECTED', // NOT_CONNECTED | CONNECTION_REQUESTED | CONNECTED | DECLINED | DISCONNECTED
  connectionToken: '',               // leader's connection token (used for re-requests)
  teamQrDataUri:   '',               // real join-this-team QR (data URI), when available
  gameStatus:    'waiting',   // waiting | ready | round1 | round2 | complete
  currentRound:  1,
  username:      '',
  wordsLocked:   false,
  maxWords:      5,
  score:         0,
  wordsGuessed:  0,
  totalWords:    0,
  timeRemaining: 0,           // seconds
  role:          'Tagasagot', // 'Manghuhula' | 'Tagasagot'
  nextMemberId:  1,
  nextWordId:    1,

  // Server-backed /api/games/<id>/settings (host-controlled).
  settings: {
    max_words_per_category: 5,
    penalty_seconds: 3,
    allow_new_teams: true,
    auto_approve_connections: false,
    max_teams: 8,
    max_members: 6,
    show_player_names: true,
    show_role_labels: true,
    show_scores: true,
    show_qr_code: true,
    show_round_category: true,
  },

  members: [],

  words: [],

  // Game timer
  timerRunning:  false,
  timerInterval: null,

  // Countdown
  countdownInterval: null,

  // Camera stream
  cameraStream: null,

  // Active fullscreen view
  fullscreenView: null, // 'countdown' | 'tagasagot' | 'qr-scanner' | 'conn-success'

  // Active tab
  activeTab: 'teams',

  // Pending delete for member/word
  pendingMemberDeleteId: null,
  pendingWordDeleteId:   null,
};

// Server-sync bookkeeping (single refreshAllData() sync point).
let refreshInProgress = false;
let lastAutoSyncAt   = 0;
let heartbeatTimer   = null;

/* ============================================================
   DOM HELPERS
============================================================ */
const $  = id  => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

/* ============================================================
   ESCAPE HTML
============================================================ */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ============================================================
   BACKEND PAYLOAD HELPERS
   ============================================================ */
function roleDisplayName(role) {
  return String(role || '').toUpperCase() === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot';
}

// Whether the current device holds the team leader role.
function isTeamLeader() {
  return String(API.getDeviceRole() || '').toUpperCase() === 'TEAM_LEADER';
}

// Backend member_payload -> local member row.
function memberFromPayload(m) {
  return {
    id:          m.member_id,
    name:        m.username || '',
    role:        roleDisplayName(m.gameplay_role),
    device_role: m.device_role || '',
    connected:   !!m.is_connected,
  };
}

// Backend word_payload (with relations) -> local word row.
function wordFromPayload(w) {
  return {
    id:        w.word_id,
    word:      w.word_text || '',
    category:  w.category_name || '',
    submitted: true,
  };
}

// Populate STATE from the player's own-team roster payload.
function applyTeamRoster(team) {
  if (!team) return;
  if (team.team_name) STATE.teamName = team.team_name;
  if (team.team_code) STATE.teamCode = team.team_code;
  if (team.connection_status) {
    STATE.connectionStatus = team.connection_status;
    STATE.hostConnected = team.connection_status === 'CONNECTED';
  }
  STATE.members = (team.members || []).map(memberFromPayload);
  const myId = team.my_member_id;
  const me = (team.members || []).find(m => m.member_id === myId);
  if (me) {
    STATE.username = me.username || STATE.username;
    STATE.role = roleDisplayName(me.gameplay_role);
    STATE.nextMemberId = Math.max(me.member_id + 1, STATE.nextMemberId);
    if (me.device_role === 'TEAM_LEADER' && team.leader && team.leader.connection_token) {
      STATE.connectionToken = team.leader.connection_token;
    }
  }
  (team.members || []).forEach(m => {
    if (m.member_id >= STATE.nextMemberId) STATE.nextMemberId = m.member_id + 1;
  });
  if (API.getUsername && API.getUsername()) STATE.username = API.getUsername();
}

/* ============================================================
   HOST-CONNECTION STATE (server-authoritative)
   ============================================================ */
function setConnectionStatus(status) {
  const prev = STATE.connectionStatus;
  STATE.connectionStatus = status;
  STATE.hostConnected = status === 'CONNECTED';
  try { renderHeader(); } catch (e) {}
  try { renderTeamsTab(); } catch (e) {}
  try { renderWaitingScreen(); } catch (e) {}
  return prev !== status;
}

function connectionStateMeta(status) {
  switch (status) {
    case 'CONNECTED':
      return { dot: 'connected', pill: 'conn-pill--connected', label: 'Host Connected', hint: '' };
    case 'CONNECTION_REQUESTED':
      return { dot: 'waiting', pill: 'conn-pill--waiting', label: 'Waiting for host…', hint: 'Request sent. The host must approve this team.' };
    case 'DECLINED':
      return { dot: 'disconnected', pill: 'conn-pill--declined', label: 'Declined by host', hint: 'Scan the host QR or enter the host code to try again.' };
    case 'DISCONNECTED':
      return { dot: 'disconnected', pill: 'conn-pill--disconnected', label: 'Disconnected by host', hint: 'Scan the host QR or enter the host code to reconnect.' };
    default:
      return { dot: 'none', pill: 'conn-pill--none', label: 'Not Connected', hint: 'Ask the host to approve this team before playing.' };
  }
}

// Populate STATE.words from the player's team words payload.
function applyMyWords(words) {
  STATE.words = (words || []).map(wordFromPayload);
  (words || []).forEach(w => {
    if (w.word_id >= STATE.nextWordId) STATE.nextWordId = w.word_id + 1;
  });
}

/* ============================================================
   SERVER SETTINGS — display toggles + per-category word cap
   ============================================================ */
function settingsGet(key, fallback) {
  return STATE.settings && STATE.settings[key] != null ? STATE.settings[key] : fallback;
}

function maxWordsPerCategory() {
  return Math.max(1, Math.abs(Number(settingsGet('max_words_per_category', 5))) || 5);
}

function applySettings(s) {
  if (!s) return;
  STATE.settings = Object.assign({}, STATE.settings, s);
  applyDisplaySettings();
  try { renderHeader(); renderTeamsTab(); renderWordsTab(); renderWaitingScreen(); } catch (e) {}
}

function applyDisplaySettings() {
  const set = (attr, val) => document.body.setAttribute(attr, val ? '1' : '0');
  set('data-show-names',        settingsGet('show_player_names', true) !== false);
  set('data-show-role-labels',  settingsGet('show_role_labels', true) !== false);
  set('data-show-scores',       settingsGet('show_scores', true) !== false);
  set('data-show-qr',           settingsGet('show_qr_code', true) !== false);
  set('data-show-round-category', settingsGet('show_round_category', true) !== false);
}

function countForCategory(cat) {
  return STATE.words.filter(w => w.submitted && w.category === cat).length;
}

function categoriesTouched() {
  return [...new Set(STATE.words.filter(w => w.submitted).map(w => w.category))];
}

function categoryReady(cat) {
  return countForCategory(cat) >= maxWordsPerCategory();
}

function readyCategories() {
  return categoriesTouched().filter(categoryReady);
}

function allCategoriesReady() {
  const cats = categoriesTouched();
  return cats.length > 0 && cats.every(categoryReady);
}

function totalCategoryCap() {
  const cats = categoriesTouched();
  return cats.length ? cats.length * maxWordsPerCategory() : maxWordsPerCategory();
}


/* ============================================================
   TOAST
============================================================ */
function showToast(msg, duration = 2400) {
  const t = $('player-toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), duration);
}

/* ============================================================
   RIPPLE
============================================================ */
function addRipple(btn, e) {
  if (!btn) return;
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x = (e.clientX - rect.left) - size / 2;
  const y = (e.clientY - rect.top)  - size / 2;
  const r = document.createElement('span');
  r.className = 'ripple';
  r.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px;`;
  btn.querySelector('.ripple')?.remove();
  btn.appendChild(r);
  r.addEventListener('animationend', () => r.remove());
}

document.addEventListener('click', e => {
  const btn = e.target.closest(
    '.player-btn, .btn-confirm, .btn-cancel, .game-ans-btn, ' +
    '.bottom-nav__item, .app-header__qr-btn'
  );
  if (btn) addRipple(btn, e);
});

/* ============================================================
   MODAL HELPERS
============================================================ */
function openModal(id) {
  const o = $(id);
  o.classList.add('open');
  o.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  const first = o.querySelector('input, select, button:not(.modal__close)');
  if (first) setTimeout(() => first.focus(), 80);
}

function closeModal(id) {
  const o = $(id);
  o.classList.remove('open');
  o.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

// Close on backdrop click
$$('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o && o.id !== 'modal-confirm') closeModal(o.id); });
});

// Escape key closes modals
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if ($('modal-confirm') && $('modal-confirm').classList.contains('open')) {
    if (!confirmBusy) resolveConfirm(false);
    return;
  }
  $$('.modal-overlay.open').forEach(o => closeModal(o.id));
  // Also close fullscreen views
  if (STATE.fullscreenView === 'qr-scanner') closeQrScanner();
});

/* ============================================================
   CONFIRM MODAL (promise-based replacement for confirm())
   Resolves true on the action button (modal stays open for the
   caller to run its async work), false on cancel/close/Escape.
============================================================ */
let confirmResolve  = null;   // currently awaiting openConfirm()
let confirmBusy     = false;  // locked while an action is processing
let confirmLastFocus = null;
let confirmLabelPending = ''; // action label restored after a busy action

function openConfirm({ title, subtitle = '', body = '', confirmLabel = 'Confirm' }) {
  return new Promise(resolve => {
    const overlay = $('modal-confirm');
    $('confirm-title').textContent    = title;
    $('confirm-subtitle').textContent = subtitle;
    $('confirm-body').textContent     = body;
    const action = $('btn-confirm-action');
    action.disabled     = false;
    action.textContent  = confirmLabel;
    const cancel  = $('cancel-confirm');
    const closeX  = $('close-confirm');
    cancel.disabled = false;
    closeX.disabled = false;
    overlay.classList.remove('modal-overlay--busy');
    confirmBusy      = false;
    confirmLastFocus = document.activeElement;
    confirmResolve   = resolve;
    openModal('modal-confirm');
  });
}

// Called when the user picks an action.
// Returns true if the modal accepted the choice, false if swallows
// (e.g. already resolved, or locked by a running action).
function resolveConfirm(val) {
  if (confirmBusy) return false;
  const resolver = confirmResolve;
  if (!resolver) return false;
  confirmResolve = null;
  const action = $('btn-confirm-action');
  if (action) action.disabled = true;
  if (val === false) closeConfirm();        // cancel path closes now
  confirmLastFocus = null;
  resolver(val);
  return true;
}

// Close the confirm modal and restore focus (use in finally).
function closeConfirm() {
  const overlay = $('modal-confirm');
  overlay.classList.remove('modal-overlay--busy');
  confirmBusy = false;
  const action = $('btn-confirm-action');
  if (action) { action.disabled = false; action.textContent = 'Confirm'; }
  const cancel = $('cancel-confirm');
  const closeX = $('close-confirm');
  if (cancel) cancel.disabled = false;
  if (closeX) closeX.disabled = false;
  closeModal('modal-confirm');
  if (confirmLastFocus) { const f = confirmLastFocus; confirmLastFocus = null; setTimeout(() => f.focus(), 30); }
}

// Lock the modal while an async action runs and show progress.
function setConfirmBusy(busy, label) {
  confirmBusy = busy;
  const overlay = $('modal-confirm');
  const action  = $('btn-confirm-action');
  const cancel  = $('cancel-confirm');
  const closeX  = $('close-confirm');
  if (busy) {
    overlay.classList.add('modal-overlay--busy');
    action.disabled = true;
    if (label) action.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${esc(label)}`;
    if (cancel) cancel.disabled = true;
    if (closeX) closeX.disabled = true;
  } else {
    overlay.classList.remove('modal-overlay--busy');
    action.disabled = false;
    action.textContent = confirmLabelPending || action.dataset.label || action.textContent;
    if (cancel) cancel.disabled = false;
    if (closeX) closeX.disabled = false;
  }
}

// Wire the shared confirm modal once at init.
(function initConfirmModal() {
  const overlay = $('modal-confirm');
  $('btn-confirm-action').addEventListener('click', () => {
    if (!confirmResolve) return;
    confirmLabelPending = $('btn-confirm-action').textContent;
    resolveConfirm(true);
  });
  $('cancel-confirm').addEventListener('click', () => resolveConfirm(false));
  $('close-confirm').addEventListener('click',  () => resolveConfirm(false));
  overlay.addEventListener('click', e => {
    if (e.target === overlay && !confirmBusy) resolveConfirm(false);
  });
})();

/* ============================================================
   QR GRID RENDERER
============================================================ */
function renderQrGrid(container, code) {
  container.classList.remove('qr-box--image');
  let seed = 0;
  for (let i = 0; i < code.length; i++) seed += code.charCodeAt(i);
  const rand = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  const SIZE = 7, total = SIZE * SIZE;
  const corners = new Set([
    0,1,2,7,8,9,14,15,16,
    4,5,6,11,12,13,18,19,20,
    28,29,30,35,36,37,42,43,44,
  ]);
  let html = '';
  for (let i = 0; i < total; i++) {
    const filled = corners.has(i) || rand() > 0.42;
    html += `<div class="qr-pixel${filled ? '' : ' qr-pixel--empty'}"></div>`;
  }
  container.innerHTML = html;
}

/* ============================================================
   COPY TO CLIPBOARD
============================================================ */
function copyText(text, label) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  showToast(`Copied: ${label || text}`);
}

/* ============================================================
   TAB NAVIGATION
============================================================ */
const TAB_IDS = {
  teams:    'tab-teams',
  words:    'tab-words',
  settings: 'tab-settings',
  waiting:  'view-waiting',
};

function switchTab(tabKey) {
  STATE.activeTab = tabKey;

  // Show/hide tab views
  Object.entries(TAB_IDS).forEach(([key, id]) => {
    const el = $(id);
    if (!el) return;
    if (key === tabKey) {
      el.classList.remove('tab-view--hidden');
    } else {
      el.classList.add('tab-view--hidden');
    }
  });

  // Update nav items active state
  $$('.bottom-nav__item').forEach(btn => {
    const isActive = btn.dataset.tab === tabKey;
    btn.classList.toggle('bottom-nav__item--active', isActive);
    btn.setAttribute('aria-selected', String(isActive));
  });
}

// Wire up all nav buttons (bottom nav + game view nav)
$$('.bottom-nav__item').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!btn.dataset.tab) return;
    // If in a fullscreen view, close it first
    if (STATE.fullscreenView) closeFullscreen();
    switchTab(btn.dataset.tab);
  });
});

/* ============================================================
   FULLSCREEN VIEW HELPERS
============================================================ */
function openFullscreen(viewId) {
  // Hide the app shell while fullscreen is open
  const shell = $('app-shell');
  shell.style.visibility = 'hidden';

  const el = $(viewId);
  el.hidden = false;
  STATE.fullscreenView = viewId.replace('view-', '');
}

function closeFullscreen() {
  if (!STATE.fullscreenView) return;
  const el = $(`view-${STATE.fullscreenView}`);
  if (el) el.hidden = true;
  STATE.fullscreenView = null;

  $('app-shell').style.visibility = '';
}

/* ============================================================
   HEADER RENDER
============================================================ */
function renderHeader() {
  $('header-team-name').textContent = STATE.teamName;
  const connected = STATE.isConnected && STATE.hostConnected;
  $('header-conn-dot').className = `conn-dot conn-dot--${connected ? 'connected' : 'disconnected'}`;
  $('header-conn-label').textContent = connected ? 'Connected' : 'Disconnected';
}

/* ============================================================
   TEAMS TAB — RENDER
============================================================ */
function renderTeamsTab() {
  const isLeader = isTeamLeader();

  // Info card
  $('team-info-name').textContent  = STATE.teamName;
  $('team-info-count').textContent = STATE.members.length;
  $('team-info-code').innerHTML = `<span class="code-val">${esc(STATE.teamCode)}</span>
    <button class="inline-copy-btn" id="btn-copy-team-code" aria-label="Copy team code">
      <i class="fa-regular fa-copy"></i>
    </button>`;

  const meta = connectionStateMeta(STATE.connectionStatus);
  $('team-info-host').innerHTML = `
    <span class="conn-dot conn-dot--${meta.dot}"></span> ${meta.label}`;

  const statusHtml = {
    waiting:  `<i class="fa-regular fa-clock" style="color:var(--accent-1-400)"></i> Waiting for Host`,
    ready:    `<i class="fa-solid fa-check" style="color:var(--secondary-400)"></i> Ready`,
    round1:   `<i class="fa-solid fa-play" style="color:var(--primary-400)"></i> Round 1 Active`,
    round2:   `<i class="fa-solid fa-play" style="color:var(--primary-400)"></i> Round 2 Active`,
    complete: `<i class="fa-solid fa-flag-checkered" style="color:var(--gold)"></i> Game Complete`,
  };
  $('team-info-status').innerHTML = statusHtml[STATE.gameStatus] || statusHtml.waiting;

  // Copy button handled centrally by delegation in the COPY BUTTONS section.

  // Member list
  renderMemberList();

  // Roles
  renderRoles();

  // QR
  renderTeamQrArea();
  $('team-code-display').textContent = STATE.teamCode || '—';

  // Game code display (meta grid cell)
  const gameCodeEl = $('game-code-display');
  if (gameCodeEl) gameCodeEl.textContent = STATE.gameCode || '—';

  // Member capacity readout + Add Member gating.
  const capEl = $('member-cap');
  if (capEl) {
    const max = settingsGet('max_members', 6);
    const n   = STATE.members.length;
    capEl.textContent = `${n} / ${max} members`;
    capEl.classList.toggle('member-cap--full', n >= max);
  }
  const addBtn = $('btn-add-member');
  if (addBtn) {
    addBtn.hidden   = !isLeader;
    addBtn.disabled = !isLeader || STATE.members.length >= settingsGet('max_members', 6);
  }

  // Connection status: pill + hint + inline connect block.
  const connMeta = connectionStateMeta(STATE.connectionStatus);
  const pill = $('team-conn-pill');
  const pillDot = $('team-conn-pill-dot');
  if (pill)     pill.className = 'conn-pill ' + connMeta.pill;
  if (pillDot)  pillDot.className = 'conn-dot conn-dot--' + connMeta.dot;
  if ($('team-conn-pill-label')) $('team-conn-pill-label').textContent = connMeta.label;
  const hintEl = $('team-conn-status-hint');
  if (hintEl) hintEl.textContent = connMeta.hint;

  // Inline host-code entry: visible when not connected.
  const connected = STATE.connectionStatus === 'CONNECTED';
  const connectBlock = $('host-connect-block');
  if (connectBlock) {
    connectBlock.hidden = connected;
    const btn = $('btn-connect-code');
    if (btn) btn.disabled = false;
  }

  // Member feedback when the team is pending/declined.
  const pendingBox = $('team-conn-pending-box');
  if (pendingBox) {
    pendingBox.hidden = !(
      STATE.connectionStatus === 'CONNECTION_REQUESTED' ||
      STATE.connectionStatus === 'DECLINED'
    );
  }

  // Team QR actions are leader-only.
  const genQr = $('btn-generate-qr');
  if (genQr) {
    genQr.hidden = !isLeader;
  }

  // Leader-only request/reconnect connection action.
  renderConnectionAction(isLeader, connected);
}

// Server-authoritative connection action for the leader.
// The backend only allows re-requests in NOT_CONNECTED / DECLINED /
// DISCONNECTED states, so the button follows that same set.
function renderConnectionAction(isLeader, alreadyConnected) {
  const area = $('conn-request-area');
  if (!area) return;
  const btn   = $('btn-request-connection');
  const label = $('btn-request-connection-label');
  const hint  = $('conn-request-hint');
  const show = isLeader && !alreadyConnected &&
    ['NOT_CONNECTED', 'DECLINED', 'DISCONNECTED'].includes(STATE.connectionStatus);
  area.hidden = !show;
  if (!show) return;
  const status = STATE.connectionStatus;
  if (status === 'NOT_CONNECTED') {
    if (label) label.textContent = 'Request Connection';
    if (hint)  hint.textContent  = 'Send a connection request to the host to start playing.';
  } else if (status === 'DECLINED') {
    if (label) label.textContent = 'Request Connection Again';
    if (hint)  hint.textContent  = 'The host declined earlier. You can try again.';
  } else {
    if (label) label.textContent = 'Reconnect to Host';
    if (hint)  hint.textContent  = 'Your team was disconnected. Reconnect to keep playing.';
  }
  if (btn) btn.disabled = false;
}

function renderMemberList() {
  const isLeader = isTeamLeader();
  const myId     = API.getMemberId();
  const namesHidden = settingsGet('show_player_names', true) === false;
  const list = $('member-list');
  list.innerHTML = STATE.members.map((m, idx) => {
    const displayName = namesHidden ? `Player ${idx + 1}` : m.name;
    const initials = (namesHidden ? displayName : m.name).split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
    const dotClass = m.connected ? 'connected' : 'disconnected';
    const roleClass = m.role === 'Manghuhula' ? 'member-row__role--manghuhula' : 'member-row__role--tagasagot';
    const isLeaderRow = String(m.device_role || '').toUpperCase() === 'TEAM_LEADER';
    const isSelf = m.id === myId;
    const removable = isLeader && !isSelf && !isLeaderRow;
    return `
      <div class="member-row" data-id="${m.id}">
        <div class="member-row__avatar">${esc(initials)}</div>
        <div class="member-row__info">
          <p class="member-row__name">${esc(displayName)}</p>
          <p class="member-row__role ${roleClass}">${esc(m.role)}</p>
        </div>
        <span class="member-row__status">
          <span class="member-row__status-label${m.connected ? ' member-row__status-label--connected' : ''}">${m.connected ? 'Connected' : 'Not Connected'}</span>
          <span class="conn-dot conn-dot--${dotClass}"></span>
        </span>
        ${removable
          ? `<button class="member-row__remove" data-id="${m.id}" aria-label="Remove ${esc(m.name)}">
              <i class="fa-solid fa-xmark"></i>
            </button>`
          : ''}
      </div>`;
  }).join('');

  // Remove member buttons
  list.querySelectorAll('.member-row__remove').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const id = +btn.dataset.id;
      const m  = STATE.members.find(x => x.id === id);
      if (!m) return;
      e.preventDefault();
      removeMember(m);
    });
  });
}

async function removeMember(m) {
  if (!m) return;
  const confirmed = await openConfirm({
    title: 'Remove member?',
    subtitle: `"${m.name}"`,
    body: 'They will be disconnected from the host and removed from your team. You can add them back at any time.',
    confirmLabel: 'Remove',
  });
  if (!confirmed) return;
  setConfirmBusy(true, 'Removing member…');
  try {
    await TeamAPI.removeMember(m.id);
    STATE.members = STATE.members.filter(x => x.id !== m.id);
    renderTeamsTab();
    renderHeader();
    renderWaitingScreen();
    showToast(`${m.name} removed`);
  } catch (err) {
    showToast((err && err.message) || 'Could not remove member', 4000);
  } finally {
    closeConfirm();
  }
}

function renderRoles() {
  const isLeader = isTeamLeader();

  // Manghuhula select
  const sel = $('select-manghuhula');
  const currentMang = STATE.members.find(m => m.role === 'Manghuhula');
  sel.innerHTML = STATE.members.map(m =>
    `<option value="${m.id}"${m.id === currentMang?.id ? ' selected' : ''}>${esc(m.name)}</option>`
  ).join('');
  sel.disabled = !isLeader;

  // Tagasagot list
  const tagList = $('tagasagot-list');
  const tagasagot = STATE.members.filter(m => m.role === 'Tagasagot');
  tagList.innerHTML = tagasagot.length
    ? tagasagot.map(m => `
        <div class="tagasagot-row">
          <i class="fa-solid fa-check"></i>
          ${esc(m.name)}
        </div>`).join('')
    : `<p style="font-size:0.82rem;color:rgba(255,255,255,0.3)">No Tagasagot assigned yet.</p>`;

  // Roles are read-only for regular team members.
  const note = $('roles-readonly-note');
  if (note) note.hidden = isLeader;
  const saveRoles = $('btn-save-roles');
  if (saveRoles) saveRoles.hidden = !isLeader;
}

/* Save Roles */
$('btn-save-roles').addEventListener('click', async () => {
  const saveBtn = $('btn-save-roles');
  const mangId = +$('select-manghuhula').value;
  STATE.members.forEach(m => {
    m.role = m.id === mangId ? 'Manghuhula' : 'Tagasagot';
  });
  renderMemberList();
  renderRoles();

  const teamId = API.getTeamId();
  if (teamId && API.getSessionToken() && window.TeamAPI) {
    const roles = STATE.members.map(m => ({
      member_id: m.id,
      gameplay_role: m.role === 'Manghuhula' ? 'MANGHUHULA' : 'TAGASAGOT',
    }));
    const original = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving…';
    try {
      await API.withLoading('player-save-roles', () =>
        TeamAPI.assignMyTeamRoles(teamId, roles)
      );
      renderWaitingScreen();
      showToast('Roles saved');
    } catch (err) {
      console.error('[Player] save roles failed', err);
      showToast(err.message || 'Could not save roles');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = original;
    }
    return;
  }
  showToast('Roles saved');
});

/* ============================================================
   ADD MEMBER MODAL
============================================================ */
$('btn-add-member').addEventListener('click', () => openModal('modal-add-member'));
$('close-add-member').addEventListener('click',  () => closeModal('modal-add-member'));
$('cancel-add-member').addEventListener('click', () => closeModal('modal-add-member'));

$('form-add-member').addEventListener('submit', async e => {
  e.preventDefault();
  const nameIn = $('add-member-name');
  const errEl  = $('err-add-member');

  const capEl = $('member-cap');
  const maxMembers = settingsGet('max_members', 6);
  if (STATE.members.length >= maxMembers) {
    if (capEl) capEl.classList.add('member-cap--full');
    errEl.textContent = `Maximum of ${maxMembers} members reached.`;
    return;
  }
  if (capEl) capEl.classList.remove('member-cap--full');

  if (!nameIn.value.trim()) {
    nameIn.classList.add('error');
    errEl.textContent = 'Please enter a username.';
    return;
  }
  nameIn.classList.remove('error');
  errEl.textContent = '';

  const username = nameIn.value.trim();

  // Real backend integration when a team context exists.
  if (window.TeamAPI && API.getTeamId()) {
    const btn = $('form-add-member').querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Adding…';
    try {
      const m = await API.withLoading('player-add-member', () => TeamAPI.addMember(API.getTeamId(), username));
      if (!STATE.members.some(x => x.id === m.member_id)) {
        STATE.members.push({
          id:        m.member_id,
          name:      m.username || username,
          role:      m.gameplay_role === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot',
          connected: !!m.is_connected,
        });
      }
      closeModal('modal-add-member');
      $('form-add-member').reset();
      renderTeamsTab();
      renderHeader();
      showToast(`"${username}" added to the team`);
    } catch (err) {
      console.error('[Player] add member failed', err);
      nameIn.classList.add('error');
      errEl.textContent = err.message || 'Could not add the member.';
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  STATE.members.push({
    id:        STATE.nextMemberId++,
    name:      username,
    role:      'Tagasagot',
    connected: false,
  });

  closeModal('modal-add-member');
  $('form-add-member').reset();
  renderTeamsTab();
  renderHeader();
  showToast(`"${username}" added to the team`);
});

/* ============================================================
   QR & SCAN BUTTONS (teams tab)
   ============================================================ */
/* Real team QR (deep-link for joining this team). Falls back to the
   decorative grid when no session/session isn't a leader yet. */
function renderTeamQrArea() {
  const box  = $('team-qr-box');
  const hint = $('team-qr-hint');
  if (!box) return;
  if (STATE.teamQrDataUri) {
    box.innerHTML = `<img class="team-qr-img" src="${STATE.teamQrDataUri}" alt="Team QR code">`;
    box.classList.add('qr-box--image');
    if (hint) hint.textContent = 'Scan to join team';
  } else {
    renderQrGrid(box, STATE.teamCode);
    box.classList.remove('qr-box--image');
    if (hint) hint.textContent = STATE.teamCode
      ? 'Your team QR — sign in as team leader to unlock'
      : 'Join a game to get your team QR';
  }
}

async function loadTeamQr() {
  const teamId = API.getTeamId();
  if (!teamId || !API.getSessionToken()) {
    renderTeamQrArea();
    showToast('QR available after you are signed in');
    return;
  }
  try {
    const res = await TeamAPI.teamQr(teamId);
    if (res && res.qr_image) {
      STATE.teamQrDataUri = res.qr_image;
      renderTeamQrArea();
      showToast('Team QR ready');
    }
  } catch (err) {
    console.warn('[player] team QR load failed', err && err.message);
    renderTeamQrArea();
    showToast(err && err.message ? 'Please join the game first' : 'Team QR unavailable');
  }
}

$('btn-generate-qr').addEventListener('click', () => {
  loadTeamQr();
});

$('btn-scan-qr-teams').addEventListener('click', () => openQrScanner());
$('btn-header-qr').addEventListener('click',    () => openQrScanner());

$('btn-copy-settings-code').addEventListener('click', () => copyText(STATE.teamCode, 'Team Code'));

// Leader-only: request / re-request connection with the host.
$('btn-request-connection').addEventListener('click', async () => {
  const btn = $('btn-request-connection');
  if (btn) btn.disabled = true;
  try {
    const res = await API.withLoading('player-request-connection', () =>
      TeamAPI.requestConnection(API.getGameId(), STATE.connectionToken || undefined)
    );
    if (res && res.connection_status) setConnectionStatus(res.connection_status);
    renderTeamsTab();
    renderWaitingScreen();
    renderHeader();
    showToast('Connection requested — waiting for the host…');
  } catch (err) {
    console.error('[Player] connection request failed', err && err.message);
    showToast((err && err.message) || 'Could not request connection', 4000);
  } finally {
    if (btn) btn.disabled = false;
  }
});

const inputHostCode = $('input-host-code');
$('btn-connect-code').addEventListener('click', () => submitHostCodeInput());
if (inputHostCode) {
  inputHostCode.addEventListener('keydown', e => {
    if (e.key === 'Enter') submitHostCodeInput();
  });
}

/* ============================================================
   WORDS TAB — RENDER
============================================================ */
function renderWordsTab() {
  const submitted = STATE.words.filter(w => w.submitted).length;
  const cats      = categoriesTouched();
  const cap       = maxWordsPerCategory();

  // Overall progress: submitted words vs total cap across touched categories.
  const capTotal  = totalCategoryCap();
  const pct       = capTotal > 0 ? Math.round((submitted / capTotal) * 100) : 0;
  $('words-progress-bar').style.width = `${Math.min(100, pct)}%`;

  const readyCats = readyCategories().length;
  $('words-submitted-label').textContent = cats.length
    ? `${readyCats} / ${cats.length} categories Ready (${submitted} words)`
    : `${submitted} word${submitted === 1 ? '' : 's'} added`;

  // Per-category summary — "Ready" once a category reaches the configured cap.
  const summary = $('word-category-summary');
  if (summary) {
    summary.innerHTML = cats.length
      ? cats.map(cat => {
          const count = countForCategory(cat);
          const ready = count >= cap;
          const pctW  = Math.min(100, Math.round((count / cap) * 100));
          return `
            <div class="word-cat-row${ready ? ' word-cat-row--ready' : ''}" data-cat="${esc(cat)}">
              <span class="word-cat-row__name">${esc(cat)}</span>
              <span class="word-cat-row__bar"><span class="word-cat-row__fill" style="width:${pctW}%"></span></span>
              <span class="word-cat-row__count">${count} / ${cap}</span>
              <span class="word-cat-row__check">${ready ? '<i class="fa-solid fa-check"></i> Ready' : ''}</span>
            </div>`;
        }).join('')
      : `<p class="word-cat-row__empty">No words added yet. Add words to mark a category Ready.</p>`;
  }

  // Category badge — show most common category
  const catCounts = {};
  STATE.words.forEach(w => { catCounts[w.category] = (catCounts[w.category] || 0) + 1; });
  const topCat = Object.entries(catCounts).sort((a,b) => b[1]-a[1])[0]?.[0] || '—';
  $('words-category-badge').textContent = topCat;

  // Ready badge
  const badge    = $('words-ready-badge');
  const locked   = STATE.wordsLocked;
  const allReady = allCategoriesReady();
  const addBtn   = $('btn-add-word');

  if (locked) {
    badge.className = 'words-ready-badge words-ready-badge--locked';
    badge.innerHTML = '<i class="fa-solid fa-lock"></i> Locked';
    addBtn.disabled = true;
    $('words-locked-overlay').hidden = false;
  } else if (allReady) {
    badge.className = 'words-ready-badge words-ready-badge--ready';
    badge.innerHTML = '<i class="fa-solid fa-check"></i> Ready';
    addBtn.disabled = false;
    $('words-locked-overlay').hidden = true;
  } else {
    badge.className = 'words-ready-badge words-ready-badge--incomplete';
    const needed = Math.max(1, cats.length - readyCats);
    badge.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> ${needed} more category${needed === 1 ? '' : 'ies'} needed`;
    addBtn.disabled = false;
    $('words-locked-overlay').hidden = true;
  }

  // Word chips
  const chips = $('word-chips');
  chips.innerHTML = STATE.words.map(w => `
    <div class="word-chip" data-id="${w.id}">
      <i class="fa-solid fa-check"></i>
      <span>${esc(w.word)}</span>
      <span style="font-size:0.72rem;color:rgba(255,255,255,0.3);margin-left:0.25rem">${esc(w.category)}</span>
      ${!locked ? `<button class="word-chip__delete" data-id="${w.id}" aria-label="Delete ${esc(w.word)}">
        <i class="fa-solid fa-xmark"></i>
      </button>` : ''}
    </div>`).join('');

  // Delete word buttons
  chips.querySelectorAll('.word-chip__delete').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const id = +btn.dataset.id;
      const w  = STATE.words.find(x => x.id === id);
      if (!w) return;
      e.preventDefault();
      deleteWord(w);
    });
  });

  // Word status card
  const statusInfo = $('word-status-info');
  if (locked) {
    statusInfo.innerHTML = `
      <div class="word-status-row">
        <i class="fa-solid fa-lock" style="color:var(--primary-400)"></i>
        <strong>Words Locked</strong>
      </div>
      <p class="word-status-desc">Words are locked for the game. Contact the host to unlock.</p>`;
  } else {
    statusInfo.innerHTML = `
      <div class="word-status-row">
        <i class="fa-solid fa-lock-open" style="color:var(--secondary-400)"></i>
        <strong>Words Unlocked</strong>
      </div>
      <p class="word-status-desc">You can add, edit, or delete words until the host locks them.</p>`;
  }
}

// Delete a word server-side (as a team, not host) and only update the
// local state on success — the backend is the source of truth.
async function deleteWord(w) {
  if (!w) return;
  const confirmed = await openConfirm({
    title: 'Delete word?',
    subtitle: `"${w.word}"`,
    body: 'This word will be removed from your team pool for all future rounds. This cannot be undone.',
    confirmLabel: 'Delete',
  });
  if (!confirmed) return;
  setConfirmBusy(true, 'Deleting…');
  try {
    await WordAPI.deleteWord(w.id, { asHost: false });
    STATE.words = STATE.words.filter(x => x.id !== w.id);
    renderWordsTab();
    renderWaitingScreen();
    showToast(`"${w.word}" deleted`);
  } catch (err) {
    console.error('[Player] delete word failed', err);
    showToast((err && err.message) || 'Could not delete the word', 4000);
  } finally {
    closeConfirm();
  }
}

/* ============================================================
   ADD WORD MODAL
============================================================ */
$('btn-add-word').addEventListener('click', () => {
  if (STATE.wordsLocked) { showToast('Words are locked by the host.'); return; }
  $('form-add-word').reset();
  $('err-add-word').textContent    = '';
  $('err-add-word-cat').textContent = '';
  openModal('modal-add-word');
});
$('close-add-word').addEventListener('click',  () => closeModal('modal-add-word'));
$('cancel-add-word').addEventListener('click', () => closeModal('modal-add-word'));

$('form-add-word').addEventListener('submit', async e => {
  e.preventDefault();
  const wordIn = $('add-word-input');
  const catIn  = $('add-word-category');
  let valid    = true;

  if (!wordIn.value.trim()) {
    wordIn.classList.add('error');
    $('err-add-word').textContent = 'Please enter a word.';
    valid = false;
  } else { wordIn.classList.remove('error'); $('err-add-word').textContent = ''; }

  if (!catIn.value) {
    catIn.classList.add('error');
    $('err-add-word-cat').textContent = 'Please select a category.';
    valid = false;
  } else { catIn.classList.remove('error'); $('err-add-word-cat').textContent = ''; }

  if (!valid) return;

  const word     = wordIn.value.trim();
  const category = catIn.value;

  if (countForCategory(category) >= maxWordsPerCategory()) {
    wordIn.classList.add('error');
    $('err-add-word').textContent = `Maximum of ${maxWordsPerCategory()} words in "${category}" reached.`;
    return;
  }

  // Real backend integration when a player game context + session exists.
  if (window.WordAPI && API.getGameId() && API.getSessionToken()) {
    const btn = $('form-add-word').querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Submitting…';
    try {
      const categoryId = window.PLAYER_CATEGORY_TO_ID ? window.PLAYER_CATEGORY_TO_ID[category] : null;
      const created = await API.withLoading('player-add-word', () =>
        WordAPI.createWord(API.getGameId(), { categoryId, wordText: word, asHost: false })
      );
      if (!created.word_id) throw new Error('No word_id returned.');
      if (!STATE.words.some(w => w.id === created.word_id)) {
        STATE.words.push({ id: created.word_id, word: created.word_text, category: created.category_name || category, submitted: true });
      }
      closeModal('modal-add-word');
      renderWordsTab();
      showToast(`"${word}" added`);
    } catch (err) {
      console.error('[Player] add word failed', err);
      wordIn.classList.add('error');
      $('err-add-word').textContent = err.message || 'Could not add the word.';
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  STATE.words.push({ id: STATE.nextWordId++, word, category, submitted: true });
  closeModal('modal-add-word');
  renderWordsTab();
  showToast(`"${word}" added`);
});

/* ============================================================
   SETTINGS TAB — RENDER & SAVE
============================================================ */
function renderSettingsTab() {
  const isLeader = isTeamLeader();
  $('setting-team-name').value     = STATE.teamName;
  $('settings-team-code').textContent = STATE.teamCode;
  $('setting-username').value      = STATE.username;
  $('settings-round').textContent  = STATE.currentRound || '—';
  $('settings-status').textContent = {
    waiting:  'Waiting for Host',
    ready:    'Ready to Start',
    round1:   'Round 1 in Progress',
    round2:   'Round 2 in Progress',
    complete: 'Game Complete',
  }[STATE.gameStatus] || 'Waiting for Host';

  // Team name is leader-only; members can still edit their username.
  const nameInput = $('setting-team-name');
  const saveBtn   = $('btn-save-team-settings');
  if (nameInput) nameInput.disabled = !isLeader;
  if (saveBtn)   saveBtn.hidden     = !isLeader;
}

$('form-team-settings').addEventListener('submit', async e => {
  e.preventDefault();
  const name = $('setting-team-name').value.trim();
  if (!name) { showToast('Team name cannot be empty.'); return; }
  STATE.teamName = name;
  renderHeader();
  renderTeamsTab();
  renderSettingsTab();

  const teamId = API.getTeamId();
  if (teamId && API.getSessionToken() && window.TeamAPI) {
    try {
      await API.withLoading('player-update-team', () =>
        TeamAPI.updateTeamName(teamId, name)
      );
      API.setTeamName(name);
      showToast('Team settings saved');
    } catch (err) {
      console.error('[Player] update team name failed', err);
      showToast(err.message || 'Could not update the team name');
    }
    return;
  }
  showToast('Team settings saved');
});

$('form-player-settings').addEventListener('submit', async e => {
  e.preventDefault();
  const uname = $('setting-username').value.trim();
  if (!uname) { showToast('Username cannot be empty.'); return; }
  STATE.username = uname;
  showToast('Username updated');

  const memberId = API.getMemberId();
  if (memberId && API.getSessionToken() && window.TeamAPI) {
    try {
      await API.withLoading('player-update-username', () =>
        TeamAPI.updateUsername(memberId, uname)
      );
      API.setUsername(uname);
      showToast('Username updated');
    } catch (err) {
      console.error('[Player] update username failed', err);
      showToast(err.message || 'Could not update the username');
    }
    return;
  }
  showToast('Username updated');
});

$('btn-leave-game').addEventListener('click', async () => {
  const confirmed = await openConfirm({
    title: 'Leave the game?',
    subtitle: '',
    body: 'You will be disconnected from the host. You can rejoin anytime with your team code or the host’s QR.',
    confirmLabel: 'Leave Game',
  });
  if (!confirmed) return;
  setConfirmBusy(true, 'Leaving game…');
  const submit = () => {
    stopHeartbeat();
    STATE.isConnected   = false;
    STATE.hostConnected = false;
    STATE.gameStatus    = 'waiting';
    try { renderHeader(); renderTeamsTab(); renderSettingsTab(); renderWaitingScreen(); } catch (err) {}
    closeConfirm();
    showToast('Left the game');
  };
  if (window.DeviceAPI && API.getSessionToken()) {
    DeviceAPI.disconnect().catch(() => {}).finally(() => submit());
  } else {
    submit();
  }
});

/* ============================================================
   WAITING SCREEN — RENDER
============================================================ */
function renderWaitingScreen() {
  $('waiting-team-name').textContent = STATE.teamName;
  if ($('waiting-game-code')) $('waiting-game-code').textContent = STATE.gameCode || '—';

  // Member checklist (holds 2 always; done when at least 2 joined).
  const connected = STATE.members.filter(m => m.connected).length;
  $('waiting-connected').textContent = connected;
  $('waiting-total').textContent     = STATE.members.length;
  setCheckItem('waiting-members-check', STATE.members.length >= 2);

  // Categories Ready (host-configured max_words_per_category limit).
  const readyCats = readyCategories().length;
  const cats      = categoriesTouched().length;
  const maxWords  = settingsGet('max_words_per_category', 5);
  const catGoal   = maxWords > 0 ? cats * maxWords : cats;
  $('waiting-words').textContent = cats
    ? `${readyCats} / ${cats} categories Ready`
    : '0 / 0 Ready';
  setCheckItem('waiting-words-check', readyCats === cats && cats > 0);
  if ($('waiting-words-goal')) {
    $('waiting-words-goal').textContent = cats
      ? `${readyCats * maxWords} / ${catGoal} words`
      : `0 / 0 words (${maxWords} per category)`;
  }

  // Roles complete: at least one Manghuhula and one Tagasagot.
  const rolesOk = teamRolesComplete();
  setCheckItem('waiting-roles-check', rolesOk);
  const tagaCount = STATE.members.filter(m => m.role === 'Tagasagot').length;
  const mangCount = STATE.members.filter(m => m.role === 'Manghuhula').length;
  let rolesText = '';
  if (rolesOk) {
    rolesText = 'Roles assigned';
  } else if (STATE.members.length === 0) {
    rolesText = 'No members yet — add at least 2';
  } else {
    const need = [];
    if (mangCount < 1) need.push('1 Manghuhula');
    if (tagaCount < 1) need.push('1 Tagasagot');
    rolesText = `Assign ${need.join(' and ')} (${mangCount} Manghuhula · ${tagaCount} Tagasagot now)`;
  }
  if ($('waiting-roles-state')) $('waiting-roles-state').textContent = rolesText;

  // Host connected + game lifecycle check.
  const hostCheck = $('waiting-host-check');
  if (hostCheck) {
    const hostOk = STATE.connectionStatus === 'CONNECTED';
    setCheckItem('waiting-host-check', hostOk);
    const hostDot = $('waiting-host-dot');
    if (hostDot) hostDot.className = 'conn-dot conn-dot--' + (hostOk ? 'connected' : 'disconnected');
  }

  // Game state line.
  if ($('waiting-game-state')) {
    $('waiting-game-state').textContent = {
      waiting:   'Waiting for the host to start',
      ready:     'Game is ready to start',
      round1:    'Round 1 is live',
      round2:    'Round 2 is live',
      complete:  'Game is complete — ask the host to play again',
    }[STATE.gameStatus] || 'Preparing…';
  }

  // Spinner caption.
  const readyForGame =
    connected === STATE.members.length && STATE.members.length > 0 &&
    rolesOk && readyCats === cats && cats > 0 &&
    STATE.gameStatus !== 'complete';
  if ($('waiting-spinner-text')) {
    $('waiting-spinner-text').textContent = readyForGame
      ? 'Ready when the host starts the round'
      : 'Your team is getting ready';
  }
}

function setCheckItem(id, ok) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('waiting-check--ready', ok);
  el.classList.toggle('waiting-check--pending', !ok);
  el.dataset.must = ok ? '' : 'true';
}

// Roles are ready when at least one Manghuhula and one Tagasagot exist.
function teamRolesComplete() {
  const mang = STATE.members.filter(m => m.role === 'Manghuhula').length;
  const taga = STATE.members.filter(m => m.role === 'Tagasagot').length;
  return mang >= 1 && taga >= 1;
}

/* ============================================================
   GAME TIMER (Tagasagot view)
============================================================ */
function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2,'0')}`;
}

function updateGameTimerDisplay() {
  const el = $('game-timer-digits');
  el.textContent = formatTime(STATE.timeRemaining);
  el.classList.remove('running','warning','critical');
  if (STATE.timerRunning) {
    if      (STATE.timeRemaining <= 10) el.classList.add('critical');
    else if (STATE.timeRemaining <= 20) el.classList.add('warning');
    else                                el.classList.add('running');
  }
}

function startGameTimer() {
  if (STATE.timerRunning) return;
  STATE.timerRunning = true;
  STATE.timerInterval = setInterval(() => {
    STATE.timeRemaining = Math.max(0, STATE.timeRemaining - 1);
    updateGameTimerDisplay();
    if (STATE.timeRemaining === 0) {
      clearInterval(STATE.timerInterval);
      STATE.timerRunning = false;
      showToast("Time's up!");
    }
  }, 1000);
  updateGameTimerDisplay();
}

function pauseGameTimer() {
  STATE.timerRunning = false;
  clearInterval(STATE.timerInterval);
  $('game-timer-digits').classList.remove('running','warning','critical');
}

function renderTagasagotView() {
  $('game-round-label').textContent  = `Round ${STATE.currentRound}`;
  $('game-score').textContent        = STATE.score;
  $('game-team-name').textContent    = STATE.teamName;
  updateGameTimerDisplay();
  updateGameProgress();
}

function updateGameProgress() {
  const pct   = STATE.totalWords > 0 ? Math.round((STATE.wordsGuessed / STATE.totalWords) * 100) : 0;
  $('game-progress-bar').style.width  = `${pct}%`;
  $('game-progress-label').textContent = `${STATE.wordsGuessed} / ${STATE.totalWords} Words`;
  $('game-progress-pct').textContent  = `${pct}%`;
}

/* Answer buttons */
function flashBtn(btn) {
  btn.classList.remove('flash');
  void btn.offsetWidth; // reflow
  btn.classList.add('flash');
  btn.addEventListener('animationend', () => btn.classList.remove('flash'), { once: true });
}

$('btn-ans-oo').addEventListener('click', e => {
  flashBtn(e.currentTarget);
  showToast('Oo!');
  console.log('[Player] Answer: Oo');
});

$('btn-ans-hindi').addEventListener('click', e => {
  flashBtn(e.currentTarget);
  showToast('Hindi!');
  console.log('[Player] Answer: Hindi');
});

$('btn-ans-pwede').addEventListener('click', e => {
  flashBtn(e.currentTarget);
  showToast('Pwede!');
  console.log('[Player] Answer: Pwede');
});

/* ============================================================
   COUNTDOWN
============================================================ */
function startCountdown(round = 1, onComplete = null) {
  STATE.currentRound = round;
  $('countdown-round-label').textContent = `Round ${round}`;

  let count = 3;
  const numEl = $('countdown-number');

  // Restart animation for first number
  numEl.style.animation = 'none';
  void numEl.offsetWidth;
  numEl.style.animation = '';
  numEl.textContent = count;

  openFullscreen('view-countdown');

  STATE.countdownInterval = setInterval(() => {
    count--;
    if (count > 0) {
      numEl.style.animation = 'none';
      void numEl.offsetWidth;
      numEl.style.animation = 'countPop 0.5s cubic-bezier(0.34,1.56,0.64,1) both';
      numEl.textContent = count;
    } else {
      clearInterval(STATE.countdownInterval);
      numEl.style.animation = 'none';
      void numEl.offsetWidth;
      numEl.style.animation = 'countPop 0.5s cubic-bezier(0.34,1.56,0.64,1) both';
      numEl.textContent = 'GO!';

      setTimeout(() => {
        closeFullscreen();
        if (onComplete) onComplete();
      }, 800);
    }
  }, 900);
}

/* ============================================================
   QR SCANNER
============================================================ */
function openQrScanner() {
  openFullscreen('view-qr-scanner');
  startCamera();
}

function closeQrScanner() {
  stopCamera();
  closeFullscreen();
}

async function startCamera() {
  const video    = $('qr-video');
  const errorBox = $('qr-error-state');
  const errorMsg = $('qr-error-msg');
  errorBox.hidden = true;

  if (!navigator.mediaDevices?.getUserMedia) {
    errorMsg.textContent = 'Your browser does not support camera access.';
    errorBox.hidden = false;
    return;
  }

  try {
    STATE.cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    });
    video.srcObject = STATE.cameraStream;
    await video.play();
    window.QrScanner.start({ video, onScan: handlePlayerQrScanned });
  } catch (err) {
    const msgs = {
      NotAllowedError:        'Camera access was denied. Please allow camera permission and try again.',
      PermissionDeniedError:  'Camera access was denied.',
      NotFoundError:          'No camera found on this device.',
      DevicesNotFoundError:   'No camera found on this device.',
      NotReadableError:       'Camera is in use by another app.',
      TrackStartError:        'Camera is in use by another app.',
    };
    errorMsg.textContent = msgs[err.name] || `Camera error: ${err.message}`;
    errorBox.hidden = false;
  }
}

function stopCamera() {
  if (window.QrScanner) window.QrScanner.stop();
  if (STATE.cameraStream) {
    STATE.cameraStream.getTracks().forEach(t => t.stop());
    STATE.cameraStream = null;
  }
  const video = $('qr-video');
  if (video) video.srcObject = null;
}

/* ============================================================
   HOST-CONNECTION FLOW
   ------------------------------------------------------------
   All entry points funnel into connectToHostWithCode(report):
     - handlePlayerQrScanned  (live QR scanner)
     - form-enter-code submit (manual code modal)
     - input-host-code        (inline card entry)
   Steps:
     1) resolve/normalize the scanned/typed code / join URL
     2) verify the game exists through the public by-code endpoint
     3) if switching games, re-join the new game (fixes stale game_id)
     4) request host approval for the (current) game
============================================================ */

function setHostConnectFeedback(msg, kind) {
  const el = $('host-connect-feedback');
  if (!el) return;
  el.textContent = msg || '';
  el.className = 'conn-hint'
    + (kind === 'error' ? ' conn-hint--error'
       : kind === 'ok'   ? ' conn-hint--ok'
       : '');
}

function setHostConnectBusy(busy) {
  const input = $('input-host-code');
  const btn = $('btn-connect-code');
  if (input) input.disabled = busy;
  if (btn) {
    btn.disabled = busy;
    btn.innerHTML = busy
      ? '<i class="fa-solid fa-spinner fa-spin"></i><span>Connecting…</span>'
      : '<i class="fa-solid fa-link"></i><span>Connect</span>';
  }
}

function submitHostCodeInput() {
  const input = $('input-host-code');
  const raw = input ? input.value.trim() : '';
  if (!raw) {
    setHostConnectFeedback('Enter a host code to connect.', 'error');
    if (input) input.focus();
    return;
  }
  connectToHostWithCode(raw, { source: 'inline' });
}

/* A detected frame: the host QR embeds the game code. Requesting
   connection is a real backend call; the host approves it. */
function handlePlayerQrScanned(raw) {
  const parsed = Connect.parseJoinUrl(raw);
  if (!parsed || !parsed.gameCode) {
    showToast('That is not a Pinoy Henyo QR code.');
    return;
  }
  connectToHostWithCode(raw, { source: 'scanner', teamCode: parsed.teamCode });
}

/* Resolve a scanned or typed host code to its game, then connect. */
async function connectToHostWithCode(raw, { source = 'inline', teamCode: preferTeamCode = null } = {}) {
  if (source === 'scanner') closeQrScanner();
  if (source === 'modal')   closeModal('modal-enter-code');

  const report = source === 'inline'
    ? setHostConnectFeedback
    : (msg) => showToast(msg);
  const parsed = Connect.parseJoinUrl(raw);
  const gameCode = (parsed && parsed.gameCode)
    ? parsed.gameCode
    : String(raw).trim().toUpperCase().replace(/^PH/i, 'PH');

  if (!gameCode) {
    report('Enter a host code to connect.', 'error');
    return;
  }

  setHostConnectBusy(true);
  if (source === 'inline') setHostConnectFeedback('Checking host code…', 'ok');

  try {
    // 1) The game must exist and still accept connection requests.
    let game;
    try {
      game = await GameAPI.getByCode(gameCode);
    } catch (err) {
      if (err && err.status === 404) {
        report(`No active game found for code "${gameCode}".`, 'error');
      } else {
        report('Could not check the host code. ' + (err.message || 'Try again.'), 'error');
      }
      return;
    }
    if (!game || !game.game_id) {
      report(`No active game found for code "${gameCode}".`, 'error');
      return;
    }
    // Terminal games no longer accept connection requests. (The backend also
    // enforces this via GAME_ENDED; the pre-check keeps the error friendly.)
    if (String(game.status).toUpperCase() === 'GAME_COMPLETE' ||
        String(game.status).toUpperCase() === 'CANCELLED' ||
        String(game.status).toUpperCase() === 'EXPIRED' ||
        String(game.status).toUpperCase() === 'ENDED') {
      report('That game has ended already.', 'error');
      return;
    }

    const gameId = game.game_id;
    const currentGameId = API.getGameId();
    const teamId = API.getTeamId();

    // 2) Same game the team is already bound to — request approval.
    if (currentGameId && String(currentGameId) === String(gameId)) {
      API.setGameCode(game.game_code || gameCode);
      STATE.gameCode = game.game_code || gameCode;
      await sendConnectionRequest(gameId, report);
      return;
    }

    // 3) Different game: the stored team/game_id is stale (the backend scopes
    //    sessions + connection requests to each game). Re-join the new game
    //    exactly like the landing page, reconnect the device session, refresh
    //    the team context, then ask the new host for approval.
    if (!teamId || !API.getSessionToken()) {
      report('Join a game first before connecting to a host.', 'error');
      return;
    }
    await switchTeamToGame(game, report, preferTeamCode);
  } finally {
    setHostConnectBusy(false);
  }
}

/* Full host-switch: move this team into `game` and reconnect the device. */
async function switchTeamToGame(game, report, preferTeamCode) {
  const gameId = game.game_id;
  const username = STATE.username || API.getUsername() || 'Player';
  const teamName = STATE.teamName || API.getTeamName() || null;
  const teamCode = preferTeamCode || STATE.teamCode || API.getTeamCode() || null;

  report('Switching this team to the new host…', 'ok');

  let joined;
  try {
    // Re-join an existing team in the new game when the code matches,
    // otherwise create a fresh team there (mirrors the landing page).
    joined = await TeamAPI.joinGame(gameId, username, null, teamCode);
  } catch (err) {
    if (err && err.code === 'TEAM_CODE_INVALID' && teamName) {
      try {
        joined = await TeamAPI.joinGame(gameId, username, teamName, null);
      } catch (err2) {
        if (err2 && err2.code === 'GAME_ENDED') {
          report('That game has ended and is no longer accepting connections.', 'error');
        } else {
          report((err2 && err2.message) || 'Could not join the new host.', 'error');
        }
        console.warn('[player] host switch create failed', err2);
        return;
      }
    } else if (err && err.status === 404) {
      report('The host has ended that game or it no longer exists.', 'error');
      return;
    } else if (err && err.code === 'GAME_ENDED') {
      report('That game has ended and is no longer accepting connections.', 'error');
      return;
    } else if (err && err.code === 'RATE_LIMITED') {
      const wait = (err.retryAfter > 0) ? ` in ${err.retryAfter}s` : '';
      report(`Too many attempts. Please wait${wait} and try again.`, 'error');
      return;
    } else {
      report((err && err.message) || 'Could not switch to the new host.', 'error');
      console.warn('[player] host switch join failed', err);
      return;
    }
  }

  try {
    API.setGameId(gameId);
    API.setGameCode(game.game_code || API.getGameCode());
    STATE.gameCode = game.game_code || API.getGameCode();

    // Bind the device session to the new game/team.
    const connectionToken = joined.connection_token
      || (joined.leader && joined.leader.connection_token)
      || null;
    if (connectionToken) await DeviceAPI.connect({ connectionToken });

    // Refresh the team context from the new session-backed roster.
    const newTeamId = API.getTeamId();
    const teamData = newTeamId ? await TeamAPI.getMyTeam(newTeamId).catch(() => null) : null;
    if (teamData) {
      applyTeamRoster(teamData);
      if (teamData.team_name) API.setTeamName(teamData.team_name);
      if (teamData.team_code) API.setTeamCode(teamData.team_code);
      if (API.getDeviceRole() === 'TEAM_LEADER') loadTeamQr();
    }
  } catch (err) {
    console.warn('[player] host switch device rebind failed', err);
    report((err && err.message) || 'Could not finish switching hosts.', 'error');
    return;
  }

  // Creating a new team is not approval to join the host screen — request it.
  if (joined.leader) {
    try {
      await sendConnectionRequest(gameId, report);
    } catch (err) {
      console.warn('[player] host switch connection request failed', err);
    }
  }

  // Reload so the realtime socket + all tabs rebind to the new game context.
  window.location.reload();
}

/* Ask the host to approve this team. Server-authoritative state is
   applied from the response / realtime events. */
async function sendConnectionRequest(gameId, report) {
  const resolvedGameId = gameId || API.getGameId();
  const teamId = API.getTeamId();
  const feedback = report || setHostConnectFeedback;
  if (!resolvedGameId || !teamId) {
    feedback('Join a game first before connecting to the host.', 'error');
    return;
  }
  try {
    await API.withLoading('player-conn-req', () =>
      TeamAPI.requestConnection(resolvedGameId, STATE.connectionToken || undefined)
    );
    setConnectionStatus('CONNECTION_REQUESTED');
    feedback('Request sent — waiting for the host to approve this team.', 'ok');
    showToast('Request sent — waiting for host approval');
  } catch (err) {
    if (err.code === 'ALREADY_CONNECTED') {
      setConnectionStatus('CONNECTED');
      feedback('This team is already connected to the host.', 'ok');
      showToast('Your team is already connected to the host');
    } else if (err.code === 'REQUEST_PENDING') {
      setConnectionStatus('CONNECTION_REQUESTED');
      feedback('This team already has a pending request — the host will approve it soon.', 'ok');
      showToast('Request is already pending — the host will approve it soon');
    } else if (err.code === 'NOT_TEAM_LEADER') {
      feedback('Only the team leader can request connection.', 'error');
      showToast('Only the team leader can request connection');
    } else if (err.code === 'GAME_ENDED') {
      feedback('That game has ended and is no longer accepting connections.', 'error');
      showToast('That game has ended and is no longer accepting connections');
    } else {
      console.warn('[player] connection request failed', err);
      feedback(err.message || 'Could not send the connection request.', 'error');
      showToast(err.message || 'Could not send the connection request.');
    }
  }
}

$('btn-qr-back').addEventListener('click', closeQrScanner);
$('btn-retry-cam').addEventListener('click', () => {
  $('qr-error-state').hidden = true;
  startCamera();
});

$('btn-enter-code-instead').addEventListener('click', () => {
  closeQrScanner();
  $('form-enter-code').reset();
  $('err-game-code').textContent = '';
  openModal('modal-enter-code');
});

/* ============================================================
   ENTER CODE MODAL
============================================================ */
$('close-enter-code').addEventListener('click',  () => closeModal('modal-enter-code'));
$('cancel-enter-code').addEventListener('click', () => closeModal('modal-enter-code'));

$('form-enter-code').addEventListener('submit', e => {
  e.preventDefault();
  const codeIn = $('input-game-code');
  const errEl  = $('err-game-code');

  if (!codeIn.value.trim()) {
    codeIn.classList.add('error');
    errEl.textContent = 'Please enter a game code or scan a join link.';
    return;
  }
  codeIn.classList.remove('error');
  errEl.textContent = '';

  // The full resolve/verify/switch flow lives in connectToHostWithCode.
  const parsed = Connect.parseJoinUrl(codeIn.value.trim());
  connectToHostWithCode(codeIn.value.trim(), {
    source: 'modal',
    teamCode: parsed ? parsed.teamCode : null,
  });
  codeIn.value = '';
});

/* ============================================================
   CONNECTION SUCCESS
============================================================ */
function showConnSuccess() {
  openFullscreen('view-conn-success');
}

$('btn-back-to-team').addEventListener('click', () => {
  closeFullscreen();
  switchTab('teams');
  renderHeader();
  renderTeamsTab();
  showToast('Connected to host!');
});

/* ============================================================
   COPY BUTTONS — delegate
============================================================ */
document.addEventListener('click', e => {
  const btn = e.target.closest('#btn-copy-team-code');
  if (btn) copyText(STATE.teamCode, 'Team Code');
});

document.addEventListener('click', e => {
  const btn = e.target.closest('#btn-copy-settings-code');
  if (btn) copyText(STATE.teamCode, 'Team Code');
});

document.addEventListener('click', e => {
  const btn = e.target.closest('#btn-copy-team-code-meta');
  if (btn) copyText(STATE.teamCode, 'Team Code');
});

document.addEventListener('click', e => {
  const btn = e.target.closest('#btn-copy-game-code');
  if (btn) copyText(STATE.gameCode, 'Game Code');
});

/* ============================================================
   SERVER SYNC — single refresh point
   ------------------------------------------------------------
   The player page is a representation of server state. Every
   manual refresh, heartbeat, or focus/visibility sync flows
   through refreshAllData() so the UI can never drift from what
   the backend actually holds.
   ============================================================ */
async function safeHeartbeat() {
  if (!API.getSessionToken()) return null;
  try {
    return await DeviceAPI.heartbeat();
  } catch (err) {
    if (err && (err.status === 401 || err.status === 403)) onSessionExpired();
    return null;
  }
}

function startHeartbeat() {
  stopHeartbeat();
  if (!API.getSessionToken() || !API.getGameId()) return;
  const beat = async () => {
    if (!API.getSessionToken() || !API.getGameId()) { stopHeartbeat(); return; }
    if (STATE.gameStatus === 'complete') { stopHeartbeat(); return; }
    if (STATE.fullscreenView === 'tagasagot') return; // gameplay: keep socket-driven state
    await safeHeartbeat();
  };
  beat();
  heartbeatTimer = setInterval(beat, 25000);
}

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
}

// Device session no longer valid server-side: clear it and prompt rejoin.
function onSessionExpired() {
  stopHeartbeat();
  API.clearTokens();
  setConnectionStatus('NOT_CONNECTED');
  Connect.showReconnectBanner({
    title: 'Session expired',
    message: 'Your connection could not be restored. Please rejoin with the QR or game code.',
  });
  document.body.setAttribute('data-reconnect-target', '../../index.html');
}

// The game is gone: stop everything and prompt a fresh join.
function onGameGone() {
  stopHeartbeat();
  API.clearTokens();
  Connect.showReconnectBanner({
    title: 'Game not found',
    message: 'This game has ended or no longer exists. Return to the lobby to join a new one.',
  });
  document.body.setAttribute('data-reconnect-target', '../../index.html');
}

// Server categories -> submission dropdown (shared by bootstrap + refresh).
async function hydrateCategories(gameId) {
  if (!gameId) return;
  try {
    const catData = await WordAPI.listCategories(gameId);
    const cats = (catData.categories || []).map(c => ({ id: c.category_id, name: c.name })).filter(c => c.name);
    window.PLAYER_CATEGORY_TO_ID = {};
    cats.forEach(c => { window.PLAYER_CATEGORY_TO_ID[c.name] = c.id; });
    if (cats.length) {
      CATEGORIES.length = 0;
      cats.forEach(c => CATEGORIES.push(c.name));
      const sel = $('add-word-category');
      if (sel) {
        sel.innerHTML = '<option value="">Select Category</option>';
        CATEGORIES.forEach(c => { sel.innerHTML += `<option value="${esc(c)}">${esc(c)}</option>`; });
      }
    }
  } catch (e) { console.warn('[player] categories offline', e && e.message); }
}

const REFRESH_TABS = ['renderHeader', 'renderTeamsTab', 'renderWordsTab', 'renderSettingsTab', 'renderWaitingScreen'];

function renderAll() {
  REFRESH_TABS.forEach(fn => { try { window[fn] && window[fn](); } catch (e) {} });
}

// Heartbeat once, then re-read status/settings/categories/roster/words
// from the server and re-render every tab.
async function refreshAllData({ silent = false } = {}) {
  if (refreshInProgress) return;
  refreshInProgress = true;
  try {
    if (API.getSessionToken()) await safeHeartbeat();
    const gameId = API.getGameId();
    const teamId = API.getTeamId();
    if (gameId) {
      try {
        const game = await GameAPI.status(gameId);
        if (!STATE.gameCode && game.game_code) STATE.gameCode = game.game_code;
        if (API.getGameCode()) STATE.gameCode = API.getGameCode();
        if (game.status) STATE.gameStatus = mapGameStatus(game.status);
        if (typeof game.word_pool_locked === 'boolean') STATE.wordsLocked = game.word_pool_locked;
      } catch (e) {
        if (e && e.status === 404) { onGameGone(); return; }
        console.warn('[player] refresh status offline', e && e.message);
      }
      try {
        const s = await GameAPI.getSettings(gameId);
        if (s) applySettings(s);
      } catch (e) { console.warn('[player] refresh settings offline', e && e.message); }
    }
    await hydrateCategories(gameId);
    if (gameId && teamId && API.getSessionToken()) {
      try {
        const [teamData, wordsData] = await Promise.all([
          TeamAPI.getMyTeam(teamId).catch(err => {
            if (err && (err.status === 401 || err.status === 403)) { onSessionExpired(); return null; }
            return null;
          }),
          WordAPI.listMyWords(gameId).catch(() => null),
        ]);
        if (teamData) {
          applyTeamRoster(teamData);
          if (teamData.team_name) API.setTeamName(teamData.team_name);
          if (teamData.team_code) API.setTeamCode(teamData.team_code);
        }
        if (wordsData && wordsData.words) applyMyWords(wordsData.words);
      } catch (e) { console.warn('[player] refresh team/words failed', e && e.message); }
    }
    renderAll();
    if (!silent) showToast('Synced');
  } finally {
    refreshInProgress = false;
    lastAutoSyncAt = Date.now();
  }
}

// Throttled background sync when the tab regains focus.
function autoSync() {
  if (refreshInProgress) return;
  if (Date.now() - lastAutoSyncAt < 5000) return;
  if (!API.getSessionToken()) return;
  if (STATE.fullscreenView) return;
  refreshAllData({ silent: true });
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') { safeHeartbeat(); autoSync(); }
});
window.addEventListener('focus', () => { safeHeartbeat(); autoSync(); });
window.addEventListener('pageshow', e => {
  if (e.persisted) autoSync();
});
window.addEventListener('pagehide', () => stopHeartbeat());

/* ============================================================
   PULL-TO-REFRESH (touch) — triggers a full server re-sync.
   ============================================================ */
(function initPullToRefresh() {
  const scroller = $('app-content');
  const indicator = $('pull-refresh');
  if (!scroller || !indicator || !('ontouchstart' in window)) return;
  const textEl = $('pull-refresh-text');
  const THRESHOLD = 64;
  let startY = null, pulling = false, currentY = 0;

  function resetPull() {
    indicator.style.transform = '';
    indicator.classList.remove('pull-refresh--armed', 'pull-refresh--refreshing');
    if (textEl) textEl.textContent = 'Pull to refresh';
    pulling = false;
    currentY = 0;
  }

  scroller.addEventListener('touchstart', e => {
    if (scroller.scrollTop > 0) return;
    if (e.target.closest('input, select, textarea, button')) return;
    if (STATE.fullscreenView || refreshInProgress) return;
    startY = e.touches[0].clientY;
    pulling = false;
    currentY = 0;
  }, { passive: true });

  scroller.addEventListener('touchmove', e => {
    if (startY === null) return;
    if (scroller.scrollTop > 0) { resetPull(); startY = null; return; }
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0) { resetPull(); startY = null; return; }
    e.preventDefault();
    pulling = true;
    currentY = Math.min(dy, 110);
    indicator.style.transform = `translateY(${currentY}px)`;
    const armed = currentY >= THRESHOLD;
    indicator.classList.toggle('pull-refresh--armed', armed);
    if (textEl) textEl.textContent = armed ? 'Release to refresh' : 'Pull to refresh';
  }, { passive: false });

  scroller.addEventListener('touchend', () => {
    if (startY === null) return;
    if (pulling && currentY >= THRESHOLD) {
      indicator.classList.add('pull-refresh--refreshing');
      indicator.classList.remove('pull-refresh--armed');
      if (textEl) textEl.textContent = 'Syncing…';
      refreshAllData({ silent: true }).finally(() => {
        resetPull();
      });
    } else {
      resetPull();
    }
    startY = null;
  });
})();

/* ============================================================
   INIT
============================================================ */
function init() {
  renderHeader();
  renderTeamsTab();
  renderWordsTab();
  renderSettingsTab();
  renderWaitingScreen();

  // Set initial tab
  switchTab('teams');

  // Populate category select in word modal
  const catSel = $('add-word-category');
  catSel.innerHTML = '<option value="">Select Category</option>';
  CATEGORIES.forEach(c => {
    catSel.innerHTML += `<option value="${esc(c)}">${esc(c)}</option>`;
  });
}

init();

/* ============================================================
   BACKEND INTEGRATION (player page)
   When a game/team/session context exists, load real categories
   so players can submit words, and reflect real team data.
   ============================================================ */
(async function bootstrapPlayerIntegration() {
  // Reconnect guard: if we have a stored device session, restore it.
  try {
    const rc = await Connect.restorePlayerSession();
    if (rc.status === 'invalid') {
      Connect.showReconnectBanner({
        title: 'Session expired',
        message: 'Your connection could not be restored. Please rejoin with the QR or game code.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
    } else if (rc.status === 'connected' && rc.data) {
      if (rc.data.game_id) API.setGameId(rc.data.game_id);
      if (rc.data.team_id) API.setTeamId(rc.data.team_id);
      if (rc.data.member_id) API.setMemberId(rc.data.member_id);
    }
  } catch (e) { /* ignore */ }

  const gameId = API.getGameId();
  const teamId = API.getTeamId();

  if (gameId) {
    try {
      const game = await GameAPI.status(gameId);
      if (API.getGameCode()) STATE.gameCode = API.getGameCode();
      else if (game.game_code) STATE.gameCode = game.game_code;
      if (game.status) STATE.gameStatus = mapGameStatus(game.status);
      // Reflect the server's word-pool lock so the player's Add Word UI
      // (and "Locked" banner) matches the backend's WORD_LOCKED behavior.
      if (typeof game.word_pool_locked === 'boolean') {
        STATE.wordsLocked = game.word_pool_locked;
      }
    } catch (e) {
      console.warn('[player] status offline', e && e.message);
      // Game no longer exists on the server — clear stale session and send
      // the player back to the landing page with a reconnect prompt.
      if (e && e.status === 404) {
        onGameGone();
        return; // stop further bootstrap work — no valid game context
      }
    }
    // Server-backed settings: display toggles + per-category word cap.
    try {
      const settingsRes = await GameAPI.getSettings(gameId);
      if (settingsRes) applySettings(settingsRes);
    } catch (e) {
      console.warn('[player] settings offline', e && e.message);
    }
  }

  // Load real categories for the word-submission dropdown.
  try { await hydrateCategories(gameId); } catch (e) { console.warn('[player] categories offline', e && e.message); }

  // Load the player's real team roster + submitted words (session-backed).
  if (gameId && teamId && API.getSessionToken()) {
    try {
      const [teamData, wordsData] = await Promise.all([
        TeamAPI.getMyTeam(teamId).catch(() => null),
        WordAPI.listMyWords(gameId).catch(() => null),
      ]);
      if (teamData) {
        applyTeamRoster(teamData);
        if (teamData.team_name) API.setTeamName(teamData.team_name);
        if (teamData.team_code) API.setTeamCode(teamData.team_code);
        if (API.getDeviceRole() === 'TEAM_LEADER') loadTeamQr();
      }
      if (wordsData && wordsData.words) applyMyWords(wordsData.words);
    } catch (e) {
      console.warn('[player] team/words load failed', e && e.message);
    }
  }

  window.PINOY_PLAYER_READY = true;

  // Keep the device session alive while the page is open. Without a
  // heartbeat the backend sweeps the device session after 60s idle,
  // which would silently break the player's session-backed calls.
  if (gameId && API.getSessionToken()) startHeartbeat();
  try { renderHeader(); renderTeamsTab(); renderWordsTab(); renderSettingsTab(); renderWaitingScreen(); } catch (e) {}
})();

/* ============================================================
   REALTIME (player page)
   ------------------------------------------------------------
   Connects as a DEVICE SESSION (auth: session token + device_id).
   Mirrors backend Socket.IO events onto STATE and the existing
   render helpers. SECURITY: only ever displays a current word when
   the payload is the Manghuhula-room secret (current_word_text is
   non-null); the public turn payload has current_word_text = null
   and is used only for timer/progress/status, never word text.
   ============================================================ */
(function realtimePlayer() {
  const rt = window.Realtime;
  if (!rt) return;
  const token = API.getSessionToken();
  if (!token) return; // no device session

  const myTeamId = API.getTeamId();
  let knownTurnId = null;
  let tickTimer = null;

  function gameIdMatches(p) { return p && p.game_id ? String(p.game_id) === String(API.getGameId()) : (myTeamId != null); }
  function forMyTeam(p) {
    if (p && p.team_id != null) return String(p.team_id) === String(myTeamId);
    if (p && p.member && p.member.team_id != null) return String(p.member.team_id) === String(myTeamId);
    return myTeamId == null; // no team context -> accept
  }

  function roundLabel(roundNumber) {
    return Number(roundNumber) >= 2 ? 'round2' : 'round1';
  }
  function roleName(role) {
    return String(role || '').toUpperCase() === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot';
  }

  /* ---------- server-authoritative timer mirror ---------- */
  function applyTimer(p) {
    if (!p) return;
    if (typeof p.remaining_seconds === 'number') STATE.timeRemaining = p.remaining_seconds;
    if (typeof p.status === 'string') {
      STATE.timerRunning = (p.status === 'ACTIVE');
      syncTimerTicker();
    }
    try { updateGameTimerDisplay(); } catch (e) {}
  }
  function syncTimerTicker() {
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    if (STATE.timerRunning) {
      tickTimer = setInterval(() => {
        STATE.timeRemaining = Math.max(0, STATE.timeRemaining - 1);
        try { updateGameTimerDisplay(); } catch (e) {}
      }, 1000);
    }
  }
  function stopTimerTicker() {
    STATE.timerRunning = false;
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    try { updateGameTimerDisplay(); } catch (e) {}
  }

  /* ---------- roster presence mirror ---------- */
  function memberId(x) { return x && (x.member_id != null ? x.member_id : x.id); }
  function upsertMember(m) {
    if (!m || m.member_id == null) return;
    let existing = STATE.members.find(x => memberId(x) === m.member_id);
    if (!existing) {
      existing = { id: m.member_id, name: '', role: 'Tagasagot', connected: false };
      STATE.members.push(existing);
    }
    if (m.username) existing.name = m.username;
    if (m.gameplay_role) existing.role = roleName(m.gameplay_role);
    existing.connected = !!m.is_connected;
    return existing;
  }

  /* ---------- event handlers ---------- */
  // Turn started: update round/status/timer/progress; secret word only to Manghuhula.
  rt.on('turn_started', (p) => {
    if (!forMyTeam(p)) return;
    const roundNo = p.round_number || STATE.currentRound;
    STATE.currentRound = Number(roundNo) || 1;
    if (gameIdMatches(p)) STATE.gameStatus = roundLabel(roundNo);
    if (typeof p.total_words === 'number') STATE.totalWords = Math.max(1, p.total_words);
    if (typeof p.correct_words === 'number') STATE.wordsGuessed = p.correct_words;
    if (p.turn_id != null) knownTurnId = p.turn_id;
    applyTimer(p);
    try { renderWaitingScreen(); renderTagasagotView(); } catch (e) {}
    // Secret (Manghuhula room) payload: current_word_text is only present there.
    if (p.current_word_text && API.getGameplayRole() === 'MANGHUHULA') {
      STATE.currentSecretWord = p.current_word_text;
      showToast('Manghuhula: ' + p.current_word_text);
    }
    if (rt.getSocket()) rt.joinTurn(p.turn_id);
  });

  // turn_state (push after join_turn) — public, no word text.
  rt.on('turn_state', (p) => {
    if (!forMyTeam(p)) return;
    if (p.turn_id != null) knownTurnId = p.turn_id;
    if (typeof p.total_words === 'number') STATE.totalWords = Math.max(1, p.total_words);
    if (typeof p.correct_words === 'number') STATE.wordsGuessed = p.correct_words;
    applyTimer(p);
    try { renderTagasagotView(); } catch (e) {}
  });

  // Word results update progress + timer.
  rt.on('word_correct', (p) => {
    if (!forMyTeam(p)) return;
    if (typeof p.correct_words === 'number') STATE.wordsGuessed = p.correct_words;
    applyTimer(p);
    try { updateGameProgress(); } catch (e) {}
  });
  rt.on('word_passed', (p) => {
    if (!forMyTeam(p)) return;
    if (typeof p.passed_words === 'number') STATE.score = p.passed_words;
    applyTimer(p);
    try { updateGameProgress(); } catch (e) {}
  });

  // Timer events.
  ['timer_updated', 'timer_paused', 'timer_resumed', 'time_added', 'time_removed', 'penalty_applied']
    .forEach((evt) => {
      rt.on(evt, (p) => {
        if (p && p.turn_id != null && p.turn_id !== knownTurnId) return; // not our turn
        if (!forMyTeam(p)) return;
        if (p.status === 'PAUSED') { stopTimerTicker(); }
        else applyTimer(p);
        try { renderTagasagotView(); } catch (e) {}
      });
    });

  // Turn / round / game completion.
  rt.on('turn_completed', (p) => {
    if (!forMyTeam(p)) return;
    STATE.currentSecretWord = null;
    stopTimerTicker();
    try { renderHeader(); renderTeamsTab(); } catch (e) {}
  });
  rt.on('round_completed', (p) => {
    if (!gameIdMatches(p)) return;
    STATE.gameStatus = 'ready';
    try { renderHeader(); renderWaitingScreen(); } catch (e) {}
    showToast('Round complete!');
  });
  rt.on('game_completed', (p) => {
    if (!gameIdMatches(p)) return;
    STATE.gameStatus = 'complete';
    try { renderHeader(); renderWaitingScreen(); } catch (e) {}
    showToast('Game complete!');
  });
  rt.on('round_started', (p) => {
    if (!gameIdMatches(p)) return;
    const roundNo = p.round_number || STATE.currentRound;
    STATE.currentRound = Number(roundNo) || 1;
    STATE.gameStatus = roundLabel(roundNo);
    try { renderHeader(); renderWaitingScreen(); } catch (e) {}
  });

  // Settings change (word cap / display toggles) → apply live.
  rt.on('settings_updated', (p) => {
    if (!gameIdMatches(p)) return;
    applySettings(p);
  });

  // Presence within our team.
  rt.on('member_joined', (p) => { if (forMyTeam(p) && p.member) { upsertMember(p.member); try { renderTeamsTab(); renderWaitingScreen(); } catch (e) {} } });
  rt.on('member_left', (p) => { if (forMyTeam(p)) { const m = STATE.members.find(x => memberId(x) === p.member_id); if (m) m.connected = false; try { renderTeamsTab(); renderWaitingScreen(); } catch (e) {} } });
  rt.on('team_connected', (p) => { if (forMyTeam(p) && p.member) { const m = upsertMember(p.member); if (m) m.connected = true; try { renderTeamsTab(); renderHeader(); renderWaitingScreen(); } catch (e) {} } });
  rt.on('team_disconnected', (p) => { if (forMyTeam(p)) { const m = STATE.members.find(x => memberId(x) === p.member_id); if (m) m.connected = false; try { renderTeamsTab(); renderHeader(); renderWaitingScreen(); } catch (e) {} } });
  rt.on('role_updated', (p) => { if (forMyTeam(p)) { const m = STATE.members.find(x => memberId(x) === p.member_id); if (m) m.role = roleName(p.gameplay_role); try { renderTeamsTab(); renderRoles(); } catch (e) {} } });
  rt.on('member_updated', (p) => { if (forMyTeam(p) && p.username) { const m = STATE.members.find(x => memberId(x) === p.member_id); if (m) m.name = p.username; if (p.member_id === API.getMemberId()) STATE.username = p.username; try { renderTeamsTab(); renderHeader(); renderSettingsTab(); } catch (e) {} } });
  rt.on('team_updated', (p) => { if (forMyTeam(p) && p.team_name) { STATE.teamName = p.team_name; try { renderHeader(); renderTeamsTab(); renderSettingsTab(); } catch (e) {} } });

  // Lifecycle: on (re)connect rejoin the known turn room to re-push state.
  // NOTE: the device socket being up is NOT proof the host approved the team —
  // host approval is ``Team.connection_status``, re-read from the server.
  async function refreshConnectionStatus() {
    const teamId = API.getTeamId();
    if (!teamId || !API.getSessionToken()) return;
    try {
      const teamData = await TeamAPI.getMyTeam(teamId);
      if (teamData) applyTeamRoster(teamData);
    } catch (e) { /* keep last known state */ }
  }
  rt.onConnect(() => {
    STATE.isConnected = true;
    if (knownTurnId) rt.joinTurn(knownTurnId);
    refreshConnectionStatus();
    try { renderHeader(); renderWaitingScreen(); } catch (e) {}
  });
  rt.onReconnect(() => {
    STATE.isConnected = true;
    if (knownTurnId) rt.joinTurn(knownTurnId);
    refreshConnectionStatus();
    try { renderHeader(); renderWaitingScreen(); } catch (e) {}
    showToast('Reconnected');
  });
  rt.onDisconnect(() => {
    STATE.isConnected = false;
    stopTimerTicker();
    try { renderHeader(); } catch (e) {}
  });

  // Host connection / approval state (server-authoritative).
  rt.on('connection_requested', (p) => {
    if (!forMyTeam(p)) return;
    setConnectionStatus('CONNECTION_REQUESTED');
  });
  rt.on('connection_approved', (p) => {
    if (!forMyTeam(p)) return;
    setConnectionStatus('CONNECTED');
    showToast('Host approved your team!');
  });
  rt.on('connection_declined', (p) => {
    if (!forMyTeam(p)) return;
    setConnectionStatus('DECLINED');
    showToast('The host declined your team. Scan or enter the code to try again.');
  });
  rt.on('connection_disconnected', (p) => {
    if (!forMyTeam(p)) return;
    setConnectionStatus('DISCONNECTED');
    showToast('The host disconnected your team.');
  });

  // Connect the device socket.
  rt.connect({ mode: 'player' });
})();

function mapGameStatus(status) {
  const s = String(status || '').toUpperCase();
  if (s.includes('COMPLETE') || s.includes('END')) return 'complete';
  if (s.includes('ROUND2') || s === 'ROUND_2') return 'round2';
  if (s.includes('ROUND1') || s === 'ROUND_1' || s === 'ROUND') return 'round1';
  if (s === 'READY') return 'ready';
  return 'waiting';
}
