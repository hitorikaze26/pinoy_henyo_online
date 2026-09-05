'use strict';
/* ============================================================
   GameAudio — background music + UI sound effects.
   ------------------------------------------------------------
   Shared audio helper. Lands on the landing page so the page
   opens with the background game music playing; the speaker
   control in the navbar area toggles sound on/off (default ON).

   Browser autoplay policy: audible playback requires a user
   gesture, so on load we attempt music.play() optimistically.
   If the browser blocks it (NotAllowedError), we resume the
   music on the first pointer/touch/key interaction via unlock().

   API:
     GameAudio.toggle() -> bool (new enabled state)
     GameAudio.play(name)   // UI effect by short name
     GameAudio.playMusic()
     GameAudio.pauseMusic()
     GameAudio.enabled      // current enabled state
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

  // One Audio element per effect; playback is restarted via currentTime=0.
  const effectEls = Object.create(null);
  for (const name in UI_EFFECTS) {
    if (!Object.prototype.hasOwnProperty.call(UI_EFFECTS, name)) continue;
    const el = new Audio(ASSET_ROOT + 'ui/' + UI_EFFECTS[name]);
    el.volume = EFFECT_VOLUME;
    el.preload = 'auto';
    effectEls[name] = el;
  }

  /** Attempt playback; returns true if playback started. */
  function playMusic() {
    if (!enabled) return false;
    const attempt = musicEl.play();
    if (attempt && typeof attempt.catch === 'function') {
      attempt.catch(() => { /* blocked by autoplay policy — wait for a gesture */ });
      return true;
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

  /** Called once on the first user gesture to satisfy autoplay policy. */
  function unlock() {
    if (!enabled) return;
    playMusic();
  }

  const UNLOCK_EVENTS = ['pointerdown', 'touchstart', 'keydown'];

  // Always attempt right away. If blocked, the first real gesture resumes
  // the music (this also unlocks the gated UI effect playback).
  playMusic();

  // A gesture is only needed if the optimistic attempt was rejected. Rather
  // than tracking rejection state (some engines resolve.play() lazily), arm
  // the unlock listeners once; they are cheap and self-remove afterwards.
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
  };
})();