'use strict';

/* ============================================================
   CONNECTIONS TAB — JS
   ------------------------------------------------------------
   Device / team connection overview for the host. Reads the
   existing roster contract (GET /api/games/<id>/teams) and acts
   through the existing TeamAPI approve/decline/disconnect calls.
   Live state arrives via the shared Realtime events that the
   backend already emits (connection_requested/approved/declined/
   disconnected, team_connected/team_disconnected, member_joined/
   member_left, team_updated).
   ============================================================ */

const $ = id => document.getElementById(id);

const STATE = {
  teams: [],            // [{ id, name, connectionStatus, status, leaderName, members:[{id,name,role,leader,status}] }]
  filter: 'all',        // all | pending | connected | disconnected
  query: '',
  inFlight: new Set(),  // team ids with an action pending
  refreshing: false,
  noSession: false,
};

let rosterGameId = null;

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
  const btn = e.target.closest('.controls-btn, .card-btn, .dash-nav__code-btn');
  if (btn) addRipple(btn, e);
});

/* ============================================================
   TOAST — delegates to the global Toast Manager
============================================================ */
function showToast(msg) {
  if (window.Toast) window.Toast.showToast(msg);
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
   ESCAPE HTML
============================================================ */
function escHtml(str) {
  return String(str == null ? '' : str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ============================================================
   CONNECTION STATUS HELPERS
   ------------------------------------------------------------
   connection_status (host-connection approval state):
     CONNECTED            -> connected
     CONNECTION_REQUESTED -> pending (awaiting host approval)
     NOT_CONNECTED        -> none (never requested a connection)
     DECLINED/DISCONNECTED-> disconnected
   Member statuses stay presence-based (device online).
============================================================ */
function connectionToCardStatus(cs) {
  switch (cs) {
    case 'CONNECTED':            return 'connected';
    case 'CONNECTION_REQUESTED': return 'pending';
    case 'DECLINED':             return 'declined';
    case 'DISCONNECTED':         return 'disconnected';
    default:                     return 'none';
  }
}
function statusLabel(status) {
  const map = { connected: 'Connected', pending: 'Pending Approval', declined: 'Declined', disconnected: 'Disconnected', none: 'Not Connected' };
  return map[status] || 'Not Connected';
}

function gameplayRole(role) {
  return String(role || '').toUpperCase() === 'MANGHUHULA' ? 'Manghuhula' : 'Tagasagot';
}

/* ============================================================
   STATE
============================================================ */
function seedRoster(teams) {
  STATE.teams = (teams || []).map(team => {
    const t = {
      id: team.team_id,
      name: team.team_name || 'Team ' + team.team_id,
      connectionStatus: team.connection_status || 'NOT_CONNECTED',
      leaderName: (team.leader && team.leader.username) || null,
      members: (team.members || []).map(m => ({
        id: m.member_id,
        name: m.username,
        role: gameplayRole(m.gameplay_role),
        leader: String(m.device_role || '').toUpperCase() === 'TEAM_LEADER',
        status: m.is_connected ? 'connected' : 'disconnected',
      })),
    };
    t.status = connectionToCardStatus(t.connectionStatus);
    return t;
  });
  render();
}

/* ============================================================
   STATS
============================================================ */
function computeStats() {
  let pending = 0, connectedTeams = 0, disconnected = 0, devicesOnline = 0;
  STATE.teams.forEach(t => {
    if (t.status === 'pending') pending++;
    else if (t.status === 'connected') connectedTeams++;
    else if (t.status === 'disconnected' || t.status === 'declined' || t.status === 'none') disconnected++;
    t.members.forEach(m => { if (m.status === 'connected') devicesOnline++; });
  });
  return { pending, connectedTeams, disconnected, devicesOnline };
}

function renderStats(s) {
  const ids = {
    pending: 'stat-pending-requests',
    connectedTeams: 'stat-connected-teams',
    devicesOnline: 'stat-devices-online',
    disconnected: 'stat-disconnected-teams',
  };
  Object.entries(ids).forEach(([key, id]) => {
    const el = $(id);
    if (el) el.textContent = String(s[key]);
  });
}

/* ============================================================
   RENDER
============================================================ */
function visibleTeams() {
  const q = STATE.query.trim().toLowerCase();
  return STATE.teams.filter(t => {
    if (STATE.filter !== 'all') {
      if (STATE.filter === 'disconnected') {
        if (t.status !== 'disconnected' && t.status !== 'declined' && t.status !== 'none') return false;
      } else if (t.status !== STATE.filter) {
        return false;
      }
    }
    if (!q) return true;
    if (String(t.name).toLowerCase().includes(q)) return true;
    if (t.leaderName && String(t.leaderName).toLowerCase().includes(q)) return true;
    return t.members.some(m => String(m.name).toLowerCase().includes(q));
  });
}

function deviceRowHtml(m) {
  const initial = escHtml((m.name || '?').trim().charAt(0).toUpperCase() || '?');
  const online = m.status === 'connected';
  return `
    <div class="device-row">
      <span class="device-row__avatar">${initial}</span>
      <span class="device-row__name">${escHtml(m.name)}</span>
      <span class="device-row__role ${m.leader ? 'device-row__role--leader' : ''}">${m.leader ? 'Leader' : 'Player'}</span>
      <span class="device-row__dot device-row__dot--${online ? 'connected' : 'disconnected'}" title="${online ? 'Online' : 'Offline'}"></span>
    </div>`;
}

function cardHtml(t) {
  const busy = STATE.inFlight.has(t.id);
  const membersHtml = t.members.length
    ? t.members.map(deviceRowHtml).join('')
    : '<p class="conn-row__empty">No members assigned yet.</p>';

  let actions = '';
  if (t.status === 'pending') {
    actions = `
      <button class="card-btn card-btn--approve" data-action="approve" data-team="${t.id}" ${busy ? 'disabled' : ''}>
        <i class="fa-solid fa-check"></i> Approve
      </button>
      <button class="card-btn card-btn--decline" data-action="decline" data-team="${t.id}" ${busy ? 'disabled' : ''}>
        <i class="fa-solid fa-xmark"></i> Decline
      </button>`;
  } else if (t.status === 'connected') {
    actions = `
      <button class="card-btn card-btn--disconnect" data-action="disconnect" data-team="${t.id}" ${busy ? 'disabled' : ''}>
        <i class="fa-solid fa-plug-circle-xmark"></i> Disconnect
      </button>`;
  }

  const onlineCount = t.members.filter(m => m.status === 'connected').length;

  return `
    <div class="team-card" data-team-card="${t.id}">
      <div class="team-card__header">
        <div>
          <div class="team-card__name">${escHtml(t.name)}</div>
          <div class="team-card__meta">
            <span class="status-badge status-badge--${t.status}">
              <span class="status-badge__dot"></span>
              ${statusLabel(t.status)}
            </span>
            <span class="team-card__member-count">${onlineCount}/${t.members.length} online</span>
          </div>
        </div>
      </div>
      <div class="team-card__body">
        <div class="conn-row__label">
          <i class="fa-solid fa-mobile-screen"></i>
          <span>Devices</span>
        </div>
        <div class="conn-row__players">${membersHtml}</div>
      </div>
      ${actions ? `<div class="team-card__actions">${actions}</div>` : ''}
    </div>`;
}

function render() {
  renderStats(computeStats());

  const grid = $('conn-grid');
  const empty = $('conn-empty');
  if (!grid) return;

  const list = visibleTeams();

  if (!STATE.noSession) {
    grid.innerHTML = list.map(cardHtml).join('');
  }

  if (empty) {
    if (!STATE.noSession && list.length === 0) {
      empty.hidden = false;
      empty.classList.remove('empty-state--nosession');
      const title = empty.querySelector('.empty-state__title');
      const sub = empty.querySelector('.empty-state__sub');
      if (title) {
        title.textContent = STATE.teams.length === 0
          ? 'No Connections Yet'
          : (STATE.filter !== 'all' ? `No ${STATE.filter} connections` : 'No matching connections');
      }
      if (sub) {
        sub.textContent = STATE.teams.length === 0
          ? 'Create teams and connect their phones to see device presence here.'
          : 'Try a different filter or search term.';
      }
    } else {
      empty.hidden = true;
    }
  }

  if (!STATE.noSession && STATE.teams.length === 0 && !empty.hidden) {
    // Empty state already visible; nothing more to do.
  }
}

/* ============================================================
   ACTIONS
============================================================ */
async function decideConnection(teamId, approve) {
  const gameId = rosterGameId || API.getGameId();
  const team = STATE.teams.find(t => String(t.id) === String(teamId));
  if (!team || !gameId) return;
  if (STATE.inFlight.has(team.id)) return;

  STATE.inFlight.add(team.id);
  render();
  try {
    if (approve) {
      await TeamAPI.approveConnection(gameId, team.id);
      team.connectionStatus = 'CONNECTED';
      showToast(`"${team.name}" is now connected`);
    } else {
      await TeamAPI.declineConnection(gameId, team.id);
      team.connectionStatus = 'DECLINED';
      showToast(`Connection request from "${team.name}" declined`);
    }
  } catch (e) {
    console.warn('[connections] decision failed', e && e.message);
    showToast(approve ? 'Could not approve connection' : 'Could not decline connection');
  } finally {
    team.status = connectionToCardStatus(team.connectionStatus);
    STATE.inFlight.delete(team.id);
    render();
  }
}

async function disconnectTeam(teamId) {
  const gameId = rosterGameId || API.getGameId();
  const team = STATE.teams.find(t => String(t.id) === String(teamId));
  if (!team || !gameId) return;
  if (STATE.inFlight.has(team.id)) return;

  const confirmed = await Confirm.open({
    title:        `Disconnect "${team.name}"?`,
    body:         'Players on this team will need to request a new connection.',
    confirmLabel: 'Disconnect',
    icon:         'disconnect',
    destructive:  true,
    requestKey:   `disconnect-team-${team.id}`,
  });
  if (!confirmed) return;

  STATE.inFlight.add(team.id);
  render();
  try {
    await TeamAPI.disconnectConnection(gameId, team.id);
    team.connectionStatus = 'DISCONNECTED';
    showToast(`"${team.name}" disconnected`);
  } catch (e) {
    console.warn('[connections] disconnect failed', e && e.message);
    showToast('Could not disconnect team');
  } finally {
    team.status = connectionToCardStatus(team.connectionStatus);
    STATE.inFlight.delete(team.id);
    render();
  }
}

function handleActionClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const teamId = btn.getAttribute('data-team');
  const action = btn.getAttribute('data-action');
  if (action === 'approve') decideConnection(teamId, true);
  else if (action === 'decline') decideConnection(teamId, false);
  else if (action === 'disconnect') disconnectTeam(teamId);
}
document.addEventListener('click', handleActionClick);

/* ============================================================
   ROSTER LOADING
============================================================ */
async function refreshRoster() {
  const gameId = rosterGameId || API.getGameId();
  if (!gameId || STATE.refreshing) return;
  STATE.refreshing = true;
  try {
    const roster = await TeamAPI.listTeams(gameId);
    seedRoster((roster && Array.isArray(roster.teams)) ? roster.teams : []);
  } catch (e) {
    console.warn('[connections] roster refresh failed', e && e.message);
  } finally {
    STATE.refreshing = false;
  }
}

async function refreshRosterFromUI() {
  const btn = $('btn-refresh-connections');
  if (btn) btn.disabled = true;
  await refreshRoster();
  showToast('Connections refreshed');
  if (btn) btn.disabled = false;
}

/* ============================================================
   NO-SESSION STATE
============================================================ */
function showNoSessionState() {
  STATE.noSession = true;
  const grid = $('conn-grid');
  const empty = $('conn-empty');
  if (!empty) return;
  empty.hidden = false;
  empty.classList.add('empty-state--nosession');
  if (grid) grid.innerHTML = '';
  const title = empty.querySelector('.empty-state__title');
  const sub = empty.querySelector('.empty-state__sub');
  const btn = empty.querySelector('.empty-state__btn');
  if (title) title.textContent = 'Game session not found';
  if (sub) sub.textContent = 'No host game is active in this browser. Return to the Host Dashboard to recover your game, or create a new one from the lobby.';
  if (btn) {
    btn.classList.remove('controls-btn--refresh');
    btn.innerHTML = '<i class="fa-solid fa-gauge-high"></i> Go to Host Dashboard';
    btn.replaceWith(btn.cloneNode(true));
    const fresh = empty.querySelector('.empty-state__btn');
    fresh.addEventListener('click', () => {
      window.location.href = 'host_dashboard.html';
    });
  }
}

/* ============================================================
   REVEAL ANIMATIONS
============================================================ */
(function initReveal() {
  const els = document.querySelectorAll('.reveal');
  if (!els.length) return;
  if (typeof IntersectionObserver === 'undefined') {
    els.forEach(el => el.classList.add('visible'));
    return;
  }
  const io = new IntersectionObserver((entries) => {
    entries.forEach(en => {
      if (en.isIntersecting) { en.target.classList.add('visible'); io.unobserve(en.target); }
    });
  }, { threshold: 0.15 });
  els.forEach(el => io.observe(el));
})();

/* ============================================================
   CONTROLS (search / filter / refresh)
============================================================ */
(function initControls() {
  const search = $('conn-search-input');
  if (search) {
    search.addEventListener('input', () => { STATE.query = search.value; render(); });
  }
  const filter = $('conn-filter-select');
  if (filter) {
    filter.addEventListener('change', () => { STATE.filter = filter.value; render(); });
  }
  const refreshBtn = $('btn-refresh-connections');
  if (refreshBtn) refreshBtn.addEventListener('click', () => refreshRosterFromUI());
  const emptyBtn = $('btn-refresh-empty');
  if (emptyBtn) emptyBtn.addEventListener('click', () => refreshRosterFromUI());

  const copyBtn = $('btn-copy-code');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const code = $('game-code-display');
      if (code && code.textContent) copyText(code.textContent);
    });
  }
})();

