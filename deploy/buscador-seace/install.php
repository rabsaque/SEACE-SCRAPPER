<?php
/**
 * SEACE Python Environment Installer
 * Runs setup commands via PHP shell_exec (no SSH needed).
 * Delete this file after setup is complete.
 */

// No time limit — pip install takes a while
set_time_limit(0);
ini_set('max_execution_time', 0);

require_once __DIR__ . '/config.php';

$log_file = LOG_DIR . '/install.log';
@mkdir(LOG_DIR, 0755, true);

// ── Detect Python binary ──────────────────────────────────────────────────────
function find_python(): string {
    $candidates = [
        '/usr/bin/python3.11', '/usr/local/bin/python3.11',
        '/usr/bin/python3.10', '/usr/local/bin/python3.10',
        '/usr/bin/python3.9',  '/usr/local/bin/python3.9',
        '/usr/bin/python3',    '/usr/local/bin/python3',
    ];
    // CloudLinux paths
    foreach (glob('/home/*/*/bin/python3*') ?: [] as $p) $candidates[] = $p;
    foreach (glob('/opt/alt/python3*/usr/bin/python3*') ?: [] as $p) $candidates[] = $p;
    foreach ($candidates as $p) {
        if (file_exists($p) && is_executable($p)) return $p;
    }
    return '';
}

$action = $_GET['action'] ?? 'status';

// ── Run a step in the background, write output to log ────────────────────────
function run_bg(string $cmd): void {
    global $log_file;
    $full = sprintf(
        'cd %s && %s >> %s 2>&1',
        escapeshellarg(PROJECT_DIR),
        $cmd,
        escapeshellarg($log_file)
    );
    shell_exec($full);
}

function append_log(string $msg): void {
    global $log_file;
    file_put_contents($log_file, "[" . date('H:i:s') . "] $msg\n", FILE_APPEND);
}

if ($action === 'run') {
    // Clear old log
    file_put_contents($log_file, "=== SEACE Install " . date('Y-m-d H:i:s') . " ===\n");

    $python = find_python();
    if (!$python) {
        append_log("ERROR: No Python 3 binary found on this server.");
        header('Location: install.php');
        exit;
    }
    append_log("Using Python: $python");

    // Step 1: Create virtualenv
    append_log("--- Creating virtualenv ---");
    run_bg("$python -m venv .venv");
    append_log("Virtualenv done.");

    // Step 2: Upgrade pip
    append_log("--- Upgrading pip ---");
    run_bg(PYTHON_BIN . " -m pip install --upgrade pip --quiet");

    // Step 3: Install requirements
    append_log("--- Installing requirements.txt ---");
    run_bg(PYTHON_BIN . " -m pip install -r requirements.txt --quiet");
    append_log("pip install done.");

    // Step 4: Playwright install
    append_log("--- Installing Playwright Chromium (this may take several minutes) ---");
    run_bg(PYTHON_BIN . " -m playwright install chromium");
    append_log("Playwright done.");

    // Step 5: Init DB
    append_log("--- Initialising database ---");
    run_bg(PYTHON_BIN . " -c \"from src.storage.repository import init_db; init_db(); print('DB OK')\"");
    append_log("=== Install complete ===");

    header('Location: install.php?action=log');
    exit;
}

// ── Read log ──────────────────────────────────────────────────────────────────
$log_content  = file_exists($log_file) ? file_get_contents($log_file) : '(no log yet)';
$python_found = find_python();
$venv_exists  = file_exists(PYTHON_BIN);

?><!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>SEACE Installer</title>
<meta http-equiv="<?= $action === 'log' ? 'refresh" content="4' : 'x-no-refresh' ?>">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
<div class="container py-5" style="max-width:760px">
  <h3 class="mb-4">🐍 SEACE — Instalación del Entorno Python</h3>

  <div class="card mb-4">
    <div class="card-body">
      <table class="table table-sm small mb-0">
        <tr><td class="text-muted">Python del sistema</td>
            <td><?= $python_found ? "✅ $python_found" : "❌ No encontrado" ?></td></tr>
        <tr><td class="text-muted">Virtualenv (.venv)</td>
            <td><?= $venv_exists ? "✅ Creado" : "❌ No existe aún" ?></td></tr>
        <tr><td class="text-muted">PROJECT_DIR</td>
            <td class="font-monospace"><?= htmlspecialchars(PROJECT_DIR) ?></td></tr>
        <tr><td class="text-muted">PYTHON_BIN</td>
            <td class="font-monospace"><?= htmlspecialchars(PYTHON_BIN) ?></td></tr>
      </table>
    </div>
  </div>

  <?php if (!$python_found): ?>
  <div class="alert alert-danger">
    <strong>❌ No se encontró Python 3 en este servidor.</strong><br>
    Contacta a tu proveedor de hosting o usa cPanel → <strong>Setup Python App</strong>
    para instalar Python primero, luego vuelve aquí.
  </div>
  <?php else: ?>

  <?php if (!$venv_exists): ?>
  <div class="alert alert-warning">
    El virtualenv no existe todavía. Haz clic en <strong>Instalar</strong> para crearlo.
    El proceso tarda 3–10 minutos (la descarga de Chromium es grande).
  </div>
  <form method="get">
    <input type="hidden" name="action" value="run">
    <button class="btn btn-success btn-lg w-100" type="submit"
      onclick="this.disabled=true;this.textContent='Instalando… (no cierres esta página)';this.form.submit()">
      🚀 Instalar entorno Python
    </button>
  </form>
  <?php else: ?>
  <div class="alert alert-success">
    ✅ Virtualenv encontrado. Si hay errores, puedes reinstalar abajo.
  </div>
  <div class="d-flex gap-2 mb-3">
    <form method="get"><input type="hidden" name="action" value="run">
      <button class="btn btn-outline-warning" type="submit">🔄 Reinstalar</button>
    </form>
    <a href="index.php" class="btn btn-primary">Ir al Dashboard →</a>
    <a href="setup.php" class="btn btn-outline-secondary">Ver diagnóstico</a>
  </div>
  <?php endif; ?>

  <div class="card mt-3">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span>📋 Log de instalación</span>
      <?php if ($action === 'log'): ?>
        <span class="badge bg-warning text-dark">Actualizando cada 4s…</span>
      <?php endif; ?>
    </div>
    <div class="card-body p-0">
      <pre class="m-0 p-3 small" style="background:#1e1e1e;color:#d4d4d4;height:320px;
        overflow-y:auto;font-size:.75rem;border-radius:0 0 4px 4px"><?=
        htmlspecialchars($log_content) ?></pre>
    </div>
  </div>
  <?php endif; ?>

  <p class="text-muted small mt-3">
    ⚠️ Elimina o protege este archivo <code>install.php</code> después de la instalación.
  </p>
</div>
</body>
</html>
