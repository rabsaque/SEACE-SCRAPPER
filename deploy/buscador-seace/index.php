<?php
// Just serve the HTML shell — all logic is in api.php + inline JS
header('Content-Type: text/html; charset=utf-8');
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEACE — Buscador de Contratos</title>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
<style>
:root{--seace-blue:#00539b;--seace-gold:#f0a500}
body{background:#f4f6f9;font-size:.9rem}
.navbar{background:var(--seace-blue)!important}
.navbar-brand{font-weight:700;letter-spacing:.5px}
.card{border:none;box-shadow:0 1px 4px rgba(0,0,0,.1);border-radius:8px}
.card-header{background:var(--seace-blue);color:#fff;font-weight:600;border-radius:8px 8px 0 0!important}
.badge-pending{background:#6c757d}
.badge-running{background:#0d6efd;animation:pulse 1.5s infinite}
.badge-done{background:#198754}
.badge-error{background:#dc3545}
.badge-stopped{background:#fd7e14}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}
#log-box{height:260px;overflow-y:auto;background:#1e1e1e;color:#d4d4d4;
  font-family:monospace;font-size:.78rem;padding:10px;border-radius:4px}
.log-INFO{color:#9cdcfe}.log-SUCCESS{color:#4ec9b0}.log-WARNING{color:#dcdcaa}
.log-ERROR{color:#f44747}.log-DEBUG{color:#808080}
.lead-row:hover{background:#f0f4ff;cursor:pointer}
.kw-tag{display:inline-block;background:#e9ecef;border-radius:3px;
  padding:1px 6px;margin:1px;font-size:.78rem}
#login-screen{min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,var(--seace-blue),#003370)}
.login-card{width:360px}
.spinner-sm{width:1rem;height:1rem;border-width:2px}
</style>
</head>
<body>

<!-- ═══════════════════ LOGIN ═══════════════════ -->
<div id="login-screen" class="d-none">
  <div class="card login-card shadow-lg">
    <div class="card-body p-4">
      <div class="text-center mb-4">
        <i class="bi bi-building-check text-primary" style="font-size:2.5rem"></i>
        <h5 class="mt-2 fw-bold">SEACE Buscador</h5>
        <small class="text-muted">Contratos de Contratación Pública</small>
      </div>
      <div id="login-err" class="alert alert-danger d-none small py-2"></div>
      <form id="login-form">
        <div class="mb-3">
          <label class="form-label fw-semibold">Usuario</label>
          <input id="l-user" type="text" class="form-control" autocomplete="username" required>
        </div>
        <div class="mb-3">
          <label class="form-label fw-semibold">Contraseña</label>
          <input id="l-pass" type="password" class="form-control" autocomplete="current-password" required>
        </div>
        <button type="submit" class="btn btn-primary w-100 fw-semibold">
          <span class="spinner-border spinner-sm d-none me-1" id="l-spin"></span>
          Ingresar
        </button>
      </form>
    </div>
  </div>
</div>

<!-- ═══════════════════ APP ═══════════════════ -->
<div id="app" class="d-none">

  <nav class="navbar navbar-expand-lg navbar-dark mb-4 px-3 py-2">
    <span class="navbar-brand"><i class="bi bi-search me-2"></i>SEACE Buscador</span>
    <div class="ms-auto d-flex align-items-center gap-3">
      <span id="nav-user" class="text-white-50 small"></span>
      <button class="btn btn-sm btn-outline-light" onclick="logout()">
        <i class="bi bi-box-arrow-right"></i> Salir
      </button>
    </div>
  </nav>

  <div class="container-fluid px-4">

    <!-- Tabs -->
    <ul class="nav nav-tabs mb-3" id="main-tabs">
      <li class="nav-item">
        <a class="nav-link active" data-tab="nueva" href="#">
          <i class="bi bi-plus-circle me-1"></i>Nueva Búsqueda
        </a>
      </li>
      <li class="nav-item">
        <a class="nav-link" data-tab="busquedas" href="#" id="tab-busquedas">
          <i class="bi bi-list-check me-1"></i>Mis Búsquedas
        </a>
      </li>
      <li class="nav-item d-none" id="tab-admin-li">
        <a class="nav-link" data-tab="admin" href="#">
          <i class="bi bi-people me-1"></i>Usuarios
        </a>
      </li>
      <li class="nav-item d-none" id="tab-debug-li">
        <a class="nav-link" data-tab="debug" href="#">
          <i class="bi bi-bug me-1"></i>Debug
        </a>
      </li>
    </ul>

    <!-- ── Nueva Búsqueda ── -->
    <div id="tab-nueva" class="tab-pane">
      <div class="row g-3">
        <div class="col-lg-7">
          <div class="card">
            <div class="card-header"><i class="bi bi-search me-1"></i>Parámetros de Búsqueda</div>
            <div class="card-body">
              <div class="mb-3">
                <label class="form-label fw-semibold">
                  Palabras Clave
                  <span class="text-muted fw-normal small">(una por línea)</span>
                </label>
                <textarea id="f-keywords" class="form-control font-monospace"
                  rows="8" placeholder="MACROMEDIDOR&#10;SENSOR DE PRESION&#10;DATALOGGER"></textarea>
              </div>
              <div class="mb-3">
                <label class="form-label fw-semibold">
                  Descripción del Objeto
                  <span class="text-muted fw-normal small">(busca en el campo SEACE directamente — omite filtro de palabras clave)</span>
                </label>
                <input id="f-query" type="text" class="form-control"
                  placeholder="Ej: servicio de calibración de macromedidores">
              </div>
              <div class="row g-3 mb-3">
                <div class="col-sm-6">
                  <label class="form-label fw-semibold">Fecha Publicación Desde</label>
                  <input id="f-date-from" type="date" class="form-control">
                </div>
                <div class="col-sm-6">
                  <label class="form-label fw-semibold">Fecha Publicación Hasta</label>
                  <input id="f-date-to" type="date" class="form-control">
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="col-lg-5">
          <div class="card mb-3">
            <div class="card-header"><i class="bi bi-sliders me-1"></i>Opciones</div>
            <div class="card-body">
              <div class="form-check form-switch mb-2">
                <input class="form-check-input" type="checkbox" id="f-pdf" checked>
                <label class="form-check-label" for="f-pdf">
                  Descargar y leer PDFs (Bases)</label>
              </div>
              <div class="form-check form-switch mb-3">
                <input class="form-check-input" type="checkbox" id="f-ai" checked>
                <label class="form-check-label" for="f-ai">
                  Análisis con IA (requiere API key)</label>
              </div>
              <div class="mb-3">
                <label class="form-label fw-semibold">
                  Máximo de páginas
                  <span class="text-muted fw-normal small">(0 = sin límite)</span>
                </label>
                <input id="f-maxpages" type="number" class="form-control" value="0" min="0" max="100">
              </div>
              <div class="alert alert-info small mb-0 py-2">
                <i class="bi bi-info-circle me-1"></i>
                Cada búsqueda corre en un proceso independiente. Múltiples
                usuarios pueden buscar simultáneamente sin interferirse.
              </div>
            </div>
          </div>
          <button id="btn-start" class="btn btn-success w-100 py-2 fw-semibold"
            onclick="startJob()">
            <i class="bi bi-play-fill me-1"></i>Iniciar Búsqueda
          </button>
        </div>
      </div>
    </div>

    <!-- ── Mis Búsquedas ── -->
    <div id="tab-busquedas" class="tab-pane d-none">
      <div id="jobs-list"></div>
    </div>

    <!-- ── Debug ── -->
    <div id="tab-debug" class="tab-pane d-none">
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span><i class="bi bi-bug me-1"></i>Diagnóstico del Sistema</span>
          <button class="btn btn-sm btn-light" onclick="loadDebug()">
            <i class="bi bi-arrow-clockwise me-1"></i>Refrescar
          </button>
        </div>
        <div class="card-body" id="debug-body">
          <p class="text-muted small">Cargando…</p>
        </div>
      </div>
    </div>

    <!-- ── Admin ── -->
    <div id="tab-admin" class="tab-pane d-none">
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span><i class="bi bi-people me-1"></i>Gestión de Usuarios</span>
          <button class="btn btn-sm btn-light" onclick="showCreateUser()">
            <i class="bi bi-person-plus me-1"></i>Nuevo Usuario
          </button>
        </div>
        <div class="card-body p-0">
          <table class="table table-sm table-hover mb-0" id="users-table">
            <thead class="table-light">
              <tr><th>ID</th><th>Usuario</th><th>Rol</th><th>Creado</th><th></th></tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>

  </div><!-- /container -->
</div><!-- /app -->


<!-- ── Detail Modal ── -->
<div class="modal fade" id="lead-modal" tabindex="-1">
  <div class="modal-dialog modal-xl modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header bg-primary text-white">
        <h6 class="modal-title" id="modal-title">Detalle</h6>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body small" id="modal-body"></div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cerrar</button>
      </div>
    </div>
  </div>
</div>

<!-- ── Create User Modal ── -->
<div class="modal fade" id="user-modal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h6 class="modal-title">Nuevo Usuario</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div id="um-err" class="alert alert-danger d-none small py-2"></div>
        <div class="mb-3"><label class="form-label">Usuario</label>
          <input id="um-user" type="text" class="form-control"></div>
        <div class="mb-3"><label class="form-label">Contraseña</label>
          <input id="um-pass" type="password" class="form-control"></div>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="um-admin">
          <label class="form-check-label" for="um-admin">Administrador</label>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Cancelar</button>
        <button class="btn btn-primary btn-sm" onclick="createUser()">Crear</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
// ── API base ──────────────────────────────────────────────────────────────────
const API = 'api.php';

async function api(action, opts={}) {
  const isGet = !opts.method || opts.method === 'GET';
  let url = API + '?action=' + action;
  if (isGet && opts.params) {
    for (const [k,v] of Object.entries(opts.params)) url += '&'+k+'='+encodeURIComponent(v);
  }
  const res = await fetch(url, {
    method: opts.method || 'GET',
    headers: isGet ? {} : {'Content-Type':'application/json'},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: 'same-origin',
  });
  return res.json();
}

// ── State ─────────────────────────────────────────────────────────────────────
let _me = null;
let _pollTimers = {};   // job_id → interval id

// ── Boot ──────────────────────────────────────────────────────────────────────
(async () => {
  const r = await api('me');
  if (r.ok && r.data) {
    _me = r.data;
    showApp();
  } else {
    showLogin();
  }
})();

function showLogin() {
  document.getElementById('login-screen').classList.remove('d-none');
  document.getElementById('app').classList.add('d-none');
}

function showApp() {
  document.getElementById('login-screen').classList.add('d-none');
  document.getElementById('app').classList.remove('d-none');
  document.getElementById('nav-user').textContent =
    (_me.is_admin ? '★ ' : '') + _me.username;
  if (_me.is_admin) {
    document.getElementById('tab-admin-li').classList.remove('d-none');
    document.getElementById('tab-debug-li').classList.remove('d-none');
  }
  loadSettings();
  showTab('nueva');
}

// ── Login / logout ────────────────────────────────────────────────────────────
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const spin = document.getElementById('l-spin');
  const err  = document.getElementById('login-err');
  spin.classList.remove('d-none');
  err.classList.add('d-none');

  const r = await api('login', {
    method: 'POST',
    body: {
      username: document.getElementById('l-user').value,
      password: document.getElementById('l-pass').value,
    }
  });
  spin.classList.add('d-none');
  if (r.ok) { _me = r.data; showApp(); }
  else { err.textContent = r.error; err.classList.remove('d-none'); }
});

async function logout() {
  await api('logout', {method:'POST'});
  _me = null;
  showLogin();
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('d-none'));
  document.querySelectorAll('[data-tab]').forEach(a => a.classList.remove('active'));
  document.getElementById('tab-' + name)?.classList.remove('d-none');
  document.querySelector(`[data-tab="${name}"]`)?.classList.add('active');

  if (name === 'busquedas') loadJobs();
  if (name === 'admin')     loadUsers();
  if (name === 'debug')     loadDebug();
}

document.querySelectorAll('[data-tab]').forEach(a => {
  a.addEventListener('click', e => { e.preventDefault(); showTab(a.dataset.tab); });
});

// ── Load settings into the New-Search form ────────────────────────────────────
async function loadSettings() {
  const r = await api('settings');
  if (!r.ok) return;
  const s = r.data;
  document.getElementById('f-keywords').value = (s.keywords || []).join('\n');
  document.getElementById('f-maxpages').value = s.max_pages || 0;
}

// ── Start job ─────────────────────────────────────────────────────────────────
async function startJob() {
  const btn = document.getElementById('btn-start');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-sm me-1"></span>Iniciando…';

  const r = await api('start_job', {
    method: 'POST',
    body: {
      keywords:     document.getElementById('f-keywords').value,
      date_from:    document.getElementById('f-date-from').value,
      date_to:      document.getElementById('f-date-to').value,
      search_query: document.getElementById('f-query').value,
      download_pdf: document.getElementById('f-pdf').checked,
      use_ai:       document.getElementById('f-ai').checked,
      max_pages:    parseInt(document.getElementById('f-maxpages').value) || 0,
    }
  });

  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Iniciar Búsqueda';

  if (!r.ok) { alert('Error: ' + r.error); return; }

  // Switch to Búsquedas tab and show the new job
  showTab('busquedas');
}

// ── Jobs list ─────────────────────────────────────────────────────────────────
async function loadJobs() {
  const r = await api('jobs');
  if (!r.ok) return;
  renderJobs(r.data);
}

function renderJobs(jobs) {
  const el = document.getElementById('jobs-list');
  if (!jobs.length) {
    el.innerHTML = '<div class="alert alert-info">No hay búsquedas registradas.</div>';
    return;
  }

  el.innerHTML = jobs.map(j => `
    <div class="card mb-3" id="job-card-${j.id}">
      <div class="card-header d-flex flex-wrap align-items-center gap-2">
        <span class="fw-bold">#${j.id}</span>
        <span class="badge badge-${j.status}">${j.status.toUpperCase()}</span>
        ${j.username ? `<span class="text-white-50 small">@${j.username}</span>` : ''}
        <span class="ms-auto text-white-50 small">${j.created_at?.substring(0,16)||''}</span>
      </div>
      <div class="card-body py-2">
        <div class="d-flex flex-wrap gap-2 align-items-center mb-2">
          ${(j.keywords||[]).slice(0,6).map(k=>`<span class="kw-tag">${esc(k)}</span>`).join('')}
          ${(j.keywords||[]).length>6?`<span class="text-muted small">+${j.keywords.length-6} más</span>`:''}
          ${j.search_query?`<span class="badge bg-secondary">"${esc(j.search_query)}"</span>`:''}
          ${j.date_from||j.date_to?`<span class="badge bg-info text-dark">${j.date_from||'inicio'} → ${j.date_to||'hoy'}</span>`:''}
        </div>
        <div class="d-flex gap-3 small text-muted mb-2">
          <span><i class="bi bi-eye me-1"></i>${j.rows_scanned} filas</span>
          <span><i class="bi bi-check2 me-1"></i>${j.matches_found} coincid.</span>
          <span><i class="bi bi-bookmark me-1"></i>${j.leads_saved} leads</span>
        </div>
        <div class="d-flex gap-2 flex-wrap">
          <button class="btn btn-sm btn-outline-primary" onclick="openResults(${j.id})">
            <i class="bi bi-table me-1"></i>Resultados
          </button>
          <button class="btn btn-sm btn-outline-secondary" onclick="toggleLog(${j.id})">
            <i class="bi bi-terminal me-1"></i>Log
          </button>
          ${j.status==='running'||j.status==='pending'
            ? `<button class="btn btn-sm btn-outline-danger" onclick="stopJob(${j.id})">
                <i class="bi bi-stop-fill me-1"></i>Detener</button>` : ''}
        </div>
        <div id="log-container-${j.id}" class="mt-2 d-none">
          <div id="log-box-${j.id}" class="mt-1" style="height:220px;overflow-y:auto;
            background:#1e1e1e;color:#d4d4d4;font-family:monospace;font-size:.75rem;
            padding:8px;border-radius:4px;"></div>
        </div>
        <div id="results-container-${j.id}" class="mt-2 d-none"></div>
      </div>
    </div>
  `).join('');

  // Start polling for running/pending jobs
  jobs.filter(j => j.status==='running'||j.status==='pending').forEach(j => {
    startPolling(j.id);
  });
}

// ── Job polling ───────────────────────────────────────────────────────────────
let _logCursors = {};  // job_id → last log id

function startPolling(job_id) {
  if (_pollTimers[job_id]) return;
  _logCursors[job_id] = 0;
  _pollTimers[job_id] = setInterval(() => pollJob(job_id), 2500);
  pollJob(job_id);
}

function stopPolling(job_id) {
  clearInterval(_pollTimers[job_id]);
  delete _pollTimers[job_id];
}

async function pollJob(job_id) {
  // Status
  const sr = await api('job_status', {params:{job_id}});
  if (sr.ok) updateJobCard(sr.data);

  // Logs (if log box is visible)
  const logBox = document.getElementById('log-box-' + job_id);
  if (logBox) {
    const lr = await api('job_logs', {params:{job_id, since: _logCursors[job_id]||0}});
    if (lr.ok && lr.data.length) {
      lr.data.forEach(l => {
        _logCursors[job_id] = l.id;
        const cls = 'log-' + l.level;
        const line = document.createElement('div');
        line.className = cls;
        line.textContent = `[${l.ts?.substring(11,19)||''}] ${l.level}: ${l.message}`;
        logBox.appendChild(line);
      });
      logBox.scrollTop = logBox.scrollHeight;
    }
  }

  // Stop polling when done
  if (sr.ok && !['running','pending'].includes(sr.data.status)) {
    stopPolling(job_id);
  }
}

function updateJobCard(j) {
  const badge = document.querySelector(`#job-card-${j.id} .badge`);
  if (badge) { badge.className = `badge badge-${j.status}`; badge.textContent = j.status.toUpperCase(); }
  const stats = document.querySelector(`#job-card-${j.id} .d-flex.gap-3`);
  if (stats) stats.innerHTML = `
    <span><i class="bi bi-eye me-1"></i>${j.rows_scanned} filas</span>
    <span><i class="bi bi-check2 me-1"></i>${j.matches_found} coincid.</span>
    <span><i class="bi bi-bookmark me-1"></i>${j.leads_saved} leads</span>`;
}

async function stopJob(job_id) {
  if (!confirm('¿Detener esta búsqueda?')) return;
  const r = await api('stop_job', {method:'POST', body:{job_id}});
  if (r.ok) { stopPolling(job_id); loadJobs(); }
  else alert(r.error);
}

function toggleLog(job_id) {
  const c = document.getElementById('log-container-' + job_id);
  c.classList.toggle('d-none');
  if (!c.classList.contains('d-none')) startPolling(job_id);
}

// ── Results ───────────────────────────────────────────────────────────────────
async function openResults(job_id) {
  const c = document.getElementById('results-container-' + job_id);
  c.classList.toggle('d-none');
  if (c.classList.contains('d-none')) return;

  c.innerHTML = '<div class="text-center py-3"><span class="spinner-border spinner-sm"></span></div>';
  const r = await api('job_leads', {params:{job_id}});
  if (!r.ok) { c.innerHTML = `<div class="alert alert-danger small">${r.error}</div>`; return; }

  if (!r.data.length) {
    c.innerHTML = '<div class="alert alert-info small">Sin resultados aún.</div>';
    return;
  }

  c.innerHTML = `
    <div class="table-responsive mt-2">
      <table class="table table-sm table-hover mb-0">
        <thead class="table-light"><tr>
          <th>Entidad</th><th>Nomenclatura</th><th>Descripción</th>
          <th>Score</th><th>Nivel</th><th></th>
        </tr></thead>
        <tbody>
          ${r.data.map(l => `
            <tr class="lead-row" onclick="openLead(${l.id})">
              <td class="small">${esc(l.entity||'').substring(0,40)}</td>
              <td class="small text-nowrap">${esc(l.nomenclature||'')}</td>
              <td class="small">${esc((l.description||'').substring(0,60))}</td>
              <td><span class="badge bg-${scoreColor(l.match_score)}">${l.match_score}</span></td>
              <td><span class="badge bg-secondary">${l.match_level||''}</span></td>
              <td>
                ${l.ficha_url?`<a href="${esc(l.ficha_url)}" target="_blank" class="btn btn-xs btn-outline-primary btn-sm py-0 px-1" onclick="event.stopPropagation()">
                  <i class="bi bi-box-arrow-up-right"></i></a>`:''}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

function scoreColor(s) {
  if (s>=80) return 'success';
  if (s>=50) return 'warning text-dark';
  return 'secondary';
}

async function openLead(id) {
  const r = await api('lead_detail', {params:{id}});
  if (!r.ok) { alert(r.error); return; }
  const l = r.data;

  const cronHtml = (l.cronograma||[]).length
    ? `<table class="table table-sm table-bordered small">
        <thead><tr>${Object.keys(l.cronograma[0]).map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead>
        <tbody>${l.cronograma.map(row=>`<tr>${Object.values(row).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody>
       </table>`
    : '<em class="text-muted small">No disponible</em>';

  document.getElementById('modal-title').textContent =
    l.nomenclature + ' — ' + (l.entity||'').substring(0,50);

  document.getElementById('modal-body').innerHTML = `
    <div class="row g-3 mb-3">
      <div class="col-md-6">
        <p class="mb-1"><strong>Entidad:</strong> ${esc(l.entity||'')}</p>
        <p class="mb-1"><strong>Nomenclatura:</strong> ${esc(l.nomenclature||'')}</p>
        <p class="mb-1"><strong>Tipo:</strong> ${esc(l.object_type||'')}</p>
        <p class="mb-0"><strong>Descripción:</strong> ${esc(l.description||'')}</p>
      </div>
      <div class="col-md-6">
        <p class="mb-1"><strong>Score IA:</strong>
          <span class="badge bg-${scoreColor(l.match_score)}">${l.match_score} — ${l.match_level||''}</span></p>
        <p class="mb-1"><strong>PDF:</strong> ${l.pdf_local_path
          ? `<span class="font-monospace small">${esc(l.pdf_local_path.split('/').pop())}</span>`
          : '<em class="text-muted">No descargado</em>'}</p>
        ${l.ficha_url
          ? `<a href="${esc(l.ficha_url)}" target="_blank" class="btn btn-sm btn-outline-primary mt-1">
               <i class="bi bi-box-arrow-up-right me-1"></i>Ver en SEACE</a>`
          : ''}
      </div>
    </div>
    ${l.ai_summary ? `<div class="alert alert-light border small mb-3"><strong>Resumen IA:</strong><br>${esc(l.ai_summary)}</div>` : ''}
    ${(l.key_requirements||[]).length ? `<p class="mb-1 fw-semibold">Requisitos:</p>
      <ul class="small mb-3">${l.key_requirements.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>` : ''}
    ${(l.disqualifiers||[]).length ? `<p class="mb-1 fw-semibold text-danger">Exclusiones:</p>
      <ul class="small mb-3">${l.disqualifiers.map(d=>`<li>${esc(d)}</li>`).join('')}</ul>` : ''}
    <p class="fw-semibold mb-1">Cronograma:</p>
    <div class="table-responsive">${cronHtml}</div>
    ${l.tech_specs_text ? `<details class="mt-2"><summary class="small text-muted">Texto técnico del PDF</summary>
      <pre class="small mt-1" style="max-height:200px;overflow-y:auto;white-space:pre-wrap">${esc(l.tech_specs_text)}</pre></details>` : ''}`;

  bootstrap.Modal.getOrCreateInstance(document.getElementById('lead-modal')).show();
}

// ── Admin / Users ─────────────────────────────────────────────────────────────
async function loadUsers() {
  const r = await api('users');
  if (!r.ok) return;
  const tbody = document.querySelector('#users-table tbody');
  tbody.innerHTML = r.data.map(u => `
    <tr>
      <td>${u.id}</td>
      <td>${esc(u.username)}</td>
      <td>${u.is_admin?'<span class="badge bg-warning text-dark">Admin</span>':'Usuario'}</td>
      <td class="small text-muted">${(u.created_at||'').substring(0,10)}</td>
      <td><button class="btn btn-sm btn-outline-danger py-0" onclick="deleteUser(${u.id},'${esc(u.username)}')">
        <i class="bi bi-trash"></i></button></td>
    </tr>`).join('');
}

function showCreateUser() {
  document.getElementById('um-user').value = '';
  document.getElementById('um-pass').value = '';
  document.getElementById('um-admin').checked = false;
  document.getElementById('um-err').classList.add('d-none');
  bootstrap.Modal.getOrCreateInstance(document.getElementById('user-modal')).show();
}

async function createUser() {
  const err = document.getElementById('um-err');
  const r = await api('create_user', {method:'POST', body:{
    username: document.getElementById('um-user').value,
    password: document.getElementById('um-pass').value,
    is_admin: document.getElementById('um-admin').checked,
  }});
  if (r.ok) {
    bootstrap.Modal.getOrCreateInstance(document.getElementById('user-modal')).hide();
    loadUsers();
  } else {
    err.textContent = r.error;
    err.classList.remove('d-none');
  }
}

async function deleteUser(uid, name) {
  if (!confirm(`¿Eliminar usuario "${name}"?`)) return;
  const r = await api('delete_user', {method:'POST', body:{user_id:uid}});
  if (r.ok) loadUsers();
  else alert(r.error);
}

// ── Debug ─────────────────────────────────────────────────────────────────────
async function loadDebug() {
  const el = document.getElementById('debug-body');
  el.innerHTML = '<p class="text-muted small">Cargando…</p>';
  const r = await api('debug');
  if (!r.ok) { el.innerHTML = `<div class="alert alert-danger">${esc(r.error)}</div>`; return; }
  const d = r.data;

  const chk = (v, label) =>
    `<li class="list-group-item py-1 small">${v ? '✅' : '❌'} ${esc(label)}</li>`;
  const row = (k, v) =>
    `<tr><td class="text-muted pe-3 text-nowrap">${esc(k)}</td><td class="font-monospace small">${esc(String(v??''))}</td></tr>`;

  el.innerHTML = `
    <div class="row g-3">
      <div class="col-md-6">
        <p class="fw-semibold mb-1">PHP / Sistema</p>
        <ul class="list-group list-group-flush mb-3">
          ${chk(d.shell_exec_enabled, 'shell_exec() habilitado')}
          ${chk(d.exec_enabled,       'exec() habilitado')}
          ${chk(d.posix_enabled,      'posix_kill() disponible')}
          ${chk(d.python_exists,      'Python binary existe')}
          ${chk(d.python_executable,  'Python binary ejecutable')}
          ${chk(d.worker_exists,      'worker.py existe')}
          ${chk(d.db_dir_writable,    'Directorio DB escribible')}
          ${chk(d.log_dir_writable,   'Directorio logs escribible')}
        </ul>
        <p class="fw-semibold mb-1">Rutas</p>
        <table class="table table-sm table-bordered small mb-3">
          ${row('PHP user',    d.php_user)}
          ${row('PROJECT_DIR', d.PROJECT_DIR)}
          ${row('PYTHON_BIN',  d.PYTHON_BIN)}
          ${row('Python ver',  d.python_version)}
          ${row('Import test', d.python_import_test)}
        </table>
      </div>
      <div class="col-md-6">
        <p class="fw-semibold mb-1">Últimos Jobs</p>
        <table class="table table-sm table-bordered small mb-3">
          <thead><tr><th>ID</th><th>Estado</th><th>PID</th><th>Error</th></tr></thead>
          <tbody>
            ${(d.recent_jobs||[]).map(j=>
              `<tr><td>${j.id}</td><td>${j.status}</td><td>${j.pid??''}</td>
               <td class="text-danger small">${esc((j.error_msg||'').substring(0,60))}</td></tr>`
            ).join('')}
          </tbody>
        </table>
        ${d.last_job_log_file ? `
          <p class="fw-semibold mb-1">Último log de worker
            <span class="text-muted fw-normal small">(${esc(d.last_job_log_file)})</span></p>
          <div style="height:200px;overflow-y:auto;background:#1e1e1e;color:#d4d4d4;
            font-family:monospace;font-size:.72rem;padding:8px;border-radius:4px">
            ${(d.last_job_log_tail||['(vacío)']).map(l=>
              `<div>${esc(l)}</div>`).join('')}
          </div>` : ''}
      </div>
    </div>`;
}

// ── Utility ───────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>
