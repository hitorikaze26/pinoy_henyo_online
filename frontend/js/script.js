'use strict';

/* ============================================================
   UTILITIES
============================================================ */

/** Set the footer year dynamically */
document.getElementById('footer-year').textContent = new Date().getFullYear();

/** Create a ripple effect at the click location inside a button */
function createRipple(event) {
  const btn  = event.currentTarget;
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x    = event.clientX - rect.left - size / 2;
  const y    = event.clientY - rect.top  - size / 2;

  const ripple = document.createElement('span');
  ripple.classList.add('ripple');
  ripple.style.cssText = `
    width: ${size}px;
    height: ${size}px;
    left: ${x}px;
    top: ${y}px;
  `;

  // Remove any existing ripple
  const old = btn.querySelector('.ripple');
  if (old) old.remove();

  btn.appendChild(ripple);
  ripple.addEventListener('animationend', () => ripple.remove());
}

/** Attach ripple to all buttons */
document.querySelectorAll('.btn-primary, .btn-secondary, .nav-btn').forEach(btn => {
  btn.addEventListener('click', createRipple);
});

/* ============================================================
   MODAL SYSTEM
============================================================ */

/**
 * Open a modal by its overlay element.
 * Traps focus and prevents body scroll.
 */
function openModal(overlay) {
  overlay.removeAttribute('aria-hidden');
  overlay.setAttribute('aria-hidden', 'false');
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';

  // Focus the first focusable element inside the modal
  const focusable = overlay.querySelector(
    'input, button:not([aria-label="Close modal"]), select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (focusable) setTimeout(() => focusable.focus(), 60);
}

/**
 * Close a modal by its overlay element and clear form state.
 */
function closeModal(overlay) {
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';

  // Reset form + errors inside the modal
  const form = overlay.querySelector('form');
  if (form) {
    form.reset();
    form.querySelectorAll('.form-input').forEach(i => i.classList.remove('error'));
    form.querySelectorAll('.form-error').forEach(e => (e.textContent = ''));
  }
}

/** Close any open modal when clicking the dark backdrop */
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeModal(overlay);
  });
});

/** Close modals on Escape key */
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.modal-overlay.open').forEach(o => {
    // If QR scanner is open, stop the camera first
    if (o.id === 'modal-qr') stopCamera();
    closeModal(o);
  });
});

/* ---------- convenience references ---------- */
const overlayStart = document.getElementById('modal-start');
const overlayJoin  = document.getElementById('modal-join');
const overlayQr    = document.getElementById('modal-qr');

/* ============================================================
   HERO BUTTON ACTIONS → open modals
============================================================ */
document.getElementById('start-btn').addEventListener('click', () => {
  console.log('[Pinoy Henyo] Start a Game clicked');
  openModal(overlayStart);
});

document.getElementById('join-btn').addEventListener('click', () => {
  console.log('[Pinoy Henyo] Join Game clicked');
  openModal(overlayJoin);
});

/* ============================================================
   MODAL: START A GAME – close triggers
============================================================ */
document.getElementById('modal-start-close').addEventListener('click',  () => closeModal(overlayStart));
document.getElementById('modal-start-cancel').addEventListener('click', () => closeModal(overlayStart));

/** "Are you a Host?" – auto-create a fresh game (host team) and open the dashboard */
document.getElementById('btn-are-you-host').addEventListener('click', async () => {
  console.log('[Pinoy Henyo] Are you a Host? clicked');

  const btn = document.getElementById('btn-are-you-host');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating…';

  // Clear any stale session so old game_ids don't linger and cause 404s.
  API.clearTokens();

  try {
    const game = await API.withLoading('create-game-host', () => GameAPI.create());

    // Store the host session + game context so host pages can reuse them.
    API.setHostToken(game.host_session_token);
    API.setGameId(game.game_id);
    API.setGameCode(game.game_code);
    API.setHostContext(game);
    window.PINOY_GAME = game;

    // Create the host's first team (required to place the host in a team).
    const team = await TeamAPI.createTeam(game.game_id, 'Host Team', 'Host');
    API.setTeamId(team.team_id);
    API.setSessionToken(null);

    btn.disabled = false;
    btn.innerHTML = original;
    closeModal(overlayStart);

    window.location.href = 'pages/host/host_dashboard.html';
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = original;
    console.error('[Pinoy Henyo] Create host game failed', err);

    if (err && err.code === 'RATE_LIMITED') {
      const wait = (err.retryAfter > 0) ? ` in ${err.retryAfter}s` : '';
      alert(`Too many requests. Please wait${wait} and try again.`);
      return;
    }

    // Surface validation failures that arise from the host defaults.
    if (err && (err.code === 'USERNAME_INVALID' || err.code === 'TEAM_NAME_INVALID')) {
      alert('Could not create the game. Check the team name and try again.');
      return;
    }

    alert(`❌ Could not create the game.\n\n${err.message || 'Please check your connection and try again.'}`);
  }
});

