// Click2CAD UI: hash-routed pages (#/submissions, #/viewer/<id>) over the /api endpoints.
import { ModelViewer } from './viewer.js';

const ACTIVE = ['queued', 'running'];
const STATUSES = ['queued', 'running', 'completed', 'failed', 'cancelled'];
const STATUS_LABEL = { queued: 'Queued', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled' };
const STAGE_LABEL = { starting: 'Starting worker', gemini: 'Asking Gemini', building: 'Building geometry', exporting: 'Exporting OBJ' };
const PROVIDER_LABEL = { azure: 'Azure OpenAI', gemini: 'Gemini', claude: 'AI Model' };
const RANGES = [['all', 'Any time'], ['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days']];
const SORTS = [['newest', 'Newest first'], ['oldest', 'Oldest first']];

const svg = (paths) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const ICON = {
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  x: svg('<path d="M18 6 6 18M6 6l12 12"/>'),
  trash: svg('<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>'),
  upload: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>'),
  download: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>'),
  cube: svg('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7 12 12l8.7-5M12 22V12"/>'),
};

const state = {
  jobs: [],
  config: null,          // /api/config: providers and their setup status
  loaded: false,
  offline: false,
  filters: { status: 'all', q: '', range: 'all', sort: 'newest' },
  route: null,
  viewer: null,          // ModelViewer while the viewer page shows a model
  viewerJobId: null,
  viewerModelUrl: null,
  viewerListKey: '',
  tableHtml: '',
};

const $ = (selector, root = document) => root.querySelector(selector);
const main = $('#main');

// ---------------------------------------------------------------- helpers

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return (res.headers.get('content-type') || '').includes('application/json') ? res.json() : res.text();
}

function timeAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

const fullDate = (ts) => new Date(ts * 1000).toLocaleString();
const cm = (m) => `${(m * 100).toFixed(1)} cm`;
const fileSafe = (name) => name.replace(/[^\w.-]+/g, '_') || 'model';

