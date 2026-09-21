<?php
/**
 * SEACE Setup / Diagnostics
 *
 * Visit this page once after uploading to verify configuration and
 * initialize the database.  Remove or restrict access after setup.
 *
 * URL: https://yourdomain.com/buscador-seace/setup.php
 */

// Auto-detect home dir from cPanel's SERVER environment
$home = $_SERVER['HOME'] ?? posix_getpwuid(posix_geteuid())['dir'] ?? '/tmp';
$project = $home . '/seace-scraper';
$db_path  = $project . '/seace_leads.db';
$worker   = $project . '/worker.py';

// Probe for Python: try cPanel virtualenv first, then .venv fallback
function find_python(string $home, string $project): string {
    // cPanel virtualenv pattern: ~/virtualenv/seace-scraper/X.Y/bin/python
    $glob = glob($home . '/virtualenv/seace-scraper/*/bin/python');
    if (!empty($glob)) return $glob[0];
    // Standard venv inside project
    $local = $project . '/.venv/bin/python';
    if (file_exists($local)) return $local;
    // system python3
    foreach (['/usr/bin/python3', '/usr/local/bin/python3'] as $p) {
        if (file_exists($p)) return $p;
    }
    return $project . '/.venv/bin/python'; // placeholder
}
$python = find_python($home, $project);

// Handle POST: force-write config with custom python path
$force_write = false;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['python_bin'])) {
    $python = trim($_POST['python_bin']);
    $force_write = true;
}

// If config.php exists and HOME_DIR is real, use it (unless force-writing)
if (!$force_write && file_exists(__DIR__ . '/config.php')) {
    require_once __DIR__ . '/config.php';
    if (defined('PROJECT_DIR') && strpos(PROJECT_DIR, 'YOUR_CPANEL') === false) {
        $project = PROJECT_DIR;
        $db_path = DB_PATH;
        $python  = PYTHON_BIN;
        $worker  = WORKER_SCRIPT;
    }
}

$ok   = '✅';
$warn = '⚠️';
$err  = '❌';

function chk(bool $v, string $msg): string {
    global $ok, $err;
    return ($v ? $ok : $err) . ' ' . htmlspecialchars($msg);
}

$dir_exists     = is_dir($project);
$db_exists      = file_exists($db_path);
$db_dir_write   = is_writable(dirname($db_path));
$python_exists  = file_exists($python);
$worker_exists  = file_exists($worker);

