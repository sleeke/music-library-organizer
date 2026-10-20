'use strict';

const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const init = {};
  if (opts.method) {
    init.method = opts.method;
    init.headers = { 'Content-Type': 'application/json' };
    if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
  }
  const resp = await fetch(path, init);
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp.status === 200 ? resp.json() : null;
}

/* ---------- tabs ---------- */
document.querySelectorAll('.tab').forEach((btn) => btn.addEventListener('click', () => {
  document.querySelectorAll('.tab')
    .forEach((b) => b.classList.toggle('active', b === btn));
  for (const v of ['library', 'duplicates', 'suggestions'])
    $(`#view-${v}`).hidden = v !== btn.dataset.view;
  if (btn.dataset.view === 'library') loadLibrary();
  if (btn.dataset.view === 'duplicates') loadDuplicates();
  if (btn.dataset.view === 'suggestions') loadSuggestions();
}));

/* ---------- library & scan ---------- */
let page = 0;

async function loadLibrary() {
  const q = $('#search-input').value.trim();
  const params = new URLSearchParams({ offset: page * 100, limit: 100 });
  if (q) params.set('q', q);
  const data = await api(`/api/library?${params}`);
  const tbody = $('#library-table tbody');
  tbody.innerHTML = '';
  for (const f of data.files) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${playButton(f.path)}</td>
      <td title="${esc(f.title || '')}">${esc(f.title || '')}${f.has_pending
        ? '<span class="pending-mark" title="Pending suggestion">✎</span>' : ''}</td>
      <td title="${esc(f.artist || '')}">${esc(f.artist || '')}</td>
      <td title="${esc(f.album || '')}">${esc(f.album || '')}</td>
      <td class="num">${esc(f.tracknumber || '')}</td>
      ${pathCell(f.path, 'td')}`;
    tbody.appendChild(tr);
  }
  if (!data.files.length)
    tbody.innerHTML = `<tr><td colspan="6" class="muted">${q
      ? 'No files match this filter.' : 'Library is empty. Scan a folder to get started.'}</td></tr>`;
  syncPlayButtons();
  $('#page-info').textContent =
    `${data.total === 0 ? 0 : page * 100 + 1}-${page * 100 + data.files.length} of ${data.total}`;
  $('#prev-page').disabled = page === 0;
  $('#next-page').disabled = page * 100 + 100 >= data.total;
}

// Safe for both element content and double-quoted attribute values.
function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

// Path cell that truncates from the left, so the filename stays visible.
function pathCell(path, tag = 'div') {
  return `<${tag} class="path" title="${esc(path)}">${pathInner(path)}</${tag}>`;
}

function pathInner(path) {
  const cut = path.lastIndexOf('/') + 1;
  return `<bdi>${esc(path.slice(0, cut))}<span class="file">${esc(path.slice(cut))}</span></bdi>`;
}

function playButton(path, group = '') {
  return `<button class="play" data-path="${esc(path)}" data-group="${esc(group)}"
            aria-label="Play ${esc(path.slice(path.lastIndexOf('/') + 1))}"></button>`;
}

function emptyState(text) {
  return `<div class="empty-state">${esc(text)}</div>`;
}

$('#search-input').addEventListener('input', debounce(() => { page = 0; loadLibrary(); }, 300));
$('#prev-page').addEventListener('click', () => { page -= 1; loadLibrary(); });
$('#next-page').addEventListener('click', () => { page += 1; loadLibrary(); });

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

$('#scan-btn').addEventListener('click', async () => {
  const folder = $('#folder-input').value.trim();
  if (!folder) { $('#scan-progress').textContent = 'Enter a folder first'; return; }
  try {
    const { job_id } = await api('/api/scan', {
      method: 'POST', body: { folder, suggest: $('#suggest-check').checked } });
    pollJob(job_id);
  } catch (err) { $('#scan-progress').textContent = err.message; }
});

async function pollJob(jobId) {
  const span = $('#scan-progress');
  while (true) {
    const job = await api(`/api/jobs/${jobId}`);
    span.textContent = job.status === 'running'
      ? `${job.phase}: ${job.done}/${job.total}` : job.status;
    if (job.status !== 'running') break;
    await new Promise((r) => setTimeout(r, 700));
  }
  page = 0;
  await loadLibrary();
}

/* ---------- shared player ---------- */
// One <audio> element for the whole app: rows only carry a small play button.
const audio = $('#audio');
let nowPlaying = { path: null, group: '' };

function playPath(path, group) {
  if (nowPlaying.path === path) {
    if (audio.paused) audio.play(); else audio.pause();
    return;
  }
  // Switching between copies in the same duplicate group keeps the position.
  const resumeAt = group && group === nowPlaying.group ? audio.currentTime : 0;
  nowPlaying = { path, group };
  audio.src = `/api/audio?path=${encodeURIComponent(path)}`;
  audio.addEventListener('loadedmetadata', () => {
    if (resumeAt && resumeAt < audio.duration) audio.currentTime = resumeAt;
  }, { once: true });
  audio.play().catch(() => {});
  $('#player-name').innerHTML = pathInner(path);
  $('#player-name').title = path;
  $('#player').hidden = false;
  syncPlayButtons();
}

function syncPlayButtons() {
  const playing = !audio.paused;
  for (const btn of document.querySelectorAll('.play[data-path]')) {
    const active = btn.dataset.path === nowPlaying.path;
    btn.classList.toggle('is-playing', active && playing);
    btn.closest('tr')?.classList.toggle('playing', active);
  }
  $('#player-toggle').classList.toggle('is-playing', playing);
}

document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.play[data-path]');
  if (!btn) return;
  ev.stopPropagation();
  playPath(btn.dataset.path, btn.dataset.group);
}, true);
$('#player-toggle').addEventListener('click', () => {
  if (audio.paused) audio.play(); else audio.pause();
});
const seek = $('#player-seek');
let seeking = false;
seek.addEventListener('input', () => { seeking = true; });
seek.addEventListener('change', () => { audio.currentTime = Number(seek.value); seeking = false; });
for (const evt of ['play', 'pause', 'ended']) audio.addEventListener(evt, syncPlayButtons);
for (const evt of ['timeupdate', 'loadedmetadata']) audio.addEventListener(evt, () => {
  if (!seeking) { seek.max = audio.duration || 0; seek.value = audio.currentTime; }
  $('#player-time').textContent =
    `${formatDuration(audio.currentTime)} / ${formatDuration(audio.duration)}`;
});

/* ---------- duplicates ---------- */
let clusterState = {}; // key -> keeper path

function formatDuration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

// Columns compared across copies. Tag columns that are empty for every copy are hidden.
const DUP_COLUMNS = [
  { key: 'title', label: 'Title', tag: true },
  { key: 'artist', label: 'Artist', tag: true },
  { key: 'albumartist', label: 'Album artist', tag: true },
  { key: 'album', label: 'Album', tag: true },
  { key: 'tracknumber', label: 'Track', tag: true, num: true, col: 'c-tiny' },
  { key: 'bitrate', label: 'Bitrate', num: true, col: 'c-short',
    fmt: (v) => (v ? `${(v / 1000).toFixed(0)}k` : '') },
  { key: 'size', label: 'Size', num: true, col: 'c-short',
    fmt: (v) => (v ? `${(v / 1024 / 1024).toFixed(1)} MB` : '') },
  { key: 'duration', label: 'Length', num: true, col: 'c-short',
    fmt: (v) => (v != null ? formatDuration(v) : '') },
];

async function loadDuplicates() {
  const data = await api('/api/duplicates');
  const wrap = $('#clusters');
  wrap.innerHTML = '';
  clusterState = {};
  if (data.clusters.length === 0) {
    wrap.innerHTML = emptyState('No duplicate groups found.');
    return;
  }
  for (const cluster of data.clusters) wrap.appendChild(renderCluster(cluster));
  syncPlayButtons();
}

function renderCluster(cluster) {
  clusterState[cluster.key] = cluster.members[0].path; // default keeper = first
  const box = document.createElement('div');
  box.className = 'cluster';
  box.dataset.key = cluster.key;

  const display = (col, m) => String((col.fmt ? col.fmt(m[col.key]) : m[col.key]) ?? '');
  const columns = DUP_COLUMNS
    .filter((col) => !col.tag || cluster.members.some((m) => display(col, m)))
    .map((col) => ({ ...col,
      differs: new Set(cluster.members.map((m) => display(col, m))).size > 1 }));
  const differing = columns.filter((col) => col.differs).map((col) => col.label);

  const first = cluster.members[0];
  const heading = first.title
    ? `${first.artist ? `${first.artist} - ` : ''}${first.title}` : first.filename;
  const rows = cluster.members.map((m, idx) => `
    <tr data-path="${esc(m.path)}" class="${idx === 0 ? 'keeper' : 'doomed'}">
      <td><input type="radio" name="keeper-${esc(cluster.key)}" ${idx === 0 ? 'checked' : ''}
                 aria-label="Keep this file"></td>
      <td>${playButton(m.path, cluster.key)}</td>
      ${pathCell(m.path, 'td')}
      ${columns.map((col) => {
        const value = display(col, m);
        return `<td class="${col.differs ? 'diff' : 'same'}${col.num ? ' num' : ''}"
                    title="${esc(value)}">${esc(value) || '<span class="muted">-</span>'}</td>`;
      }).join('')}
    </tr>`).join('');

  box.innerHTML = `
    <div class="cluster-head">
      <h2>${esc(heading)}</h2>
      <span class="diff-summary">${cluster.members.length} copies.
        ${differing.length
          ? `Differs in ${differing.map((l) => `<strong>${esc(l)}</strong>`).join(' ')}`
          : 'Tags and audio details are identical.'}</span>
    </div>
    <table>
      <colgroup><col class="c-pick"><col class="c-play"><col class="c-file">
        ${columns.map((col) => `<col class="${col.col || ''}">`).join('')}</colgroup>
      <thead><tr><th></th><th></th><th>File</th>
        ${columns.map((col) => `<th class="${col.num ? 'num' : ''}">${esc(col.label)}</th>`).join('')}
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="cluster-actions">
      <button class="danger delete-rest">Move others to Trash</button>
      <button class="keep-all">Keep all</button>
      <span class="muted keeper-note"></span>
    </div>`;

  const updateKeeper = () => {
    const keeper = clusterState[cluster.key];
    for (const tr of box.querySelectorAll('tbody tr')) {
      const isKeeper = tr.dataset.path === keeper;
      tr.classList.toggle('keeper', isKeeper);
      tr.classList.toggle('doomed', !isKeeper);
      tr.querySelector('input[type=radio]').checked = isKeeper;
    }
    const others = cluster.members.length - 1;
    box.querySelector('.keeper-note').textContent =
      `Keeping ${keeper.slice(keeper.lastIndexOf('/') + 1)}. ${others} file${others === 1 ? '' : 's'} will move to Trash.`;
  };
  for (const tr of box.querySelectorAll('tbody tr'))
    tr.addEventListener('click', () => { clusterState[cluster.key] = tr.dataset.path; updateKeeper(); });
  updateKeeper();
  box.querySelector('.delete-rest').addEventListener('click', () => deleteOthers(cluster));
  box.querySelector('.keep-all').addEventListener('click', () => dismissCluster(cluster));
  return box;
}

async function deleteOthers(cluster) {
  const keeperPath = clusterState[cluster.key];
  const doomed = cluster.members.filter((m) => m.path !== keeperPath)
    .map((m) => m.path);
  if (!doomed.length) return;
  if (!confirm(`Move ${doomed.length} file(s) to Trash?\n\n${doomed.join('\n')}`)) return;
  const res = await api('/api/trash', { method: 'POST', body: { paths: doomed } });
  renderTrashDetails(res.results);
  await loadDuplicates();
}

function renderTrashDetails(results) {
  const el = $('#trash-details');
  if (!results || !results.length) { el.hidden = true; return; }
  const failed = results.filter((r) => !r.ok);
  renderResults(el, `${results.length - failed.length} moved to Trash`
    + (failed.length ? `, ${failed.length} failed` : ''), results.map((r) => (r.ok
    ? { kind: 'ok', label: 'Trashed', path: r.path }
    : { kind: 'bad', label: 'Failed', path: r.path, note: r.error })));
}

// Result panel shared by Trash and Apply: one row per file with a status tag.
function renderResults(el, title, items) {
  el.innerHTML = `
    <div class="result-head"><strong>${esc(title)}</strong>
      <button class="ghost dismiss">Dismiss</button></div>
    <ul class="result-list">${items.map((it) => `
      <li><span class="status ${it.kind}">${esc(it.label)}</span>${pathCell(it.path)}
        ${it.note ? `<span class="note">${esc(it.note)}</span>` : ''}</li>`).join('')}
    </ul>`;
  el.querySelector('.dismiss').addEventListener('click', () => { el.hidden = true; });
  el.hidden = false;
}

async function dismissCluster(cluster) {
  await api('/api/duplicates/dismiss', { method: 'POST', body: { cluster_key: cluster.key } });
  loadDuplicates();
}

/* ---------- suggestions ---------- */
async function loadSuggestions() {
  const data = await api('/api/suggestions?status=pending');
  const wrap = $('#cards');
  wrap.innerHTML = '';
  $('#suggest-count').textContent = `${data.suggestions.length} pending`;
  if (data.suggestions.length === 0) {
    wrap.innerHTML = emptyState('Nothing pending. Run a scan with suggestions enabled.');
    return;
  }
  for (const card of data.suggestions) renderCard(card, wrap);
  syncPlayButtons();
}

function renderCard(card, wrap) {
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.sid = card.id;
  const badge = card.confidence == null ? '' :
    `<span class="badge ${card.confidence > 0.85 ? 'high' : 'low'}"
           title="Match confidence">${(card.confidence * 100).toFixed(0)}%</span>`;
  const rows = Object.entries(card.fields).map(([field, proposed]) => {
    const current = card.current[field];
    const unchanged = String(current ?? '') === String(proposed ?? '');
    return `
    <div class="row${unchanged ? ' unchanged' : ''}" data-field="${esc(field)}">
      <span class="field">${esc(field)}</span>
      <span class="current${current ? '' : ' empty'}" title="${esc(current ?? '')}">${esc(current || 'empty')}</span>
      <input value="${esc(proposed)}" aria-label="Suggested ${esc(field)}">
      <span class="badge" title="Source">${esc(card.sources[field] || '')}</span>
    </div>`;
  }).join('');
  el.innerHTML = `
    <div class="card-head">${playButton(card.path)}${pathCell(card.path)}${badge}</div>
    <div class="card-body">
      <div class="row head"><span>Field</span><span>Current</span>
        <span>Suggested</span><span>Source</span></div>
      ${rows}
    </div>
    <div class="card-actions">
      <button class="primary approve">Approve</button>
      <button class="reject">Reject</button>
    </div>`;
  el.querySelector('.approve').addEventListener('click', () => saveAndApprove(el, true));
  el.querySelector('.reject').addEventListener('click', () => rejectCard(el, card.id));
  wrap.appendChild(el);
}

async function collectEdits(el) {
  const fields = {};
  for (const row of el.querySelectorAll('.row[data-field]')) {
    const input = row.querySelector('input');
    if (input) fields[row.dataset.field] = input.value;
  }
  await api(`/api/suggestions/${el.dataset.sid}`, { method: 'PATCH', body: { fields } });
  return fields;
}

async function saveAndApprove(el) {
  await collectEdits(el);
  await api(`/api/suggestions/${el.dataset.sid}/approve`, { method: 'POST' });
  el.remove();
  bumpCount(-1);
}

async function rejectCard(el, sid) {
  await api(`/api/suggestions/${sid}/reject`, { method: 'POST' });
  el.remove();
  bumpCount(-1);
}

function bumpCount(delta) {
  const el = $('#suggest-count');
  const current = parseInt(el.textContent, 10) || 0;
  el.textContent = `${current + delta} pending`;
  if (!document.querySelector('#cards .card'))
    $('#cards').innerHTML = emptyState('All reviewed. Apply approved changes when ready.');
}

$('#approve-all-btn').addEventListener('click', async () => {
  const ids = [...document.querySelectorAll('#cards .card')]
    .map((el) => Number(el.dataset.sid));
  if (!ids.length) return;
  // Save edits first so approvals capture what the reviewer sees.
  await Promise.all([...document.querySelectorAll('#cards .card')].map(collectEdits));
  await api('/api/suggestions/approve-batch', { method: 'POST', body: { ids } });
  loadSuggestions();
});

$('#apply-btn').addEventListener('click', async () => {
  const summary = await api('/api/apply', { method: 'POST' });
  renderApplyDetails(summary);
  loadSuggestions();
});

function renderApplyDetails(summary) {
  const el = $('#apply-details');
  const items = [
    ...summary.applied.map((a) => ({ kind: 'ok', label: 'Applied', path: a.new_path })),
    ...summary.conflicts.map((c) => ({ kind: 'warn', label: 'Conflict', path: c.file,
      note: `Target already exists: ${c.target}` })),
    ...summary.errors.map((e) => ({ kind: 'bad', label: 'Error', path: e.file, note: e.error })),
  ];
  if (!items.length) { el.hidden = true; return; }
  const n = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
  renderResults(el, `${summary.applied.length} applied, ${n(summary.conflicts.length, 'conflict')}, `
    + n(summary.errors.length, 'error'), items);
}

/* ---------- init ---------- */
loadLibrary();
