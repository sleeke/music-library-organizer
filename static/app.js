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
      <td>${esc(f.title || '')}${f.has_pending ? ' ✎' : ''}</td>
      <td>${esc(f.artist || '')}</td><td>${esc(f.album || '')}</td>
      <td>${esc(f.tracknumber || '')}</td>
      <td class="path">${esc(f.path)}</td>
      <td><audio controls preload="none" src="/api/audio?path=${encodeURIComponent(f.path)}"></audio></td>`;
    tbody.appendChild(tr);
  }
  $('#page-info').textContent =
    `${data.total === 0 ? 0 : page * 100 + 1}–${page * 100 + data.files.length} of ${data.total}`;
  $('#prev-page').disabled = page === 0;
  $('#next-page').disabled = page * 100 + 100 >= data.total;
}

function esc(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
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
  span.textContent += ' — done';
}

/* ---------- duplicates ---------- */
let clusterState = {}; // key -> keeper path

function formatDuration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  const mins = Math.floor(total / 60);
  const secs = String(total % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

async function loadDuplicates() {
  const data = await api('/api/duplicates');
  const wrap = $('#clusters');
  wrap.innerHTML = '';
  clusterState = {};
  if (data.clusters.length === 0) {
    wrap.innerHTML = '<p class="muted">No duplicate clusters found.</p>';
    return;
  }
  for (const cluster of data.clusters) {
    clusterState[cluster.key] = cluster.members[0].path; // default keeper = first
    const box = document.createElement('div');
    box.className = 'cluster';
    box.dataset.key = cluster.key;
    const rows = cluster.members.map((m, idx) => `
      <tr>
        <td><input type="radio" name="keeper-${esc(cluster.key)}"
                   ${idx === 0 ? 'checked' : ''}></td>
        <td>${esc(m.artist || '?')} — ${esc(m.title || m.filename)}</td>
        <td class="path">${esc(m.path)}</td>
        <td>${m.bitrate ? (m.bitrate / 1000).toFixed(0) + 'k' : '?'}</td>
        <td>${m.size ? (m.size / 1024 / 1024).toFixed(1) + ' MB' : '?'}</td>
        <td>${m.duration != null ? formatDuration(m.duration) : '?'}</td>
        <td><audio controls preload="none"
                   src="/api/audio?path=${encodeURIComponent(m.path)}"></audio></td>
      </tr>`).join('');
    box.innerHTML = `
      <strong>Cluster ${esc(cluster.key)}</strong>
      <table>
        <thead><tr><th></th><th>Track</th><th>Path</th><th>Bitrate</th>
          <th>Size</th><th>Length</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <button class="danger delete-rest">Delete others (→ Trash)</button>
      <button class="keep-all">Keep all / dismiss</button>`;
    box.querySelector('.delete-rest').addEventListener('click', () => deleteOthers(box, cluster));
    box.querySelector('.keep-all').addEventListener('click', () => dismissCluster(cluster));
    wrap.appendChild(box);
  }
}

async function deleteOthers(box, cluster) {
  const checked = box.querySelector(`input[name="keeper-${CSS.escape(cluster.key)}"]:checked`);
  const keeperPath = cluster.members[
    [...box.querySelectorAll('input[type=radio]')].indexOf(checked)].path;
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
  const ok = results.length - failed.length;
  const lines = [`${ok} moved to Trash`];
  for (const r of failed)
    lines.push(`✗ ${r.path}\n   ${r.error}`);
  el.innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join('');
  el.classList.toggle('has-errors', failed.length > 0);
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
    wrap.innerHTML = '<p class="muted">Nothing pending. Run a scan with suggestions enabled.</p>';
    return;
  }
  for (const card of data.suggestions) renderCard(card, wrap);
}

function renderCard(card, wrap) {
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.sid = card.id;
  const badge = card.confidence == null ? '' :
    `<span class="badge ${card.confidence > 0.85 ? 'high' : 'low'}">
       ${(card.confidence * 100).toFixed(0)}%</span>`;
  const rows = Object.entries(card.fields).map(([field, proposed]) => `
    <div class="row" data-field="${esc(field)}">
      <span>${esc(field)}</span>
      <span class="muted">${esc(card.current[field] ?? '—')}</span>
      <input value="${esc(proposed)}">
      <span class="badge">${esc(card.sources[field] || '')}</span>
    </div>`).join('');
  el.innerHTML = `
    <header>
      <span>${esc(card.filename)}</span>
      <span>${badge}<audio controls preload="none"
        src="/api/audio?path=${encodeURIComponent(card.path)}"></audio></span>
    </header>
    <div class="row"><strong>Field</strong><strong>Current</strong>
      <strong>Suggested</strong><strong>Source</strong></div>
    ${rows}
    <button class="primary approve">Approve</button>
    <button class="reject">Reject</button>`;
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
  $('#apply-summary').textContent =
    `${summary.applied.length} applied · ${summary.conflicts.length} conflicts · ${summary.errors.length} errors`;
  renderApplyDetails(summary);
  loadSuggestions();
});

function renderApplyDetails(summary) {
  const el = $('#apply-details');
  const lines = [];
  for (const a of summary.applied)
    lines.push(`✓ ${a.new_path}`);
  for (const c of summary.conflicts)
    lines.push(`⚠ conflict: ${c.file}\n   target ${c.target} already exists`);
  for (const e of summary.errors)
    lines.push(`✗ ${e.file}\n   ${e.error}`);
  if (!lines.length) { el.hidden = true; return; }
  const hasErrors = summary.conflicts.length > 0 || summary.errors.length > 0;
  el.innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join('');
  el.classList.toggle('has-errors', hasErrors);
  el.hidden = false;
}

/* ---------- init ---------- */
loadLibrary();
