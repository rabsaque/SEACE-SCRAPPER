<?php
/**
 * SEACE Dashboard API
 *
 * All endpoints return JSON.  Authentication uses PHP sessions.
 * The SQLite DB is shared with the Python scraper (read-only for most calls).
 *
 * Actions (via GET ?action=... or POST body):
 *   login, logout, me
 *   jobs, start_job, stop_job
 *   job_status, job_logs
 *   job_leads, lead_detail, review_lead, clear_leads
 *   users, create_user, delete_user
 *   settings, save_settings
 */

require_once __DIR__ . '/config.php';

// ── Session ───────────────────────────────────────────────────────────────────
ini_set('session.cookie_path', MOUNT_PATH);
ini_set('session.gc_maxlifetime', SESSION_TTL);
session_name(SESSION_NAME);
session_start();

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');

// ── DB connection (PDO SQLite) ────────────────────────────────────────────────
try {
    if (!is_dir(dirname(DB_PATH))) {
        _fail(503, 'DB directory does not exist: ' . dirname(DB_PATH)
            . ' — run setup.php first or check config.php');
    }
    $db = new PDO('sqlite:' . DB_PATH, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $db->exec("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;");
    _ensure_tables($db);
} catch (Exception $e) {
    _fail(503, 'DB unavailable (' . DB_PATH . '): ' . $e->getMessage()
        . ' — visit setup.php to diagnose');
}

// ── Route ─────────────────────────────────────────────────────────────────────
$action = $_GET['action'] ?? ($_POST['action'] ?? '');
$body   = json_decode(file_get_contents('php://input'), true) ?? [];
$method = $_SERVER['REQUEST_METHOD'];

switch ($action) {
    // ── Auth ─────────────────────────────────────────────────────────────────
    case 'login':        _login($db, $body);        break;
    case 'logout':       _logout();                  break;
    case 'me':           _me($db);                   break;

    // ── Jobs ─────────────────────────────────────────────────────────────────
    case 'jobs':         _list_jobs($db);            break;
    case 'start_job':    _start_job($db, $body);     break;
    case 'stop_job':     _stop_job($db, $body);      break;
    case 'job_status':   _job_status($db);           break;
    case 'job_logs':     _job_logs($db);             break;

    // ── Leads ─────────────────────────────────────────────────────────────────
    case 'job_leads':    _job_leads($db);            break;
    case 'lead_detail':  _lead_detail($db);          break;
    case 'review_lead':  _review_lead($db, $body);   break;
    case 'clear_leads':  _clear_leads($db, $body);   break;

    // ── Users (admin only) ────────────────────────────────────────────────────
    case 'users':        _list_users($db);           break;
    case 'create_user':  _create_user($db, $body);   break;
    case 'delete_user':  _delete_user($db, $body);   break;

    // ── Settings ──────────────────────────────────────────────────────────────
    case 'settings':     _settings($db);             break;
    case 'save_settings': _save_settings($db, $body); break;

    // ── Debug (admin only) ────────────────────────────────────────────────────
    case 'debug':        _debug($db);                break;

    default: _fail(400, "Unknown action: $action");
}


// ═══════════════════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════════════════

function _ok(mixed $data = null): void {
    echo json_encode(['ok' => true, 'data' => $data], JSON_UNESCAPED_UNICODE);
    exit;
}

function _fail(int $code, string $msg): void {
    http_response_code($code);
    echo json_encode(['ok' => false, 'error' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

function _auth(): array {
    // Returns ['user_id'=>int, 'username'=>str, 'is_admin'=>bool]
    if (empty($_SESSION['user_id'])) _fail(401, 'Not authenticated');
    return [
        'user_id'  => (int)$_SESSION['user_id'],
        'username' => $_SESSION['username'] ?? '',
        'is_admin' => (bool)($_SESSION['is_admin'] ?? false),
    ];
}

function _admin(): array {
    $u = _auth();
    if (!$u['is_admin']) _fail(403, 'Admin only');
    return $u;
}


// ═══════════════════════════════════════════════════════════════════════════════
// Auth
// ═══════════════════════════════════════════════════════════════════════════════

function _login(PDO $db, array $body): void {
    $username = trim($body['username'] ?? '');
    $password = $body['password'] ?? '';
    if (!$username || !$password) _fail(400, 'Username and password required');

    $row = $db->prepare("SELECT * FROM users WHERE username = ?");
    $row->execute([$username]);
    $user = $row->fetch();

    if (!$user || !password_verify($password, $user['password_hash'])) {
        _fail(401, 'Invalid credentials');
    }

    session_regenerate_id(true);
    $_SESSION['user_id']  = $user['id'];
    $_SESSION['username'] = $user['username'];
    $_SESSION['is_admin'] = (bool)$user['is_admin'];

    _ok(['user_id' => $user['id'], 'username' => $user['username'],
         'is_admin' => (bool)$user['is_admin']]);
}

function _logout(): void {
    session_destroy();
    _ok();
}

function _me(PDO $db): void {
    if (empty($_SESSION['user_id'])) {
        _ok(null);  // not logged in — return null (not an error)
    }
    _ok([
        'user_id'  => (int)$_SESSION['user_id'],
        'username' => $_SESSION['username'],
        'is_admin' => (bool)($_SESSION['is_admin'] ?? false),
    ]);
}


// ═══════════════════════════════════════════════════════════════════════════════
// Jobs
// ═══════════════════════════════════════════════════════════════════════════════

function _list_jobs(PDO $db): void {
    $u = _auth();
    if ($u['is_admin']) {
        $stmt = $db->query(
            "SELECT j.*, u.username FROM scrape_jobs j
             LEFT JOIN users u ON u.id = j.user_id
             ORDER BY j.created_at DESC LIMIT 100"
        );
    } else {
        $stmt = $db->prepare(
            "SELECT j.*, u.username FROM scrape_jobs j
             LEFT JOIN users u ON u.id = j.user_id
             WHERE j.user_id = ? ORDER BY j.created_at DESC LIMIT 50"
        );
        $stmt->execute([$u['user_id']]);
    }
    $jobs = $stmt->fetchAll();
    foreach ($jobs as &$j) {
        $j['keywords'] = json_decode($j['keywords_json'] ?? '[]', true);
        $j['download_pdf'] = (bool)$j['download_pdf'];
        $j['use_ai'] = (bool)$j['use_ai'];
        unset($j['keywords_json']);
    }
    _ok($jobs);
}

function _start_job(PDO $db, array $body): void {
    $u = _auth();

    // Parse keywords — accept newline-separated or array
    $raw_kw = $body['keywords'] ?? [];
    if (is_string($raw_kw)) {
        $raw_kw = preg_split('/[\r\n,]+/', $raw_kw);
    }
    $keywords = array_values(array_filter(array_map('trim', $raw_kw)));
    if (empty($keywords)) _fail(400, 'At least one keyword is required');

    $date_from    = trim($body['date_from'] ?? '');
    $date_to      = trim($body['date_to'] ?? '');
    $search_query = trim($body['search_query'] ?? '');
    $download_pdf = !empty($body['download_pdf']);
    $use_ai       = !empty($body['use_ai']);
    $max_pages    = (int)($body['max_pages'] ?? 0);

    $date_from = _fmt_date($date_from);
    $date_to   = _fmt_date($date_to);

    // Pre-flight checks (soft — don't block job creation)
    $warnings = [];
    if (!file_exists(PYTHON_BIN))    $warnings[] = 'Python binary not found: ' . PYTHON_BIN;
    if (!file_exists(WORKER_SCRIPT)) $warnings[] = 'worker.py not found: ' . WORKER_SCRIPT;

    // Insert job row (status='pending' — cron_worker.py picks it up within 1 minute)
    $stmt = $db->prepare(
        "INSERT INTO scrape_jobs
         (user_id, status, keywords_json, date_from, date_to, search_query,
          download_pdf, use_ai, max_pages, created_at)
         VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))"
    );
    $stmt->execute([
        $u['user_id'], 'pending',
        json_encode($keywords, JSON_UNESCAPED_UNICODE),
        $date_from, $date_to, $search_query,
        $download_pdf ? 1 : 0,
        $use_ai ? 1 : 0,
        $max_pages,
    ]);
    $job_id = (int)$db->lastInsertId();

    _ok([
        'job_id'   => $job_id,
        'status'   => 'pending',
        'warnings' => $warnings,
        'note'     => 'Job queued. The cron worker will start it within 1 minute.',
    ]);
}

function _debug(PDO $db): void {
    _admin();

    $info = [];

    // PHP capabilities
    $info['shell_exec_enabled']  = function_exists('shell_exec');
    $info['exec_enabled']        = function_exists('exec');
    $info['posix_enabled']       = function_exists('posix_kill');
    $info['php_user']            = function_exists('posix_getpwuid')
        ? (posix_getpwuid(posix_geteuid())['name'] ?? '?') : '?';

    // Paths
    $info['PROJECT_DIR']         = PROJECT_DIR;
    $info['PYTHON_BIN']          = PYTHON_BIN;
    $info['WORKER_SCRIPT']       = WORKER_SCRIPT;
    $info['DB_PATH']             = DB_PATH;
    $info['LOG_DIR']             = LOG_DIR;

    // Existence checks
    $info['project_dir_exists']  = is_dir(PROJECT_DIR);
    $info['python_exists']       = file_exists(PYTHON_BIN);
    $info['python_executable']   = is_executable(PYTHON_BIN);
    $info['worker_exists']       = file_exists(WORKER_SCRIPT);
    $info['cron_worker_exists']  = file_exists(PROJECT_DIR . '/cron_worker.py');
    $info['log_dir_writable']    = is_writable(dirname(LOG_DIR)) || is_writable(LOG_DIR);
    $info['db_dir_writable']     = is_writable(dirname(DB_PATH));

    // Cron worker lock file (indicates whether a job is actively running)
    $lock = LOG_DIR . '/cron_worker.pid';
    $info['cron_lock_file']      = $lock;
    $info['cron_lock_exists']    = file_exists($lock);
    if (file_exists($lock)) {
        $info['cron_lock_pid']   = trim(file_get_contents($lock));
    }

    // Cron log tail
    $cron_log = LOG_DIR . '/cron.log';
    if (file_exists($cron_log)) {
        $lines = file($cron_log, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $info['cron_log_tail'] = array_slice($lines, -20);
    }

    // Recent jobs
    $info['recent_jobs'] = $db->query(
        "SELECT id, user_id, status, pid, error_msg, created_at FROM scrape_jobs ORDER BY id DESC LIMIT 5"
    )->fetchAll();

    // Last log lines for most recent job
    $last = $db->query("SELECT id FROM scrape_jobs ORDER BY id DESC LIMIT 1")->fetchColumn();
    if ($last) {
        $log_file = LOG_DIR . '/worker_' . $last . '.log';
        $info['last_job_log_file']   = $log_file;
        $info['last_job_log_exists'] = file_exists($log_file);
        if (file_exists($log_file)) {
            $lines = file($log_file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
            $info['last_job_log_tail'] = array_slice($lines, -30);
        }
    }

    _ok($info);
}

function _stop_job(PDO $db, array $body): void {
    $u = _auth();
    $job_id = (int)($body['job_id'] ?? 0);
    if (!$job_id) _fail(400, 'job_id required');

    $stmt = $db->prepare("SELECT * FROM scrape_jobs WHERE id=?");
    $stmt->execute([$job_id]);
    $job = $stmt->fetch();
    if (!$job) _fail(404, 'Job not found');
    if (!$u['is_admin'] && $job['user_id'] != $u['user_id']) _fail(403, 'Forbidden');

    if ($job['pid']) {
        // Send SIGTERM; ignore errors (process may have already finished)
        @posix_kill((int)$job['pid'], SIGTERM);
    }
    $db->prepare("UPDATE scrape_jobs SET status='stopped', completed_at=datetime('now') WHERE id=?")
       ->execute([$job_id]);
    _ok();
}

function _job_status(PDO $db): void {
    $u = _auth();
    $job_id = (int)($_GET['job_id'] ?? 0);
    if (!$job_id) _fail(400, 'job_id required');

    $stmt = $db->prepare("SELECT * FROM scrape_jobs WHERE id=?");
    $stmt->execute([$job_id]);
    $job = $stmt->fetch();
    if (!$job) _fail(404, 'Job not found');
    if (!$u['is_admin'] && $job['user_id'] != $u['user_id']) _fail(403, 'Forbidden');

    $job['keywords'] = json_decode($job['keywords_json'] ?? '[]', true);
    $job['download_pdf'] = (bool)$job['download_pdf'];
    $job['use_ai'] = (bool)$job['use_ai'];
    unset($job['keywords_json']);
    _ok($job);
}

function _job_logs(PDO $db): void {
    $u      = _auth();
    $job_id = (int)($_GET['job_id'] ?? 0);
    $since  = (int)($_GET['since']  ?? 0);
    if (!$job_id) _fail(400, 'job_id required');

    // Verify ownership
    $stmt = $db->prepare("SELECT user_id FROM scrape_jobs WHERE id=?");
    $stmt->execute([$job_id]);
    $row = $stmt->fetch();
    if (!$row) _fail(404, 'Job not found');
    if (!$u['is_admin'] && $row['user_id'] != $u['user_id']) _fail(403, 'Forbidden');

    $stmt = $db->prepare(
        "SELECT id, ts, level, message FROM job_logs
         WHERE job_id=? AND id>? ORDER BY id LIMIT 200"
    );
    $stmt->execute([$job_id, $since]);
    _ok($stmt->fetchAll());
}


// ═══════════════════════════════════════════════════════════════════════════════
// Leads
// ═══════════════════════════════════════════════════════════════════════════════

function _job_leads(PDO $db): void {
    $u      = _auth();
    $job_id = (int)($_GET['job_id'] ?? 0);
    if (!$job_id) _fail(400, 'job_id required');

    // Ownership check
    $stmt = $db->prepare("SELECT user_id FROM scrape_jobs WHERE id=?");
    $stmt->execute([$job_id]);
    $row = $stmt->fetch();
    if (!$row) _fail(404, 'Job not found');
    if (!$u['is_admin'] && $row['user_id'] != $u['user_id']) _fail(403, 'Forbidden');

    $stmt = $db->prepare(
        "SELECT id, entity, nomenclature, object_type, description, ficha_url,
                match_score, match_level, ai_summary, pdf_local_path,
                reviewed, bid_decision, review_notes, scraped_at
         FROM leads WHERE job_id=? ORDER BY match_score DESC, id DESC LIMIT 500"
    );
    $stmt->execute([$job_id]);
    _ok($stmt->fetchAll());
}

function _lead_detail(PDO $db): void {
    $u  = _auth();
    $id = (int)($_GET['id'] ?? 0);
    if (!$id) _fail(400, 'id required');

    $stmt = $db->prepare("SELECT * FROM leads WHERE id=?");
    $stmt->execute([$id]);
    $lead = $stmt->fetch();
    if (!$lead) _fail(404, 'Lead not found');

    // Decode JSON fields
    foreach (['key_requirements_json','disqualifiers_json','cronograma_json'] as $f) {
        $short = str_replace('_json', '', $f);
        $lead[$short] = json_decode($lead[$f] ?? '[]', true);
        unset($lead[$f]);
    }
    $lead['reviewed'] = (bool)$lead['reviewed'];
    _ok($lead);
}

function _review_lead(PDO $db, array $body): void {
    _auth();
    $id       = (int)($body['id'] ?? 0);
    $reviewed = !empty($body['reviewed']);
    $notes    = trim($body['review_notes'] ?? '');
    $decision = trim($body['bid_decision'] ?? '');
    if (!$id) _fail(400, 'id required');

    $db->prepare(
        "UPDATE leads SET reviewed=?,review_notes=?,bid_decision=? WHERE id=?"
    )->execute([$reviewed?1:0, $notes, $decision, $id]);
    _ok();
}

function _clear_leads(PDO $db, array $body): void {
    $u      = _auth();
    $job_id = (int)($body['job_id'] ?? 0);
    if (!$job_id) _fail(400, 'job_id required');

    // Only job owner or admin can clear
    $stmt = $db->prepare("SELECT user_id FROM scrape_jobs WHERE id=?");
    $stmt->execute([$job_id]);
    $row = $stmt->fetch();
    if (!$row) _fail(404, 'Job not found');
    if (!$u['is_admin'] && $row['user_id'] != $u['user_id']) _fail(403, 'Forbidden');

    $db->prepare("DELETE FROM leads WHERE job_id=?")->execute([$job_id]);
    _ok();
}


// ═══════════════════════════════════════════════════════════════════════════════
// Users (admin only)
// ═══════════════════════════════════════════════════════════════════════════════

function _list_users(PDO $db): void {
    _admin();
    $rows = $db->query(
        "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
    )->fetchAll();
    foreach ($rows as &$r) $r['is_admin'] = (bool)$r['is_admin'];
    _ok($rows);
}

function _create_user(PDO $db, array $body): void {
    _admin();
    $username = trim($body['username'] ?? '');
    $password = $body['password'] ?? '';
    $is_admin = !empty($body['is_admin']);
    if (!$username || !$password) _fail(400, 'username and password required');
    if (strlen($password) < 6) _fail(400, 'Password must be at least 6 characters');

    $hash = password_hash($password, PASSWORD_BCRYPT);
    try {
        $db->prepare(
            "INSERT INTO users (username, password_hash, is_admin, created_at)
             VALUES (?, ?, ?, datetime('now'))"
        )->execute([$username, $hash, $is_admin ? 1 : 0]);
    } catch (Exception $e) {
        _fail(409, 'Username already exists');
    }
    _ok(['id' => (int)$db->lastInsertId()]);
}

function _delete_user(PDO $db, array $body): void {
    $me = _admin();
    $uid = (int)($body['user_id'] ?? 0);
    if (!$uid) _fail(400, 'user_id required');
    if ($uid === $me['user_id']) _fail(400, 'Cannot delete your own account');

    $db->prepare("DELETE FROM user_sessions WHERE user_id=?")->execute([$uid]);
    $db->prepare("DELETE FROM users WHERE id=?")->execute([$uid]);
    _ok();
}


// ═══════════════════════════════════════════════════════════════════════════════
// Settings (per user)
// ═══════════════════════════════════════════════════════════════════════════════

function _settings(PDO $db): void {
    $u = _auth();
    // Default keywords from global setting
    $kw = _get_setting($db, 'keywords', '[]');
    // User override
    $kw_u = _get_setting($db, 'u' . $u['user_id'] . '.keywords', null);
    _ok([
        'keywords'        => json_decode($kw_u ?? $kw, true),
        'spec_start_page' => (int)_get_setting($db, 'spec_start_page', '20'),
        'spec_end_page'   => (int)_get_setting($db, 'spec_end_page', '30'),
        'max_pages'       => (int)_get_setting($db, 'max_pages', '0'),
    ]);
}

function _save_settings(PDO $db, array $body): void {
    $u = _auth();
    // Keywords are saved per-user
    if (isset($body['keywords'])) {
        $kw = is_array($body['keywords'])
            ? $body['keywords']
            : preg_split('/[\r\n,]+/', $body['keywords']);
        $kw = array_values(array_filter(array_map('trim', $kw)));
        _upsert_setting($db, 'u' . $u['user_id'] . '.keywords',
                        json_encode($kw, JSON_UNESCAPED_UNICODE));
    }
    // Global settings (admin only)
    if ($u['is_admin']) {
        foreach (['spec_start_page','spec_end_page','max_pages'] as $k) {
            if (isset($body[$k])) {
                _upsert_setting($db, $k, json_encode((int)$body[$k]));
            }
        }
    }
    _ok();
}


// ═══════════════════════════════════════════════════════════════════════════════
// DB utilities
// ═══════════════════════════════════════════════════════════════════════════════

function _get_setting(PDO $db, string $key, ?string $default): ?string {
    $stmt = $db->prepare("SELECT value FROM app_settings WHERE key=?");
    $stmt->execute([$key]);
    $row = $stmt->fetch();
    return $row ? $row['value'] : $default;
}

function _upsert_setting(PDO $db, string $key, string $value): void {
    $db->prepare(
        "INSERT INTO app_settings(key,value,updated_at)
         VALUES(?,?,datetime('now'))
         ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
    )->execute([$key, $value]);
}

function _fmt_date(string $ymd): string {
    // Convert YYYY-MM-DD → DD/MM/YYYY (SEACE format).  Pass-through other formats.
    if (preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $ymd, $m)) {
        return "{$m[3]}/{$m[2]}/{$m[1]}";
    }
    return $ymd;
}

function _ensure_tables(PDO $db): void {
    // Ensure the tables the PHP side needs exist (Python's init_db() normally creates them)
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

    // Seed default admin if no users exist
    $cnt = $db->query("SELECT COUNT(*) FROM users")->fetchColumn();
    if ($cnt == 0) {
        $hash = password_hash('admin1234', PASSWORD_BCRYPT);
        $db->prepare(
            "INSERT INTO users (username, password_hash, is_admin) VALUES ('admin',?,1)"
        )->execute([$hash]);
    }

    // Seed default keywords if none set
    $kw = $db->query("SELECT value FROM app_settings WHERE key='keywords'")->fetchColumn();
    if (!$kw) {
        $defaults = json_encode([
            "DATALOGGER","MACROMEDIDOR","MEDIDOR DE FLUJO","CAUDALIMETRO ULTRASONICO",
            "MEDIDOR DE NIVEL","TRANSMISOR DE FLUJO","GEOFONO","CORRELADOR",
            "SENSOR DE PRESION","TRANSMISOR DE PRESION","CALIBRADOR DE PRESION",
            "MULTICALIBRADOR DE PRESION","CAMARA DE INSPECCION","INDICADOR DE PRESION",
            "LOCALIZADOR DE AVERIAS","LOCALIZADOR DE CABLES","MANOMETRO",
            "TRANSDUCTOR DE PRESION","MANIFOLD","DETECTOR DE FUGA","LOCALIZADOR DE FUGA",
            "DETECTOR DE METALES","GEORADAR","MULTIPARAMETRO","MEDIDOR DE CLORO",
            "DETECTOR DE GAS","EXPLOSIMETRO","DETECTOR MULTIGAS","CABINA DE FLUJO",
            "CABINA DE BIOSEGURIDAD","MANTENIMIENTO DE MACROMEDIDORES",
            "CALIBRACION DE MEDIDORES","CONTROL DE SECTORES IMPLEMENTADOS",
            "CALIBRACION","INSTALACION DE MACROMEDIDORES","DETECCION DE FUGAS","MANTENIMIENTO"
        ], JSON_UNESCAPED_UNICODE);
        $db->prepare("INSERT INTO app_settings(key,value) VALUES('keywords',?)")->execute([$defaults]);
    }
}
