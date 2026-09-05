'use strict';
/* ============================================================
   GameAudio — background music + UI sound effects.
   ------------------------------------------------------------
   Shared audio helper. Lands on the landing page so the page
   opens with the background game music playing; the speaker
   control in the navbar area toggles sound on/off (default ON).

   Browser autoplay policy: browsers block AUDIBLE autoplay until the user
   has interacted with the origin at least once, but always allow MUTED
   autoplay. So on load we start the music MUTED (guaranteed to be running
   the instant the page opens), then the first pointer/touch/key gesture
   unmutes it in the same gesture (allowed). Once the origin has gesture
   history, the browser permits audible autoplay, so later opens start
   audibly and the very first gesture just keeps them playing.

   API:
     GameAudio.toggle() -> bool (new enabled state)
     GameAudio.play(name)   // UI effect by short name
     GameAudio.playMusic()
     GameAudio.pauseMusic()
     GameAudio.enabled      // current enabled state
     GameAudio.musicPlaying // music is running (not paused/ended)
     GameAudio.musicMuted   // music is running muted (pre-gesture first visit)
   ============================================================ */
(function () {
  const ASSET_ROOT = 'assets/sounds/';

  // Short name -> file under assets/sounds/ui/ (extra names reserved).
  const UI_EFFECTS = {
    click:        'click.mp3',
    popup:        'pop-up.mp3',
    start:        'start-button.mp3',
    confirm:      'confirm-ui.mp3',
    error:        'error-ui.mp3',
    notification: 'notification.mp3',
    loading:      'complete-loading.mp3',
    levelup:      'level-up.mp3',
  };

  const MUSIC_SRC = ASSET_ROOT + 'game%20music.mp3';
  const MUSIC_VOLUME = 0.4;
  const EFFECT_VOLUME = 0.6;

  let enabled = true;

  const musicEl = new Audio();
  musicEl.src = MUSIC_SRC;
  musicEl.loop = true;
  musicEl.volume = MUSIC_VOLUME;
  musicEl.preload = 'auto';
  // Start muted so autoplay policy never blocks the music from running on
  // open; the first user gesture unmutes it (see onFirstGesture below).
  musicEl.muted = true;

  // One Audio element per effect; playback is restarted via currentTime=0.
  const effectEls = Object.create(null);
  for (const name in UI_EFFECTS) {
    if (!Object.prototype.hasOwnProperty.call(UI_EFFECTS, name)) continue;
    const el = new Audio(ASSET_ROOT + 'ui/' + UI_EFFECTS[name]);
    el.volume = EFFECT_VOLUME;
    el.preload = 'auto';
    effectEls[name] = el;
  }

  /** Start (or restart) the music. When called from a non-gesture context
      (e.g. page load) it plays muted — allowed by browsers. */
  function playMusic() {
    if (!enabled) return false;
    const attempt = musicEl.play();
    if (attempt && typeof attempt.catch === 'function') {
      attempt.catch(() => { /* nothing audible to resume until a gesture */ });
    }
    return true;
  }

  function pauseMusic() {
    musicEl.pause();
  }

  function stopMusic() {
    musicEl.pause();
    musicEl.currentTime = 0;
  }

  function play(name) {
    if (!enabled) return;
    const el = effectEls[name];
    if (!el) return;
    try {
      el.currentTime = 0;
      const attempt = el.play();
      if (attempt && typeof attempt.catch === 'function') {
        attempt.catch(() => { /* blocked until first gesture */ });
      }
    } catch (e) { /* ignore */ }
  }

  function toggle() {
    enabled = !enabled;
    if (enabled) {
      playMusic();
    } else {
      pauseMusic();
    }
    return enabled;
  }

  /** Called once on the first user gesture: unmute (allowed during the
      gesture) so the music and UI effects become audible. */
  function unlock() {
    if (!enabled) return;
    musicEl.muted = false;
    playMusic();
  }
  const UNLOCK_EVENTS = ['pointerdown', 'touchstart', 'keydown'];

  // Start as soon as possible: audible if allowed, muted-autoplay otherwise.
  playMusic();

  // The first real gesture unmutes the muted fallback. The listeners are
  // cheap and self-remove afterwards.
  let unlocked = false;
  const onFirstGesture = function () {
    if (unlocked) return;
    unlocked = true;
    UNLOCK_EVENTS.forEach((ev) => document.removeEventListener(ev, onFirstGesture, true));
    unlock();
  };
  UNLOCK_EVENTS.forEach((ev) => document.addEventListener(ev, onFirstGesture, true));

  window.GameAudio = {
    toggle,
    play,
    playMusic,
    pauseMusic,
    stopMusic,
    get enabled() { return enabled; },
    get musicPlaying() { return !musicEl.paused && !musicEl.ended; },
    get musicMuted() { return musicEl.muted; },
  };
})();