// Keep the roster honest on tab focus / visibility changes even with no events.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refreshRoster();
});
window.addEventListener('focus', () => refreshRoster());

/* ============================================================
   BOOTSTRAP
============================================================ */
(async function bootstrapConnections() {
  const diagToken = API.getHostToken ? (API.getHostToken() ? 'present' : 'missing') : 'n/a';
  const diagGameId = API.getGameId();
  const diagHostGameId = API.getHostGameId();
  const diagGameCode = API.getGameCode();
  const diagBase = API.getBaseUrl ? API.getBaseUrl() : 'n/a';
  console.log('[connections] bootstrap', {
    host_token: diagToken,
    game_id: diagGameId,
    host_game_id: diagHostGameId,
    game_code: diagGameCode,
    teams_api_url: diagGameId ? `${diagBase}/games/${diagGameId}/teams` : '(no game_id)',
  });

  let gameId = diagGameId || diagHostGameId;

  try {
    const r = await Connect.restoreHostSession();
    if (r.status === 'connected' && r.data && r.data.game_id) {
      gameId = r.data.game_id;
    }
    if (r.status === 'invalid' || r.status === 'unavailable') {
      Connect.showReconnectBanner({
        title: 'Host session not found',
        message: 'Your host session could not be restored. Reconnect to your game.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
    }
  } catch (e) { /* ignore */ }

  if (!gameId) {
    console.warn('[connections] no host game session; showing "Game session not found"', { diagGameId, diagHostGameId });
    showNoSessionState();
    return;
  }

  if (!diagGameId && gameId) {
    if (API.setGameId) API.setGameId(gameId);
    if (API.setHostGameId) API.setHostGameId(gameId);
    rosterGameId = gameId;
  }

  const code = API.getGameCode();
  if (code) {
    const codeEl = $('game-code-display');
    if (codeEl) codeEl.textContent = code;
  }

  rosterGameId = gameId;

  try {
    const roster = await TeamAPI.listTeams(gameId);
    console.log('[connections] roster response', {
      game_id: gameId,
      count: (roster && Array.isArray(roster.teams)) ? roster.teams.length : 0,
    });
    seedRoster((roster && Array.isArray(roster.teams)) ? roster.teams : []);
  } catch (e) { console.warn('[connections] roster offline', e.message); }

  initRealtime(gameId);
  updateRoundNav(gameId);
})();

/* ============================================================
   ROUND NAV
============================================================ */
async function updateRoundNav(gameId) {
  const roundEl = $('round-number');
  if (!roundEl || !gameId) return;
  try {
    const status = await GameAPI.status(gameId);
    roundEl.textContent = String((status && status.current_round) || 1);
  } catch (e) { /* keep current label */ }
}

/* ============================================================
   REALTIME PRESENCE (host connections page)
   ------------------------------------------------------------
   Connects the HOST socket and reflects live team/member state
   from the backend presence + connection events onto STATE, then
   re-renders. Events carry only public data.
============================================================ */
function initRealtime(gameId) {
  const rt = window.Realtime;
  rosterGameId = rosterGameId || gameId;
  if (!rt || !gameId) return;

  function ensureTeam(teamId) {
    let team = STATE.teams.find(t => String(t.id) === String(teamId));
    if (!team) {
      team = {
        id: teamId,
        name: 'Team ' + teamId,
        connectionStatus: 'NOT_CONNECTED',
        leaderName: null,
        members: [],
        status: 'none',
      };
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
      m = { id: payload.member_id, name: '', role: 'Tagasagot', leader: false, status: 'disconnected' };
      team.members.push(m);
    }
    if (payload.username) m.name = payload.username;
    if (payload.device_role) m.leader = String(payload.device_role).toUpperCase() === 'TEAM_LEADER';
    if (payload.gameplay_role) m.role = gameplayRole(payload.gameplay_role);
    m.status = payload.is_connected ? 'connected' : 'disconnected';
    return m;
  }
  function applyConnectionStatus(team, cs) {
    team.connectionStatus = cs || 'NOT_CONNECTED';
    team.status = connectionToCardStatus(team.connectionStatus);
    return team;
  }

  const reRender = () => {
    try { render(); } catch (e) {}
  };

  rt.on('member_joined', (p) => {
    if (!p || !p.member) return;
    const team = ensureTeam(p.member.team_id || p.team_id);
    upsertMember(team, p.member);
    reRender();
  });
  rt.on('team_connected', (p) => {
    if (!p || !p.member) return;
    const team = ensureTeam(p.member.team_id || p.team_id);
    const m = upsertMember(team, p.member);
    m.status = 'connected';
    reRender();
  });
  rt.on('member_left', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m) m.status = 'disconnected';
    reRender();
  });
  rt.on('team_disconnected', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m) m.status = 'disconnected';
    reRender();
  });
  rt.on('role_updated', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m && p.gameplay_role) m.role = gameplayRole(p.gameplay_role);
    reRender();
  });
  rt.on('team_updated', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    reRender();
  });

  rt.on('member_updated', (p) => {
    if (!p) return;
    const team = ensureTeam(p.team_id);
    const m = memberById(team, p.member_id);
    if (m && p.username) m.name = p.username;
    reRender();
  });
  rt.on('connection_requested', (p) => {
    if (!p || !p.team_id) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    applyConnectionStatus(team, p.connection_status || 'CONNECTION_REQUESTED');
    reRender();
    showToast(`"${team.name}" wants to connect`);
  });
  rt.on('connection_approved', (p) => {
    if (!p || !p.team_id) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    applyConnectionStatus(team, p.connection_status || 'CONNECTED');
    reRender();
    showToast(`"${team.name}" is now connected`);
  });
  rt.on('connection_declined', (p) => {
    if (!p || !p.team_id) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    applyConnectionStatus(team, p.connection_status || 'DECLINED');
    reRender();
  });
  rt.on('connection_disconnected', (p) => {
    if (!p || !p.team_id) return;
    const team = ensureTeam(p.team_id);
    if (p.team_name) team.name = p.team_name;
    applyConnectionStatus(team, p.connection_status || 'DISCONNECTED');
    reRender();
  });

  ['round_started', 'round_completed', 'game_started', 'game_paused',
   'game_resumed', 'game_completed', 'match_started'].forEach((evt) => {
    rt.on(evt, () => { updateRoundNav(rosterGameId || gameId); });
  });

  if (!rt.getSocket()) {
    rt.connect({ mode: 'host' });
    rt.onConnect(() => { refreshRoster(); reRender(); showToast('Realtime connected'); });
    rt.onReconnect(() => { refreshRoster(); reRender(); showToast('Realtime reconnected'); });
    rt.onDisconnect(() => { showToast('Realtime disconnected'); });
  }
}

if (typeof window !== 'undefined') window.ConnectionsPage = {
  state: STATE,
  seedRoster,
  render,
  refreshRoster,
  decideConnection,
  disconnectTeam,
};