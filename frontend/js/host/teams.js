'use strict';

/* ============================================================
   CONSTANTS
============================================================ */
let GAME_CODE  = '';
const ROLES      = ['Manghuhula', 'Tagasagot'];
const STATUSES   = ['connected', 'waiting', 'disconnected', 'none'];

// Cached real backend QR image (data URI), populated during bootstrap.
let qrDataUri = null;

/* ============================================================
   STATE
============================================================ */
let STATE = {
  locked: false,
  // Roster comes from the real backend (bootstrap) + realtime presence events.
  nextTeamId: 5,
  nextMemberId: 20,
  activeManageTeamId: null,   // team open in Manage Members modal
  activeEditTeamId: null,     // team open in Edit Team modal
  pendingRemoveTeamId: null,  // team pending removal confirmation
  search: '',
  filter: 'all',              // all | connected | waiting | disconnected

  teams: [],
};

/* ============================================================
   DOM HELPERS
============================================================ */
const $  = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

/* ============================================================
   RIPPLE
============================================================ */
function addRipple(btn, e) {
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
    '.controls-btn, .card-btn, .connect-action-btn, .btn-confirm, .btn-danger, ' +
    '.btn-cancel, .btn-add-member, .connect-info__copy-btn, .dash-nav__code-btn'
  );
  if (btn) addRipple(btn, e);
});

/* ============================================================
   TOAST
============================================================ */
function showToast(msg) {
  const t = $('copy-toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2200);
}

/* ============================================================
   COPY
============================================================ */
function copyText(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  showToast(`Copied: ${text}`);
  const icon = $('copy-icon');
  if (icon) {
    icon.className = 'fa-solid fa-check';
    setTimeout(() => { icon.className = 'fa-regular fa-copy'; }, 1800);
  }
}

/* ============================================================
   MODAL HELPERS
============================================================ */
function openModal(overlay) {
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  const first = overlay.querySelector('input, select, button:not(.modal__close)');
  if (first) setTimeout(() => first.focus(), 60);
}

function closeModal(overlay) {
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

// Close on backdrop click
$$('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) closeModal(o); });
});

// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  $$('.modal-overlay.open').forEach(o => closeModal(o));
});

/* ============================================================
   QR GRID RENDERER
============================================================ */
function renderQrGrid(container, code) {
  let seed = 0;
  for (let i = 0; i < code.length; i++) seed += code.charCodeAt(i);
  const rand = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };

  const SIZE = 7, total = SIZE * SIZE;
  const corners = new Set([
    0,1,2,7,8,9,14,15,16,       // top-left
    4,5,6,11,12,13,18,19,20,     // top-right
    28,29,30,35,36,37,42,43,44,  // bottom-left
  ]);

  let html = '';
  for (let i = 0; i < total; i++) {
    const filled = corners.has(i) || rand() > 0.42;
    html += `<div class="qr-pixel${filled ? '' : ' qr-pixel--empty'}"></div>`;
  }
  container.innerHTML = html;
}

/* ============================================================
   DERIVED STATS
============================================================ */
function calcStats() {
  const totalTeams      = STATE.teams.length;
  const connectedTeams  = STATE.teams.filter(t => t.status === 'connected').length;
  const allMembers      = STATE.teams.flatMap(t => t.members);
  const totalPlayers    = allMembers.length;
  const connectedPlayers = allMembers.filter(m => m.status === 'connected').length;
  return { totalTeams, connectedTeams, totalPlayers, connectedPlayers };
}

/* ============================================================
   COUNT-UP ANIMATION
============================================================ */
function animateCount(el, to) {
  const from = parseInt(el.textContent, 10) || 0;
  if (from === to) return;
  const dur = 500, start = performance.now();
  const step = now => {
    const pct = Math.min((now - start) / dur, 1);
    el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - pct, 3)));
    if (pct < 1) requestAnimationFrame(step);
    else el.textContent = to;
  };
  requestAnimationFrame(step);
}

/* ============================================================
   RENDER STATS
============================================================ */
function renderStats() {
  const { totalTeams, connectedTeams, totalPlayers, connectedPlayers } = calcStats();
  animateCount($('stat-total-teams'),       totalTeams);
  animateCount($('stat-connected-teams'),   connectedTeams);
  animateCount($('stat-total-players'),     totalPlayers);
  animateCount($('stat-connected-players'), connectedPlayers);
}