function duration(job) {
  if (!job.started_at) return '—';
  const end = job.finished_at || Date.now() / 1000;
  const s = Math.max(0, Math.round(end - job.started_at));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

const pill = (job) => `<span class="pill pill-${esc(job.status)}"><span class="dot"></span>${STATUS_LABEL[job.status] || esc(job.status)}</span>`;
const options = (list, current) => list.map(([value, label]) => `<option value="${value}"${value === current ? ' selected' : ''}>${label}</option>`).join('');
const thumb = (job) => (job.thumb_url ? `<img src="${esc(job.thumb_url)}" alt="" loading="lazy">` : `<div class="thumb-ph">${ICON.cube}</div>`);
const providerLabel = (id) => state.config?.providers.find((p) => p.id === id)?.label || PROVIDER_LABEL[id] || id || '—';
const stageLabel = (job) => (job.stage === 'asking' ? `Asking ${providerLabel(job.provider)}` : STAGE_LABEL[job.stage] || job.stage);

function jobSubtitle(job) {
  if (job.parent_id) {
    const parent = state.jobs.find((j) => j.id === job.parent_id);
    const from = `<span class="refined-from">Refined from ${esc(parent ? parent.name : 'a deleted submission')}</span>`;
    return job.feedback ? `${from} · ${esc(job.feedback)}` : from;
  }
  return job.prompt ? esc(job.prompt) : '<span class="muted">No notes</span>';
}

function toast(message, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  $('#toast-root').appendChild(el);
  setTimeout(() => el.classList.add('leaving'), 3200);
  setTimeout(() => el.remove(), 3600);
}

function openModal(html, { wide = false } = {}) {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `<div class="modal${wide ? ' modal-wide' : ''}" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(backdrop);
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const handlers = [];
  function close() {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
    handlers.forEach((fn) => fn());
  }
  document.addEventListener('keydown', onKey);
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
  backdrop.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
  return { el: backdrop.firstElementChild, close, onClose: (fn) => handlers.push(fn) };
}

const modalHead = (title) => `<header class="modal-head"><h2>${title}</h2><button class="icon-btn" data-close aria-label="Close">${ICON.x}</button></header>`;

// ---------------------------------------------------------------- data

let pollTimer = null;

async function refresh() {
  clearTimeout(pollTimer);
  try {
    const data = await api('/api/jobs');
    state.jobs = data.jobs;
    state.loaded = true;
    if (state.offline) toast('Reconnected', 'success');
    state.offline = false;
    onJobsUpdated();
  } catch {
    if (!state.offline) toast('Lost connection to the Click2CAD server', 'error');
    state.offline = true;
  } finally {
    const busy = state.jobs.some((j) => ACTIVE.includes(j.status));
    pollTimer = setTimeout(refresh, busy ? 2000 : 8000);
  }
}

function onJobsUpdated() {
  const active = state.jobs.filter((j) => ACTIVE.includes(j.status)).length;
  const badge = $('#nav-active');
  badge.textContent = active;
  badge.hidden = active === 0;
  if (state.route.page === 'submissions') updateSubmissions();
  else selectViewerJob(state.route.id);
}

async function loadConfig() {
  try {
    const c = await api('/api/config');
    state.config = c;
    $('#engine-info').innerHTML = `
      ${c.providers.map((p) => `
        <div><span>${esc(p.label)}${p.id === c.default_provider ? ' <span class="default-tag">default</span>' : ''}</span>
          <b class="${p.ready ? '' : 'warn'}">${p.ready ? esc(p.model) : 'not set up'}</b></div>`).join('')}
      <div>Blender <b>${esc(c.blender || 'not installed')}</b></div>
      <div>Parallel jobs <b>${c.max_parallel_jobs}</b></div>`;
  } catch { /* the jobs poll reports connection problems */ }
  return state.config;
}

// ---------------------------------------------------------------- routing

function parseRoute() {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/');
  return { page: page === 'viewer' ? 'viewer' : 'submissions', id: id ? decodeURIComponent(id) : null };
}

function render() {
  const previous = state.route;
  state.route = parseRoute();
  document.querySelectorAll('.sidenav a[data-route]').forEach((a) => {
    const on = a.dataset.route === state.route.page;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  if (state.route.page === 'viewer') {
    if (previous?.page !== 'viewer') renderViewerPage();
    selectViewerJob(state.route.id);
  } else {
    destroyViewer();
    state.viewerJobId = null;
    renderSubmissionsPage();
  }
}

// ---------------------------------------------------------------- submissions page

function renderSubmissionsPage() {
  const f = state.filters;
  main.innerHTML = `
    <header class="page-head">
      <div>
        <h1>Submissions</h1>
        <p class="page-sub">Furniture photos in, Blender models out.</p>
      </div>
      <button class="btn btn-primary" id="add-btn">${ICON.plus}<span>Add</span></button>
    </header>
    <div class="toolbar">
      <div class="chips" id="status-chips" role="group" aria-label="Filter by status"></div>
      <div class="toolbar-right">
        <input class="input" type="search" id="f-q" placeholder="Search name or notes" aria-label="Search" value="${esc(f.q)}">
        <select class="input" id="f-range" aria-label="Submitted">${options(RANGES, f.range)}</select>
        <select class="input" id="f-sort" aria-label="Sort">${options(SORTS, f.sort)}</select>
      </div>
    </div>
    <div class="card">
      <div class="table-scroll">
        <table class="jobs">
          <thead><tr>
            <th class="col-thumb"><span class="sr-only">Photo</span></th>
            <th>Submission</th><th>Status</th><th>Model</th><th class="num">Photos</th><th>Submitted</th><th>Duration</th>
            <th class="col-actions"><span class="sr-only">Actions</span></th>
          </tr></thead>
          <tbody id="jobs-body"></tbody>
        </table>
      </div>
      <div class="empty" id="jobs-empty" hidden></div>
    </div>`;

  state.tableHtml = '';
  $('#add-btn').onclick = openAddModal;
  $('#f-q').oninput = (e) => { f.q = e.target.value; updateSubmissions(); };
  $('#f-range').onchange = (e) => { f.range = e.target.value; updateSubmissions(); };
  $('#f-sort').onchange = (e) => { f.sort = e.target.value; updateSubmissions(); };
  $('#status-chips').onclick = (e) => {
    const chip = e.target.closest('[data-status]');
    if (chip) { f.status = chip.dataset.status; updateSubmissions(); }
  };
  $('#jobs-body').onclick = onJobAction;
  $('#jobs-empty').onclick = (e) => { if (e.target.closest('[data-add]')) openAddModal(); };
  updateSubmissions();
}

function matchesSearchAndRange(job) {
  const { q, range } = state.filters;
  const needle = q.trim().toLowerCase();
  const since = range === 'all' ? 0 : Date.now() / 1000 - Number(range) * 86400;
  return job.created_at >= since && (!needle || `${job.name} ${job.prompt} ${job.feedback || ''} ${job.id}`.toLowerCase().includes(needle));
}

function updateSubmissions() {
  if (state.route?.page !== 'submissions') return;
  const f = state.filters;
  const base = state.jobs.filter(matchesSearchAndRange);
  const count = (s) => (s === 'all' ? base.length : base.filter((j) => j.status === s).length);
  $('#status-chips').innerHTML = ['all', ...STATUSES].map((s) => `
    <button type="button" class="chip${f.status === s ? ' active' : ''}" data-status="${s}" aria-pressed="${f.status === s}">
      ${s === 'all' ? 'All' : STATUS_LABEL[s]}<span class="chip-count">${count(s)}</span>
    </button>`).join('');

  const rows = base
    .filter((j) => f.status === 'all' || j.status === f.status)
    .sort((a, b) => (f.sort === 'oldest' ? a.created_at - b.created_at : b.created_at - a.created_at));
  const html = rows.map(rowHtml).join('');
  if (html !== state.tableHtml) {  // avoid re-rendering (and losing hover/focus) when nothing changed
    $('#jobs-body').innerHTML = html;
    state.tableHtml = html;
  }

  const empty = $('#jobs-empty');
  empty.hidden = rows.length > 0;
  if (!rows.length) {
    empty.innerHTML = !state.loaded ? 'Loading…'
      : state.jobs.length ? 'No submissions match these filters.'
      : `${ICON.upload}<p>No submissions yet.</p><button class="btn btn-primary" data-add>${ICON.plus}<span>Add photos</span></button>`;
  }
}

function rowHtml(job) {
  const active = ACTIVE.includes(job.status);
  const button = (action, label, cls = '') => `<button class="btn btn-sm ${cls}" data-action="${action}">${label}</button>`;
  const actions = [];
  if (job.status === 'completed') actions.push(button('view', 'View 3D', 'btn-accent'));
  if (!active && job.script_url) actions.push(button('refine', 'Refine'));
  if (!active && job.images.length) actions.push(button('retry', job.status === 'completed' ? 'Regenerate' : 'Retry'));
  if (active) actions.push(button('cancel', 'Cancel'));
  if (job.status !== 'queued') actions.push(button('log', 'Log'));
  if (!active) actions.push(`<button class="icon-btn danger" data-action="delete" aria-label="Delete" title="Delete">${ICON.trash}</button>`);

  const stage = job.status === 'running' && job.stage ? `<div class="stage">${esc(stageLabel(job))}…</div>` : '';
  const error = job.status === 'failed' && job.error ? `<div class="job-error" title="${esc(job.error)}">${esc(job.error)}</div>` : '';
  return `
    <tr data-id="${esc(job.id)}"${job.status === 'completed' ? ' class="clickable"' : ''}>
      <td class="col-thumb">${thumb(job)}</td>
      <td class="col-main">
        <div class="job-name">${esc(job.name)}</div>
        <div class="job-sub">${jobSubtitle(job)}</div>
        ${error}
      </td>
      <td>${pill(job)}${stage}</td>
      <td><div class="model-cell">${esc(providerLabel(job.provider))}<small>${esc(job.model || '')}</small></div></td>
      <td class="num">${job.images.length}</td>
      <td title="${esc(fullDate(job.created_at))}">${timeAgo(job.created_at)}</td>
      <td class="tabular">${duration(job)}</td>
      <td class="col-actions"><div class="actions">${actions.join('')}</div></td>
    </tr>`;
}

async function onJobAction(e) {
  const row = e.target.closest('tr[data-id]');
  const job = row && state.jobs.find((j) => j.id === row.dataset.id);
  if (!job) return;
  const action = e.target.closest('[data-action]')?.dataset.action;
  const url = `/api/jobs/${encodeURIComponent(job.id)}`;
  try {
    if (!action || action === 'view') {
      if (job.status === 'completed') location.hash = `#/viewer/${encodeURIComponent(job.id)}`;
    } else if (action === 'log') {
      openLogModal(job);
    } else if (action === 'refine') {
      openRefineModal(job);
    } else if (action === 'retry') {
      if (job.status === 'completed' && !confirm(`Regenerate "${job.name}"? The current model will be replaced.`)) return;
      await api(`${url}/retry`, { method: 'POST' });
      toast('Queued again', 'success');
      refresh();
    } else if (action === 'cancel') {
      await api(`${url}/cancel`, { method: 'POST' });
      toast('Cancelled');
      refresh();
    } else if (action === 'delete') {
      if (!confirm(`Delete "${job.name}" and all of its files?`)) return;
      await api(url, { method: 'DELETE' });
      toast('Deleted');
      refresh();
    }
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------- add modal

async function openAddModal() {
  await loadConfig();  // pick up .env changes, e.g. a newly added API key
  const files = [];  // { file, url }
  const { el, close, onClose } = openModal(`
    ${modalHead('New submission')}
    <div class="modal-body">
      <label class="dropzone" id="dz">
        <input type="file" id="file-input" multiple accept="image/jpeg,image/png,image/webp" hidden>
        ${ICON.upload}
        <span class="dz-title">Drop photos here or <u>browse</u></span>
        <span class="dz-hint">JPG, PNG or WebP · up to 25 MB each</span>
      </label>
      <div class="file-grid" id="file-grid"></div>
      <fieldset class="mode" id="mode" hidden>
        <legend>These photos are…</legend>
        <label class="mode-opt"><input type="radio" name="mode" value="separate" checked>
          <span><b>Separate pieces</b><small>One job per photo</small></span></label>
        <label class="mode-opt"><input type="radio" name="mode" value="multiview">
          <span><b>One piece, several views</b><small>All photos go to Gemini as one job</small></span></label>
      </fieldset>
      ${providerPicker(state.config?.default_provider)}
      <label class="field"><span>Name <small>optional</small></span>
        <input class="input" id="f-name" maxlength="120" placeholder="Defaults to the file name"></label>
      <label class="field"><span>Notes for the model <small>optional</small></span>
        <textarea class="input" id="f-prompt" rows="3" maxlength="1000" placeholder="e.g. Stacking chair, curved plastic seat and backrest, four steel tube legs"></textarea></label>
    </div>
    <footer class="modal-foot">
      <span class="hint" id="submit-hint"></span>
      <button class="btn" data-close>Cancel</button>
      <button class="btn btn-primary" id="submit-btn" disabled>Submit</button>
    </footer>`);
  onClose(() => files.forEach((f) => URL.revokeObjectURL(f.url)));

  const input = $('#file-input', el);
  const grid = $('#file-grid', el);
  const dropzone = $('#dz', el);
  const submit = $('#submit-btn', el);
  const mode = () => $('input[name=mode]:checked', el).value;
  let providerReady = true;
  const provider = wireProviderPicker(el, (p) => { providerReady = !p || p.ready; sync(); });

  function addFiles(list) {
    for (const file of list) {
      const ok = /^image\/(jpeg|png|webp)$/.test(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name);
      if (!ok) { toast(`${file.name}: use JPG, PNG or WebP`, 'error'); continue; }
      files.push({ file, url: URL.createObjectURL(file) });
    }
    sync();
  }

  function sync() {
    grid.innerHTML = files.map((f, i) => `
      <figure class="file-tile">
        <img src="${f.url}" alt="">
        <figcaption title="${esc(f.file.name)}">${esc(f.file.name)}</figcaption>
        <button type="button" class="tile-x" data-remove="${i}" aria-label="Remove ${esc(f.file.name)}">${ICON.x}</button>
      </figure>`).join('');
    const n = files.length;
    const jobs = n === 0 ? 0 : mode() === 'multiview' ? 1 : n;
    $('#mode', el).hidden = n < 2;
    submit.disabled = n === 0 || !providerReady;
    submit.textContent = n === 0 ? 'Submit' : `Submit ${jobs} job${jobs > 1 ? 's' : ''}`;
    $('#submit-hint', el).textContent = n ? `${n} photo${n > 1 ? 's' : ''} selected` : '';
  }

  input.onchange = () => { addFiles(input.files); input.value = ''; };
  grid.onclick = (e) => {
    const remove = e.target.closest('[data-remove]');
    if (!remove) return;
    const [removed] = files.splice(Number(remove.dataset.remove), 1);
    URL.revokeObjectURL(removed.url);
    sync();
  };
  el.querySelectorAll('input[name=mode]').forEach((radio) => { radio.onchange = sync; });
  ['dragenter', 'dragover'].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.remove('drag'); }));
  dropzone.addEventListener('drop', (e) => addFiles(e.dataTransfer.files));

  submit.onclick = async () => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f.file, f.file.name));
    form.append('mode', mode());
    form.append('provider', provider());
    form.append('name', $('#f-name', el).value);
    form.append('prompt', $('#f-prompt', el).value);
    submit.disabled = true;
    submit.textContent = 'Uploading…';
    try {
      const res = await api('/api/jobs', { method: 'POST', body: form });
      close();
      toast(`Queued ${res.jobs.length} job${res.jobs.length > 1 ? 's' : ''}`, 'success');
      state.filters.status = 'all';
      if (state.route.page !== 'submissions') location.hash = '#/submissions';
      refresh();
    } catch (err) {
      toast(err.message, 'error');
      sync();
    }
  };
}

