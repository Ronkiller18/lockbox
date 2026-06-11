/* ── LockBox frontend — app.js ───────────────────────────────────────────
   Step 5 additions:
   - Auto-lock after 5 minutes of inactivity
   - Password strength indicator
   - Keyboard shortcuts: Ctrl+N, Ctrl+L, Escape
────────────────────────────────────────────────────────────────────────── */

const API = '/api';

// ── App state ──────────────────────────────────────────────────────────────
const state = {
  entries: [],
  filtered: [],
  activeTag: 'all',
  searchQuery: '',
};

// ── DOM refs ───────────────────────────────────────────────────────────────
const screens = {
  setup:  document.getElementById('screen-setup'),
  unlock: document.getElementById('screen-unlock'),
  vault:  document.getElementById('screen-vault'),
};

// ── Utility ────────────────────────────────────────────────────────────────
function show(screenName) {
  Object.values(screens).forEach(s => s.classList.add('hidden'));
  screens[screenName].classList.remove('hidden');
}

function showError(elId, msg) {
  const el = document.getElementById(elId);
  el.textContent = msg;
  el.classList.remove('hidden');
}

function clearError(elId) {
  const el = document.getElementById(elId);
  el.textContent = '';
  el.classList.add('hidden');
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.classList.add('hidden'), 200);
  }, 2000);
}

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

// ── Eye (show/hide password) buttons ──────────────────────────────────────
document.querySelectorAll('.eye-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = document.getElementById(btn.dataset.target);
    input.type = input.type === 'password' ? 'text' : 'password';
  });
});

// ── Auto-lock ──────────────────────────────────────────────────────────────
// Locks the vault after AUTO_LOCK_MS of no user interaction.
// We reset the timer on every mouse move, click, or keypress.
// When the timer fires we call the same lock function as the manual lock btn.

const AUTO_LOCK_MS = 5 * 60 * 1000; // 5 minutes
let autoLockTimer = null;

function resetAutoLock() {
  clearTimeout(autoLockTimer);
  // Only schedule auto-lock if vault screen is visible
  if (!screens.vault.classList.contains('hidden')) {
    autoLockTimer = setTimeout(triggerAutoLock, AUTO_LOCK_MS);
  }
}

async function triggerAutoLock() {
  await api('POST', '/lock');
  document.getElementById('unlock-pw').value = '';
  clearError('unlock-error');
  show('unlock');
  toast('Vault locked due to inactivity');
}

// Attach activity listeners — passive:true means they never block scrolling
['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'].forEach(evt => {
  document.addEventListener(evt, resetAutoLock, { passive: true });
});

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
// Ctrl+N  → new entry  (only when vault is visible)
// Ctrl+L  → lock vault (only when vault is visible)
// Escape  → close open modal
//
// We check event.key (layout-independent) rather than keyCode.
// We guard against firing shortcuts while typing in an input/textarea.

document.addEventListener('keydown', e => {
  const vaultVisible = !screens.vault.classList.contains('hidden');
  const modalOpen    = !document.getElementById('modal-overlay').classList.contains('hidden');
  const tagsOpen     = !document.getElementById('tags-modal-overlay').classList.contains('hidden');
  const typingInField = ['INPUT','TEXTAREA'].includes(document.activeElement.tagName);

  // Escape — close modals (highest priority, always active)
  if (e.key === 'Escape') {
    if (modalOpen)  { closeModal();     return; }
    if (tagsOpen)   { closeTagsModal(); return; }
  }

  // Shortcuts that require vault to be visible and no modal open
  if (vaultVisible && !modalOpen && !tagsOpen) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
      e.preventDefault(); // prevent browser's new-window shortcut
      openModal();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
      e.preventDefault(); // prevent browser's address-bar focus
      document.getElementById('btn-lock').click();
      return;
    }
    // '/' focuses search (common convention, like GitHub)
    if (e.key === '/' && !typingInField) {
      e.preventDefault();
      document.getElementById('search-input').focus();
      return;
    }
  }
});

// ── Initialise: check vault status ────────────────────────────────────────
async function init() {
  const { ok, data } = await api('GET', '/status');
  if (!ok) { show('unlock'); return; }

  if (!data.vault_exists) {
    show('setup');
  } else if (data.unlocked) {
    await loadVault();
    show('vault');
    resetAutoLock();
  } else {
    show('unlock');
  }
}