/* ============================================================
   STATUS HELPERS
============================================================ */
function statusClass(status) {
  const map = { connected: 'connected', waiting: 'waiting', disconnected: 'disconnected', none: 'none' };
  return map[status] || 'none';
}
function statusLabel(status) {
  const map = { connected: 'Connected', waiting: 'Waiting', disconnected: 'Disconnected', none: 'Not Connected' };
  return map[status] || 'Not Connected';
}

/* ============================================================
   BUILD TEAM CARD HTML
============================================================ */
function buildTeamCard(team) {
  const sc   = statusClass(team.status);
  const sl   = statusLabel(team.status);
  const manghuhula = team.members.filter(m => m.role === 'Manghuhula');
  const tagasagot  = team.members.filter(m => m.role === 'Tagasagot');
  const count = team.members.length;
  const locked = STATE.locked;

  const playerRow = m => `
    <div class="player-row">
      <span class="player-row__dot player-row__dot--${statusClass(m.status)}"></span>
      <span>${escHtml(m.name)}</span>
    </div>`;

  const mangRows = manghuhula.length
    ? manghuhula.map(playerRow).join('')
    : `<p class="role-section__empty">None assigned</p>`;

  const tagRows = tagasagot.length
    ? tagasagot.map(playerRow).join('')
    : `<p class="role-section__empty">None assigned</p>`;

  const actionBtns = locked
    ? `<span style="font-size:0.75rem;color:rgba(255,255,255,0.25);padding:0.25rem 0.4rem;">
         <i class="fa-solid fa-lock" style="font-size:0.7rem;margin-right:0.3rem;"></i>Locked
       </span>`
    : `<button class="card-btn card-btn--edit"    data-id="${team.id}"><i class="fa-solid fa-pen"></i> Edit</button>
       <button class="card-btn card-btn--members" data-id="${team.id}"><i class="fa-solid fa-user-group"></i> Members</button>
       <button class="card-btn card-btn--remove"  data-id="${team.id}"><i class="fa-solid fa-trash"></i></button>`;

  return `
    <div class="team-card${locked ? ' locked' : ''}" data-id="${team.id}">
      <div class="team-card__lock-badge"><i class="fa-solid fa-lock"></i></div>
      <div class="team-card__header">
        <div>
          <p class="team-card__name">${escHtml(team.name)}</p>
          <div class="team-card__meta">
            <span class="status-badge status-badge--${sc}">
              <span class="status-badge__dot"></span>${sl}
            </span>
            <span class="team-card__member-count">${count} member${count !== 1 ? 's' : ''}</span>
          </div>
        </div>
      </div>

      <div class="team-card__body">
        <div class="role-section">
          <p class="role-section__label role-section__label--guesser">
            <i class="fa-solid fa-bullseye"></i> Manghuhula
          </p>
          <div class="role-section__players">${mangRows}</div>
        </div>
        <div class="role-section">
          <p class="role-section__label role-section__label--answerer">
            <i class="fa-solid fa-comments"></i> Tagasagot
          </p>
          <div class="role-section__players">${tagRows}</div>
        </div>
      </div>

      <div class="team-card__actions">${actionBtns}</div>
    </div>`;
}

/* ============================================================
   RENDER TEAMS GRID
============================================================ */
function renderTeams() {
  const query  = STATE.search.trim().toLowerCase();
  const filter = STATE.filter;

  const visible = STATE.teams.filter(t => {
    const matchSearch = !query || t.name.toLowerCase().includes(query);
    const matchFilter = filter === 'all' || t.status === filter;
    return matchSearch && matchFilter;
  });

  const grid  = $('teams-grid');
  const empty = $('empty-state');

  if (visible.length === 0) {
    grid.innerHTML = '';
    empty.hidden = false;
  } else {
    empty.hidden = true;
    grid.innerHTML = visible.map(buildTeamCard).join('');
  }

  // Attach card button events
  grid.querySelectorAll('.card-btn--edit').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openEditTeam(+btn.dataset.id); });
  });
  grid.querySelectorAll('.card-btn--members').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openManageMembers(+btn.dataset.id); });
  });
  grid.querySelectorAll('.card-btn--remove').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openRemoveTeam(+btn.dataset.id); });
  });
}