/* ============================================================
   MODAL: START A GAME – form submit
   ============================================================ */

// Shared input validation helpers (limits mirror the backend:
// team_service MAX_USERNAME_LENGTH / MAX_TEAM_NAME_LENGTH = 50).
const START_NAME_MAX = 50;
const START_TEAM_MAX = 50;

function clearInputError(input, errorEl) {
  input.classList.remove('error');
  if (errorEl) errorEl.textContent = '';
}

function validateCreateField(input, errorEl, label, maxLen) {
  const value = (input.value || '').trim();
  if (!value) {
    input.classList.add('error');
    errorEl.textContent = `Please enter a ${label.toLowerCase()}.`;
    return null;
  }
  if (value.length > maxLen) {
    input.classList.add('error');
    errorEl.textContent = `${label} must be ${maxLen} characters or fewer.`;
    return null;
  }
  input.classList.remove('error');
  errorEl.textContent = '';
  return value;
}

['input-username', 'input-teamname'].forEach((id) => {
  const el = document.getElementById(id);
  const err = document.getElementById(id === 'input-username' ? 'error-username' : 'error-teamname');
  el && el.addEventListener('input', () => clearInputError(el, err));
});

document.getElementById('form-start').addEventListener('submit', (e) => {
  e.preventDefault();

  const usernameInput  = document.getElementById('input-username');
  const teamnameInput  = document.getElementById('input-teamname');
  const usernameError  = document.getElementById('error-username');
  const teamnameError  = document.getElementById('error-teamname');

  const username = validateCreateField(usernameInput, usernameError, 'Username', START_NAME_MAX);
  const teamname = validateCreateField(teamnameInput, teamnameError, 'Team name', START_TEAM_MAX);
  if (username === null || teamname === null) return;

  console.log('[Pinoy Henyo] Create Team →', { username, teamname });

  const btn = document.getElementById('form-start').querySelector('button[type="submit"]');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating…';

  // Clear any stale session before creating a new game so old game_ids
  // don't linger and cause 404s on subsequent pages.
  API.clearTokens();

  API.withLoading('create-game', () => GameAPI.create())
    .then(async (game) => {
      // Reserve the host session on disk so the host dashboard remains reachable,
      // but the creator below connects as a team-leader device session.
      API.setHostToken(game.host_session_token);
      API.setGameId(game.game_id);
      API.setGameCode(game.game_code);
      window.PINOY_GAME = game;

      // Create the player's team (the creator becomes the team leader).
      const team = await TeamAPI.createTeam(game.game_id, teamname, username);

      // Establish a real device session for the leader so the player page loads
      // the real roster/words/settings on the next screen.
      const connectionToken = team.leader && team.leader.connection_token;
      if (connectionToken) {
        await DeviceAPI.connect({ connectionToken });
      }

      closeModal(overlayStart);
      btn.disabled = false;
      btn.innerHTML = original;

      window.location.href = 'pages/player/player.html';
    })
    .catch((err) => {
      btn.disabled = false;
      btn.innerHTML = original;

      // Surface validation errors from the backend into the form fields.
      if (err && err.code === 'USERNAME_INVALID') {
        validateCreateField(usernameInput, usernameError, 'Username', START_NAME_MAX);
        usernameInput.classList.add('error');
        usernameError.textContent = 'Please enter a valid username (1–50 characters).';
        return;
      }
      if (err && err.code === 'TEAM_NAME_INVALID') {
        teamnameInput.classList.add('error');
        teamnameError.textContent = 'Please enter a valid team name (1–50 characters).';
        return;
      }

      console.error('[Pinoy Henyo] Create game failed', err);

      // Rate-limited -> tell the user to wait before retrying.
      if (err && err.code === 'RATE_LIMITED') {
        const wait = (err.retryAfter > 0) ? ` in ${err.retryAfter}s` : '';
        alert(`Too many requests. Please wait${wait} and try again.`);
        return;
      }

      alert(`❌ Could not create the game.\n\n${err.message || 'Please check your connection and try again.'}`);
    });
});