function providerPicker(selected) {
  const providers = state.config?.providers || [];
  if (!providers.length) return '';
  return `
    <fieldset class="provider">
      <legend>Model</legend>
      <div class="segmented">${providers.map((p) => `
        <label class="seg"><input type="radio" name="provider" value="${esc(p.id)}"${p.id === selected ? ' checked' : ''}><span>${esc(p.label)}</span></label>`).join('')}
      </div>
      <p class="provider-status" id="provider-status"></p>
    </fieldset>`;
}

// Keeps the picker's status line current; returns a getter for the chosen provider id.
function wireProviderPicker(el, onChange) {
  const status = $('#provider-status', el);
  const chosen = () => $('input[name=provider]:checked', el)?.value || '';
  const update = () => {
    const p = state.config?.providers.find((x) => x.id === chosen());
    if (status) {
      status.classList.toggle('warn', Boolean(p && !p.ready));
      status.textContent = !p ? '' : p.ready ? `Uses ${p.model}` : `Not set up yet: add ${p.missing.join(' and ')} to .env`;
    }
    onChange(p);
  };
  el.querySelectorAll('input[name=provider]').forEach((radio) => radio.addEventListener('change', update));
  update();
  return chosen;
}

async function openRefineModal(job) {
  await loadConfig();
  const failed = job.status === 'failed';
  const { el, close } = openModal(`
    ${modalHead(`Refine · ${esc(job.name)}`)}
    <div class="modal-body">
      <div class="refine-source">
        ${thumb(job)}
        <div>
          <div class="job-name">${esc(job.name)}</div>
          <div class="job-sub">${failed
            ? `Failed: ${esc(job.error || 'unknown error')}`
            : 'Its Blender script is sent with your notes. The result is saved as a new submission; this one stays as it is.'}</div>
        </div>
      </div>
      <label class="field"><span>What should change?${failed ? ' <small>optional: the error is sent automatically</small>' : ''}</span>
        <textarea class="input" id="r-feedback" rows="4" maxlength="2000" placeholder="e.g. The backrest is missing. Add a mesh backrest with horizontal slots, attached to the back of the seat."></textarea></label>
      ${providerPicker(state.config?.default_provider)}
      <label class="field"><span>Name</span>
        <input class="input" id="r-name" maxlength="120" value="${esc(job.name.replace(/\s*\(refined\)$/, ''))} (refined)"></label>
    </div>
    <footer class="modal-foot">
      <span class="hint"></span>
      <button class="btn" data-close>Cancel</button>
      <button class="btn btn-primary" id="r-submit" disabled>Refine</button>
    </footer>`);

  const submit = $('#r-submit', el);
  const feedback = $('#r-feedback', el);
  let providerReady = true;
  const sync = () => { submit.disabled = !providerReady || (!failed && !feedback.value.trim()); };
  const provider = wireProviderPicker(el, (p) => { providerReady = !p || p.ready; sync(); });
  feedback.oninput = sync;
  feedback.focus();

  submit.onclick = async () => {
    const form = new FormData();
    form.append('feedback', feedback.value);
    form.append('provider', provider());
    form.append('name', $('#r-name', el).value);
    submit.disabled = true;
    submit.textContent = 'Queuing…';
    try {
      await api(`/api/jobs/${encodeURIComponent(job.id)}/refine`, { method: 'POST', body: form });
      close();
      toast('Refinement queued', 'success');
      state.filters.status = 'all';
      if (state.route.page !== 'submissions') location.hash = '#/submissions';
      refresh();
    } catch (err) {
      toast(err.message, 'error');
      submit.textContent = 'Refine';
      sync();
    }
  };
}

