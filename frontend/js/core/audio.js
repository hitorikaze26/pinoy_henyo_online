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
     GameAudio.setMusicEnabled(bool)  -> new music sub-switch state
     GameAudio.setEffectsEnabled(bool) -> new sfx sub-switch state
     GameAudio.getMusicEnabled() / getEffectsEnabled()
     GameAudio.setVolume('music'|'effects', 0..1) -> applied multiplier
     GameAudio.setMusicTrack(fileName)  -> switch background track
   ============================================================ */
(function () {
  const ASSET_ROOT = 'assets/sounds/';
  const SETTINGS_KEY = 'pinoy_henyo_settings';

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

  // Master switch (dashboard mute button). Sub-switches + volume multipliers
  // below are driven by the Host Settings page and default to the classic
  // behaviour (music and effects on at full volume).
  let enabled = true;
  let musicEnabled = true;
  let sfxEnabled = true;
  let musicVolume = 1;
  let sfxVolume = 1;

  function clamp01(v) {
    const n = Number(v);
    return isFinite(n) ? Math.min(1, Math.max(0, n)) : 1;
  }

  function applyMusicTrack(fileName) {
    if (!fileName) return;
    let src = String(fileName);
    if (!/^(https?:)?\/\//.test(src) && src.indexOf('/') === -1) {
      src = ASSET_ROOT + src;
    }
    src = src.replace(/ /g, '%20');
    musicEl.src = src;
  }

  function readSettingsPrefs() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (!raw) return;
      const audio = (JSON.parse(raw) || {}).audio || null;
      if (!audio) return;
      if (typeof audio.musicOn === 'boolean') musicEnabled = audio.musicOn;
      if (typeof audio.sfxOn === 'boolean') sfxEnabled = audio.sfxOn;
      if (audio.musicVolume !== undefined) musicVolume = clamp01(audio.musicVolume);
      if (audio.sfxVolume !== undefined) sfxVolume = clamp01(audio.sfxVolume);
      if (audio.musicTrack && typeof audio.musicTrack === 'string') applyMusicTrack(audio.musicTrack);
    } catch (e) { /* storage disabled or malformed */ }
  }

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

  // Apply any saved Host Settings audio preferences (track, switches, volume).
  readSettingsPrefs();
  musicEl.volume = MUSIC_VOLUME * musicVolume;
  for (const name in effectEls) {
    effectEls[name].volume = EFFECT_VOLUME * sfxVolume;
  }

  /** Start (or restart) the music. When called from a non-gesture context
      (e.g. page load) it plays muted — allowed by browsers. */
  function playMusic() {
    if (!enabled || !musicEnabled) return false;
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
    if (!enabled || !sfxEnabled) return;
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

  function setMusicEnabled(value) {
    musicEnabled = !!value;
    if (musicEnabled) playMusic();
    else pauseMusic();
    return musicEnabled;
  }

  function setEffectsEnabled(value) {
    sfxEnabled = !!value;
    return sfxEnabled;
  }

  function setVolume(kind, value) {
    const v = clamp01(value);
    if (kind === 'music') {
      musicVolume = v;
      musicEl.volume = MUSIC_VOLUME * v;
    } else if (kind === 'effects' || kind === 'sfx') {
      sfxVolume = v;
      for (const name in effectEls) {
        effectEls[name].volume = EFFECT_VOLUME * v;
      }
    }
    return v;
  }

  function setMusicTrack(fileName) {
    if (!fileName) return false;
    applyMusicTrack(fileName);
    playMusic();
    return true;
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
    setMusicEnabled,
    setEffectsEnabled,
    getMusicEnabled: () => musicEnabled,
    getEffectsEnabled: () => sfxEnabled,
    setVolume,
    setMusicTrack,
    get enabled() { return enabled; },
    get musicPlaying() { return !musicEl.paused && !musicEl.ended; },
    get musicMuted() { return musicEl.muted; },
  };
})();