/* ============================================================
   MODAL: JOIN A GAME – close triggers
============================================================ */
document.getElementById('modal-join-close').addEventListener('click',  () => closeModal(overlayJoin));
document.getElementById('modal-join-cancel').addEventListener('click', () => closeModal(overlayJoin));

/* ============================================================
   MODAL: JOIN A GAME – form submit
============================================================ */
document.getElementById('form-join').addEventListener('submit', async (e) => {
  e.preventDefault();

  const usernameInput   = document.getElementById('input-join-username');
  const usernameError   = document.getElementById('error-join-username');
  const codeInput       = document.getElementById('input-gamecode');
  const codeError       = document.getElementById('error-gamecode');
  const teamnameInput   = document.getElementById('input-join-teamname');
  const teamnameError   = document.getElementById('error-join-teamname');
  const teamcodeInput   = document.getElementById('input-join-teamcode');
  const teamcodeError   = document.getElementById('error-join-teamcode');

  const username = validateCreateField(usernameInput, usernameError, 'Username', START_NAME_MAX);
  const rawCode  = (codeInput.value || '').trim();
  if (username === null) return;
  if (!rawCode) {
    codeInput.classList.add('error');
    codeError.textContent = 'Please enter a game code.';
    return;
  }
  codeInput.classList.remove('error');
  codeError.textContent = '';

  const teamName = (teamnameInput.value || '').trim();
  const teamCode = (teamcodeInput.value || '').trim();
  clearInputError(teamnameInput, teamnameError);
  clearInputError(teamcodeInput, teamcodeError);

  // The backend /join accepts exactly one of team_name (create) or team_code (join).
  if (teamName && teamCode) {
    teamnameInput.classList.add('error');
    teamnameError.textContent = 'Choose either a new team name OR a team code, not both.';
    return;
  }
  if (!teamName && !teamCode) {
    teamcodeInput.classList.add('error');
    teamcodeError.textContent = 'Enter a team name to create a team, or a team code to join one.';
    return;
  }
  if (teamName && teamName.length > START_TEAM_MAX) {
    teamnameInput.classList.add('error');
    teamnameError.textContent = `Team name must be ${START_TEAM_MAX} characters or fewer.`;
    return;
  }

  const code = rawCode.toUpperCase();
  console.log('[Pinoy Henyo] Join Game →', { username, code, teamName, teamCode });

  const btn = document.getElementById('form-join').querySelector('button[type="submit"]');
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting…';

  try {
    // 1) Resolve the game by its public code.
    const game = await GameAPI.getByCode(code);
    const gameId = game.game_id;

    // 2) Create a new team OR join an existing one via the backend /join.
    const joined = await TeamAPI.joinGame(gameId, username, teamName || null, teamCode || null);
    API.setGameId(gameId);
    API.setGameCode(game.game_code || code);

    // 3) Establish a real device session using the returned connection token.
    const connectionToken = joined.connection_token
      || (joined.leader && joined.leader.connection_token)
      || null;
    if (connectionToken) {
      await DeviceAPI.connect({ connectionToken });
    }

    // 4) Creating a NEW team is not approval to join the host's screen. The
    //    entered/scanned host code is an explicit CONNECTION REQUEST that the
    //    host must approve before gameplay. Joining an existing team as a
    //    member leaves the team's connection status untouched.
    if (joined.leader) {
      try {
        await TeamAPI.requestConnection(gameId, joined.leader.connection_token);
      } catch (err) {
        if (err.code !== 'ALREADY_CONNECTED' && err.code !== 'REQUEST_PENDING') {
          console.warn('[Pinoy Henyo] connection request failed', err);
        }
      }
    }

    closeModal(overlayJoin);
    window.location.href = 'pages/player/player.html';
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = original;

    if (err && err.status === 404) {
      codeInput.classList.add('error');
      codeError.textContent = `Game "${code}" not found. Check the code and try again.`;
    } else if (err && err.status === 409) {
      // Game is frozen/expired/cancelled — no longer accepting players.
      codeInput.classList.add('error');
      codeError.textContent = (err && err.message) || 'This game is no longer accepting players. It may have ended.';
    } else if (err && err.code === 'TEAM_CODE_INVALID') {
      teamcodeInput.classList.add('error');
      teamcodeError.textContent = 'That team code does not belong to this game.';
    } else if (err && err.network) {
      codeError.textContent = 'Could not reach the server. Make sure the host has started the game.';
      codeInput.classList.add('error');
    } else if (err && err.code === 'RATE_LIMITED') {
      const wait = (err.retryAfter > 0) ? ` in ${err.retryAfter}s` : '';
      codeError.textContent = `Too many attempts. Please wait${wait} and try again.`;
      codeInput.classList.add('error');
    } else if (err && err.code === 'USERNAME_INVALID') {
      usernameInput.classList.add('error');
      usernameError.textContent = 'Please enter a valid username (1–50 characters).';
    } else {
      codeError.textContent = err.message || 'Could not join the game. Please try again.';
      codeInput.classList.add('error');
    }
    console.error('[Pinoy Henyo] Join game failed', err);
  }
});