/* ============================================================
   RENDER CONNECTION SECTION
============================================================ */
function renderConnectSection() {
  const total     = STATE.teams.length;
  const connected = STATE.teams.filter(t => t.status === 'connected').length;
  const pct       = total > 0 ? Math.round((connected / total) * 100) : 0;

  $('connect-count').textContent       = connected;
  $('connect-total').textContent       = total;
  $('connect-game-code').textContent   = GAME_CODE;
  $('connect-progress-bar').style.width = pct + '%';

  // Team dots
  $('connect-team-dots').innerHTML = STATE.teams.map(t => `
    <div class="connect-team-chip">
      <span class="connect-team-chip__dot connect-team-chip__dot--${statusClass(t.status)}"></span>
      ${escHtml(t.name)}
    </div>`).join('');

  // Status message
  const msgEl = $('connect-status-msg');
  const txtEl = $('connect-status-text');
  if (connected === total && total > 0) {
    msgEl.className = 'connect-status-msg connect-status-msg--all';
    txtEl.textContent = 'All teams are connected — ready to play!';
  } else {
    msgEl.className = 'connect-status-msg';
    txtEl.textContent = `Waiting for ${total - connected} more team${total - connected !== 1 ? 's' : ''} to connect…`;
  }
}

/* ============================================================
   RENDER LOCK BUTTON STATE
============================================================ */
function renderLockBtn() {
  const btn   = $('btn-lock-teams');
  const icon  = $('lock-icon');
  const label = $('lock-label');
  const addBtn = $('btn-add-team');
  const addBtnEmpty = $('btn-add-team-empty');

  if (STATE.locked) {
    btn.classList.add('locked');
    icon.className  = 'fa-solid fa-lock-open';
    label.textContent = 'Unlock Teams';
    addBtn.disabled = true;
    if (addBtnEmpty) addBtnEmpty.disabled = true;
  } else {
    btn.classList.remove('locked');
    icon.className  = 'fa-solid fa-lock';
    label.textContent = 'Lock Teams';
    addBtn.disabled = false;
    if (addBtnEmpty) addBtnEmpty.disabled = false;
  }
}

/* ============================================================
   FULL RE-RENDER
============================================================ */
function render() {
  renderStats();
  renderTeams();
  renderConnectSection();
  renderLockBtn();
}

/* ============================================================
   ESCAPE HTML
============================================================ */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ============================================================
   MEMBER ROW BUILDER (for Add / Edit forms)
============================================================ */
function buildMemberRow(idx, name = '', role = 'Tagasagot') {
  const row = document.createElement('div');
  row.className = 'member-row';
  row.innerHTML = `
    <input type="text" class="form-input member-name-input"
           placeholder="Player name" value="${escHtml(name)}" maxlength="40" />
    <select class="form-select member-role-select">
      <option value="Manghuhula"${role === 'Manghuhula' ? ' selected' : ''}>Manghuhula</option>
      <option value="Tagasagot"${role  === 'Tagasagot'  ? ' selected' : ''}>Tagasagot</option>
    </select>
    <button type="button" class="member-row__remove" aria-label="Remove member">
      <i class="fa-solid fa-trash"></i>
    </button>`;
  row.querySelector('.member-row__remove').addEventListener('click', () => row.remove());
  return row;
}

function getMemberRowsData(container) {
  return [...container.querySelectorAll('.member-row')].map(row => ({
    name: row.querySelector('.member-name-input').value.trim(),
    role: row.querySelector('.member-role-select').value,
  })).filter(m => m.name);
}

/* ============================================================
   MODAL: ADD TEAM
============================================================ */
function openAddTeam() {
  const form    = $('form-add-team');
  const nameIn  = $('add-team-name');
  const listEl  = $('add-members-list');

  form.reset();
  nameIn.classList.remove('error');
  $('err-add-team-name').textContent = '';
  listEl.innerHTML = '';

  // Pre-populate one Manghuhula row
  listEl.appendChild(buildMemberRow(0, '', 'Manghuhula'));
  listEl.appendChild(buildMemberRow(1, '', 'Tagasagot'));

  openModal($('modal-add-team'));
}

$('btn-add-team').addEventListener('click', openAddTeam);
$('btn-add-team-empty').addEventListener('click', openAddTeam);
$('close-add-team').addEventListener('click',   () => closeModal($('modal-add-team')));
$('cancel-add-team').addEventListener('click',  () => closeModal($('modal-add-team')));