async function openLogModal(job) {
  const { el } = openModal(`
    ${modalHead(`Log · ${esc(job.name)}`)}
    <div class="modal-body">
      ${job.error ? `<div class="alert">${esc(job.error)}</div>` : ''}
      <pre class="log" id="log-text">Loading…</pre>
    </div>`, { wide: true });
  try {
    const text = await api(`/api/jobs/${encodeURIComponent(job.id)}/log`);
    $('#log-text', el).textContent = text || '(no log output yet)';
  } catch (err) {
    $('#log-text', el).textContent = err.message;
  }
}

async function openScriptModal(job) {
  const { el } = openModal(`
    ${modalHead(`Blender script · ${esc(job.name)}`)}
    <div class="modal-body"><pre class="log" id="script-text">Loading…</pre></div>`, { wide: true });
  try {
    $('#script-text', el).textContent = await api(job.script_url);
  } catch (err) {
    $('#script-text', el).textContent = err.message;
  }
}

// ---------------------------------------------------------------- viewer page

const completedJobs = () => state.jobs.filter((j) => j.status === 'completed' && j.model_url);

function renderViewerPage() {
  main.innerHTML = `
    <div class="viewer-layout">
      <aside class="card model-list">
        <div class="model-list-head">
          <h2>Models</h2>
          <input class="input" type="search" id="m-q" placeholder="Search" aria-label="Search models">
        </div>
        <ul id="model-items"></ul>
      </aside>
      <section class="viewer-main" id="viewer-main"></section>
    </div>`;
  state.viewerListKey = '';
  $('#m-q').oninput = () => updateModelList(true);
  $('#model-items').onclick = (e) => {
    const item = e.target.closest('[data-id]');
    if (item) location.hash = `#/viewer/${encodeURIComponent(item.dataset.id)}`;
  };
}