// Clear per-field errors as the player types.
['input-join-username', 'input-gamecode', 'input-join-teamname', 'input-join-teamcode'].forEach((id) => {
  const el = document.getElementById(id);
  const errMap = {
    'input-join-username': 'error-join-username',
    'input-gamecode': 'error-gamecode',
    'input-join-teamname': 'error-join-teamname',
    'input-join-teamcode': 'error-join-teamcode',
  };
  const err = document.getElementById(errMap[id]);
  el && el.addEventListener('input', () => clearInputError(el, err));
});

/* ============================================================
   QR CODE SCANNER
============================================================ */

let qrStream = null; // holds the active MediaStream

/** Open the QR scanner modal and start the camera */
document.getElementById('btn-scan-qr').addEventListener('click', () => {
  closeModal(overlayJoin);   // hide Join modal first
  openModal(overlayQr);
  startCamera();
});

document.getElementById('modal-qr-close').addEventListener('click', () => {
  stopCamera();
  closeModal(overlayQr);
  openModal(overlayJoin);    // return to Join modal
});

document.getElementById('modal-qr-cancel').addEventListener('click', () => {
  stopCamera();
  closeModal(overlayQr);
  openModal(overlayJoin);    // return to Join modal
});

document.getElementById('btn-retry-camera').addEventListener('click', () => {
  document.getElementById('qr-error').hidden = true;
  startCamera();
});

/**
 * Request camera access and stream to the <video> element.
 * Uses the rear camera on mobile via { facingMode: 'environment' }.
 */
async function startCamera() {
  const video    = document.getElementById('qr-video');
  const errorBox = document.getElementById('qr-error');
  const errorMsg = document.getElementById('qr-error-msg');

  errorBox.hidden = true;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    errorMsg.textContent = 'Your browser does not support camera access.';
    errorBox.hidden = false;
    return;
  }

  try {
    qrStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } },
      audio: false,
    });
    video.srcObject = qrStream;
    await video.play();
    window.QrScanner.start({ video, onScan: handleQrScanned });
    console.log('[Pinoy Henyo] Camera started');
  } catch (err) {
    console.warn('[Pinoy Henyo] Camera error:', err.name, err.message);

    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      errorMsg.textContent = 'Camera access was denied. Please allow camera permission and try again.';
    } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      errorMsg.textContent = 'No camera found on this device.';
    } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
      errorMsg.textContent = 'Camera is already in use by another app.';
    } else {
      errorMsg.textContent = `Could not access camera: ${err.message}`;
    }

    errorBox.hidden = false;
  }
}

