'use strict';
/* ============================================================
   CustomSelect — styled dropdowns for host pages.
   ------------------------------------------------------------
   Enhances any native <select class="dd"> into a consistent
   button + listbox UI. The real <select> stays in the DOM
   (visually hidden inside the wrapper), so existing JS that
   reads `.value` or listens to `change` keeps working: picking
   an option dispatches a real bubbling `change` event.

   API:
     CustomSelect.init(root)     enhance every `select.dd` under root
     CustomSelect.refresh(scope) re-sync existing wrappers / bind new ones

   Dynamic `<select class="dd">` elements inserted later are
   auto-enhanced (body MutationObserver); option lists rebuilt
   via innerHTML are auto-synced (per-select observer).
   ============================================================ */
(function () {
  const BOUND = 'data-cs-bound';
  let uid = 0;

  const active = { wrapper: null }; // currently open dropdown

  function enhance(select) {
    if (select.__cs) return select.__cs;           // already bound
    // The native select still carries the `dd` class, so `.closest('.dd')`
    // matches the select itself here; only skip when it is already inside
    // an existing wrapper (i.e. closest resolves to a different element).
    const alreadyWrapped = select.closest('.dd');
    if (alreadyWrapped && alreadyWrapped !== select) return null;
    if (!select.parentNode) return null;
    select.setAttribute(BOUND, '1');

    const wrapper = document.createElement('div');
    wrapper.className = 'dd';
    wrapper.dataset.csWrapper = '1';
    // Carry modifier classes (e.g. `dd--pill`) over to the wrapper so the
    // button/listbox pick up their styles; drop layout-bearing classes that
    // only apply to the hidden native element.
    Array.prototype.forEach.call(select.classList, (c) => {
      if (c !== 'dd' && c !== 'form-select' && c !== 'controls-filter') {
        wrapper.classList.add(c);
      }
    });

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dd__button';
    btn.setAttribute('aria-haspopup', 'listbox');

    const labelEl = document.createElement('span');
    labelEl.className = 'dd__label';

    const caret = document.createElement('span');
    caret.className = 'dd__caret';
    caret.setAttribute('aria-hidden', 'true');

    const listbox = document.createElement('ul');
    const boxId = 'dd-list-' + (++uid);
    listbox.id = boxId;
    listbox.className = 'dd__listbox';
    listbox.setAttribute('role', 'listbox');
    listbox.hidden = true;
    btn.setAttribute('aria-controls', boxId);

    btn.appendChild(labelEl);
    btn.appendChild(caret);
    wrapper.appendChild(btn);
    wrapper.appendChild(listbox);

    select.classList.add('dd__native');
    select.classList.remove('dd');                 // hide native; avoids self-match on re-enhance
    select.parentNode.insertBefore(wrapper, select); // wrapper takes select's slot
    wrapper.appendChild(select);                     // then hide the real select inside

    const api = {
      wrapper,
      btn,
      labelEl,
      listbox,
      open,
      close,
      toggle,
      renderOptions,
    };
    wrapper.__api = api;

    /* ---------- rendering ---------- */
    let optionCount = 0;
    function renderOptions() {
      const selected = select.selectedIndex >= 0 ? select.options[select.selectedIndex] : null;
      labelEl.textContent = selected ? selected.textContent.trim() : '\u00A0';
      btn.title = selected ? selected.textContent.trim() : '';

      const frag = document.createDocumentFragment();
      optionCount = 0;
      const buildOpt = (opt) => {
        const idx = optionCount++;
        const li = document.createElement('li');
        li.className = 'dd__option' + (opt.disabled ? ' dd__option--disabled' : '');
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', opt.selected ? 'true' : 'false');
        li.textContent = opt.textContent.trim();
        if (!opt.disabled) li.dataset.idx = String(idx);
        frag.appendChild(li);
      };
      Array.prototype.forEach.call(select.children, (child) => {
        if (child.tagName === 'OPTGROUP') {
          if (child.label) {
            const g = document.createElement('li');
            g.className = 'dd__group';
            g.setAttribute('role', 'presentation');
            g.textContent = child.label;
            frag.appendChild(g);
          }
          Array.prototype.forEach.call(child.options, buildOpt);
        } else if (child.tagName === 'OPTION') {
          buildOpt(child);
        }
      });
      listbox.innerHTML = '';
      listbox.appendChild(frag);
      syncDisabled();
    }

    function syncDisabled() {
      btn.disabled = !!select.disabled;
      btn.classList.toggle('dd__button--disabled', !!select.disabled);
    }

    /* ---------- open / close ---------- */
    function open() {
      renderOptions(); // re-sync label/options right before showing
      listbox.hidden = false;
      btn.setAttribute('aria-expanded', 'true');
      wrapper.classList.add('dd--open');
      active.wrapper = wrapper;
      const chosen = listbox.querySelector('.dd__option--selected') ||
        listbox.querySelector('.dd__option:not(.dd__option--disabled)');
      if (chosen) setActive(chosen);
    }
    function close() {
      listbox.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      wrapper.classList.remove('dd--open');
      if (active.wrapper === wrapper) active.wrapper = null;
    }
    function toggle() { listbox.hidden ? open() : close(); }

    /* ---------- selection ---------- */
    function choose(li) {
      const idx = Number(li && li.dataset.idx);
      const opt = select.options[idx];
      if (!opt || opt.disabled) return;
      select.value = opt.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      close();
      renderOptions();
    }

    function setActive(li) {
      const prev = listbox.querySelector('.dd__option--active');
      if (prev) prev.classList.remove('dd__option--active');
      li.classList.add('dd__option--active');
      btn.setAttribute('aria-activedescendant', li.id || '');
      if (typeof li.scrollIntoView === 'function') {
        li.scrollIntoView({ block: 'nearest' });
      }
    }
    function activeOption() {
      return listbox.querySelector('.dd__option--active');
    }
    function move(delta) {
      open();
      const items = Array.prototype.slice.call(listbox.querySelectorAll('.dd__option:not(.dd__option--disabled)'));
      if (!items.length) return;
      const cur = activeOption();
      let i = cur ? items.indexOf(cur) : -1;
      i = delta === -Infinity ? 0 : (delta === Infinity ? items.length - 1 : i + delta);
      if (i < 0) i = items.length - 1;
      if (i >= items.length) i = 0;
      setActive(items[i]);
    }

    /* ---------- typeahead ---------- */
    const typeahead = { q: '', timer: null };
    function typeaheadMatch(key) {
      const items = Array.prototype.slice.call(listbox.querySelectorAll('.dd__option:not(.dd__option--disabled)'));
      if (!items.length) return;
      open();
      typeahead.q = (typeahead.q + key).toLowerCase();
      clearTimeout(typeahead.timer);
      typeahead.timer = setTimeout(() => { typeahead.q = ''; }, 800);
      const cur = activeOption();
      let start = cur ? items.indexOf(cur) + 1 : 0;
      for (let n = 0; n < items.length; n++) {
        const li = items[(start + n) % items.length];
        if (li.textContent.trim().toLowerCase().indexOf(typeahead.q) === 0) {
          setActive(li);
          return;
        }
      }
      // fall back to allowing any-match within the word
      for (let n = 0; n < items.length; n++) {
        const li = items[(start + n) % items.length];
        if (li.textContent.trim().toLowerCase().indexOf(typeahead.q) > 0) {
          setActive(li);
          return;
        }
      }
    }

    /* ---------- events ---------- */
    btn.addEventListener('click', (e) => { e.preventDefault(); toggle(); });
    btn.addEventListener('keydown', (e) => {
      switch (e.key) {
        case 'ArrowDown': e.preventDefault(); move(1); break;
        case 'ArrowUp': e.preventDefault(); move(-1); break;
        case 'Home': e.preventDefault(); move(-Infinity); break;
        case 'End': e.preventDefault(); move(Infinity); break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          if (listbox.hidden) { open(); }
          else { choose(activeOption()); }
          break;
        case 'Escape':
          e.preventDefault(); close(); break;
        default:
          if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            typeaheadMatch(e.key);
          }
      }
    });

    listbox.addEventListener('mousedown', (e) => e.preventDefault()); // keep focus on button
    listbox.addEventListener('click', (e) => {
      const li = e.target.closest('.dd__option');
      if (li) choose(li);
    });

    // Rebuild options when JS rewrites the native select (innerHTML swaps).
    const mo = new MutationObserver(() => renderOptions());
    mo.observe(select, { childList: true, subtree: true, characterData: true });

    select.__cs = api;
    renderOptions();
    return api;
  }

  /* ---------- document-level close-on-outside + one-open-at-a-time ---------- */
  document.addEventListener('pointerdown', (e) => {
    const w = e.target instanceof Element ? e.target.closest('.dd') : null;
    if (w !== active.wrapper && active.wrapper) {
      const openEls = active.wrapper.querySelectorAll('.dd__listbox');
      openEls.forEach((l) => { l.hidden = true; });
      active.wrapper.classList.remove('dd--open');
      const b = active.wrapper.querySelector('.dd__button');
      if (b) b.setAttribute('aria-expanded', 'false');
      active.wrapper = null;
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && active.wrapper) {
      active.wrapper.__api && active.wrapper.__api.close && active.wrapper.__api.close();
    }
  });

  /* ---------- public API ---------- */
  function enhanceAll(root) {
    const scope = (root && root.querySelectorAll) ? root : document;
    const selects = scope.querySelectorAll ? scope.querySelectorAll('select.dd') : [];
    for (let i = 0; i < selects.length; i++) enhance(selects[i]);
  }

  function init(root) { enhanceAll(root); }
  function refresh(scope) {
    const root = (scope && scope.querySelectorAll) ? scope : document;
    const selects = root.querySelectorAll('select.dd');
    for (let i = 0; i < selects.length; i++) {
      if (selects[i].__cs) { selects[i].__cs.renderOptions(); continue; }
      enhance(selects[i]);
    }
  }

  window.CustomSelect = { init, refresh };

  function boot() {
    init(document);
    if (document.body) {
      // Auto-enhance dynamically inserted `select.dd` elements.
      new MutationObserver(() => {
        if (window.requestAnimationFrame) {
          window.requestAnimationFrame(() => init(document));
        } else {
          init(document);
        }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();