$('btn-add-member-row').addEventListener('click', () => {
  const list = $('add-members-list');
  list.appendChild(buildMemberRow(list.children.length));
});

$('form-add-team').addEventListener('submit', async (e) => {
  e.preventDefault();
  const nameIn = $('add-team-name');
  const errEl  = $('err-add-team-name');
  const name   = nameIn.value.trim();

  if (!name) {
    nameIn.classList.add('error');
    errEl.textContent = 'Team name is required.';
    return;
  }
  if (STATE.teams.some(t => t.name.toLowerCase() === name.toLowerCase())) {
    nameIn.classList.add('error');
    errEl.textContent = 'A team with this name already exists.';
    return;
  }
  nameIn.classList.remove('error');
  errEl.textContent = '';

  const members = getMemberRowsData($('add-members-list'));

  const gameId = API.getGameId();
  if (gameId) {
    const btn = $('form-add-team').querySelector('button[type="submit"]');
    const originalBtn = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Creating…';
    try {
      const leaderName = (members[0] && members[0].name) || name;
      const team = await API.withLoading('add-team', () =>
        TeamAPI.createTeam(gameId, name, leaderName)
      );
      const teamId = team.team_id;
      if (teamId) API.addKnownTeam(teamId, team.team_name || name);

      // Add remaining members (position 1 onward).
      const createdMemberIds = [team.leader ? team.leader.member_id : null];
      for (let i = 1; i < members.length; i++) {
        if (!members[i].name) continue;
        const m = await TeamAPI.addMember(teamId, members[i].name);
        createdMemberIds.push(m.member_id);
      }

      // Assign roles to every member that has one (Manghuhula / Tagasagot).
      const roleMap = { Manghuhula: 'MANGHUHULA', Tagasagot: 'TAGASAGOT' };
      const allMembers = members.map((m, i) => ({
        member_id: createdMemberIds[i],
        role: m.role,
      })).filter(m => m.member_id != null);
      if (allMembers.length) {
        await TeamAPI.assignRoles(teamId, allMembers.map(({ member_id, role }) => ({
          member_id,
          gameplay_role: roleMap[role] || 'TAGASAGOT',
        })));
      }

      closeModal($('modal-add-team'));
      // The backend has no team-list endpoint; reflect the created team.
      STATE.teams.push({
        id: teamId,
        name: team.team_name,
        status: team.team_status || 'waiting',
        members: allMembers.map(({ member_id, role }, i) => ({
          id: member_id,
          name: members[i] && members[i].name ? members[i].name : 'Member',
          role,
          status: 'none',
        })),
      });
      render();
      showToast(`Team "${name}" created`);
    } catch (err) {
      console.error('[Pinoy Henyo] create team failed', err);
      nameIn.classList.add('error');
      errEl.textContent = err.message || 'Could not create the team.';
    } finally {
      btn.disabled = false;
      btn.textContent = originalBtn;
    }
    return;
  }

  // Fallback (no game context): local demo behaviour.
  const localMembers = members.map((m, i) => ({
    id: STATE.nextMemberId++,
    name: m.name,
    role: m.role,
    status: 'none',
  }));

  STATE.teams.push({
    id: STATE.nextTeamId++,
    name,
    status: 'none',
    members: localMembers,
  });

  closeModal($('modal-add-team'));
  render();
  showToast(`Team "${name}" added`);
});

/* ============================================================
   MODAL: EDIT TEAM
============================================================ */
function openEditTeam(teamId) {
  const team = STATE.teams.find(t => t.id === teamId);
  if (!team) return;
  STATE.activeEditTeamId = teamId;

  $('edit-team-name').value = team.name;
  $('edit-team-name').classList.remove('error');
  $('err-edit-team-name').textContent = '';
  $('edit-team-subtitle').textContent = team.name;

  const listEl = $('edit-members-list');
  listEl.innerHTML = '';
  team.members.forEach((m, i) => listEl.appendChild(buildMemberRow(i, m.name, m.role)));

  openModal($('modal-edit-team'));
}

$('close-edit-team').addEventListener('click',  () => closeModal($('modal-edit-team')));
$('cancel-edit-team').addEventListener('click', () => closeModal($('modal-edit-team')));

$('btn-add-member-edit').addEventListener('click', () => {
  const list = $('edit-members-list');
  list.appendChild(buildMemberRow(list.children.length));
});