// ── Setup ──────────────────────────────────────────────────────────────────
document.getElementById('setup-submit').addEventListener('click', async () => {
  clearError('setup-error');
  const pw      = document.getElementById('setup-pw').value;
  const confirm = document.getElementById('setup-confirm').value;

  if (!pw)           return showError('setup-error', 'Please enter a master password.');
  if (pw.length < 8) return showError('setup-error', 'Password must be at least 8 characters.');
  if (pw !== confirm) return showError('setup-error', 'Passwords do not match.');

  const btn = document.getElementById('setup-submit');
  btn.textContent = 'Creating vault…';
  btn.disabled = true;

  const init_res = await api('POST', '/init', { master_password: pw });
  if (!init_res.ok) {
    btn.textContent = 'Create vault';
    btn.disabled = false;
    return showError('setup-error', init_res.data.detail || 'Failed to create vault.');
  }

  const unlock_res = await api('POST', '/unlock', { master_password: pw });
  if (!unlock_res.ok) {
    btn.textContent = 'Create vault';
    btn.disabled = false;
    return showError('setup-error', 'Vault created but could not unlock. Refresh and try.');
  }

  await loadVault();
  show('vault');
  resetAutoLock();
});

document.getElementById('setup-pw').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('setup-confirm').focus();
});
document.getElementById('setup-confirm').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('setup-submit').click();
});

// ── Unlock ─────────────────────────────────────────────────────────────────
document.getElementById('unlock-submit').addEventListener('click', async () => {
  clearError('unlock-error');
  const pw = document.getElementById('unlock-pw').value;
  if (!pw) return showError('unlock-error', 'Please enter your master password.');

  const btn = document.getElementById('unlock-submit');
  btn.textContent = 'Unlocking…';
  btn.disabled = true;

  const res = await api('POST', '/unlock', { master_password: pw });
  btn.textContent = 'Unlock';
  btn.disabled = false;

  if (!res.ok) {
    return showError('unlock-error',
      res.status === 401 ? 'Wrong password.' : (res.data.detail || 'Failed to unlock.'));
  }

  await loadVault();
  show('vault');
  resetAutoLock();
});

document.getElementById('unlock-pw').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('unlock-submit').click();
});

// ── Lock ───────────────────────────────────────────────────────────────────
document.getElementById('btn-lock').addEventListener('click', async () => {
  clearTimeout(autoLockTimer);
  await api('POST', '/lock');
  document.getElementById('unlock-pw').value = '';
  clearError('unlock-error');
  show('unlock');
});

// ── Load vault data ────────────────────────────────────────────────────────
async function loadVault() {
  const { ok, data } = await api('GET', '/entries');
  if (!ok) return;
  state.entries = data.entries || [];
  applyFilter();
  renderSidebarTags();
}

// ── Filter & search ────────────────────────────────────────────────────────
function applyFilter() {
  const q = state.searchQuery.toLowerCase();
  state.filtered = state.entries.filter(e => {
    const matchesTag = state.activeTag === 'all' ||
      (e.tags || []).map(t => t.toLowerCase()).includes(state.activeTag.toLowerCase());
    const matchesSearch = !q ||
      e.title.toLowerCase().includes(q) ||
      (e.username || '').toLowerCase().includes(q) ||
      (e.url || '').toLowerCase().includes(q);
    return matchesTag && matchesSearch;
  });
  renderEntries();
}

document.getElementById('search-input').addEventListener('input', e => {
  state.searchQuery = e.target.value;
  applyFilter();
});

// ── Sidebar tags ───────────────────────────────────────────────────────────
function getAllTags() {
  const set = new Set();
  state.entries.forEach(e => (e.tags || []).forEach(t => set.add(t)));
  return [...set].sort();
}