// Try to open / create the DB
$db_ok  = false;
$db_err = '';
$admin_created = false;
try {
    $db = new PDO('sqlite:' . $db_path, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
    $db->exec("PRAGMA journal_mode=WAL;");
    // Create tables
    $db->exec("
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS scrape_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            keywords_json TEXT DEFAULT '[]',
            date_from TEXT DEFAULT '',
            date_to TEXT DEFAULT '',
            search_query TEXT DEFAULT '',
            download_pdf INTEGER DEFAULT 1,
            use_ai INTEGER DEFAULT 1,
            max_pages INTEGER DEFAULT 0,
            pid INTEGER,
            rows_scanned INTEGER DEFAULT 0,
            matches_found INTEGER DEFAULT 0,
            leads_saved INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            started_at TEXT,
            completed_at TEXT,
            error_msg TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS job_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            ts TEXT DEFAULT (datetime('now')),
            level TEXT DEFAULT 'INFO',
            message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT DEFAULT (datetime('now'))
        );
    ");

    // Also run the ALTER TABLE migrations that Python normally handles
    foreach ([
        "ALTER TABLE leads ADD COLUMN job_id INTEGER DEFAULT 0",
        "ALTER TABLE leads ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE leads ADD COLUMN cronograma_json TEXT DEFAULT '[]'",
    ] as $sql) {
        try { $db->exec($sql); } catch (Exception $e) {}
    }

    // Seed admin user
    $cnt = $db->query("SELECT COUNT(*) FROM users")->fetchColumn();
    if ($cnt == 0) {
        $hash = password_hash('admin1234', PASSWORD_BCRYPT);
        $db->prepare("INSERT INTO users (username,password_hash,is_admin) VALUES ('admin',?,1)")
           ->execute([$hash]);
        $admin_created = true;
    }

    $db_ok = true;
} catch (Exception $e) {
    $db_err = $e->getMessage();
}

// Generate the correct config.php content
$cfg = <<<PHP
<?php
define('HOME_DIR',      '$home');
define('PROJECT_DIR',   '$project');
define('PYTHON_BIN',    '$python');
define('WORKER_SCRIPT', '$worker');
define('DB_PATH',       '$db_path');
define('LOG_DIR',       PROJECT_DIR . '/logs');
define('SESSION_NAME',  'seace_sess');
define('SESSION_TTL',   7 * 24 * 3600);
define('MOUNT_PATH',    '/buscador-seace');
PHP;

// Write config.php if not already correctly configured, or if forced via POST
$wrote_config = false;
$cfg_path = __DIR__ . '/config.php';
if ($force_write || !file_exists($cfg_path) || strpos(file_get_contents($cfg_path), 'YOUR_CPANEL') !== false) {
    if (file_put_contents($cfg_path, $cfg) !== false) {
        $wrote_config = true;
    }
}
?>
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>SEACE Setup</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
</head>
<body class="bg-light">
<div class="container py-5" style="max-width:720px">
  <h3 class="mb-4">⚙️ SEACE — Diagnóstico de Configuración</h3>

  <div class="card mb-4">
    <div class="card-header fw-bold">Rutas detectadas</div>
    <div class="card-body small font-monospace">
      <div>HOME_DIR:      <strong><?= htmlspecialchars($home) ?></strong></div>
      <div>PROJECT_DIR:   <strong><?= htmlspecialchars($project) ?></strong></div>
      <div>DB_PATH:       <strong><?= htmlspecialchars($db_path) ?></strong></div>
      <div>PYTHON_BIN:    <strong><?= htmlspecialchars($python) ?></strong></div>
      <div>WORKER_SCRIPT: <strong><?= htmlspecialchars($worker) ?></strong></div>
    </div>
  </div>

  <div class="card mb-4">
    <div class="card-header fw-bold">Verificaciones</div>
    <ul class="list-group list-group-flush small">
      <li class="list-group-item"><?= chk($dir_exists,  "Directorio del proyecto existe: $project") ?></li>
      <li class="list-group-item"><?= chk($db_dir_write, "Directorio de BD escribible") ?></li>
      <li class="list-group-item"><?= chk($python_exists, "Python virtualenv encontrado: $python") ?></li>
      <li class="list-group-item"><?= chk($worker_exists, "Worker script encontrado: $worker") ?></li>
      <li class="list-group-item"><?= chk($db_ok, "Base de datos SQLite: " . ($db_ok ? "OK" : $db_err)) ?></li>
      <?php if ($wrote_config): ?>
      <li class="list-group-item">✅ config.php actualizado automáticamente</li>
      <?php endif; ?>
      <?php if ($admin_created): ?>
      <li class="list-group-item">✅ Usuario admin creado (usuario: <strong>admin</strong>, contraseña: <strong>admin1234</strong>)</li>
      <?php endif; ?>
    </ul>
  </div>

  <?php if (!$db_ok): ?>
  <div class="alert alert-danger">
    <strong>Error de BD:</strong> <?= htmlspecialchars($db_err) ?><br><br>
    Asegúrate de que el directorio <code><?= htmlspecialchars(dirname($db_path)) ?></code>
    existe y tiene permisos de escritura para el usuario web de PHP (normalmente el mismo usuario cPanel).<br><br>
    <strong>Desde SSH:</strong><br>
    <code>mkdir -p <?= htmlspecialchars($project) ?></code><br>
    <code>chmod 755 <?= htmlspecialchars($project) ?></code>
  </div>
  <?php elseif (!$dir_exists || !$python_exists || !$worker_exists): ?>
  <div class="alert alert-warning">
    Algunos componentes no se encontraron. Asegúrate de haber subido el proyecto
    a <code><?= htmlspecialchars($project) ?></code> y de haber creado el virtualenv:<br><br>
    <code>cd <?= htmlspecialchars($project) ?> && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt</code>
  </div>
  <?php else: ?>
  <div class="alert alert-success fw-semibold">
    ✅ Todo listo. Puedes <a href="index.php">ir al dashboard</a>.<br>
    <small class="fw-normal">Recuerda eliminar o proteger este archivo setup.php después de configurar.</small>
  </div>
  <?php endif; ?>

  <details class="mt-3">
    <summary class="text-muted small">Ver config.php generado</summary>
    <pre class="bg-dark text-light p-3 rounded small mt-2"><?= htmlspecialchars($cfg) ?></pre>
  </details>

  <div class="card mt-4 border-warning">
    <div class="card-header fw-bold bg-warning bg-opacity-25">⚙️ Paso final: Configurar Cron Job en cPanel</div>
    <div class="card-body small">
      <p class="mb-2">
        Este servidor no permite que PHP ejecute procesos directamente.<br>
        Necesitas configurar <strong>un cron job en cPanel</strong> que ejecute las búsquedas cada minuto.
      </p>
      <p class="mb-1 fw-semibold">En cPanel → Cron Jobs → Add New Cron Job:</p>
      <ul class="mb-2">
        <li><strong>Minute:</strong> <code>*</code> &nbsp; Every minute</li>
        <li><strong>Command:</strong></li>
      </ul>
      <pre class="bg-dark text-light p-2 rounded small"><?= htmlspecialchars($python) ?> <?= htmlspecialchars($project) ?>/cron_worker.py >> <?= htmlspecialchars($project) ?>/logs/cron.log 2>&1</pre>
      <p class="text-muted mt-2 mb-0">
        Cuando un usuario inicie una búsqueda, el cron la tomará en menos de 1 minuto y la ejecutará automáticamente.
      </p>
    </div>
  </div>

  <div class="card mt-4">
    <div class="card-header fw-bold">Ajustar ruta de Python manualmente</div>
    <div class="card-body">
      <p class="small text-muted mb-2">
        Usa esto si el virtualenv de cPanel no fue detectado automáticamente.<br>
        Ejemplo: <code>/home5/zkcbvnvr/virtualenv/seace-scraper/3.11/bin/python</code>
      </p>
      <form method="POST">
        <div class="input-group">
          <input type="text" name="python_bin" class="form-control font-monospace"
                 placeholder="/home/user/virtualenv/seace-scraper/3.11/bin/python"
                 value="<?= htmlspecialchars($python) ?>">
          <button class="btn btn-primary" type="submit">Guardar y reescribir config.php</button>
        </div>
      </form>
      <?php if ($force_write && $wrote_config): ?>
      <div class="alert alert-success mt-2 mb-0 py-2">✅ config.php actualizado con la nueva ruta.</div>
      <?php elseif ($force_write && !$wrote_config): ?>
      <div class="alert alert-danger mt-2 mb-0 py-2">❌ No se pudo escribir config.php. Verifica permisos.</div>
      <?php endif; ?>
    </div>
  </div>
</div>
</body>
</html>