$('form-edit-team').addEventListener('submit', e => {
  e.preventDefault();
  const team   = STATE.teams.find(t => t.id === STATE.activeEditTeamId);
  if (!team) return;

  const nameIn = $('edit-team-name');
  const errEl  = $('err-edit-team-name');
  const name   = nameIn.value.trim();

  if (!name) {
    nameIn.classList.add('error');
    errEl.textContent = 'Team name is required.';
    return;
  }
  if (STATE.teams.some(t => t.id !== team.id && t.name.toLowerCase() === name.toLowerCase())) {
    nameIn.classList.add('error');
    errEl.textContent = 'A team with this name already exists.';
    return;
  }
  nameIn.classList.remove('error');
  errEl.textContent = '';

  team.name = name;

  // Preserve existing member statuses where possible, otherwise default to 'none'
  const oldMap = Object.fromEntries(team.members.map(m => [m.id, m]));
  const rows   = getMemberRowsData($('edit-members-list'));

  team.members = rows.map((r, i) => {
    const existing = team.members[i];
    return {
      id: existing ? existing.id : STATE.nextMemberId++,
      name: r.name,
      role: r.role,
      status: existing ? existing.status : 'none',
    };
  });

  closeModal($('modal-edit-team'));
  render();
  showToast(`Team "${name}" updated`);
});

/* ============================================================
   MODAL: REMOVE TEAM
============================================================ */
function openRemoveTeam(teamId) {
  const team = STATE.teams.find(t => t.id === teamId);
  if (!team) return;
  STATE.pendingRemoveTeamId = teamId;
  $('remove-team-subtitle').textContent = `Remove "${team.name}"?`;
  openModal($('modal-remove-team'));
}

$('close-remove-team').addEventListener('click',  () => closeModal($('modal-remove-team')));
$('cancel-remove-team').addEventListener('click', () => closeModal($('modal-remove-team')));

$('btn-confirm-remove').addEventListener('click', () => {
  const team = STATE.teams.find(t => t.id === STATE.pendingRemoveTeamId);
  if (!team) return;
  const name = team.name;
  STATE.teams = STATE.teams.filter(t => t.id !== STATE.pendingRemoveTeamId);
  STATE.pendingRemoveTeamId = null;
  closeModal($('modal-remove-team'));
  render();
  showToast(`Team "${name}" removed`);
});

/* ============================================================
   MODAL: MANAGE MEMBERS
============================================================ */
function buildManageMemberRow(teamId, member) {
  const sc = statusClass(member.status);
  const roleClass = member.role === 'Manghuhula' ? 'manage-member-row__role--guesser' : 'manage-member-row__role--answerer';
  const roleIcon  = member.role === 'Manghuhula' ? 'fa-bullseye' : 'fa-comments';
  const connClass = member.status === 'connected' ? 'manage-member-row__status--connected'
                  : member.status === 'disconnected' ? 'manage-member-row__status--disconnected'
                  : 'manage-member-row__status--none';

  const row = document.createElement('div');
  row.className = 'manage-member-row';
  row.dataset.memberId = member.id;
  row.innerHTML = `
    <span class="manage-member-row__name">${escHtml(member.name)}</span>
    <span class="manage-member-row__role ${roleClass}">
      <i class="fa-solid ${roleIcon}"></i> ${member.role}
    </span>
    <span class="manage-member-row__status ${connClass}"></span>
    <div class="manage-member-row__actions">
      <button class="manage-member-row__btn manage-member-row__btn--remove" aria-label="Remove ${escHtml(member.name)}">
        <i class="fa-solid fa-trash"></i>
      </button>
    </div>`;

  row.querySelector('.manage-member-row__btn--remove').addEventListener('click', () => {
    const team = STATE.teams.find(t => t.id === teamId);
    if (!team) return;
    team.members = team.members.filter(m => m.id !== member.id);
    renderManageMembersList(teamId);
    renderStats();
    renderTeams();
    showToast(`${member.name} removed`);
  });

  return row;
}

function renderManageMembersList(teamId) {
  const team   = STATE.teams.find(t => t.id === teamId);
  const listEl = $('manage-members-list');
  listEl.innerHTML = '';
  if (!team) return;
  team.members.forEach(m => listEl.appendChild(buildManageMemberRow(teamId, m)));
}

