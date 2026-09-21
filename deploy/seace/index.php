<?php
/**
 * SEACE Dashboard — PHP Reverse Proxy
 *
 * Forwards all HTTP requests from Apache → FastAPI backend (127.0.0.1:8765).
 * Lives at:  public_html/seace/index.php
 *
 * The Python backend must be running:
 *   python main.py dashboard --host 127.0.0.1 --port 8765
 *
 * This file also injects window._BASE='/seace' into HTML responses so the
 * dashboard JavaScript prepends the subdirectory prefix to every API call.
 */

define('BACKEND',     'http://127.0.0.1:8765');
define('MOUNT_PATH',  '/seace');          // the subdirectory this proxy lives in
define('TIMEOUT_SEC', 120);               // long enough for the scraper log polling

// ── Build target URL ─────────────────────────────────────────────────────────

$uri = $_SERVER['REQUEST_URI'] ?? '/';

// Strip query string — curl handles it separately
$qs_pos = strpos($uri, '?');
$path   = ($qs_pos !== false) ? substr($uri, 0, $qs_pos) : $uri;
$qs     = ($qs_pos !== false) ? substr($uri, $qs_pos)     : '';

// Remove the mount prefix so FastAPI sees clean paths (/api/..., /, etc.)
if (MOUNT_PATH !== '' && strpos($path, MOUNT_PATH) === 0) {
    $path = substr($path, strlen(MOUNT_PATH));
}
if ($path === '' || $path === false) $path = '/';

$target = BACKEND . $path . $qs;

// ── Set up cURL ───────────────────────────────────────────────────────────────

if (!function_exists('curl_init')) {
    http_response_code(503);
    echo 'Error: PHP cURL extension is not enabled on this server.';
    exit;
}

$ch = curl_init();
curl_setopt($ch, CURLOPT_URL,            $target);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);  // don't auto-follow redirects
curl_setopt($ch, CURLOPT_HEADER,         true);   // include response headers in output
curl_setopt($ch, CURLOPT_TIMEOUT,        TIMEOUT_SEC);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);

// ── Method & body ─────────────────────────────────────────────────────────────

$method = strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);

if (in_array($method, ['POST', 'PUT', 'PATCH', 'DELETE'])) {
    $body = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
}

// ── Forward request headers ───────────────────────────────────────────────────

$fwd_headers = [];
$raw_headers = function_exists('getallheaders') ? getallheaders() : [];
foreach ($raw_headers as $name => $value) {
    $lower = strtolower($name);
    // Drop headers that cURL or the backend should not receive
    if (in_array($lower, ['host', 'connection', 'transfer-encoding'])) continue;
    $fwd_headers[] = "$name: $value";
}
curl_setopt($ch, CURLOPT_HTTPHEADER, $fwd_headers);

// ── Execute ───────────────────────────────────────────────────────────────────

$raw_response = curl_exec($ch);

if ($raw_response === false) {
    $err = curl_error($ch);
    curl_close($ch);
    http_response_code(502);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!DOCTYPE html><html><body>';
    echo '<h2>SEACE Dashboard — Backend Not Available</h2>';
    echo '<p>No se pudo conectar con el servidor Python en <code>' . htmlspecialchars(BACKEND) . '</code>.</p>';
    echo '<p>Asegurate de que el proceso Python este en ejecucion:</p>';
    echo '<pre>cd ~/seace-scraper && source .venv/bin/activate
python main.py dashboard --host 127.0.0.1 --port 8765</pre>';
    echo '<p>Error: ' . htmlspecialchars($err) . '</p>';
    echo '</body></html>';
    exit;
}

$http_code   = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
$header_size = (int) curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$content_type = curl_getinfo($ch, CURLINFO_CONTENT_TYPE) ?: '';
curl_close($ch);

// ── Split response headers / body ─────────────────────────────────────────────

$raw_hdrs = substr($raw_response, 0, $header_size);
$body     = substr($raw_response, $header_size);

// ── Set response code ─────────────────────────────────────────────────────────

http_response_code($http_code);

// ── Forward response headers ──────────────────────────────────────────────────

foreach (explode("\r\n", $raw_hdrs) as $line) {
    $line = trim($line);
    if (empty($line) || strncmp($line, 'HTTP/', 5) === 0) continue;
    $lower_line = strtolower($line);
    // Skip hop-by-hop headers that PHP/Apache manage
    if (strncmp($lower_line, 'transfer-encoding:', 18) === 0) continue;
    if (strncmp($lower_line, 'connection:', 11) === 0) continue;
    header($line, false);
}

// ── Inject base-path variable into HTML responses ─────────────────────────────
// The dashboard JS reads window._BASE to prepend the mount path to every
// API fetch call, so /api/leads becomes /seace/api/leads etc.

if (MOUNT_PATH !== '' && stripos($content_type, 'text/html') !== false) {
    $inject = '<script>window._BASE=' . json_encode(MOUNT_PATH) . ';</script>';
    // Insert just before </head> (case-insensitive)
    $body = preg_replace('/<\/head>/i', $inject . '</head>', $body, 1);
}

echo $body;