function renderSidebarTags() {
  const container = document.getElementById('sidebar-tags');
  const noTags    = document.getElementById('nav-no-tags');
  const tags      = getAllTags();
  container.innerHTML = '';

  document.getElementById('nav-count-all').textContent = state.entries.length;

  if (!tags.length) {
    noTags.style.display = '';
    return;
  }
  noTags.style.display = 'none';

  tags.forEach(tag => {
    const count = state.entries.filter(e => (e.tags || []).includes(tag)).length;
    const el = document.createElement('div');
    el.className = 'nav-item' + (state.activeTag === tag ? ' active' : '');
    el.dataset.filter = tag;
    el.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
      ${escHtml(tag)}
      <span class="nav-count">${count}</span>`;
    el.addEventListener('click', () => {
      state.activeTag = tag;
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      el.classList.add('active');
      applyFilter();
    });
    container.appendChild(el);
  });
}

document.querySelector('[data-filter="all"]').addEventListener('click', () => {
  state.activeTag = 'all';
  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  document.querySelector('[data-filter="all"]').classList.add('active');
  applyFilter();
});

// ── Render entries ─────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function avatarText(title) {
  const words = title.trim().split(/\s+/);
  return words.length >= 2
    ? (words[0][0] + words[1][0]).toUpperCase()
    : title.slice(0, 2).toUpperCase();
}

function renderEntries() {
  const list  = document.getElementById('entries-list');
  const empty = document.getElementById('empty-state');
  const meta  = document.getElementById('entries-meta');

  list.innerHTML = '';

  if (!state.filtered.length) {
    empty.classList.remove('hidden');
    meta.textContent = '';
    if (state.entries.length && (state.searchQuery || state.activeTag !== 'all')) {
      empty.querySelector('p').textContent    = 'No results';
      empty.querySelector('span').textContent = 'Try a different search or tag filter';
    } else {
      empty.querySelector('p').textContent    = 'No entries yet';
      empty.querySelector('span').textContent = 'Click "New entry" or press Ctrl+N';
    }
    return;
  }

  empty.classList.add('hidden');
  meta.textContent = `${state.filtered.length} item${state.filtered.length !== 1 ? 's' : ''}`;

  state.filtered.forEach(entry => {
    const card = document.createElement('div');
    card.className  = 'entry-card';
    card.dataset.id = entry.id;

    const tags = (entry.tags || []).map(t =>
      `<span class="entry-tag">${escHtml(t)}</span>`).join('');

    card.innerHTML = `
      <div class="entry-avatar">${escHtml(avatarText(entry.title))}</div>
      <div class="entry-info">
        <div class="entry-title">${escHtml(entry.title)}</div>
        <div class="entry-meta">${escHtml(entry.username || entry.url || '—')}</div>
        ${tags ? `<div class="entry-tags">${tags}</div>` : ''}
      </div>
      <div class="entry-actions">
        <button class="entry-btn" data-action="copy" title="Copy password">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        </button>
        <button class="entry-btn" data-action="edit" title="Edit">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="entry-btn danger" data-action="delete" title="Delete">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
        </button>
      </div>`;

    card.querySelector('[data-action="copy"]').addEventListener('click', e => {
      e.stopPropagation();
      navigator.clipboard.writeText(entry.password).then(() => toast('Password copied'));
    });
    card.querySelector('[data-action="edit"]').addEventListener('click', e => {
      e.stopPropagation();
      openModal(entry);
    });
    card.querySelector('[data-action="delete"]').addEventListener('click', e => {
      e.stopPropagation();
      deleteEntry(entry.id, entry.title);
    });
    card.addEventListener('click', () => openModal(entry));

    list.appendChild(card);
  });
}

// ── Delete entry ───────────────────────────────────────────────────────────
async function deleteEntry(id, title) {
  if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;
  const { ok } = await api('DELETE', `/entries/${id}`);
  if (ok) {
    toast('Entry deleted');
    await loadVault();
  }
}

// ── Password strength ──────────────────────────────────────────────────────
// Scores the password on 5 axes and returns 0-4:
//   0 = very weak   (shown in red)
//   1 = weak        (shown in orange)
//   2 = fair        (shown in yellow)
//   3 = strong      (shown in green)
//   4 = very strong (shown in bright green)
//
// Scoring criteria (each adds 1 point):
//   - Length ≥ 10
//   - Length ≥ 16
//   - Contains uppercase + lowercase
//   - Contains numbers
//   - Contains symbols
//
// No library needed — pure JS, deterministic, instant.

const STRENGTH_LABELS = ['Very weak', 'Weak', 'Fair', 'Strong', 'Very strong'];
const STRENGTH_COLORS = ['#e24b4a', '#e2874a', '#e2c44a', '#1d9e75', '#34d399'];

function scorePassword(pw) {
  if (!pw) return -1; // hidden state
  let score = 0;
  if (pw.length >= 10) score++;
  if (pw.length >= 16) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return Math.min(score, 4);
}

function updateStrengthBar(pw) {
  const bar      = document.getElementById('strength-bar');
  const label    = document.getElementById('strength-label');
  const wrap     = document.getElementById('strength-wrap');
  const score    = scorePassword(pw);

  if (score === -1) {
    wrap.classList.add('hidden');
    return;
  }

  wrap.classList.remove('hidden');
  const pct   = ((score + 1) / 5) * 100;
  const color = STRENGTH_COLORS[score];
  bar.style.width      = pct + '%';
  bar.style.background = color;
  label.textContent    = STRENGTH_LABELS[score];
  label.style.color    = color;
}

// Hook into the password field in the modal
document.getElementById('entry-password').addEventListener('input', e => {
  updateStrengthBar(e.target.value);
});

// ── Password generator ─────────────────────────────────────────────────────
const CHARS = {
  upper: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  lower: 'abcdefghijklmnopqrstuvwxyz',
  nums:  '0123456789',
  syms:  '!@#$%^&*()_+-=[]{}|;:,.<>?',
};

function generatePassword() {
  const len  = parseInt(document.getElementById('gen-length').value);
  const pool = [
    document.getElementById('gen-upper').checked ? CHARS.upper : '',
    document.getElementById('gen-lower').checked ? CHARS.lower : '',
    document.getElementById('gen-nums').checked  ? CHARS.nums  : '',
    document.getElementById('gen-syms').checked  ? CHARS.syms  : '',
  ].join('') || CHARS.lower;

  const arr = new Uint8Array(len);
  crypto.getRandomValues(arr);
  return Array.from(arr).map(b => pool[b % pool.length]).join('');
}

function refreshGenerator() {
  document.getElementById('gen-length-val').textContent =
    document.getElementById('gen-length').value;
  document.getElementById('gen-preview').textContent = generatePassword();
}

document.getElementById('gen-length').addEventListener('input', refreshGenerator);
['gen-upper','gen-lower','gen-nums','gen-syms'].forEach(id => {
  document.getElementById(id).addEventListener('change', refreshGenerator);
});

let genOpen = false;
document.getElementById('gen-toggle').addEventListener('click', () => {
  genOpen = !genOpen;
  document.getElementById('gen-panel').style.display = genOpen ? 'flex' : 'none';
  document.getElementById('gen-toggle').classList.toggle('active', genOpen);
  if (genOpen) refreshGenerator();
});

document.getElementById('gen-use').addEventListener('click', () => {
  const pw = document.getElementById('gen-preview').textContent;
  const input = document.getElementById('entry-password');
  input.value = pw;
  input.type  = 'text';
  updateStrengthBar(pw);   // update strength when generator applies a password
  toast('Password applied');
});

// ── Tag editor ─────────────────────────────────────────────────────────────
function getModalTags() {
  return [...document.querySelectorAll('#tag-editor .tag-chip')]
    .map(c => c.dataset.tag);
}

function addTagChip(tag, container) {
  const chip = document.createElement('div');
  chip.className    = 'tag-chip';
  chip.dataset.tag  = tag;
  chip.innerHTML    = `${escHtml(tag)}<button aria-label="Remove tag" title="Remove">×</button>`;
  chip.querySelector('button').addEventListener('click', () => chip.remove());
  container.insertBefore(chip, container.querySelector('.tag-input-field'));
}

function buildTagEditor(existingTags = []) {
  const editor = document.getElementById('tag-editor');
  editor.innerHTML = '';

  existingTags.forEach(t => addTagChip(t, editor));

  const input = document.createElement('input');
  input.type        = 'text';
  input.className   = 'tag-input-field';
  input.placeholder = 'Add tag, press Enter…';
  input.maxLength   = 30;
  editor.appendChild(input);

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const val = input.value.trim().replace(/,/g, '');
      if (val && !getModalTags().includes(val)) {
        addTagChip(val, editor);
        input.value = '';
      }
    }
    if (e.key === 'Backspace' && !input.value) {
      const chips = editor.querySelectorAll('.tag-chip');
      if (chips.length) chips[chips.length - 1].remove();
    }
  });

  editor.addEventListener('click', () => input.focus());
}

// ── Modal: open / close ────────────────────────────────────────────────────
function openModal(entry = null) {
  clearError('modal-error');
  document.getElementById('modal-title').textContent  = entry ? 'Edit entry' : 'New entry';
  document.getElementById('modal-save').textContent   = entry ? 'Save changes' : 'Save entry';
  document.getElementById('entry-id').value           = entry?.id || '';
  document.getElementById('entry-title').value        = entry?.title || '';
  document.getElementById('entry-username').value     = entry?.username || '';
  document.getElementById('entry-password').value     = entry?.password || '';
  document.getElementById('entry-password').type      = 'password';
  document.getElementById('entry-url').value          = entry?.url || '';
  document.getElementById('entry-notes').value        = entry?.notes || '';

  // Reset generator
  genOpen = false;
  document.getElementById('gen-panel').style.display = 'none';
  document.getElementById('gen-toggle').classList.remove('active');

  // Update strength bar for existing entry password
  updateStrengthBar(entry?.password || '');

  buildTagEditor(entry?.tags || []);

  document.getElementById('modal-overlay').classList.remove('hidden');
  setTimeout(() => document.getElementById('entry-title').focus(), 50);
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

document.getElementById('btn-new-entry').addEventListener('click', () => openModal());
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-cancel').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});

// ── Modal: save ────────────────────────────────────────────────────────────
document.getElementById('modal-save').addEventListener('click', async () => {
  clearError('modal-error');

  const id    = document.getElementById('entry-id').value;
  const title = document.getElementById('entry-title').value.trim();
  const pw    = document.getElementById('entry-password').value;

  if (!title) return showError('modal-error', 'Title is required.');
  if (!pw)    return showError('modal-error', 'Password is required.');

  const payload = {
    title,
    username: document.getElementById('entry-username').value.trim() || null,
    password: pw,
    url:      document.getElementById('entry-url').value.trim() || null,
    notes:    document.getElementById('entry-notes').value.trim() || null,
    tags:     getModalTags(),
  };

  const btn = document.getElementById('modal-save');
  btn.disabled    = true;
  btn.textContent = 'Saving…';

  const { ok, data } = id
    ? await api('PUT',  `/entries/${id}`, payload)
    : await api('POST', '/entries',       payload);

  btn.disabled    = false;
  btn.textContent = id ? 'Save changes' : 'Save entry';

  if (!ok) return showError('modal-error', data.detail || 'Failed to save entry.');

  closeModal();
  toast(id ? 'Entry updated' : 'Entry saved');
  await loadVault();
});

// ── Manage tags modal ──────────────────────────────────────────────────────
function openTagsModal() {
  const list   = document.getElementById('all-tags-list');
  const noHint = document.getElementById('no-tags-hint');
  const tags   = getAllTags();
  list.innerHTML = '';

  if (!tags.length) {
    noHint.style.display = '';
    list.style.display   = 'none';
  } else {
    noHint.style.display = 'none';
    list.style.display   = 'flex';
    tags.forEach(tag => {
      const el = document.createElement('div');
      el.className = 'deletable-tag';
      el.innerHTML = `${escHtml(tag)}<button aria-label="Delete tag ${escHtml(tag)}" title="Delete tag">×</button>`;
      el.querySelector('button').addEventListener('click', async () => {
        await deleteTagFromAllEntries(tag);
        el.remove();
        renderSidebarTags();
        applyFilter();
        if (!getAllTags().length) { noHint.style.display = ''; list.style.display = 'none'; }
      });
      list.appendChild(el);
    });
  }

  document.getElementById('tags-modal-overlay').classList.remove('hidden');
}

function closeTagsModal() {
  document.getElementById('tags-modal-overlay').classList.add('hidden');
}

async function deleteTagFromAllEntries(tag) {
  const affected = state.entries.filter(e => (e.tags || []).includes(tag));
  for (const entry of affected) {
    const payload = {
      title:    entry.title,
      username: entry.username || null,
      password: entry.password,
      url:      entry.url || null,
      notes:    entry.notes || null,
      tags:     (entry.tags || []).filter(t => t !== tag),
    };
    await api('PUT', `/entries/${entry.id}`, payload);
  }
  await loadVault();
  toast(`Tag "${tag}" deleted`);
}

document.getElementById('btn-manage-tags').addEventListener('click', openTagsModal);
document.getElementById('tags-modal-close').addEventListener('click', closeTagsModal);
document.getElementById('tags-modal-done').addEventListener('click', closeTagsModal);
document.getElementById('tags-modal-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeTagsModal();
});

// ── Boot ───────────────────────────────────────────────────────────────────
init();