function openManageMembers(teamId) {
  const team = STATE.teams.find(t => t.id === teamId);
  if (!team) return;
  STATE.activeManageTeamId = teamId;
  $('manage-members-team-name').textContent = team.name;
  renderManageMembersList(teamId);
  openModal($('modal-manage-members'));
}

$('close-manage-members').addEventListener('click',   () => closeModal($('modal-manage-members')));
$('close-manage-members-2').addEventListener('click', () => closeModal($('modal-manage-members')));

$('btn-add-member-manage').addEventListener('click', () => {
  // Open Add Member modal on top
  const team = STATE.teams.find(t => t.id === STATE.activeManageTeamId);
  if (!team) return;
  $('add-member-team-name').textContent = team.name;
  $('add-member-name').value = '';
  $('add-member-name').classList.remove('error');
  $('err-add-member-name').textContent = '';
  $('add-member-role').value = 'Tagasagot';
  openModal($('modal-add-member'));
});

/* ============================================================
   MODAL: ADD MEMBER
============================================================ */
$('close-add-member').addEventListener('click',  () => closeModal($('modal-add-member')));
$('cancel-add-member').addEventListener('click', () => closeModal($('modal-add-member')));

$('form-add-member').addEventListener('submit', async e => {
  e.preventDefault();
  const nameIn = $('add-member-name');
  const roleIn = $('add-member-role');
  const errEl  = $('err-add-member-name');
  const name   = nameIn.value.trim();
  const role   = roleIn.value;
  const team   = STATE.teams.find(t => t.id === STATE.activeManageTeamId);
  if (!team) return;

  if (!name) {
    nameIn.classList.add('error');
    errEl.textContent = 'Player name is required.';
    return;
  }
  // Enforce single Manghuhula
  if (role === 'Manghuhula' && team.members.some(m => m.role === 'Manghuhula')) {
    nameIn.classList.add('error');
    errEl.textContent = 'This team already has a Manghuhula.';
    return;
  }
  nameIn.classList.remove('error');
  errEl.textContent = '';

  // Real backend integration when a host game context exists.
  if (API.getGameId()) {
    const btn = $('form-add-member').querySelector('button[type="submit"]');
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Adding…';
    try {
      const m = await API.withLoading('add-member', () => TeamAPI.addMember(team.id, name));
      await TeamAPI.assignRoles(team.id, [{
        member_id: m.member_id,
        gameplay_role: role === 'Manghuhula' ? 'MANGHUHULA' : 'TAGASAGOT',
      }]);
      team.members.push({ id: m.member_id, name, role, status: 'none' });

      closeModal($('modal-add-member'));
      renderManageMembersList(team.id);
      renderStats();
      renderTeams();
      showToast(`${name} added to ${team.name}`);
    } catch (err) {
      console.error('[Pinoy Henyo] add member failed', err);
      nameIn.classList.add('error');
      errEl.textContent = err.message || 'Could not add the member.';
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
    return;
  }

  team.members.push({ id: STATE.nextMemberId++, name, role, status: 'none' });

  closeModal($('modal-add-member'));
  renderManageMembersList(team.id);
  renderStats();
  renderTeams();
  showToast(`${name} added to ${team.name}`);
});

/* ============================================================
   MODAL: LOCK / UNLOCK TEAMS
============================================================ */
function openLockModal() {
  const icon    = $('modal-lock-icon');
  const title   = $('lock-teams-title');
  const sub     = $('lock-teams-subtitle');
  const bodyTxt = $('lock-teams-body-text');
  const list    = $('lock-info-list');
  const confBtn = $('btn-confirm-lock');
  const confIcon= $('confirm-lock-icon');
  const confLbl = $('confirm-lock-label');

  if (STATE.locked) {
    // Unlock mode
    icon.className    = 'fa-solid fa-lock-open';
    title.textContent = 'Unlock Teams';
    sub.textContent   = 'Allow editing teams again.';
    bodyTxt.textContent = 'Unlocking will allow changes to teams, members, and roles.';
    list.hidden       = true;
    confIcon.className = 'fa-solid fa-lock-open';
    confLbl.textContent = 'Unlock Teams';
    confBtn.style.background = 'var(--secondary-600)';
  } else {
    // Lock mode
    icon.className    = 'fa-solid fa-lock';
    title.textContent = 'Lock Teams';
    sub.textContent   = 'Confirm before starting the game.';
    bodyTxt.textContent = 'Make sure all teams, members, and roles are correct before starting.';
    list.hidden       = false;
    confIcon.className = 'fa-solid fa-lock';
    confLbl.textContent = 'Lock Teams';
    confBtn.style.background = '';
  }

  openModal($('modal-lock-teams'));
}

$('btn-lock-teams').addEventListener('click', openLockModal);
$('close-lock-teams').addEventListener('click',  () => closeModal($('modal-lock-teams')));
$('cancel-lock-teams').addEventListener('click', () => closeModal($('modal-lock-teams')));

$('btn-confirm-lock').addEventListener('click', () => {
  STATE.locked = !STATE.locked;
  closeModal($('modal-lock-teams'));
  render();
  showToast(STATE.locked ? 'Teams locked' : 'Teams unlocked');
});

/* ============================================================
   MODAL: QR CODE
============================================================ */
function openQrModal() {
  renderRealQr($('qr-modal-visual'), qrDataUri);
  $('qr-modal-code').textContent = GAME_CODE;
  openModal($('modal-qr'));
}

$('btn-show-qr').addEventListener('click', openQrModal);
$('close-qr-modal').addEventListener('click',   () => closeModal($('modal-qr')));
$('close-qr-modal-2').addEventListener('click', () => closeModal($('modal-qr')));
$('btn-copy-qr-code').addEventListener('click', () => copyText(GAME_CODE));

/* ============================================================
   NAV COPY CODE
============================================================ */
$('btn-copy-code').addEventListener('click', () => copyText(GAME_CODE));

/* ============================================================
   CONNECT SECTION BUTTONS
============================================================ */
$('btn-copy-connect').addEventListener('click',  () => copyText(GAME_CODE));
$('btn-copy-code-2').addEventListener('click',   () => copyText(GAME_CODE));
$('btn-share-link').addEventListener('click',    () => {
  const url = `${location.origin}${location.pathname.replace('teams.html', '')}?code=${GAME_CODE}`;
  copyText(url);
  showToast('Link copied');
});

/* ============================================================
   SEARCH & FILTER
============================================================ */
$('search-input').addEventListener('input', e => {
  STATE.search = e.target.value;
  renderTeams();
});

$('filter-select').addEventListener('change', e => {
  STATE.filter = e.target.value;
  renderTeams();
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
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      revealObs.unobserve(entry.target);
    }
  });
}, { threshold: 0.1, rootMargin: '0px 0px -30px 0px' });

