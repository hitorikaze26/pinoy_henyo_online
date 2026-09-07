'use strict';
/* ============================================================
   HOST — LEAVE GAME (shared)
   ------------------------------------------------------------
   Ends this device's host session and returns to the lobby.
   The server keeps the game (teams, words, scores) alive and
   leaves the session token valid for rejoin; the lobby's My
   Games registry keeps the host token, so "Continue" can re-open
   the dashboard from the lobby at any time.

   Injects a "Leave Game" action into the host sidebar footer
   (next to Back to Lobby) and exposes HostLeaveGame.confirmAndLeave()
   for page-specific buttons (e.g. the Settings danger zone).
   ============================================================ */
(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  const LOBBY_URL = '../../index.html';

  function currentGameId() {
    return (API.getGameId && API.getGameId()) || (API.getHostGameId && API.getHostGameId()) || null;
  }

  function clearSession() {
    // Close the realtime socket so no reconnect attempts fire during the
    // redirect window. Player leave uses the same approach.
    if (Realtime && typeof Realtime.getSocket === 'function') {
      try { Realtime.getSocket()?.close(); } catch (err) { /* noop */ }
    }
    // Wipe the live host context (role/tokens/code). The My Games registry
    // keeps host_token per game, so the lobby "Continue" still works.
    API.clearTokens();
  }

  async function confirmAndLeave() {
    const id = currentGameId();
    if (!id) { window.location.href = LOBBY_URL; return; }

    const confirmed = await window.Confirm.open({
      title: 'Leave this game?',
      body: 'Your host session on this device ends and you return to the lobby. The game, teams, words, and scores stay on the server — reopen it from My Games.',
      confirmLabel: 'Leave Game',
      icon: 'leave',
      destructive: true,
      requestKey: 'leave-game',
    });
    if (!confirmed) return;

    window.Confirm.busy(true, 'Leaving…');

    try {
      await GameAPI.leave(id);
    } catch (e) {
      console.warn('[host-leave] leave failed', e && e.message);
      window.Confirm.close();
      const reason =
        (API.messageForStatus && e && e.status
          ? API.messageForStatus(e.status, e.message)
          : null) ||
        (e && e.message) ||
        'Could not leave right now. Check the connection.';
      window.showToast(reason);
      return;
    }

    clearSession();
    window.location.href = LOBBY_URL;
  }

  /* -- sidebar footer injection (all host pages) -- */
  function injectSidebarButton() {
    const footer = document.querySelector('.sidebar__footer');
    if (!footer || footer.querySelector('.sidebar__leave-btn')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'btn-leave-game-sidebar';
    btn.className = 'sidebar__leave-btn';
    btn.setAttribute('aria-label', 'Leave Game');
    btn.innerHTML = '<i class="fa-solid fa-right-from-bracket"></i><span>Leave Game</span>';
    btn.addEventListener('click', confirmAndLeave);

    footer.appendChild(btn);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectSidebarButton);
  } else {
    injectSidebarButton();
  }

  window.HostLeaveGame = { confirmAndLeave };
})();