/** Stop all camera tracks, release the stream, and halt QR decoding */
function stopCamera() {
  if (window.QrScanner) window.QrScanner.stop();
  if (qrStream) {
    qrStream.getTracks().forEach(track => track.stop());
    qrStream = null;
  }

  const video = document.getElementById('qr-video');
  video.srcObject = null;
  console.log('[Pinoy Henyo] Camera stopped');
}

/* ============================================================
   QR CODE DECODING
   Delegates to the shared QrScanner module (js/qr/scanner.js),
   which decodes each frame with jsQR FIRST and only races the
   native BarcodeDetector against a short timeout, so a hanging
   native API can never starve the jsQR fallback. On a hit we stop
   the camera and route the player back to the Join modal with the
   scanned game/team codes pre-filled.
   ============================================================ */

function handleQrScanned(raw) {
  const parsed = Connect.parseJoinUrl(raw);

  if (!parsed || !parsed.gameCode) {
    stopCamera();
    const errorBox = document.getElementById('qr-error');
    const errorMsg = document.getElementById('qr-error-msg');
    errorMsg.textContent = 'That is not a valid Pinoy Henyo QR code. Please scan the code on the host screen.';
    errorBox.hidden = false;
    return;
  }

  if (window.QrScanner) window.QrScanner.stop();
  stopCamera();
  closeModal(overlayQr);

  // Pre-fill the Join modal with the public codes carried by the QR payload.
  const gameCodeInput = document.getElementById('input-gamecode');
  if (parsed.gameCode) gameCodeInput.value = parsed.gameCode;
  if (parsed.teamCode) document.getElementById('input-join-teamcode').value = parsed.teamCode;

  openModal(overlayJoin);
}

/* ============================================================
   NAVIGATION DROPDOWNS
============================================================ */
const dropdowns = [
  { btn: document.getElementById('how-btn'),  menu: document.getElementById('how-menu')  },
  { btn: document.getElementById('feat-btn'), menu: document.getElementById('feat-menu') },
];

function closeAllDropdowns(except) {
  dropdowns.forEach(({ btn, menu }) => {
    if (menu === except) return;
    menu.classList.remove('open');
    btn.classList.remove('active');
    btn.setAttribute('aria-expanded', 'false');
  });
}

dropdowns.forEach(({ btn, menu }) => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = menu.classList.contains('open');
    closeAllDropdowns(null);
    if (!isOpen) {
      menu.classList.add('open');
      btn.classList.add('active');
      btn.setAttribute('aria-expanded', 'true');
    }
  });
});

// Close dropdowns when clicking outside
document.addEventListener('click', () => closeAllDropdowns(null));

/* ============================================================
   MOBILE HAMBURGER MENU
============================================================ */
const hamburgerBtn = document.getElementById('hamburger-btn');
const mobileMenu   = document.getElementById('mobile-menu');

hamburgerBtn.addEventListener('click', () => {
  const isOpen = mobileMenu.classList.contains('open');
  mobileMenu.classList.toggle('open');
  hamburgerBtn.classList.toggle('open');
  hamburgerBtn.setAttribute('aria-expanded', String(!isOpen));
  mobileMenu.setAttribute('aria-hidden', String(isOpen));
});

// Close mobile menu when a link is clicked
mobileMenu.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => {
    mobileMenu.classList.remove('open');
    hamburgerBtn.classList.remove('open');
    hamburgerBtn.setAttribute('aria-expanded', 'false');
    mobileMenu.setAttribute('aria-hidden', 'true');
  });
});

/* ============================================================
   SMOOTH SCROLLING (anchor links)
============================================================ */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', (e) => {
    const target = document.querySelector(anchor.getAttribute('href'));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

/* ============================================================
   SCROLL-REVEAL (Intersection Observer)
============================================================ */
const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
);

document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