$$('.reveal').forEach(el => revealObs.observe(el));

/* ============================================================
   INIT
============================================================ */
function init() {
  if (API.getGameCode) GAME_CODE = API.getGameCode() || GAME_CODE;

  // Render QR grid in connect section
  renderQrGrid($('qr-visual'), GAME_CODE);
  $('connect-game-code').textContent = GAME_CODE;

  // Full render
  render();
}

init();

/* ============================================================
   BACKEND INTEGRATION (host teams page)
   - Host reconnect guard
   - Replace the demo QR + game code with the real backend QR/data
     when a host game context exists.
   ============================================================ */
function renderRealQr(container, dataUri) {
  if (!container) return;
  if (!dataUri) { renderQrGrid(container, GAME_CODE); return; }
  container.innerHTML = '';
  container.style.cssText = 'background:#fff;padding:6px;border-radius:8px;display:flex;align-items:center;justify-content:center;';
  const img = document.createElement('img');
  img.src = dataUri;
  img.alt = 'Join QR';
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;';
  container.appendChild(img);
}

(async function bootstrapTeamsIntegration() {
  const gameId = API.getGameId();
  if (!gameId) return;

  try {
    const r = await Connect.restoreHostSession();
    if (r.status === 'invalid' || r.status === 'unavailable') {
      Connect.showReconnectBanner({
        title: 'Host session not found',
        message: 'Your host session could not be restored. Reconnect to your game.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
    }
  } catch (e) { /* ignore */ }

  const code = API.getGameCode();
  if (code) {
    GAME_CODE = code;
    ['connect-game-code', 'game-code-display', 'qr-modal-code'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = code;
    });
  }

  // Load the real team roster from the backend and seed STATE.teams so the
  // page shows live data instead of a static demo roster.
  function gameplayRole(role) {
    return String(role || '').toUpperCase() === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot';
  }
  function seedRoster(teams) {
    STATE.teams = (teams || []).map(team => ({
      id: team.team_id,
      name: team.team_name || 'Team ' + team.team_id,
      status: (team.members || []).some(m => m.is_connected)
        ? 'connected'
        : ((team.members || []).length ? 'waiting' : 'none'),
      members: (team.members || []).map(m => ({
        id: m.member_id,
        name: m.username,
        role: gameplayRole(m.gameplay_role),
        status: m.is_connected ? 'connected' : 'disconnected',
      })),
    }));
    // Keep known teams in sync for other setup pages (words/match filters).
    (teams || []).forEach(t => {
      if (API.addKnownTeam) API.addKnownTeam(t.team_id, t.team_name);
    });
    render();
  }

  try {
    const roster = await TeamAPI.listTeams(gameId);
    seedRoster((roster && Array.isArray(roster.teams)) ? roster.teams : []);
  } catch (e) { console.warn('[teams] roster offline', e.message); }

  try {
    const qr = await GameAPI.gameQr(gameId);
    qrDataUri = (qr && qr.qr_image) || null;
    const vis = document.getElementById('qr-visual');
    const modal = document.getElementById('qr-modal-visual');
    if (vis) renderRealQr(vis, qrDataUri);
    if (modal) renderRealQr(modal, qrDataUri);
  } catch (e) { console.warn('[teams] QR offline', e.message); }
})();

/* ============================================================
   REALTIME PRESENCE (host teams page)
   ------------------------------------------------------------
   Connects the HOST socket and reflects live team/member state
   from the backend presence events onto STATE.teams, then re-renders.
   These events carry only PUBLIC data (no secret word text), so
   this is safe to apply directly to the roster.
   ============================================================ */
(function realtimePresence() {
  const rt = window.Realtime;
  const gameId = API.getGameId();
  if (!rt || !gameId) return; // no realtime lib or no game -> skip

  function gameplayRole(role) {
    return String(role || '').toUpperCase() === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot';
  }
  function ensureTeam(teamId) {
    let team = STATE.teams.find(t => String(t.id) === String(teamId));
    if (!team) {
      team = { id: teamId, name: 'Team ' + teamId, status: 'waiting', members: [] };
      STATE.teams.push(team);
    }
    return team;
  }
  function memberById(team, memberId) {
    return team.members.find(m => String(m.id) === String(memberId));
  }
  function upsertMember(team, payload) {
    let m = memberById(team, payload.member_id);
    if (!m) {
      m = { id: payload.member_id, name: '', role: 'Tagasagot', status: 'none' };
      team.members.push(m);
    }
    if (payload.username) m.name = payload.username;
    if (payload.gameplay_role) m.role = gameplayRole(payload.gameplay_role);
    m.status = payload.is_connected ? 'connected' : 'disconnected';
    return m;
  }
  function recomputeTeamStatus(team) {
    const anyConnected = team.members.some(m => m.status === 'connected');
    team.status = anyConnected ? 'connected' : (team.members.length ? 'waiting' : 'none');
  }

  const reRender = () => {
    try { render(); } catch (e) {}
  };

  // Roster / presence events -> mirror onto STATE.teams and re-render.
  rt.on('member_joined', (p) => {
    if (!p || !p.member) return;
    const team = ensureTeam(p.member.team_id || p.team_id);
    upsertMember(team, p.member);
    recomputeTeamStatus(team);
    reRender();
  });
  rt.on('team_connected', (p) => {
    if (!p || !p.member) return;
    const team = ensureTeam(p.member.team_id || p.team_id);
    const m = upsertMember(team, p.member);
    m.status = 'connected';
    recomputeTeamStatus(team);
    reRender();
  });
  rt.on('member_left', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m) m.status = 'disconnected';
    recomputeTeamStatus(team);
    reRender();
  });
  rt.on('team_disconnected', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m) m.status = 'disconnected';
    recomputeTeamStatus(team);
    reRender();
  });
  rt.on('role_updated', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m) m.role = gameplayRole(p.gameplay_role);
    reRender();
  });
  rt.on('team_updated', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    reRender();
  });

  // Connect the host socket; on (re)connect re-render presence.
  if (!rt.getSocket()) {
    rt.connect({ mode: 'host' });
    rt.onConnect(() => { reRender(); showToast('Realtime connected'); });
    rt.onReconnect(() => { reRender(); showToast('Realtime reconnected'); });
    rt.onDisconnect(() => { showToast('Realtime disconnected'); });
  }
})();