function updateModelList(force = false) {
  if (state.route?.page !== 'viewer') return;
  const jobs = completedJobs();
  const key = `${jobs.map((j) => j.id + j.finished_at).join('|')}#${state.viewerJobId}`;
  if (!force && key === state.viewerListKey) return;
  state.viewerListKey = key;
  const q = $('#m-q').value.trim().toLowerCase();
  const list = jobs.filter((j) => !q || `${j.name} ${j.prompt}`.toLowerCase().includes(q));
  $('#model-items').innerHTML = list.length
    ? list.map((j) => `
        <li data-id="${esc(j.id)}"${j.id === state.viewerJobId ? ' class="active" aria-current="true"' : ''}>
          ${thumb(j)}
          <div><div class="m-name">${esc(j.name)}</div><div class="m-sub">${timeAgo(j.finished_at || j.created_at)}</div></div>
        </li>`).join('')
    : `<li class="m-empty">${jobs.length ? 'No matches' : 'No models yet'}</li>`;
}

function selectViewerJob(id) {
  if (state.route?.page !== 'viewer') return;
  if (!state.loaded) {
    $('#viewer-main').innerHTML = '<div class="card viewer-empty">Loading…</div>';
    return;
  }
  const current = state.jobs.find((j) => j.id === state.viewerJobId && j.model_url);
  const job = id ? state.jobs.find((j) => j.id === id) : current || completedJobs()[0];
  state.viewerJobId = job?.id ?? null;
  if (!job) {
    viewerMessage(id ? 'Model not found' : 'No models yet', id ? 'This submission may have been deleted.' : 'Completed submissions show up here.');
  } else if (!job.model_url) {
    viewerMessage(esc(job.name), `There is no model to show yet. ${pill(job)}`);
  } else if (!(state.viewer && state.viewerModelUrl === job.model_url)) {
    renderViewerMain(job);
  }
  updateModelList();
}