/* ============================================================
   PARTICLE BACKGROUND
   Golden sparkles floating upward
============================================================ */
(function initParticles() {
  const canvas = document.getElementById('particle-canvas');
  const ctx    = canvas.getContext('2d');

  let W = 0, H = 0;
  const PARTICLE_COUNT = 55;
  const particles = [];

  // Resize handler
  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  window.addEventListener('resize', resize);
  resize();

  // Particle colors – golden / blue palette
  const COLORS = [
    'rgba(245,185,66,',   // gold
    'rgba(238,147,38,',   // orange-gold
    'rgba(49,154,251,',   // blue
    'rgba(255,255,255,',  // white
  ];

  function randomBetween(a, b) {
    return a + Math.random() * (b - a);
  }

  function createParticle() {
    return {
      x:      randomBetween(0, W),
      y:      randomBetween(0, H),
      r:      randomBetween(1, 3.2),
      vx:     randomBetween(-0.3, 0.3),
      vy:     randomBetween(-0.8, -0.25),
      alpha:  randomBetween(0.3, 0.85),
      dalpha: randomBetween(0.002, 0.006),
      fade:   'in',
      color:  COLORS[Math.floor(Math.random() * COLORS.length)],
      twinkle: Math.random() > 0.5,
    };
  }

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push(createParticle());
  }

  function drawStar(cx, cy, r, alpha, color) {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle   = color + alpha + ')';

    if (r > 2.2) {
      // Draw a small 4-point star
      ctx.beginPath();
      const arms  = 4;
      const outer = r;
      const inner = r * 0.4;
      for (let i = 0; i < arms * 2; i++) {
        const angle  = (i * Math.PI) / arms - Math.PI / 2;
        const radius = i % 2 === 0 ? outer : inner;
        const px = cx + Math.cos(angle) * radius;
        const py = cy + Math.sin(angle) * radius;
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
    } else {
      // Simple circle for small particles
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
  }

  let lastTime = 0;

  function animate(time) {
    const delta = Math.min((time - lastTime) / 16.67, 3); // cap delta
    lastTime = time;

    ctx.clearRect(0, 0, W, H);

    particles.forEach((p, i) => {
      // Move
      p.x += p.vx * delta;
      p.y += p.vy * delta;

      // Twinkle
      if (p.twinkle) {
        if (p.fade === 'in') {
          p.alpha += p.dalpha * delta;
          if (p.alpha >= 0.9) p.fade = 'out';
        } else {
          p.alpha -= p.dalpha * delta;
          if (p.alpha <= 0.15) p.fade = 'in';
        }
      }

      drawStar(p.x, p.y, p.r, p.alpha, p.color);

      // Reset when off-screen
      if (p.y < -10 || p.x < -10 || p.x > W + 10) {
        particles[i] = createParticle();
        particles[i].y = H + 5;
      }
    });

    requestAnimationFrame(animate);
  }

  requestAnimationFrame(animate);
})();

/* ============================================================
   NAVBAR SHADOW ON SCROLL
============================================================ */
const navbar = document.querySelector('.navbar');
window.addEventListener('scroll', () => {
  if (window.scrollY > 20) {
    navbar.style.background = 'rgba(15, 23, 42, 0.92)';
    navbar.style.borderBottomColor = 'rgba(255,255,255,0.09)';
  } else {
    navbar.style.background = 'rgba(15, 23, 42, 0.72)';
    navbar.style.borderBottomColor = 'rgba(255,255,255,0.07)';
  }
}, { passive: true });

/* ============================================================
   DEEP-LINK JOIN — consume a shared game link (?code=...)
   Pre-fills the Join modal when the landing page is opened from
   a host "Share Link" (or a ?game=/?team= deep link).
============================================================ */
(function handleDeepLinkJoin() {
  if (!window.Connect || !overlayJoin) return;
  const parsed = Connect.parseLocation();
  if (!parsed || !parsed.code) return;
  const gameCodeInput = document.getElementById('input-gamecode');
  if (gameCodeInput) {
    gameCodeInput.value = parsed.code.toUpperCase().replace(/^PH/i, 'PH');
  }
  openModal(overlayJoin);
})();
