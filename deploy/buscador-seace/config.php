<?php
/**
 * SEACE Dashboard — Server Configuration
 *
 * Edit these paths to match your cPanel account.
 * This file is included by api.php and must NOT be publicly accessible.
 */

// ── Server paths ─────────────────────────────────────────────────────────────
// cPanel home directory (no trailing slash)
define('HOME_DIR',      '/home/YOUR_CPANEL_USER');

// Full path to the seace-scraper project directory
define('PROJECT_DIR',   HOME_DIR . '/seace-scraper');

// Python interpreter inside the virtualenv
define('PYTHON_BIN',    PROJECT_DIR . '/.venv/bin/python');

// The worker script that runs one scrape job
define('WORKER_SCRIPT', PROJECT_DIR . '/worker.py');

// SQLite database file
define('DB_PATH',       PROJECT_DIR . '/seace_leads.db');

// Directory where worker logs are written
define('LOG_DIR',       PROJECT_DIR . '/logs');

// ── App settings ──────────────────────────────────────────────────────────────
// Session name (keep unique to avoid conflicts with WordPress)
define('SESSION_NAME', 'seace_sess');

// Session lifetime in seconds (default 7 days)
define('SESSION_TTL', 7 * 24 * 3600);

// URL path of this dashboard (for cookie path)
define('MOUNT_PATH', '/buscador-seace');