function viewerMessage(title, body) {
  destroyViewer();
  $('#viewer-main').innerHTML = `
    <div class="card viewer-empty">${ICON.cube}<h2>${title}</h2><p>${body}</p>
      <a class="btn" href="#/submissions">Go to submissions</a></div>`;
}

function renderViewerMain(job) {
  destroyViewer();
  const photos = job.image_urls.length
    ? `<div class="photo-strip">${job.image_urls.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="Source photo" loading="lazy"></a>`).join('')}</div>`
    : '<p class="muted">No photo stored for this submission.</p>';
  $('#viewer-main').innerHTML = `
    <div class="viewer-head">
      <div>
        <h1>${esc(job.name)}</h1>
        <div class="page-sub">${pill(job)}<span>Generated ${timeAgo(job.finished_at || job.created_at)} · ${esc(providerLabel(job.provider))}${job.model ? ` (${esc(job.model)})` : ''}</span></div>
      </div>
      <div class="viewer-actions">
        <button class="btn" id="v-wire" aria-pressed="false">Wireframe</button>
        <button class="btn" id="v-reset">Reset view</button>
        ${job.script_url ? '<button class="btn" id="v-refine">Refine</button><button class="btn" id="v-script">Script</button>' : ''}
        <a class="btn btn-primary" href="${esc(job.model_url)}" download="${esc(fileSafe(job.name))}.obj">${ICON.download}<span>Download OBJ</span></a>
      </div>
    </div>
    <div class="card canvas-card">
      <div class="canvas-host" id="canvas-host"></div>
      <div class="canvas-msg" id="canvas-msg">Loading model…</div>
      <div class="canvas-hint">Drag to orbit · scroll to zoom · right-drag to pan</div>
    </div>
    <div class="stats" id="v-stats"></div>
    <div class="viewer-details">
      <div class="card detail-card"><h3>Source photos</h3>${photos}</div>
      <div class="card detail-card"><h3>Notes</h3><p>${job.prompt ? esc(job.prompt) : '<span class="muted">No notes</span>'}</p>${job.parent_id ? `<p class="refine-note">${jobSubtitle(job)}</p>` : ''}</div>
    </div>`;

  let viewer;
  try {
    viewer = new ModelViewer($('#canvas-host'));
  } catch {
    $('#canvas-msg').textContent = 'WebGL is not available in this browser.';
    return;
  }
  state.viewer = viewer;
  state.viewerModelUrl = job.model_url;

  viewer.load(job.model_url).then((info) => {
    if (state.viewer !== viewer) return;
    $('#canvas-msg').hidden = true;
    const stats = [
      ['Width', cm(info.size.x)], ['Depth', cm(info.size.z)], ['Height', cm(info.size.y)],
      ['Triangles', info.triangles.toLocaleString()], ['Parts', info.parts.length, info.parts.join(', ')],
    ];
    $('#v-stats').innerHTML = stats.map(([label, value, title]) => `<div class="stat"${title ? ` title="${esc(title)}"` : ''}><span>${label}</span><b>${value}</b></div>`).join('');
  }).catch((err) => {
    if (state.viewer === viewer) $('#canvas-msg').textContent = `Could not load the model: ${err.message}`;
  });

  $('#v-wire').onclick = (e) => {
    const on = e.currentTarget.getAttribute('aria-pressed') !== 'true';
    e.currentTarget.setAttribute('aria-pressed', String(on));
    viewer.setWireframe(on);
  };
  $('#v-reset').onclick = () => viewer.resetView();
  if (job.script_url) $('#v-script').onclick = () => openScriptModal(job);
  if (job.script_url) $('#v-refine').onclick = () => openRefineModal(job);
}

function destroyViewer() {
  state.viewer?.dispose();
  state.viewer = null;
  state.viewerModelUrl = null;
}

// ---------------------------------------------------------------- start

// A file dropped outside the drop zone would otherwise navigate away from the app.
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());
window.addEventListener('hashchange', render);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

if (!location.hash) history.replaceState(null, '', '#/submissions');
render();
loadConfig();
refresh();
