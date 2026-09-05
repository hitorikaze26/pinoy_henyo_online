'use strict';

/* ============================================================
   GAME STATE
   Fallback/demo defaults only — replaced by live backend data.
============================================================ */
const STATE = {
  round:       1,
  gameCode:    '',        // real value set by backend bootstrap
  qrDataUri:   null,    // real backend QR image (data URI), cached after bootstrap
  soundOn:     true,

  // Timer
  timerTotal:  0,   // seconds (set by backend)
  timerLeft:   0,
  timerRunning: false,
  timerInterval: null,

  // Active team index (index into STATE.teams)
  activeTeamIndex: 0,

  // Teams (empty — real roster loaded from backend)
  teams: [],

  // Word bank (empty — real words come per turn from the backend)
  wordBank: [],

  // Current word index into wordBank
  wordIndex: 0,

  // Per-turn counters (reset each turn; real values from backend)
  wordsCorrect: 0,
  wordsPassed:  0,
  wordsTotal:   0,
};

/* ============================================================
   DOM REFERENCES
============================================================ */
const $ = id => document.getElementById(id);

const DOM = {
  // Nav
  roundNumber:    $('round-number'),
  gameCodeDisplay: $('game-code-display'),
  copyCodeBtn:    $('btn-copy-code'),
  copyIcon:       $('copy-icon'),

  // Control panel
  currentCategory: $('current-category'),
  currentWord:     $('current-word'),
  teamSelect:      $('team-select'),
  btnSound:        $('btn-sound'),
  soundIcon:       $('sound-icon'),
  btnSetTime:      $('btn-set-time'),
  btnPenalty:      $('btn-penalty'),
  btnPausePlay:    $('btn-pause-play'),
  pauseIcon:       $('pause-icon'),
  btnBonus:        $('btn-bonus'),
  btnStop:         $('btn-stop'),
  btnCorrect:      $('btn-correct'),
  btnPass:         $('btn-pass'),
  teamStatusGrid:  $('team-status-grid'),

  // Timer
  timerDisplay:   $('timer-display'),
  timerPanel:     $('timer-display-panel'),
  timerState:     $('timer-state'),
  timerCard:      $('timer-card'),
  btnTimerReset:  $('btn-timer-reset'),

  // Progress
  wordsCorrectEl: $('words-correct'),
  wordsTotalEl:   $('words-total'),
  progressBar:    $('progress-bar'),
  progressPct:    $('progress-pct'),
  currentScore:   $('current-score'),
  currentPenalties: $('current-penalties'),
  currentPasses:  $('current-passes'),

  // Word queue
  wordQueue:      $('word-queue'),

  // Leaderboard
  leaderboardList: $('leaderboard-list'),

  // QR card
  qrVisual:       $('qr-visual'),
  qrCodeLabel:    $('qr-code-label'),

  // Connection bar
  connectedCount:     $('connected-count'),
  totalCount:         $('total-count'),
  connectionTeamChips: $('connection-team-chips'),
  btnShowQr:          $('btn-show-qr'),

  // Set Time Modal
  modalSetTime:   $('modal-set-time'),
  inputMinutes:   $('input-minutes'),
  inputSeconds:   $('input-seconds'),
  btnConfirmTime: $('btn-confirm-time'),
  btnCancelTime:  $('btn-cancel-time'),
  closeSetTime:   $('close-set-time'),

  // All Teams Modal
  modalAllTeams:  $('modal-all-teams'),
  allTeamsTbody:  $('all-teams-tbody'),
  btnViewAllTeams: $('btn-view-all-teams'),
  closeAllTeams:  $('close-all-teams'),
  btnCloseAllTeams: $('btn-close-all-teams'),

  // QR Display Modal
  modalQrDisplay: $('modal-qr-display'),
  qrModalGrid:    $('qr-modal-grid'),
  qrModalCodeText: $('qr-modal-code-text'),
  btnCopyModalCode: $('btn-copy-modal-code'),
  closeQrDisplay: $('close-qr-display'),
  btnCloseQrDisplay: $('btn-close-qr-display'),

  // Connection Approval Modal
  modalApproveConnection: $('modal-approve-connection'),
  approveConnectionTitle: $('approve-connection-title'),
  approveConnectionDetails: $('approve-connection-details'),
  approveTeamName:  $('approve-team-name'),
  approveLeaderName: $('approve-leader-name'),
  approveMemberCount: $('approve-member-count'),
  btnApproveConnection: $('btn-approve-connection'),
  btnDeclineConnection: $('btn-decline-connection'),
  closeApproveConnection: $('close-approve-connection'),

  // Sidebar nav
  btnBackLobby: $('btn-back-lobby'),
};

/* ============================================================
   UTILITIES
============================================================ */

