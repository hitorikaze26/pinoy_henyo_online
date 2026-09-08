'use strict';

/* ============================================================
   AI Word Generator — shared two-step overlay (host + player)
   ------------------------------------------------------------
   Entry point: window.AIWordGenerator.open({ ...context })
     gameId          : game id to generate words for
     mode            : 'host' | 'player'
     locked          : whether the word pool is locked (guard only)
     categories      : [{ id, name }] — real backend categories
     capacityFor(name): remaining slots for a category, or null = unlimited
     existingWordsFor(name): current pool words in that category (for dedupe)
     addWord(word, categoryName, categoryId): authoritative per-word create
     onWordsChanged()   : refetch + rerender after adding (host: refreshWordPool,
                          player: refreshWordsFromServer)
   Generated words are never auto-inserted: the user locks the ones they
   want and adds them through the same per-word API the manual flow uses.
   ============================================================ */

const AIWordGenerator = (() => {
  const COUNT_CHOICES = [3, 5, 10, 15, 20];
  const MAX_COUNT = 20;

  let ctx = null;
  let s = {
    step: 'setup',            // 'setup' | 'results'
    categoryId: null,
    categoryName: '',
    isPlace: false,
    count: 5,
    language: 'both',
    pool: [],                 // words the user chose to keep (locked)
    batch: [],                // latest suggestions, each { word, locked }
    seen: new Set(),          // every word ever suggested this session
    busy: false,
  };

  let overlay = null;
  let selfClosing = false;
  let observer = null;

  function esc(v) {
    return String(v ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function showToast(msg, duration) {
    if (typeof window.showToast === 'function') window.showToast(msg, duration);
    else if (window.Toast && typeof window.Toast.showToast === 'function') window.Toast.showToast(msg, duration);
  }

  function normalize(w) {
    return String(w || '').trim().toLowerCase().replace(/\s+/g, ' ');
  }

  function isPlaceCategory(name) {
    const n = String(name || '').toLowerCase();
    return n.includes('lugar') || n.includes('place');
  }

  function hasBackend() {
    return Boolean(ctx && window.AIAPI && ctx.gameId && API && API.getGameId());
  }

  function remaining(catName) {
    if (!ctx || typeof ctx.capacityFor !== 'function') return null;
    return ctx.capacityFor(catName);
  }

  function idleBusy(on) {
    s.busy = on;
    overlay.querySelectorAll('button').forEach(b => { b.disabled = on; });
    const st = overlay.querySelector('.ai-status');
    if (st && !on) st.textContent = '';
  }

  function buildDom() {
    overlay = document.createElement('div');
    overlay.id = 'ai-overlay';
    overlay.className = 'modal-overlay ai-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.setAttribute('aria-labelledby', 'ai-title');
    overlay.innerHTML = `
      <div class="modal ai-modal">
        <button class="modal__close ai-close" type="button" aria-label="Close">
          <i class="fa-solid fa-xmark"></i>
        </button>
        <div class="modal__header">
          <div class="modal__icon modal__icon--ai"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
          <div>
            <h2 class="modal__title" id="ai-title">AI Word Generator</h2>
            <p class="modal__subtitle ai-subtitle">Let AI suggest words for your game.</p>
          </div>
        </div>

        <div class="ai-panel ai-panel--setup">
          <div class="form-group">
            <label class="form-label" for="ai-category"><i class="fa-solid fa-tag"></i> Category</label>
            <select id="ai-category" class="form-select"></select>
          </div>
          <div class="form-group">
            <label class="form-label"><i class="fa-solid fa-hashtag"></i> How many words?</label>
            <div class="ai-count-row" id="ai-count-chips"></div>
            <div class="ai-count-manual">
              <label class="form-label ai-count-manual__label" for="ai-count-manual">Custom</label>
              <input type="number" id="ai-count-manual" class="form-input ai-count-manual__input" min="1" max="${MAX_COUNT}" step="1" placeholder="1–${MAX_COUNT}" />
            </div>
            <span class="form-hint" id="ai-capacity-hint"></span>
          </div>
          <div class="form-group ai-lang">
            <label class="form-label"><i class="fa-solid fa-language"></i> Language</label>
            <div class="ai-lang-row">
              <label class="ai-pill"><input type="radio" name="ai-lang" value="tagalog" /><span>Tagalog</span></label>
              <label class="ai-pill"><input type="radio" name="ai-lang" value="english" /><span>English</span></label>
              <label class="ai-pill"><input type="radio" name="ai-lang" value="both" checked /><span>Both</span></label>
            </div>
          </div>
          <p class="ai-note"><i class="fa-solid fa-bolt"></i> Suggestions are AI-composed — review them before adding. Nothing is added until you confirm.</p>
          <span class="ai-status" aria-live="polite"></span>
          <div class="modal__actions">
            <button type="button" class="btn-cancel ai-cancel">Cancel</button>
            <button type="button" class="btn-confirm ai-generate">
              <i class="fa-solid fa-wand-magic-sparkles"></i> Generate
            </button>
          </div>
        </div>

        <div class="ai-panel ai-panel--results" hidden>
          <p class="ai-results-head" id="ai-results-head">Suggestions</p>
          <div class="ai-results-count" id="ai-results-count" aria-live="polite"></div>
          <div class="ai-results-body">
            <div class="ai-pool-section" id="ai-pool-section" hidden>
              <p class="ai-section-label">Ready to add</p>
              <div class="ai-pool" id="ai-pool"></div>
            </div>
            <div class="ai-batch-section">
              <p class="ai-section-label">New suggestions</p>
              <div class="ai-batch" id="ai-batch"></div>
            </div>
          </div>
          <span class="ai-status" aria-live="polite"></span>
          <div class="modal__actions ai-results-actions">
            <button type="button" class="btn-cancel ai-back"><i class="fa-solid fa-arrow-left"></i> Back</button>
            <button type="button" class="btn-cancel ai-more">Generate more</button>
            <button type="button" class="btn-confirm ai-add">
              <i class="fa-solid fa-check"></i> Add <span class="ai-add-count"></span>
            </button>
          </div>
        </div>
      </div>`;

    document.body.appendChild(overlay);

    overlay.querySelector('.ai-close').addEventListener('click', e => {
      e.stopPropagation();
      close();
    });
    overlay.querySelector('.ai-cancel').addEventListener('click', () => close());
    overlay.querySelector('.ai-back').addEventListener('click', () => showSetup());
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

    overlay.querySelector('#ai-category').addEventListener('change', onCategoryChange);
    overlay.querySelectorAll('input[name="ai-lang"]').forEach(r => {
      r.addEventListener('change', () => {
        const v = overlay.querySelector('input[name="ai-lang"]:checked');
        if (v) s.language = v.value;
      });
    });
    const manual = overlay.querySelector('#ai-count-manual');
    manual.addEventListener('input', () => { s.count = clampInt(manual.value, 1, MAX_COUNT, 5); syncCountChips(); });
    manual.addEventListener('change', () => {
      s.count = clampInt(manual.value, 1, MAX_COUNT, 5);
      manual.value = s.count;
      syncCountChips();
    });

    overlay.querySelector('.ai-generate').addEventListener('click', doGenerate);
    overlay.querySelector('.ai-more').addEventListener('click', doGenerateMore);
    overlay.querySelector('.ai-add').addEventListener('click', doAdd);

    // If the page-level Escape / backdrop handlers (which iterate every
    // .modal-overlay.open) close our overlay, tidy up our own state.
    observer = new MutationObserver(() => {
      if (!overlay) return;
      if (!overlay.classList.contains('open') && !selfClosing) onExternalClose();
    });
    observer.observe(overlay, { attributes: true, attributeFilter: ['class'] });
  }

  function clampInt(v, min, max, fallback) {
    const n = parseInt(v, 10);
    if (Number.isNaN(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  function fillCategorySelect() {
    const sel = overlay.querySelector('#ai-category');
    sel.innerHTML = '<option value="">Select category</option>';
    ctx.categories.forEach(c => {
      sel.innerHTML += `<option value="${esc(c.id)}" data-name="${esc(c.name)}">${esc(c.name)}</option>`;
    });
  }

  function renderCountChips() {
    const row = overlay.querySelector('#ai-count-chips');
    row.innerHTML = COUNT_CHOICES.map(n => `
      <button type="button" class="ai-chip ${n === s.count ? 'is-active' : ''}" data-n="${n}">${n}</button>
    `).join('');
    row.querySelectorAll('.ai-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        s.count = Number(chip.dataset.n);
        overlay.querySelector('#ai-count-manual').value = '';
        syncCountChips();
      });
    });
  }

  function syncCountChips() {
    const manual = overlay.querySelector('#ai-count-manual');
    overlay.querySelectorAll('.ai-chip').forEach(chip => {
      const on = manual.value !== '' ? Number(chip.dataset.n) === Number(manual.value) : Number(chip.dataset.n) === s.count;
      chip.classList.toggle('is-active', on);
    });
  }

  function selectedCategory() {
    const sel = overlay.querySelector('#ai-category');
    const opt = sel && sel.options[sel.selectedIndex];
    if (!opt || !opt.value) return null;
    return { id: Number(opt.value), name: opt.getAttribute('data-name') || opt.textContent };
  }

  function updateCapacityHint() {
    const hint = overlay.querySelector('#ai-capacity-hint');
    const cat = selectedCategory();
    if (ctx.mode !== 'player') {
      hint.textContent = cat ? 'Host pool — no per-category word cap applies.' : '';
      hint.classList.remove('form-hint--full');
      return;
    }
    const left = cat ? remaining(cat.name) : null;
    if (left == null || left === Infinity) {
      hint.textContent = cat ? 'No per-category word cap applies.' : '';
    } else {
      hint.textContent = left <= 0
        ? 'This category is full — no slots left.'
        : `${left} slot${left === 1 ? '' : 's'} left in this category.`;
      hint.classList.toggle('form-hint--full', left <= 0);
    }
  }

  function onCategoryChange() {
    const cat = selectedCategory();
    if (!cat) return;
    s.categoryId = cat.id;
    s.categoryName = cat.name;
    s.isPlace = isPlaceCategory(cat.name);
    const langGroup = overlay.querySelector('.ai-lang');
    if (langGroup) langGroup.hidden = s.isPlace;
    s.pool = [];
    s.batch = [];
    s.seen = new Set();
    updateCapacityHint();
    const manual = overlay.querySelector('#ai-count-manual');
    if (manual) manual.value = '';
    s.count = 5;
    syncCountChips();
  }

  function setStatus(msg, isError) {
    const st = overlay.querySelector('.ai-status');
    if (!st) return;
    st.textContent = msg || '';
    st.classList.toggle('ai-status--error', Boolean(isError));
  }

  function showSetup() {
    s.step = 'setup';
    overlay.querySelector('.ai-panel--setup').hidden = false;
    overlay.querySelector('.ai-panel--results').hidden = true;
    setStatus('');
    updateCapacityHint();
  }

  function showResults() {
    s.step = 'results';
    renderResults();
    overlay.querySelector('.ai-panel--setup').hidden = true;
    overlay.querySelector('.ai-panel--results').hidden = false;
  }

  function renderResults() {
    const head = overlay.querySelector('#ai-results-head');
    head.textContent = `Suggestions for ${esc(s.categoryName)}`;

    const total = s.pool.length + s.batch.length;
    const locked = s.pool.length + s.batch.filter(w => w.locked).length;
    overlay.querySelector('#ai-results-count').textContent =
      `${total} word${total === 1 ? '' : 's'} · ${locked} locked`;

    const poolSec = overlay.querySelector('#ai-pool-section');
    const pool = overlay.querySelector('#ai-pool');
    poolSec.hidden = !s.pool.length;
    pool.innerHTML = s.pool.map((w, i) => `
      <div class="ai-item ai-item--locked">
        <span class="ai-item__text">${esc(w.word)}</span>
        <button type="button" class="ai-item__unlock" data-i="${i}" title="Remove" aria-label="Remove ${esc(w.word)}">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>`).join('');
    pool.querySelectorAll('.ai-item__unlock').forEach(btn => {
      btn.addEventListener('click', () => {
        s.pool.splice(Number(btn.dataset.i), 1);
        renderResults();
      });
    });

    const batch = overlay.querySelector('#ai-batch');
    if (!s.batch.length) {
      batch.innerHTML = `<p class="ai-empty">No new suggestions yet — tap “Generate more”.</p>`;
    } else {
      batch.innerHTML = s.batch.map((w, i) => `
        <div class="ai-item ${w.locked ? 'ai-item--locked' : ''}" data-i="${i}">
          <span class="ai-item__text">${esc(w.word)}</span>
          <button type="button" class="ai-item__lock" data-i="${i}" title="${w.locked ? 'Not this one' : 'Keep this one'}" aria-label="${w.locked ? 'Unlock' : 'Lock'} ${esc(w.word)}">
            <i class="fa-solid ${w.locked ? 'fa-lock' : 'fa-lock-open'}"></i>
          </button>
        </div>`).join('');
      batch.querySelectorAll('.ai-item__lock').forEach(btn => {
        btn.addEventListener('click', () => {
          const i = Number(btn.dataset.i);
          s.batch[i].locked = !s.batch[i].locked;
          renderResults();
        });
      });
    }

    const addBtn = overlay.querySelector('.ai-add');
    addBtn.querySelector('.ai-add-count').textContent = locked ? ` ${locked}` : '';
    addBtn.disabled = locked === 0;
  }

  function seenWords() {
    const existing = (typeof ctx.existingWordsFor === 'function')
      ? ctx.existingWordsFor(s.categoryName)
      : [];
    const all = new Set();
    existing.forEach(w => all.add(normalize(w)));
    s.seen.forEach(w => all.add(w));
    s.pool.forEach(w => all.add(normalize(w.word)));
    s.batch.forEach(w => all.add(normalize(w.word)));
    return Array.from(all);
  }

  async function doGenerate() {
    const cat = selectedCategory();
    if (!cat) { setStatus('Please select a category.', true); return; }
    if (!hasBackend()) { setStatus('AI needs an active server connection.', true); return; }

    const left = remaining(cat.name);
    if (ctx.mode === 'player' && left != null && left !== Infinity && left <= 0) {
      setStatus('This category is full — no more words can be added.', true);
      return;
    }

    setupFor(cat);
    const toRequest = (left != null && left !== Infinity) ? Math.min(s.count, Math.max(left, 1)) : s.count;
    idleBusy(true);
    setStatus('');
    overlay.querySelector('.ai-generate').innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generating…';
    try {
      const data = await AIAPI.generateWords(ctx.gameId, {
        categoryId: cat.id,
        count: toRequest,
        language: s.isPlace ? null : s.language,
        excludeWords: seenWords(),
      });
      s.categoryName = data.category_name || cat.name;
      s.batch = (data.suggestions || []).map(w => ({ word: w, locked: true }));
      s.batch.forEach(w => s.seen.add(normalize(w.word)));
      if (!s.batch.length) {
        setStatus('AI returned no new words for this category.', false);
        showResults();
        return;
      }
      showResults();
    } catch (err) {
      handleError(err);
    } finally {
      idleBusy(false);
      overlay.querySelector('.ai-generate').innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate';
    }
  }

  async function doGenerateMore() {
    const cat = selectedCategory();
    if (!cat) return;

    // The currently locked batch words are kept for adding.
    s.batch.filter(w => w.locked).forEach(w => { s.pool.push({ ...w }); });

    const left = remaining(cat.name);
    if (ctx.mode === 'player' && left != null && left !== Infinity && left <= 0) {
      setStatus('This category is full — no more words can be added.', true);
      renderResults();
      return;
    }

    s.batch = [];
    await doGenerate();
  }

  function setupFor(cat) {
    s.categoryId = cat.id;
    s.categoryName = cat.name;
    s.isPlace = isPlaceCategory(cat.name);
  }

  async function doAdd() {
    const cat = selectedCategory();
    if (!cat || s.busy) return;
    const targets = [];
    s.pool.forEach(w => targets.push(w.word));
    s.batch.filter(w => w.locked).forEach(w => targets.push(w.word));
    if (!targets.length) return;

    const addBtn = overlay.querySelector('.ai-add');
    const moreBtn = overlay.querySelector('.ai-more');
    const backBtn = overlay.querySelector('.ai-back');
    addBtn.disabled = moreBtn.disabled = backBtn.disabled = true;
    addBtn.innerHTML = '<i class="fa-solid fa-check"></i> Adding…';
    setStatus('');

    let added = 0;
    let skipped = 0;
    let fail = null;
    try {
      for (const word of targets) {
        try {
          const created = await ctx.addWord(word, s.categoryName, s.categoryId);
          if (created && (created.word_id || created.id)) added++; else skipped++;
        } catch (err) {
          const code = (err && err.code) || '';
          if (/DUPLICATE|EXISTS|TAKEN/.test(code) || /category.*full|limit/i.test(err && err.message)) {
            skipped++;
          } else {
            fail = err;
            break;
          }
        }
      }
      if (fail) {
        setStatus((fail && fail.message) || 'Could not add the selected words.', true);
        return;
      }
      if (typeof ctx.onWordsChanged === 'function') await ctx.onWordsChanged();
      close();
      const total = added + skipped;
      showToast(skipped
        ? `${added} AI word${added === 1 ? '' : 's'} added to ${esc(s.categoryName)} (${skipped} skipped — already in the pool)`
        : `${added} AI word${added === 1 ? '' : 's'} added to ${esc(s.categoryName)}`, 4000);
    } catch (err) {
      console.error('[AI Word Generator] add failed', err);
      setStatus((err && err.message) || 'Could not add the selected words.', true);
    } finally {
      addBtn.disabled = moreBtn.disabled = backBtn.disabled = false;
      const locked = s.pool.length + s.batch.filter(w => w.locked).length;
      addBtn.innerHTML = `<i class="fa-solid fa-check"></i> Add <span class="ai-add-count">${locked ? ` ${locked}` : ''}</span>`;
    }
  }

  function handleError(err) {
    console.warn('[AI Word Generator] generate failed', err && err.message);
    const code = (err && err.code) || '';
    if (code === 'AI_RATE_LIMITED') {
      const secs = (err && err.retryAfter) || 30;
      setStatus(`Hold on — generating too fast. Try again in ${secs == null ? 'a moment' : `${Math.ceil(secs)}s`}.`, true);
    } else if (code === 'AI_NOT_CONFIGURED') {
      setStatus('The host has not connected an AI provider yet. Once GEMINI_API_KEY is set, AI suggestions will work here.', true);
    } else if (code === 'AI_GENERATION_UNAVAILABLE' || code === 'AI_GENERATION_INVALID_RESPONSE') {
      setStatus('The AI service could not generate words right now. Please try again.', true);
    } else if (err && err.network) {
      setStatus('Could not reach the server. Check your connection and try again.', true);
    } else {
      setStatus((err && err.message) || 'Something went wrong while generating words.', true);
    }
  }

  function onExternalClose() {
    selfClosing = false;
    s.busy = false;
    overlay.querySelectorAll('button').forEach(b => { b.disabled = false; });
    document.body.style.overflow = '';
  }

  function close() {
    if (!overlay) return;
    selfClosing = true;
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
    const anyOtherOpen = document.querySelectorAll('.modal-overlay.open').length > 0;
    if (!anyOtherOpen) document.body.style.overflow = '';
    s = { step: 'setup', categoryId: null, categoryName: '', isPlace: false, count: 5, language: 'both', pool: [], batch: [], seen: new Set(), busy: false };
  }

  function open(context) {
    if (!context || typeof context !== 'object') {
      showToast('AI Word Generator is not available here.');
      return false;
    }
    if (context.locked) {
      showToast('Words are locked.');
      return false;
    }
    ctx = Object.assign({
      gameId: null,
      mode: 'host',
      locked: false,
      categories: [],
      capacityFor: () => null,
      existingWordsFor: () => [],
      addWord: null,
      onWordsChanged: null,
    }, context);

    if (!hasBackend()) {
      showToast('AI Word Generator needs an active game connection.');
      return false;
    }

    if (!overlay) buildDom();

    overlay.querySelectorAll('button').forEach(b => { b.disabled = false; });

    s = { step: 'setup', categoryId: null, categoryName: '', isPlace: false, count: 5, language: 'both', pool: [], batch: [], seen: new Set(), busy: false };

    fillCategorySelect();
    renderCountChips();
    const langGroup = overlay.querySelector('.ai-lang');
    if (langGroup) langGroup.hidden = false;
    const radio = overlay.querySelector('input[name="ai-lang"][value="both"]');
    if (radio) radio.checked = true;
    overlay.querySelector('#ai-count-manual').value = '';
    overlay.querySelector('.ai-panel--results').hidden = true;
    overlay.querySelector('.ai-panel--setup').hidden = false;
    showSetup();

    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const first = overlay.querySelector('#ai-category');
    if (first) setTimeout(() => first.focus(), 60);
    return true;
  }

  return { open };
})();

if (typeof window !== 'undefined') window.AIWordGenerator = AIWordGenerator;