/** Format seconds → "M:SS" */
function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Create a ripple at click position inside a button */
function addRipple(btn, e) {
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x    = (e.clientX - rect.left) - size / 2;
  const y    = (e.clientY - rect.top)  - size / 2;
  const r    = document.createElement('span');
  r.className = 'ripple';
  r.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px;`;
  const old = btn.querySelector('.ripple');
  if (old) old.remove();
  btn.appendChild(r);
  r.addEventListener('animationend', () => r.remove());
}

/** Attach ripple to every interactive button on the page */
document.querySelectorAll(
  '.ctrl-btn, .action-btn, .timer-btn, .leaderboard-view-all, ' +
  '.connection-bar__qr-btn, .dash-nav__code-btn, .dash-nav__back-btn, ' +
  '.dash-modal__confirm, .preset-btn, .sidebar__logout-btn, .sidebar__nav-item'
).forEach(btn => btn.addEventListener('click', e => addRipple(btn, e)));

/** Escape HTML so user-provided strings can be safely embedded in toast HTML */
function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Reflect the timer state on the display panel + status pill.
    state: 'ready' | 'running' | 'paused' | 'warning' | 'critical' */
function setTimerState(state, label) {
  const panel = DOM.timerPanel;
  const pill  = DOM.timerState;
  ['ready', 'running', 'paused', 'warning', 'critical'].forEach(c => {
    if (panel) panel.classList.remove(c);
    if (pill)  pill.classList.remove(c);
  });
  if (panel) panel.classList.add(state);
  if (pill)  pill.classList.add(state);
  const fallback = { ready: 'Ready', running: 'Running', paused: 'Paused', warning: 'Hurry up!', critical: 'Last 10s' };
  if (pill) pill.textContent = label || fallback[state] || '';
}

/** Show a brief toast message (HTML-aware so FA icons render) */
function showToast(msg) {
  let toast = document.querySelector('.copy-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'copy-toast';
    document.body.appendChild(toast);
  }
  toast.innerHTML = msg;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), 2000);
}

/** Animate a numeric element (count-up) */
function animateCount(el, from, to, duration = 400) {
  const start = performance.now();
  const diff  = to - from;
  function step(now) {
    const pct  = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - pct, 3); // ease-out-cubic
    el.textContent = Math.round(from + diff * ease);
    if (pct < 1) requestAnimationFrame(step);
    else { el.textContent = to; el.classList.add('score-pop'); }
  }
  requestAnimationFrame(step);
  el.addEventListener('animationend', () => el.classList.remove('score-pop'), { once: true });
}

/* ============================================================
   MODAL HELPERS
============================================================ */
function openModal(overlay) {
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  const first = overlay.querySelector('input, button:not(.dash-modal__close)');
  if (first) setTimeout(() => first.focus(), 60);
}

function closeModal(overlay) {
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
}

// Close on backdrop click
document.querySelectorAll('.dash-modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) closeModal(o); });
});

// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.dash-modal-overlay.open').forEach(o => closeModal(o));
});

/* ============================================================
   CATEGORY ICON HELPER
   Maps category key → inline icon HTML (SVG asset or FA)
============================================================ */
const CATEGORY_ICONS = {
  person: `<img src="../../assets/svg/human-cannonball-circus-svgrepo-com.svg" class="cat-icon" alt="">`,
  object: `<img src="../../assets/svg/things-broom-svgrepo-com.svg"            class="cat-icon" alt="">`,
  animal: `<img src="../../assets/svg/animal-dog-domestic-svgrepo-com.svg"     class="cat-icon" alt="">`,
  food:   `<img src="../../assets/svg/food-gyoza-japanese-food-svgrepo-com.svg" class="cat-icon" alt="">`,
  place:  `<img src="../../assets/svg/place-hospital-svgrepo-com.svg"          class="cat-icon" alt="">`,
};

function getCategoryIcon(key) {
  return CATEGORY_ICONS[key] || `<i class="fa-solid fa-tag cat-icon-fa"></i>`;
}

/** Render leaderboard sorted by score desc */
function renderLeaderboard() {
  if (!STATE.teams || !STATE.teams.length) {
    DOM.leaderboardList.innerHTML = '<li class="lb-item">No teams yet</li>';
    return;
  }
  const sorted = [...STATE.teams]
    .map((t, i) => ({ ...t, originalIndex: i }))
    .sort((a, b) => b.score - a.score || a.penalties - b.penalties);

  const activeTeam = (STATE.teams[STATE.activeTeamIndex] || {}).name;

  const medalImgs = [
    `<img src="../../assets/svg/gold-medal.svg"   class="lb-medal-img" alt="Gold">`,
    `<img src="../../assets/svg/silver-medal.svg" class="lb-medal-img" alt="Silver">`,
    `<img src="../../assets/svg/bronze-medal.svg" class="lb-medal-img" alt="Bronze">`,
  ];

  DOM.leaderboardList.innerHTML = sorted.map((team, rank) => {
    const isActive   = team.name === activeTeam;
    const medals     = ['gold', 'silver', 'bronze'];
    const medalClass = rank < 3 ? `lb-medal--${medals[rank]}` : 'lb-medal--plain';
    const rankLabel  = rank < 3 ? medalImgs[rank] : rank + 1;
    const penClass   = team.penalties > 0 ? '' : 'lb-pen--zero';

    return `
      <li class="lb-item ${isActive ? 'lb-item--active' : ''}" aria-label="${team.name}, rank ${rank+1}">
        <span class="lb-medal ${medalClass}" aria-hidden="true">${rankLabel}</span>
        <span class="lb-team-name">${team.name}</span>
        <span class="lb-score-wrap">
          <span class="lb-pts">${team.score} pts</span>
          <span class="lb-pen ${penClass}">${team.penalties} pen</span>
        </span>
      </li>`;
  }).join('');
}

/** Render team status chips in left column */
function renderTeamStatus() {
  DOM.teamStatusGrid.innerHTML = STATE.teams.map(team => {
    const dotClass = team.connected ? 'team-status-chip__dot--online' : 'team-status-chip__dot--offline';
    return `
      <div class="team-status-chip">
        <span class="team-status-chip__dot ${dotClass}" aria-hidden="true"></span>
        <span>${team.name}</span>
        <span class="team-status-chip__score">Score: ${team.score}</span>
      </div>`;
  }).join('');
}

/** Render connection chips in bottom bar */
function renderConnectionBar() {
  const connected = STATE.teams.filter(t => t.connected).length;
  DOM.connectedCount.textContent = connected;
  DOM.totalCount.textContent     = STATE.teams.length;

  DOM.connectionTeamChips.innerHTML = STATE.teams.map(team => {
    const dotClass = team.connected ? 'conn-chip__dot--online' : 'conn-chip__dot--offline';
    return `
      <div class="conn-chip">
        <span class="conn-chip__dot ${dotClass}" aria-hidden="true"></span>
        ${team.name}
      </div>`;
  }).join('');
}

/** Render the upcoming word queue — first item is highlighted as "next" */
function renderWordQueue() {
  if (!STATE.wordBank || !STATE.wordBank.length) {
    DOM.wordQueue.innerHTML = '<div class="queue-item">No words yet</div>';
    return;
  }
  const items = [];
  for (let i = 1; i <= 3; i++) {
    const idx   = (STATE.wordIndex + i) % STATE.wordBank.length;
    const entry = STATE.wordBank[idx];
    const isNext = i === 1;
    items.push(`
      <div class="queue-item${isNext ? ' queue-item--next' : ''}">
        <span class="queue-item__index">${isNext ? '→' : i}</span>
        <span>${escHtml(entry.word)}</span>
        ${isNext ? '<span class="queue-item__tag">NEXT</span>' : ''}
      </div>`);
  }
  DOM.wordQueue.innerHTML = items.join('');
}

/** Set the current word + category */
function renderCurrentWord(animate = true) {
  const current = STATE.wordBank && STATE.wordBank[STATE.wordIndex];
  if (!current) {
    DOM.currentWord.textContent = '—';
    if (DOM.currentCategory) DOM.currentCategory.innerHTML = '<span>No current word</span>';
    return;
  }

  if (animate) {
    DOM.currentWord.classList.remove('word-reveal');
    void DOM.currentWord.offsetWidth;
    DOM.currentWord.classList.add('word-reveal');
  }

  DOM.currentWord.textContent = current.word;

  // Category with icon
  DOM.currentCategory.innerHTML =
    `${getCategoryIcon(current.category)}<span>${current.categoryLabel}</span>`;
}

/** Sync the team select and per-turn stat displays */
function renderActiveTeam() {
  // Keep select in sync with STATE
  if (DOM.teamSelect.value !== String(STATE.activeTeamIndex)) {
    DOM.teamSelect.value = STATE.activeTeamIndex;
  }

  const team = STATE.teams && STATE.teams[STATE.activeTeamIndex];
  if (!team) {
    if (DOM.currentScore) DOM.currentScore.textContent = '0';
    if (DOM.currentPenalties) DOM.currentPenalties.textContent = '0';
    if (DOM.currentPasses) DOM.currentPasses.textContent = '0';
    return;
  }
  const prevScore = parseInt(DOM.currentScore.textContent, 10);
  if (prevScore !== team.score) {
    animateCount(DOM.currentScore, prevScore, team.score);
  } else {
    DOM.currentScore.textContent = team.score;
  }
  DOM.currentPenalties.textContent = team.penalties;
  DOM.currentPasses.textContent    = team.passes;
}

/** Render the progress bar for current turn */
function renderProgress() {
  const total   = STATE.wordsTotal;
  const correct = STATE.wordsCorrect;
  const pct     = total > 0 ? Math.round((correct / total) * 100) : 0;

  DOM.wordsCorrectEl.textContent  = correct;
  DOM.wordsTotalEl.textContent    = total;
  DOM.progressBar.style.width     = `${pct}%`;
  DOM.progressBar.parentElement.setAttribute('aria-valuenow', pct);
  DOM.progressPct.textContent     = `${pct}%`;
}

/** Render the decorative QR grid (pseudo-random but deterministic) */
function renderQrGrid(containerEl, code) {
  // Simple seeded pseudo-random for consistent pattern per code
  let seed = 0;
  for (let i = 0; i < code.length; i++) seed += code.charCodeAt(i);
  function rand() {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  }

  // Always-filled corner squares (finder patterns)
  const SIZE = 7;
  const total = SIZE * SIZE;
  const corners = new Set();

  // Top-left 3×3
  [0,1,2,7,8,9,14,15,16].forEach(i => corners.add(i));
  // Top-right 3×3
  [4,5,6,11,12,13,18,19,20].forEach(i => corners.add(i));
  // Bottom-left 3×3
  [28,29,30,35,36,37,42,43,44].forEach(i => corners.add(i));

  let html = '';
  for (let i = 0; i < total; i++) {
    const filled = corners.has(i) || rand() > 0.42;
    html += `<div class="qr-pixel${filled ? '' : ' qr-pixel--empty'}"></div>`;
  }

  containerEl.innerHTML = html;
}

/** Render All Teams Modal table */
function renderAllTeamsTable() {
  const sorted = [...STATE.teams]
    .map((t, i) => ({ ...t, originalIndex: i }))
    .sort((a, b) => b.score - a.score);

  const medalImgsSm = [
    `<img src="../../assets/svg/gold-medal.svg"   class="lb-medal-img lb-medal-img--sm" alt="Gold">`,
    `<img src="../../assets/svg/silver-medal.svg" class="lb-medal-img lb-medal-img--sm" alt="Silver">`,
    `<img src="../../assets/svg/bronze-medal.svg" class="lb-medal-img lb-medal-img--sm" alt="Bronze">`,
  ];

  DOM.allTeamsTbody.innerHTML = sorted.map((team, rank) => {
    const rankDisplay = rank < 3
      ? medalImgsSm[rank]
      : `<span class="rank-badge" style="color:rgba(255,255,255,0.35)">${rank + 1}</span>`;

    const connIcon = team.connected
      ? `<span style="color:var(--secondary-400)">● Connected</span>`
      : `<span style="color:var(--gray-600)">○ Offline</span>`;

    return `
      <tr>
        <td>${rankDisplay}</td>
        <td style="font-weight:700;color:#fff">${team.name}</td>
        <td style="color:var(--primary-300);font-weight:700">${team.score}</td>
        <td style="color:var(--accent-2-400)">${team.penalties}</td>
        <td style="color:var(--gray-400)">${team.passes}</td>
        <td>${connIcon}</td>
      </tr>`;
  }).join('');
}

/* ============================================================
   TIMER
============================================================ */
function updateTimerDisplay() {
  DOM.timerDisplay.textContent = formatTime(STATE.timerLeft);

  if (STATE.timerLeft <= 0) {
    DOM.timerDisplay.textContent = '0:00';
    stopTimer();
    onTimerEnd();
    return;
  }

  if (STATE.timerRunning) {
    if (STATE.timerLeft <= 10) {
      setTimerState('critical');
    } else if (STATE.timerLeft <= 20) {
      setTimerState('warning');
    } else {
      setTimerState('running');
    }
  } else {
    setTimerState('ready');
  }
}

function startTimer() {
  if (STATE.timerRunning || STATE.timerLeft <= 0) return;
  STATE.timerRunning = true;

  // btn-pause-play becomes a Pause button
  DOM.btnPausePlay.classList.add('playing');
  DOM.pauseIcon.className = 'fa-solid fa-pause';

  STATE.timerInterval = setInterval(() => {
    STATE.timerLeft = Math.max(0, STATE.timerLeft - 1);
    updateTimerDisplay();
  }, 1000);

  updateTimerDisplay();
}

function pauseTimer() {
  if (!STATE.timerRunning) return;
  STATE.timerRunning = false;
  clearInterval(STATE.timerInterval);
  STATE.timerInterval = null;

  // btn-pause-play becomes a Play/Start button
  DOM.btnPausePlay.classList.remove('playing');
  DOM.pauseIcon.className = 'fa-solid fa-play';

  setTimerState('paused');
}

function resetTimer() {
  pauseTimer();
  STATE.timerLeft = STATE.timerTotal;
  updateTimerDisplay();
}

function stopTimer() {
  pauseTimer();
}

function onTimerEnd() {
  setTimerState('critical', 'Time\u2019s up!');
  showToast('<i class="fa-regular fa-clock"></i> Time\u2019s up!');
  console.log('[Pinoy Henyo] Timer ended');
}

function setTimerDuration(totalSeconds) {
  STATE.timerTotal = totalSeconds;
  STATE.timerLeft  = totalSeconds;
  resetTimer();
}

// Timer button events
DOM.btnTimerReset.addEventListener('click', (e) => { addRipple(DOM.btnTimerReset, e); resetTimer(); });

// Central pause/play button in control panel
DOM.btnPausePlay.addEventListener('click', (e) => {
  addRipple(DOM.btnPausePlay, e);
  STATE.timerRunning ? pauseTimer() : startTimer();
});

/* ============================================================
   CORRECT / PASS / PENALTY / BONUS
============================================================ */

/** Advance to the next word */
function nextWord(animate = true) {
  STATE.wordIndex = (STATE.wordIndex + 1) % STATE.wordBank.length;
  renderCurrentWord(animate);
  renderWordQueue();
}

// Correct
DOM.btnCorrect.addEventListener('click', (e) => {
  addRipple(DOM.btnCorrect, e);

  const team = STATE.teams[STATE.activeTeamIndex];
  const prev = team.score;
  team.score += 1;

  STATE.wordsCorrect += 1;

  // Celebrate animation
  DOM.btnCorrect.classList.remove('celebrate');
  void DOM.btnCorrect.offsetWidth;
  DOM.btnCorrect.classList.add('celebrate');
  DOM.btnCorrect.addEventListener('animationend', () => DOM.btnCorrect.classList.remove('celebrate'), { once: true });

  // Animate score
  animateCount(DOM.currentScore, prev, team.score);

  renderProgress();
  renderLeaderboard();
  renderTeamStatus();

  showToast(`<i class="fa-solid fa-check"></i> Correct! +1 for ${escHtml(team.name)}`);
  console.log('[Pinoy Henyo] Correct →', team);

  nextWord(true);
});

// Pass
DOM.btnPass.addEventListener('click', (e) => {
  addRipple(DOM.btnPass, e);

  const team = STATE.teams[STATE.activeTeamIndex];
  team.passes   += 1;
  STATE.wordsPassed += 1;

  DOM.currentPasses.textContent = team.passes;
  renderTeamStatus();
  showToast(`<i class="fa-solid fa-forward"></i> Passed \u2014 ${escHtml(team.name)}`);
  console.log('[Pinoy Henyo] Pass →', team);

  nextWord(true);
});

// -3s time adjustment
DOM.btnPenalty.addEventListener('click', (e) => {
  addRipple(DOM.btnPenalty, e);
  STATE.timerLeft = Math.max(0, STATE.timerLeft - 3);
  updateTimerDisplay();
  showToast(`⏪ -3s`);
  console.log('[Pinoy Henyo] -3s → timerLeft:', STATE.timerLeft);
});

// +3s time adjustment
DOM.btnBonus.addEventListener('click', (e) => {
  addRipple(DOM.btnBonus, e);
  STATE.timerLeft = Math.min(STATE.timerLeft + 3, 599); // cap at 9:59
  updateTimerDisplay();
  showToast(`⏩ +3s`);
  console.log('[Pinoy Henyo] +3s → timerLeft:', STATE.timerLeft);
});

// Stop round
DOM.btnStop.addEventListener('click', (e) => {
  addRipple(DOM.btnStop, e);
  stopTimer();
  showToast('🛑 Round stopped');
  console.log('[Pinoy Henyo] Round stopped');
});

/* ============================================================
   TEAM SELECT DROPDOWN
============================================================ */
DOM.teamSelect.addEventListener('change', () => {
  STATE.activeTeamIndex = parseInt(DOM.teamSelect.value, 10);

  // Reset turn counters for new team
  STATE.wordsCorrect = 0;
  STATE.wordsPassed  = 0;

  renderActiveTeam();
  renderProgress();
  renderLeaderboard();
  renderTeamStatus();
  resetTimer();

  showToast(`<i class="fa-solid fa-arrows-rotate"></i> Now: ${escHtml(STATE.teams[STATE.activeTeamIndex].name)}`);
  console.log('[Pinoy Henyo] Active team →', STATE.teams[STATE.activeTeamIndex]);
});

/* ============================================================
   NEXT ROUND BUTTON
============================================================ */
document.getElementById('btn-next-round').addEventListener('click', (e) => {
  addRipple(document.getElementById('btn-next-round'), e);

  STATE.round += 1;

  // Update round number in nav
  DOM.roundNumber.textContent = STATE.round;

  // Update badge on the button
  document.getElementById('next-round-badge').textContent = `Round ${STATE.round + 1}`;

  // Reset turn counters for the new round
  STATE.wordsCorrect = 0;
  STATE.wordsPassed  = 0;
  STATE.wordIndex    = 0;

  renderCurrentWord(true);
  renderWordQueue();
  renderActiveTeam();
  renderProgress();
  resetTimer();

  showToast(`Round ${STATE.round} started`);
  console.log('[Pinoy Henyo] Next round →', STATE.round);

  // Keep leaderboard round badge in sync
  const roundBadge = document.querySelector('.leaderboard-card__round-badge');
  if (roundBadge) roundBadge.textContent = `Round ${STATE.round}`;
});

/* ============================================================
   RESET ROUND BUTTON
============================================================ */
document.getElementById('btn-reset-round').addEventListener('click', (e) => {
  addRipple(document.getElementById('btn-reset-round'), e);

  if (!confirm(`Reset Round ${STATE.round}?\n\nThis will:\n• Reset the timer\n• Reset word index to the first word\n• Clear correct/pass counters for the current turn\n\nScores will NOT be changed.`)) return;

  // Reset word index and turn counters — keep round number and scores intact
  STATE.wordIndex    = 0;
  STATE.wordsCorrect = 0;
  STATE.wordsPassed  = 0;

  renderCurrentWord(true);
  renderWordQueue();
  renderActiveTeam();
  renderProgress();
  resetTimer();

  showToast(`Round ${STATE.round} reset`);
  console.log('[Pinoy Henyo] Round reset →', STATE.round);
});
DOM.btnSound.addEventListener('click', () => {
  STATE.soundOn = !STATE.soundOn;
  DOM.soundIcon.className = STATE.soundOn
    ? 'fa-solid fa-volume-high'
    : 'fa-solid fa-volume-xmark';
  DOM.btnSound.title = STATE.soundOn ? 'Mute sound' : 'Unmute sound';
  showToast(STATE.soundOn ? '🔊 Sound on' : '🔇 Sound off');
});

/* ============================================================
   COPY GAME CODE
============================================================ */
function copyGameCode(code) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(code)
      .then(() => showToast(`<i class="fa-solid fa-clipboard-check"></i> Copied: ${escHtml(code)}`))
      .catch(() => showToast(`<i class="fa-solid fa-key"></i> Game code: ${escHtml(code)}`));
  } else {
    showToast(`<i class="fa-solid fa-key"></i> Game code: ${escHtml(code)}`);
  }
  // Brief icon swap feedback
  DOM.copyIcon.className = 'fa-solid fa-check';
  setTimeout(() => { DOM.copyIcon.className = 'fa-regular fa-copy'; }, 1800);
}

DOM.copyCodeBtn.addEventListener('click', () => copyGameCode(STATE.gameCode));

/* ============================================================
   SIDEBAR NAV (placeholder interaction)
============================================================ */
document.querySelectorAll('.sidebar__nav-item').forEach(item => {
  if (item.tagName === 'A' && item.href && !item.href.endsWith('#')) return; // real links navigate
  item.addEventListener('click', (e) => {
    e.preventDefault();
    document.querySelectorAll('.sidebar__nav-item').forEach(i => i.classList.remove('sidebar__nav-item--active'));
    item.classList.add('sidebar__nav-item--active');
    item.setAttribute('aria-current', 'page');
    showToast(`Coming soon: ${item.querySelector('span').textContent}`);
  });
});

/* ============================================================
   SET TIME MODAL
============================================================ */
DOM.btnSetTime.addEventListener('click', () => {
  const m = Math.floor(STATE.timerLeft / 60);
  const s = STATE.timerLeft % 60;
  DOM.inputMinutes.value = m;
  DOM.inputSeconds.value = s;
  openModal(DOM.modalSetTime);
});

DOM.closeSetTime.addEventListener('click',  () => closeModal(DOM.modalSetTime));
DOM.btnCancelTime.addEventListener('click', () => closeModal(DOM.modalSetTime));

// Preset buttons
document.querySelectorAll('.preset-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const secs = parseInt(btn.dataset.seconds, 10);
    DOM.inputMinutes.value = Math.floor(secs / 60);
    DOM.inputSeconds.value = secs % 60;
  });
});

DOM.btnConfirmTime.addEventListener('click', () => {
  const m    = Math.max(0, Math.min(9,  parseInt(DOM.inputMinutes.value, 10) || 0));
  const s    = Math.max(0, Math.min(59, parseInt(DOM.inputSeconds.value, 10) || 0));
  const total = m * 60 + s;
  if (total === 0) { showToast('⚠️ Please set a time greater than 0'); return; }
  setTimerDuration(total);
  closeModal(DOM.modalSetTime);
  showToast(`⏱️ Timer set to ${formatTime(total)}`);
});

/* ============================================================
   ALL TEAMS MODAL
============================================================ */
DOM.btnViewAllTeams.addEventListener('click', () => {
  renderAllTeamsTable();
  openModal(DOM.modalAllTeams);
});
DOM.closeAllTeams.addEventListener('click',     () => closeModal(DOM.modalAllTeams));
DOM.btnCloseAllTeams.addEventListener('click',  () => closeModal(DOM.modalAllTeams));

/* ============================================================
   QR CODE MODAL
============================================================ */
function openQrModal() {
  renderRealQr(DOM.qrModalGrid, STATE.qrDataUri);
  DOM.qrModalCodeText.textContent = STATE.gameCode;
  openModal(DOM.modalQrDisplay);
}

DOM.btnShowQr.addEventListener('click',      openQrModal);
DOM.closeQrDisplay.addEventListener('click', () => closeModal(DOM.modalQrDisplay));
DOM.btnCloseQrDisplay.addEventListener('click', () => closeModal(DOM.modalQrDisplay));

DOM.btnCopyModalCode.addEventListener('click', () => copyGameCode(STATE.gameCode));

/* ============================================================
   INITIAL RENDER
============================================================ */
function init() {
  // Nav
  DOM.roundNumber.textContent      = STATE.round;
  DOM.gameCodeDisplay.textContent  = STATE.gameCode;
  DOM.qrCodeLabel.textContent      = STATE.gameCode;

  // Populate team select dropdown
  DOM.teamSelect.innerHTML = STATE.teams.map((t, i) =>
    `<option value="${i}">${t.name}</option>`
  ).join('');
  DOM.teamSelect.value = STATE.activeTeamIndex;

  // Timer
  updateTimerDisplay();

  // Word + team + progress
  renderCurrentWord(false);
  renderActiveTeam();
  renderProgress();
  renderWordQueue();

  // Right column
  renderLeaderboard();

  // Bottom + team status
  renderTeamStatus();
  renderConnectionBar();

  // QR card decorative grid
  renderQrGrid(DOM.qrVisual, STATE.gameCode);
}

init();

/* ============================================================
   BACKEND INTEGRATION (host dashboard)
   When a host game context exists, load the real game identity
   (host-provided game code + status) so the displayed code, copy
   button and QR reflect the actual server game.
   ============================================================ */
(async function bootstrapDashboardIntegration() {
  const gameId = API.getGameId();
  if (!gameId) {
    // No game context at all — send back to lobby immediately.
    window.location.replace('../../index.html');
    return;
  }

  // Host reconnect guard.
  try {
    const r = await Connect.restoreHostSession();
    if (r.status === 'invalid') {
      // Token is wrong or game no longer exists — session already cleared by
      // restoreHostSession. Redirect to lobby; don't continue loading the page.
      Connect.showReconnectBanner({
        title: 'Host session not found',
        message: 'Your host session could not be restored. Create a new game from the lobby.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
      setTimeout(() => window.location.replace('../../index.html'), 2500);
      return;
    }
    if (r.status === 'unavailable') {
      // Server is unreachable — show banner but keep the page alive so the
      // host can wait for the server to come back.
      Connect.showReconnectBanner({
        title: 'Server unreachable',
        message: 'Could not reach the server. Check your connection and try again.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
    }
  } catch (e) { /* ignore */ }

  try {
    // Game code is only returned at creation; use the shared client context.
    const code = API.getGameCode() || (await GameAPI.status(gameId)).game_code;
    console.log('[HOST DASHBOARD]', {
      gameId,
      gameCode: code,
      teamsApiUrl: `${API.getBaseUrl()}/games/${gameId}/teams`,
    });
    if (code) {
      STATE.gameCode = code;
      if (DOM.gameCodeDisplay) DOM.gameCodeDisplay.textContent = STATE.gameCode;
      if (DOM.qrCodeLabel) DOM.qrCodeLabel.textContent = STATE.gameCode;
      if (DOM.qrModalCodeText) DOM.qrModalCodeText.textContent = STATE.gameCode;
      STATE.qrDataUri = await safeGameQr(gameId);
      if (DOM.qrModalGrid) renderRealQr(DOM.qrModalGrid, STATE.qrDataUri);
      if (DOM.qrVisual) renderRealQr(DOM.qrVisual, STATE.qrDataUri);
    }
    console.log('[dashboard] loaded real game code', STATE.gameCode);
  } catch (e) {
    console.warn('[dashboard] game status offline', e && e.message);
    if (e && e.status === 404) {
      // Game was deleted — clear session and redirect to lobby.
      API.clearTokens();
      Connect.showReconnectBanner({
        title: 'Game not found',
        message: 'This game no longer exists. Return to the lobby to create a new one.',
      });
      document.body.setAttribute('data-reconnect-target', '../../index.html');
      setTimeout(() => window.location.replace('../../index.html'), 2500);
    }
  }
})();

// Backend QR: backend generates a real PNG (data URI). Replace the demo grid.
async function safeGameQr(gameId) {
  try {
    const qr = await GameAPI.gameQr(gameId);
    return (qr && qr.qr_image) || null;
  } catch (e) {
    return null;
  }
}

// Render a backend QR image into a container (falls back to the demo grid).
function renderRealQr(container, dataUri) {
  if (!container) return;
  if (!dataUri) { renderQrGrid(container, STATE.gameCode); return; }
  container.innerHTML = '';
  container.style.cssText = 'background:#fff;padding:6px;border-radius:8px;display:flex;align-items:center;justify-content:center;';
  const img = document.createElement('img');
  img.src = dataUri;
  img.alt = 'Join QR';
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block;';
  container.appendChild(img);
}

/* ============================================================
   REAL GAMEPLAY INTEGRATION (host dashboard)
   ------------------------------------------------------------
   When a live host game context exists, this replaces the demo
   flow and drives real backend turns:
     - auto-assigns words + starts a turn (one-click "Start")
     - Correct / Pass / Timeout / Stop call the turn endpoints
     - -3s / +3s call the backend time adjustments (authoritative)
     - timer + scores are displayed from the server payload only
   The backend is always authoritative: no scoring or time math is
   invented on the client.
   ============================================================ */
(function gameplayIntegration() {
  const gameId = API.getGameId();
  if (!gameId) return; // no live game -> keep the demo preview

  const MIN_CORRECT = 3; // turn completes at 3 correct words
  const AUTO_WORDS  = 5; // MAX_WORDS_PER_TURN (backend caps at 5)
  const POLL_MS     = 1000; // light re-auth polling while a turn is active
  const TICK_MS     = 250;  // smooth local ticking between server payloads

  function rebind(id, handler, eventName) {
    const event = eventName || 'click';
    const el = document.getElementById(id);
    if (!el) return null;
    const fresh = el.cloneNode(true);
    el.replaceWith(fresh);
    fresh.addEventListener(event, handler);
    if (fresh.classList) fresh.classList.add('gp-bound');
    return fresh;
  }

  // Real team-name lookup (scores + known-teams registry).
  const teamNameOf = (() => {
    const map = {};
    const fn = (teamId) => map[teamId] || ('Team #' + teamId);
    fn.register = (id, name) => { if (id) map[id] = name; };
    return fn;
  })();

  let matches = [];
  let scores = [];
  let roster = [];          // real team roster [{team_id, team_name, members:[...]}]
  let activeMatch = null;
  let turn = null;          // latest turn_play_payload (server truth)
  let timerBase = { at: 0, remaining: 0, elapsed: 0 };
  let tickId = null;
  let pollId = null;

  const $ = (id) => document.getElementById(id);

  /* ---------- data loading ---------- */
  async function loadData() {
    const [scoreRes, matchRes] = await Promise.all([
      GameAPI.scores(gameId).catch(() => ({ scores: [] })),
      MatchAPI.listMatches(gameId).catch(() => ({ matches: [] })),
    ]);
    scores = (scoreRes && scoreRes.scores) || [];
    matches = (matchRes && matchRes.matches) || [];
    (scores || []).forEach((s) => {
      if (s.team_id && s.team_name) teamNameOf.register(s.team_id, s.team_name);
    });
    (API.getKnownTeams() || []).forEach((t) => {
      if (t.team_name) teamNameOf.register(t.team_id, t.team_name);
    });
  }

  function teamScore(teamId) {
    return scores
      .filter((s) => s.team_id === teamId)
      .reduce((acc, s) => acc + (s.points || 0), 0);
  }

  // Fetch the real team roster (names + real connection status).
  async function loadRoster() {
    try {
      const res = await TeamAPI.listTeams(gameId);
      roster = (res && res.teams) || [];
      // Pending teams whose live ``connection_requested`` event was missed
      // still need an approve/decline affordance.
      maybePromptPendingApprovals();
    } catch (e) {
      /* keep last known roster */
    }
  }

  // True if the team is CONNECTED to the host screen (host approval given).
  // Falls back to active member sockets only when the roster lacks the field.
  function teamConnected(teamId) {
    const r = roster.find((t) => t.team_id === teamId);
    if (!r) return false;
    if (typeof r.connection_status === 'string') return r.connection_status === 'CONNECTED';
    return !!(r.members || []).some((m) => m.is_connected);
  }

  function teamConnectionStatus(teamId) {
    const r = roster.find((t) => t.team_id === teamId);
    if (!r || typeof r.connection_status !== 'string') return 'OFFLINE';
    return r.connection_status;
  }

  function allRosterTeams() {
    return roster.slice().sort((a, b) => a.team_id - b.team_id);
  }

  // Authoritative roster merged with score data. A team is ALWAYS listed even
  // when it has no matches yet (lobby/setup stage); match-specific fields
  // default to empty values instead of dropping the team from the UI.
  function rankedTeams() {
    const totals = {};
    scores.forEach((s) => {
      const cur = totals[s.team_id] || { points: 0, penalties: 0, passes: 0 };
      totals[s.team_id] = {
        points: cur.points + (s.points || 0),
        penalties: cur.penalties + (s.penalty_seconds || 0),
        passes: cur.passes + (s.passed_words || 0),
      };
    });
    return allRosterTeams()
      .map((t) => {
        const row = totals[t.team_id] || { points: 0, penalties: 0, passes: 0 };
        return {
          team_id: t.team_id,
          team_name: t.team_name || teamNameOf(t.team_id),
          points: row.points,
          penalties: row.penalties,
          passes: row.passes,
        };
      })
      .sort((a, b) => (b.points - a.points) || (a.team_id - b.team_id));
  }

  // True when the team has at least one COMPLETED match (status-chip dot).
  function teamHasCompletedMatch(teamId) {
    return matches.some((m) => m.team_id === teamId && m.status === 'COMPLETED');
  }

  // Round-major ordering (matches of round 1 then round 2), then match_order.
  function orderedMatches() {
    return matches.slice().sort(
      (a, b) => (a.round_number - b.round_number) || (a.match_order - b.match_order)
    );
  }

  // Matches that still need to be played (not yet completed).
  function playableMatches() {
    return orderedMatches().filter((m) => m.status !== 'COMPLETED');
  }

  function currentRoundLabel() {
    if (!matches.length) return 'Round';
    const r = orderedMatches()[0].round_number;
    return 'Round ' + r;
  }

  /* ---------- turn helpers ---------- */
  function setActiveTurn(payload) {
    turn = payload;
    timerBase = {
      at: Date.now(),
      remaining: payload ? payload.remaining_seconds : 0,
      elapsed: payload ? payload.elapsed_seconds : 0,
    };
    if (tickId) { clearInterval(tickId); tickId = null; }
    if (pollId) { clearInterval(pollId); pollId = null; }
    if (payload && isTurnRunning(payload)) {
      tickId = setInterval(tickDisplay, TICK_MS);
      pollId = setInterval(pollTurn, POLL_MS);
    }
    renderAll();
  }

  function isTurnRunning(p) {
    return p && (p.status === 'ACTIVE' || p.status === 'PAUSED');
  }

  function activeTurnId() {
    return turn ? turn.turn_id : null;
  }

  // Host-authenticated turn fetch so the host always sees the full
  // (secret) payload, not the public view that blanks word text.
  async function hostTurn(turnId) {
    return API.request('/turns/' + turnId, { host: true });
  }

  // Server-authoritative re-auth while a turn is active/paused.
  async function pollTurn() {
    if (!turn || !activeTurnId()) return;
    try {
      const latest = await hostTurn(turn.turn_id);
      if (!latest) return;
      setActiveTurn(latest);
    } catch (e) { /* transient poll failure is fine */ }
  }

  /* ---------- server-authoritative timer display ---------- */
  function tickDisplay() {
    if (!turn) { setTimerText('0:00'); return; }
    const p = turn;
    const now = Date.now();
    const secondsSince = (now - timerBase.at) / 1000;
    const paused = p.status === 'PAUSED';
    if (p.timer_mode === 'COUNTUP') {
      const val = paused
        ? p.elapsed_seconds
        : Math.min(p.starting_seconds, timerBase.elapsed + secondsSince);
      setTimerText(formatTime(Math.round(val)), p);
    } else {
      const val = paused
        ? p.remaining_seconds
        : Math.max(0, timerBase.remaining - secondsSince);
      setTimerText(formatTime(Math.round(val)), p);
    }
  }

  function setTimerText(text, p) {
    const el = $('timer-display');
    if (!el) return;
    el.textContent = text;
    if (!p) { setTimerState('ready'); return; }
    if (p.status === 'PAUSED') { setTimerState('paused'); return; }
    if (!isTurnRunning(p)) { setTimerState('ready'); return; }
    const val = p.timer_mode === 'COUNTUP'
      ? (p.elapsed_seconds || 0)
      : (p.remaining_seconds || 0);
    const frac = p.starting_seconds ? val / p.starting_seconds : 0;
    if (p.timer_mode === 'COUNTUP') {
      if (val >= (p.starting_seconds || 0) || frac >= 0.9) setTimerState('warning');
      else setTimerState('running');
    } else {
      if (frac <= 0.2) setTimerState('critical');
      else if (frac <= 0.4) setTimerState('warning');
      else setTimerState('running');
    }
  }

  /* ---------- UI rendering ---------- */
  function renderSelect() {
    const sel = $('team-select');
    if (!sel) return;
    const playable = playableMatches();
    const options = playable.length
      ? playable.map((m) => {
          const opp = m.opponent_team_id
            ? (' vs ' + teamNameOf(m.opponent_team_id))
            : '';
          return '<option value="' + m.match_id + '">Round ' + m.round_number +
            ' - ' + teamNameOf(m.team_id) + opp + '</option>';
        })
      : ['<option value="">No pending matches</option>'];
    sel.innerHTML = options.join('');
    if (activeMatch) sel.value = String(activeMatch.match_id);
  }

  function renderCategory() {
    const el = $('current-category');
    if (!el) return;
    if (activeMatch) {
      const opp = activeMatch.opponent_team_id
        ? ' vs ' + teamNameOf(activeMatch.opponent_team_id)
        : '';
      el.innerHTML = '<i class="fa-solid fa-shield-halved"></i> ' +
        teamNameOf(activeMatch.team_id) + opp +
        ' <span style="opacity:.6">- Round ' + activeMatch.round_number + '</span>';
    } else {
      el.textContent = 'No active match';
    }
  }

  function renderWord() {
    const el = $('current-word');
    if (!el) return;
    if (turn && turn.current_word_text) {
      el.classList.remove('word-reveal');
      void el.offsetWidth;
      el.classList.add('word-reveal');
      el.textContent = turn.current_word_text;
    } else {
      el.textContent = '—';
    }
  }

  function renderQueue() {
    const el = $('word-queue');
    if (!el) return;
    if (!turn) { el.innerHTML = '<div class="queue-item" style="opacity:.6">No active turn</div>'; return; }
    const items = (turn.words || []).slice();
    el.innerHTML = items.map((w, i) => {
      const label = w.result === 'CORRECT' ? '✓' : (w.result === 'PASSED' ? '⏭' : (w.result === 'FAILED' ? '✗' : ''));
      const resCls = label
        ? ' queue-item__result--' + (label === '✓' ? 'correct' : label === '⏭' ? 'passed' : 'failed')
        : '';
      const cls = w.word_id === turn.current_word_id && !label ? ' queue-item--next' : '';
      return '<div class="queue-item' + cls + '">' +
        '<span class="queue-item__index">' + (label || (i + 1)) + '</span>' +
        '<span>' + (w.word_text || '...') + '</span>' +
        (label ? '<span class="queue-item__result' + resCls + '">' + label + '</span>' : '') +
        '</div>';
    }).join('');
  }

  function renderProgress() {
    const correct = turn ? (turn.correct_words || 0) : 0;
    const total = Math.max(MIN_CORRECT, (turn ? (turn.total_words || 0) : 0));
    const goal = Math.max(MIN_CORRECT, Math.min(total, MIN_CORRECT));
    const pct = Math.round((Math.min(correct, goal) / goal) * 100);
    const wordsCorrectEl = $('words-correct');
    const wordsTotalEl = $('words-total');
    const bar = $('progress-bar');
    const pctEl = $('progress-pct');
    if (wordsCorrectEl) wordsCorrectEl.textContent = String(correct);
    if (wordsTotalEl) wordsTotalEl.textContent = String(goal);
    if (bar) bar.style.width = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
  }

  function renderStats() {
    const scoreEl = $('current-score');
    const penEl = $('current-penalties');
    const passEl = $('current-passes');
    if (activeMatch) {
      const tid = activeMatch.team_id;
      const teamRows = scores.filter((s) => s.team_id === tid);
      const penalty = teamRows.reduce((a, s) => a + (s.penalty_seconds || 0), 0);
      const passed = turn ? (turn.passed_words || 0) : 0;
      if (scoreEl) scoreEl.textContent = String(teamScore(tid));
      if (penEl) penEl.textContent = String(penalty);
      if (passEl) passEl.textContent = String(passed);
    } else {
      if (scoreEl) scoreEl.textContent = '0';
      if (penEl) penEl.textContent = '0';
      if (passEl) passEl.textContent = '0';
    }
  }

  function renderTeamStatus() {
    const grid = $('team-status-grid');
    if (!grid) return;
    const rows = rankedTeams().slice(0, 8).map((t) => {
      const done = teamHasCompletedMatch(t.team_id);
      return '<div class="team-status-chip">' +
        '<span class="team-status-chip__dot ' + (done ? '' : 'team-status-chip__dot--online') + '"></span>' +
        '<span>' + t.team_name + '</span>' +
        '<span class="team-status-chip__score">' + t.points + ' pts</span>' +
        '</div>';
    });
    grid.innerHTML = rows.join('') || '<div class="team-status-chip">No teams</div>';
  }

  function renderLeaderboard() {
    const list = $('leaderboard-list');
    if (!list) return;
    const ranked = rankedTeams().sort((a, b) => b.points - a.points);

    const medals = ['gold', 'silver', 'bronze'];
    list.innerHTML = ranked.map((t, i) => {
      const isActive = activeMatch && t.team_id === activeMatch.team_id;
      const medalClass = i < 3 ? 'lb-medal--' + medals[i] : 'lb-medal--plain';
      const rankLabel = i < 3
        ? '<img src="../../assets/svg/' + medals[i] + '-medal.svg" class="lb-medal-img" alt="">'
        : String(i + 1);
      return '<li class="lb-item ' + (isActive ? 'lb-item--active' : '') + '">' +
        '<span class="lb-medal ' + medalClass + '" aria-hidden="true">' + rankLabel + '</span>' +
        '<span class="lb-team-name">' + t.team_name + '</span>' +
        '<span class="lb-score-wrap"><span class="lb-pts">' + t.points + ' pts</span></span>' +
        '</li>';
    }).join('') || '<li class="lb-item">No scores yet</li>';
  }

  function renderAllTeams() {
    const tbody = $('all-teams-tbody');
    if (!tbody) return;
    const rows = rankedTeams();
    tbody.innerHTML = rows.map((t, idx) => {
      const online = teamConnected(t.team_id);
      return '<tr><td>' + (idx + 1) + '</td>' +
        '<td style="font-weight:700;color:#fff">' + t.team_name + '</td>' +
        '<td style="color:var(--primary-300);font-weight:700">' + t.points + '</td>' +
        '<td style="color:var(--gray-400)">' + t.penalties + '</td>' +
        '<td style="color:var(--gray-600)">' + t.passes + '</td>' +
        '<td><span style="color:' + (online ? 'var(--secondary-400)' : 'var(--gray-500)') + '">' +
        (online ? '● Connected' : '○ Offline') + '</span></td></tr>';
    }).join('') || '<tr><td colspan="6">No teams</td></tr>';
  }

  function renderConnections() {
    const teams = allRosterTeams();
    const connected = teams.filter((t) => teamConnected(t.team_id)).length;
    const pending   = teams.filter((t) => teamConnectionStatus(t.team_id) === 'CONNECTION_REQUESTED').length;
    const connEl = $('connected-count');
    const totalEl = $('total-count');
    const chipsEl = $('connection-team-chips');
    if (connEl) connEl.textContent = String(connected);
    if (totalEl) totalEl.textContent = String(teams.length);
    if (chipsEl) {
      chipsEl.innerHTML = teams.map((t) => {
        const status = teamConnectionStatus(t.team_id);
        let dotClass = 'conn-chip__dot--offline';
        if (status === 'CONNECTED')           dotClass = 'conn-chip__dot--online';
        else if (status === 'CONNECTION_REQUESTED') dotClass = 'conn-chip__dot--pending';
        return '<div class="conn-chip">' +
          '<span class="conn-chip__dot ' + dotClass + '" aria-hidden="true"></span>' +
          t.team_name + '</div>';
      }).join('') || '<div class="conn-chip">No teams</div>';
    }
  }

  function renderAll() {
    renderSelect();
    renderCategory();
    renderWord();
    renderQueue();
    renderProgress();
    renderStats();
    renderTeamStatus();
    renderLeaderboard();
    renderConnections();
    const roundEl = $('round-number');
    if (roundEl) roundEl.textContent = currentRoundLabel().replace('Round ', '');
    const navBadge = $('next-round-badge');
    if (navBadge && matches.length) navBadge.textContent = currentRoundLabel();
    const lbBadge = document.querySelector('.leaderboard-card__round-badge');
    if (lbBadge) lbBadge.textContent = currentRoundLabel();
    tickDisplay();
  }

  /* ---------- statefulness / busy guards ---------- */
  function setBusy(id, on) {
    const el = $(id);
    if (el) el.disabled = on;
  }
  function busyAll(on) {
    ['btn-correct', 'btn-pass', 'btn-penalty', 'btn-bonus', 'btn-stop', 'btn-pause-play'].forEach((i) => setBusy(i, on));
  }

  function toast(msg) {
    const t = document.querySelector('.copy-toast');
    if (t) { t.innerHTML = msg; showToastSafe(t); }
    else if (typeof showToast === 'function') showToast(msg);
  }
  function showToastSafe(t) {
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 2500);
  }

  /* ---------- action handlers (backend) ---------- */
  async function handleStartPause(e) {
    if (e) addRipple(e.currentTarget, e);
    if (!activeMatch) { toast('Select a match first.'); return; }
    busyAll(true);
    try {
      if (turn && isTurnRunning(turn)) {
        // pause/resume an active turn
        const p = turn.status === 'ACTIVE'
          ? await TurnAPI.pause(turn.turn_id)
          : await TurnAPI.resume(turn.turn_id);
        setActiveTurn(p);
        renderAll();
        const icon = $('pause-icon');
        if (icon) icon.className = p.status === 'PAUSED' ? 'fa-solid fa-play' : 'fa-solid fa-pause';
        const btn = $('btn-pause-play');
        if (btn) btn.classList.toggle('playing', p.status === 'ACTIVE');
      } else {
        // auto-assign words + start the turn
        await TurnAPI.createTurn(activeMatch.match_id, { count: AUTO_WORDS });
        const p = await TurnAPI.startTurn(activeMatch.match_id);
        setActiveTurn(p);
        renderAll();
        const icon = $('pause-icon');
        if (icon) icon.className = 'fa-solid fa-pause';
        const btn = $('btn-pause-play');
        if (btn) btn.classList.add('playing');
        toast('Turn started - <b>' + (p.current_word_text || '...') + '</b>');
      }
    } catch (err) {
      toast(API.messageForStatus && err && err.status ? API.messageForStatus(err.status, err.message) : (err && err.message ? err.message : 'Could not start turn.'));
    } finally {
      busyAll(false);
    }
  }

  async function handleAction(actionName, e) {
    if (e) addRipple(e.currentTarget, e);
    if (!turn || !activeTurnId() || !isTurnRunning(turn)) {
      toast('Start a turn first.');
      return;
    }
    busyAll(true);
    try {
      let payload;
      if (actionName === 'correct') payload = await TurnAPI.correct(turn.turn_id);
      else if (actionName === 'pass') payload = await TurnAPI.pass(turn.turn_id);
      else if (actionName === 'timeout') payload = await TurnAPI.timeout(turn.turn_id);
      else if (actionName === 'end') payload = await TurnAPI.end(turn.turn_id);
      const finished = payload && (payload.status === 'COMPLETED' || payload.status === 'TIMEOUT' || payload.status === 'FAILED');
      setActiveTurn(payload);
      renderAll();
      if (!finished) {
        const w = $('current-word');
        if (w) { w.classList.remove('word-reveal'); void w.offsetWidth; w.classList.add('word-reveal'); }
      }
      handleCompletion(payload);
      // refresh scores from the server
      try { await loadData(); renderAll(); } catch (err) { /* ignore */ }
    } catch (err) {
      toast(API.messageForStatus && err && err.status ? API.messageForStatus(err.status, err.message) : (err && err.message ? err.message : 'Action failed.'));
    } finally {
      busyAll(false);
    }
  }

  function handleCompletion(payload) {
    if (!payload) return;
    if (payload.status === 'COMPLETED') {
      const won = !!(payload.outcome && payload.outcome.won);
      toast(won
        ? '<i class="fa-solid fa-trophy"></i> Turn complete! 3 correct words - WINNER'
        : '<i class="fa-solid fa-flag-checkered"></i> Turn complete');
    } else if (payload.status === 'TIMEOUT') {
      toast('<i class="fa-regular fa-clock"></i> Time is up - turn ended');
    } else if (payload.status === 'FAILED') {
      toast('Turn stopped - remaining words missed');
    }
    if (payload.match_status === 'COMPLETED') {
      const w = payload.match_winner_team_id ? teamNameOf(payload.match_winner_team_id) : '';
      toast('🏆 Match complete' + (w ? ' - winner ' + w : ''));
    }
  }

  async function handlePenalty(delta, e) {
    if (e) addRipple(e.currentTarget, e);
    if (!turn || !activeTurnId() || !isTurnRunning(turn)) { toast('Start a turn first.'); return; }
    busyAll(true);
    try {
      const payload = delta < 0
        ? await TurnAPI.removeTime(turn.turn_id, Math.abs(delta))
        : await TurnAPI.addTime(turn.turn_id, Math.abs(delta));
      setActiveTurn(payload);
      renderAll();
      toast((delta < 0 ? '⏪ -' : '⏩ +') + Math.abs(delta) + 's applied (server)');
    } catch (err) {
      toast(API.messageForStatus && err && err.status ? API.messageForStatus(err.status, err.message) : (err && err.message ? err.message : 'Penalty failed.'));
    } finally {
      busyAll(false);
    }
  }

  /* ---------- round / game completion checks ---------- */
  function currentRoundMatches() {
    if (!matches.length) return [];
    const r = orderedMatches()[0].round_number;
    return matches.filter((m) => m.round_number === r);
  }
  let lastRoundToastR = null;
  function checkRoundComplete() {
    if (!matches.length) return;
    const roundMatches = currentRoundMatches();
    if (roundMatches.length && roundMatches.every((m) => m.status === 'COMPLETED')) {
      const r = orderedMatches()[0].round_number;
      if (lastRoundToastR !== r) {
        lastRoundToastR = r;
        toast('✅ Round ' + r + ' complete!');
      }
    }
  }
  async function checkGameComplete() {
    try {
      const st = await GameAPI.status(gameId);
      if (st.status === 'GAME_COMPLETE') {
        API.updateMyGame({ game_id: gameId, status: 'GAME_COMPLETE' });
        if (!gameOverShown) {
          toast('🏆 Game complete');
          showGameOverModal();
        }
      }
    } catch (e) { /* ignore */ }
  }

  /* ---------- save game (checkpoint marker) ---------- */
  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function saveGameNow() {
    try {
      const res = await API.withLoading('save-game', () => GameAPI.save(gameId));
      const savedAt = (res && res.saved_at) || new Date().toISOString();
      API.updateMyGame({ game_id: gameId, saved_at: savedAt });
      if (res && res.saved_at) {
        const t = new Date(res.saved_at);
        toast('💾 Game saved' + (isNaN(t.getTime()) ? '' : ' at ' + t.toLocaleTimeString()));
      } else {
        toast('💾 Game saved');
      }
    } catch (e) {
      toast('Could not save the game: ' + ((e && e.message) || 'please try again'));
    }
  }

  /* ---------- game over modal (winner + leaderboard + delete) ---------- */
  let gameOverShown = false;

  async function showGameOverModal() {
    const ov = $('modal-game-over');
    if (!ov) return;
    resetGameOverDelete();
    const [lbRes, stRes] = await Promise.all([
      GameAPI.leaderboard(gameId).catch(() => null),
      GameAPI.statistics(gameId).catch(() => null),
    ]);
    const board = (lbRes && lbRes.leaderboard) || [];
    const stats = stRes || {};
    const w = stats.winning_team || board[0] || null;

    const winnerEl = $('game-over-winner');
    if (winnerEl) {
      winnerEl.innerHTML = w
        ? '<i class="fa-solid fa-trophy"></i> ' + escHtml(w.team_name || '') +
          ' <span class="gameover-winner__pts">' + Number(w.points || 0) + ' pts</span>'
        : '<i class="fa-solid fa-trophy"></i> Game complete';
    }
    const codeEl = $('game-over-code');
    if (codeEl) codeEl.textContent = 'Game ' + (STATE.gameCode || gameId);
    const hintEl = $('game-over-delete-hint');
    if (hintEl) hintEl.textContent = STATE.gameCode || '';

    const statsEl = $('game-over-stats');
    if (statsEl) {
      const fast = stats.fastest_team;
      const chips = [
        ['Teams', stats.total_teams],
        ['Words', stats.total_words],
        ['Correct', stats.total_correct_answers],
        ['Passes', stats.total_passes],
        ['Penalties', stats.total_penalties],
        ['Duration', (stats.total_game_duration_seconds != null && isFinite(stats.total_game_duration_seconds))
          ? Math.round(stats.total_game_duration_seconds / 60) + ' min' : '—'],
        ['Fastest', fast ? fast.team_name : '—'],
      ].map(([label, value]) =>
        '<span class="gameover-stats__chip"><span>' + escHtml(label) + '</span><strong>' +
        escHtml(value == null ? '—' : value) + '</strong></span>'
      ).join('');
      statsEl.innerHTML = chips || 'No statistics yet.';
    }

    const tbody = $('game-over-tbody');
    if (tbody) {
      tbody.innerHTML = board.length
        ? board.map((t) =>
            '<tr>' +
              '<td>' + Number(t.rank || 0) + '</td>' +
              '<td>' + escHtml(t.team_name || '') + '</td>' +
              '<td>' + Number(t.points || 0) + '</td>' +
              '<td>' + Number(t.correct_words || 0) + '</td>' +
              '<td>' + Number(t.passed_words || 0) + '</td>' +
              '<td>' + Number(t.penalty_seconds || 0) + '</td>' +
            '</tr>'
          ).join('')
        : '<tr><td colspan="6">No scores recorded.</td></tr>';
    }

    gameOverShown = true;
    openModal(ov);
  }

  function resetGameOverDelete() {
    const box = $('game-over-delete');
    const input = $('input-game-over-delete');
    const btn = $('btn-confirm-delete-game');
    if (box) box.hidden = true;
    if (input) input.value = '';
    if (btn) btn.disabled = true;
    const err = $('game-over-delete-error');
    if (err) err.textContent = '';
  }

  rebind('btn-save-game', saveGameNow);
  rebind('btn-save-game-over', saveGameNow);
  rebind('close-game-over', () => { closeModal($('modal-game-over')); resetGameOverDelete(); });
  rebind('btn-close-game-over', () => { closeModal($('modal-game-over')); resetGameOverDelete(); });
  rebind('btn-prompt-delete', () => {
    const box = $('game-over-delete');
    const input = $('input-game-over-delete');
    const btn = $('btn-confirm-delete-game');
    const err = $('game-over-delete-error');
    if (err) err.textContent = '';
    if (input) input.value = '';
    if (btn) btn.disabled = true;
    if (box) box.hidden = false;
    if (input) input.focus();
  });

  const goDeleteInput = $('input-game-over-delete');
  if (goDeleteInput) {
    goDeleteInput.addEventListener('input', () => {
      const btn = $('btn-confirm-delete-game');
      const code = goDeleteInput.value.trim().toUpperCase();
      if (btn) btn.disabled = !(STATE.gameCode && code === String(STATE.gameCode).toUpperCase());
    });
    goDeleteInput.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      const btn = $('btn-confirm-delete-game');
      if (btn && !btn.disabled) deleteFinishedGame();
    });
  }

  async function deleteFinishedGame() {
    const btn = $('btn-confirm-delete-game');
    const err = $('game-over-delete-error');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Deleting…';
    if (err) err.textContent = '';
    try {
      await API.withLoading('delete-game', () => GameAPI.deleteGame(gameId, { confirm: true }));
      API.removeMyGame(gameId);
      API.clearTokens();
      window.location.replace('../../index.html');
    } catch (e) {
      btn.disabled = false;
      btn.innerHTML = original;
      const map = {
        INVALID_OPERATION: 'Only completed, cancelled, or expired games can be deleted.',
        WITH_CONFIRMATION_REQUIRED: 'Please type the game code to confirm the deletion.',
        GAME_FROZEN: 'This game is read-only and cannot be deleted.',
      };
      if (err) err.textContent = map[e.code] || (e && e.message) || 'Could not delete the game.';
    }
  }
  rebind('btn-confirm-delete-game', deleteFinishedGame);

  /* ---------- button wiring (replaces demo handlers) ---------- */
  rebind('btn-pause-play', handleStartPause);
  rebind('btn-correct', (e) => handleAction('correct', e));
  rebind('btn-pass', (e) => handleAction('pass', e));
  rebind('btn-stop', (e) => handleAction('timeout', e));
  rebind('btn-penalty', (e) => handlePenalty(-3, e));
  rebind('btn-bonus', (e) => handlePenalty(+3, e));
  rebind('btn-timer-reset', () => {
    if (turn && isTurnRunning(turn)) { toast('Timer is server-controlled. Pause to stop it.'); }
    else toast('Start a turn to run the server timer.');
  });
  rebind('btn-set-time', () => {
    toast('Timer is server-authoritative. Set the round timer during setup.');
  });
  rebind('team-select', () => {
    const v = $('team-select') ? $('team-select').value : '';
    activeMatch = v ? pendingMatchForId(parseInt(v, 10)) : null;
    if (activeMatch) {
      // load an existing active/pending turn for this match if any
      TurnAPI.listTurns(activeMatch.match_id).then((d) => {
        const turns = (d && d.turns) || [];
        const live = turns.find((t) => t.status === 'ACTIVE' || t.status === 'PAUSED');
        (async () => {
          if (live) {
            const tv = await hostTurn(live.turn_id).catch(() => null);
            if (tv) setActiveTurn(tv);
          } else {
            setActiveTurn(null);
          }
          renderAll();
        })();
      }).catch(() => { setActiveTurn(null); renderAll(); });
    } else {
      setActiveTurn(null);
    }
    renderAll();
  }, 'change');

  const viewAll = $('btn-view-all-teams');
  if (viewAll && typeof openModal === 'function') {
    const fresh = viewAll.cloneNode(true);
    viewAll.replaceWith(fresh);
    fresh.addEventListener('click', () => { renderAllTeams(); openModal($('modal-all-teams')); });
  }

  const nextRound = $('btn-next-round');
  if (nextRound) {
    const fresh = nextRound.cloneNode(true);
    nextRound.replaceWith(fresh);
    fresh.addEventListener('click', () => {
      toast('Select the next round\'s match from the dropdown to continue.');
    });
  }

  const resetRound = $('btn-reset-round');
  if (resetRound) {
    const fresh = resetRound.cloneNode(true);
    resetRound.replaceWith(fresh);
    fresh.addEventListener('click', () => {
      toast('Round reset is not supported by the backend. Use Stop to end a turn.');
    });
  }

  /* ---------- connection approval (dashboard) ----------
     Mirrors the approval flow from teams.html/teams.js so hosts can
     handle connection requests without leaving the dashboard. */
  let approvalTeamId = null;
  let approvalBusy   = false;
  const dismissedApprovalTeamIds = new Set();

  function buildApprovalPayload(t) {
    const leader = (t.leader && t.leader.username)
      || ((t.members && t.members[0] && t.members[0].username) || '—');
    return {
      team_id: t.team_id,
      team_name: t.team_name || 'Team ' + t.team_id,
      connection_status: t.connection_status || 'CONNECTION_REQUESTED',
      leader: { username: leader },
      member_count: (t.members && t.members.length) || 0,
    };
  }

  // Surface a connection request whose live socket event was missed (page
  // opened after the request, or the socket was down) so pending teams are
  // always actionable. Dismissed teams stay suppressed until they re-request.
  function maybePromptPendingApprovals() {
    if (approvalTeamId != null) return;             // a decision modal is already showing
    if (!DOM.modalApproveConnection) return;
    const pending = roster.find(t =>
      t.connection_status === 'CONNECTION_REQUESTED' &&
      !dismissedApprovalTeamIds.has(t.team_id));
    if (!pending) return;
    approvalTeamId = pending.team_id;
    openApprovalModal(buildApprovalPayload(pending));
  }

  function openApprovalModal(payload) {
    if (!DOM.modalApproveConnection) return;
    const teamName = payload.team_name || 'Unknown';
    const leader   = (payload.leader && payload.leader.username) || '\u2014';
    const count    = payload.member_count != null ? String(payload.member_count) : '\u2014';
    DOM.approveTeamName.textContent  = teamName;
    DOM.approveLeaderName.textContent = leader;
    DOM.approveMemberCount.textContent = count;
    DOM.approveConnectionDetails.textContent =
      '\u201c' + teamName + '\u201d is requesting to join the host screen for this game.';
    approvalBusy = false;
    openModal(DOM.modalApproveConnection);
  }

  async function decideConnection(teamId, approve) {
    if (approvalBusy) return;
    approvalBusy = true;
    DOM.btnApproveConnection.disabled = true;
    DOM.btnDeclineConnection.disabled = true;
    try {
      const res = approve
        ? await TeamAPI.approveConnection(API.getGameId(), teamId)
        : await TeamAPI.declineConnection(API.getGameId(), teamId);
      if (approvalTeamId === teamId) { closeModal(DOM.modalApproveConnection); approvalTeamId = null; }
      loadRoster().then(renderConnections).catch(() => {});
      toast(approve ? 'Team connected to the host screen' : 'Connection declined');
    } catch (err) {
      console.error('[dashboard] connection decision failed', err);
      if (approvalTeamId === teamId) { closeModal(DOM.modalApproveConnection); approvalTeamId = null; }
      toast((err && err.message) || 'Action failed');
      maybePromptPendingApprovals();
    } finally {
      approvalBusy = false;
      DOM.btnApproveConnection.disabled = false;
      DOM.btnDeclineConnection.disabled = false;
    }
  }

  DOM.btnApproveConnection.addEventListener('click', () => {
    if (approvalTeamId != null) decideConnection(approvalTeamId, true);
  });
  DOM.btnDeclineConnection.addEventListener('click', () => {
    if (approvalTeamId != null) decideConnection(approvalTeamId, false);
  });
  DOM.closeApproveConnection.addEventListener('click', () => {
    if (approvalTeamId != null) dismissedApprovalTeamIds.add(approvalTeamId);
    approvalTeamId = null;
    closeModal(DOM.modalApproveConnection);
    maybePromptPendingApprovals();
  });

  /* ---------- realtime socket bridge (host) ----------
     Connects the HOST socket. Because the backend only broadcasts a
     PUBLIC turn payload (word text blanked) to the game/turn rooms,
     the host keeps using hostTurn() (REST, full secret payload) as the
     authoritative view. Socket events just trigger an immediate,
     debounced hostTurn() refresh plus reloads for server-originated
     setup/completion events — so the UI reacts in realtime without
     duplicating listeners or leaking secret words. */
  const rt = window.Realtime;
  const rtPollDebounce = {};
  function rtSchedulePoll(label) {
    if (!turn || !activeTurnId()) return;
    // Debounce bursts (e.g. word_correct + timer_updated together).
    if (rtPollDebounce[label]) clearTimeout(rtPollDebounce[label]);
    rtPollDebounce[label] = setTimeout(() => {
      delete rtPollDebounce[label];
      pollTurn();
    }, 60);
  }

  function rtForThisGame(payload) {
    return payload && gameId && payload.game_id === gameId;
  }
  function rtForActiveTurn(payload) {
    return turn && payload && payload.turn_id === turn.turn_id;
  }

  // Public turn/timer events → refresh host truth for the active turn.
  ['word_correct', 'word_passed', 'timer_updated', 'timer_paused',
   'timer_resumed', 'time_added', 'time_removed', 'penalty_applied',
   'turn_started', 'turn_completed', 'turn_state'].forEach((evt) => {
    if (!rt) return;
    rt.on(evt, (payload) => {
      if (!rtForActiveTurn(payload)) return;
      rtSchedulePoll(evt);
    });
  });

  // Server-originated match/game lifecycle → reload + re-render.
  function rtReload() {
    loadData().then(() => { renderAll(); }).catch(() => {});
  }
  if (rt) {
    ['match_started', 'round_started', 'round_completed',
     'game_started', 'game_paused', 'game_resumed',
     'game_completed'].forEach((evt) => {
      rt.on(evt, (payload) => {
        if (!rtForThisGame(payload)) return;
        rtReload();
      });
    });
    // Presence of teams is useful context on the host dashboard.
    const refreshPresence = () => {
      loadRoster().then(renderConnections).catch(() => {});
    };
    rt.on('team_connected', (p) => { if (p && p.member && p.member.team_id && p.member.username) teamNameOf.register(p.member.team_id, p.member.username); refreshPresence(); });
    rt.on('member_joined', (p) => { if (p && p.member && p.member.team_id && p.member.username) teamNameOf.register(p.member.team_id, p.member.username); refreshPresence(); });
    rt.on('team_disconnected', (p) => { if (p && p.team_id) refreshPresence(); });
    rt.on('member_left', (p) => { if (p && p.team_id) refreshPresence(); });

    // Connection request approval — show modal on request, dismiss on resolve.
    rt.on('connection_requested', (p) => {
      if (!p || !p.team_id) return;
      dismissedApprovalTeamIds.delete(p.team_id);
      approvalTeamId = p.team_id;
      if (p.team_name) teamNameOf.register(p.team_id, p.team_name);
      openApprovalModal(p);
      refreshPresence();
    });
    rt.on('connection_approved', (p) => {
      if (!p || !p.team_id) return;
      if (approvalTeamId === p.team_id) { closeModal(DOM.modalApproveConnection); approvalTeamId = null; }
      toast((p.team_name || 'Team') + ' connected');
      refreshPresence();
    });
    rt.on('connection_declined', (p) => {
      if (!p || !p.team_id) return;
      if (approvalTeamId === p.team_id) { closeModal(DOM.modalApproveConnection); approvalTeamId = null; }
      refreshPresence();
    });
    rt.on('connection_disconnected', (p) => {
      if (!p || !p.team_id) return;
      refreshPresence();
    });
  }

  // Connect the host socket once. On (re)connect re-request state and
  // rejoin the active turn room so the server re-sends turn_state.
  if (rt && !rt.getSocket()) {
    rt.connect({ mode: 'host' });
    const rtRosterRefresh = () => {
      loadRoster().then(() => { renderConnections(); renderAllTeams(); }).catch(() => {});
    };
    rt.onConnect(() => {
      if (activeMatch && turn && activeTurnId()) rt.joinTurn(turn.turn_id);
      rtReload();
      rtRosterRefresh();
    });
    rt.onReconnect(() => {
      if (activeMatch && turn && activeTurnId()) rt.joinTurn(turn.turn_id);
      rtReload();
      rtRosterRefresh();
    });
    rt.onDisconnect(() => { /* connection banner handled by pages */ });
  }

  // If the host returns to this tab after teams connected while away,
  // refresh the roster (realtime events are not guaranteed to be missed).
  window.addEventListener('focus', () => {
    loadRoster().then(() => { renderConnections(); renderAllTeams(); }).catch(() => {});
  });

  // helper that returns a match object by id from `matches`
  function pendingMatchForId(id) {
    return matches.find((m) => m.match_id === id) || null;
  }

  /* ---------- bootstrap ---------- */
  (async function init() {
    await loadData();
    await loadRoster();
    renderAll();
    // Watch for server-driven completion states.
    const completeWatch = setInterval(async () => {
      if (activeMatch) {
        try {
          const d = await MatchAPI.listMatches(gameId);
          if (d && d.matches) {
            matches = d.matches;
            const cur = matches.find((m) => m.match_id === activeMatch.match_id);
            if (cur && cur.status === 'COMPLETED' && (!activeMatch || activeMatch.status !== 'COMPLETED')) {
              toast('🏆 Match complete');
            }
            activeMatch = cur || null;
            renderAll();
          }
        } catch (e) { /* ignore */ }
      }
      checkRoundComplete();
      checkGameComplete();
    }, 3000);
  })();
})();

