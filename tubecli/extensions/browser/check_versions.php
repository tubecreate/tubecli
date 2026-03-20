<?php
/**
 * Browser Engine Version Check API v2
 * ====================================
 * 1. Returns known BAS/Chromium versions with Bablosoft download URLs (primary)
 * 2. Scans local 'apps/' folder for self-hosted mirrors (secondary/fallback)
 * 3. Optionally checks Bablosoft URL availability (?check=1)
 *
 * Params:
 *   ?latest=1       — Only return the single latest version
 *   ?bas_version=X  — Filter by specific BAS version
 *   ?check=1        — Also verify bablosoft URLs (slower, uses HEAD requests)
 */
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');

// =====================================================================
// CONFIG: Known BAS versions and their Chromium browser versions
// Updated: 2026-03-20
// Add new entries here as Bablosoft releases new versions.
// =====================================================================
$KNOWN_VERSIONS = [
    ['bas_version' => '29.8.1', 'browser_version' => '145.0.7632.46', 'architecture' => 'x64'],
    ['bas_version' => '29.8.0', 'browser_version' => '145.0.7632.46', 'architecture' => 'x64'],
    ['bas_version' => '29.7.0', 'browser_version' => '144.0.7559.60', 'architecture' => 'x64'],
    ['bas_version' => '29.6.1', 'browser_version' => '143.0.7499.41', 'architecture' => 'x64'],
    ['bas_version' => '29.6.0', 'browser_version' => '143.0.7499.41', 'architecture' => 'x64'],
    ['bas_version' => '29.5.0', 'browser_version' => '142.0.7444.60', 'architecture' => 'x64'],
    ['bas_version' => '29.4.1', 'browser_version' => '141.0.7390.55', 'architecture' => 'x64'],
];

// Bablosoft download URL pattern
function bablosoftUrl($basVersion) {
    return "http://downloads.bablosoft.com/distr/FastExecuteScript64/{$basVersion}/FastExecuteScript.x64.zip";
}

// Check if a remote URL is reachable (HEAD request) — only used with ?check=1
function checkUrlExists($url, $timeoutSec = 3) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_NOBODY         => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT        => $timeoutSec,
        CURLOPT_CONNECTTIMEOUT => $timeoutSec,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_SSL_VERIFYPEER => false,
    ]);
    curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $fileSize = curl_getinfo($ch, CURLINFO_CONTENT_LENGTH_DOWNLOAD);
    curl_close($ch);
    return [
        'exists'    => ($httpCode >= 200 && $httpCode < 400),
        'http_code' => $httpCode,
        'file_size' => ($fileSize > 0) ? $fileSize : null,
    ];
}

// =====================================================================
// Build versions list
// =====================================================================
$versions = [];
$appsDir  = "apps";
$doCheck  = isset($_GET['check']) && $_GET['check'];

// Server base URL for local downloads
$protocol = isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] === 'on' ? "https" : "http";
$host     = $_SERVER['HTTP_HOST'];
$dirUrl   = rtrim(dirname($_SERVER['PHP_SELF']), '/\\');

// 1. Known versions
foreach ($KNOWN_VERSIONS as $kv) {
    $basVer = $kv['bas_version'];
    $bUrl   = bablosoftUrl($basVer);

    $entry = $kv;
    $entry['download_url']  = $bUrl;          // Primary = Bablosoft
    $entry['source']        = 'bablosoft';
    $entry['bablosoft_url'] = $bUrl;

    // Check local apps/ folder
    $localZipName = "bas_{$basVer}.zip";
    $localZipPath = $appsDir . DIRECTORY_SEPARATOR . $basVer . DIRECTORY_SEPARATOR . $localZipName;

    if (file_exists($localZipPath)) {
        $entry['local_url']       = "$protocol://$host$dirUrl/apps/$basVer/$localZipName";
        $entry['available_local'] = true;
    } else {
        $entry['local_url']       = null;
        $entry['available_local'] = false;
    }

    // Only verify bablosoft URL if ?check=1 is passed
    if ($doCheck) {
        $check = checkUrlExists($bUrl);
        $entry['bablosoft_available'] = $check['exists'];
        if ($check['file_size']) {
            $entry['file_size_bytes'] = (int)$check['file_size'];
            $entry['file_size_mb']    = round($check['file_size'] / 1048576, 1);
        }
        // Fallback to local if bablosoft is down
        if (!$check['exists'] && $entry['available_local']) {
            $entry['download_url'] = $entry['local_url'];
            $entry['source']       = 'local';
        }
    }

    $versions[] = $entry;
}

// 2. Scan apps/ for extra versions not in known list
if (is_dir($appsDir)) {
    $knownBasVersions = array_column($KNOWN_VERSIONS, 'bas_version');

    foreach (scandir($appsDir) as $dir) {
        if ($dir === '.' || $dir === '..' || in_array($dir, $knownBasVersions)) continue;

        $versionPath = $appsDir . DIRECTORY_SEPARATOR . $dir;
        $jsonPath    = $versionPath . DIRECTORY_SEPARATOR . 'browser_versions.json';
        $zipName     = "bas_{$dir}.zip";
        $zipPath     = $versionPath . DIRECTORY_SEPARATOR . $zipName;

        if (is_dir($versionPath) && file_exists($zipPath)) {
            $browserVersion = 'Unknown';
            if (file_exists($jsonPath)) {
                $jsonData = json_decode(file_get_contents($jsonPath), true);
                if (is_array($jsonData) && !empty($jsonData)) {
                    $browserVersion = $jsonData[0]['browser_version'] ?? 'Unknown';
                }
            }

            $bUrl = bablosoftUrl($dir);
            $versions[] = [
                'bas_version'     => $dir,
                'browser_version' => $browserVersion,
                'architecture'    => 'x64',
                'download_url'    => $bUrl,
                'source'          => 'bablosoft',
                'bablosoft_url'   => $bUrl,
                'local_url'       => "$protocol://$host$dirUrl/apps/$dir/$zipName",
                'available_local' => true,
            ];
        }
    }
}

// 3. Sort by BAS version (latest first)
usort($versions, function ($a, $b) {
    return version_compare($b['bas_version'], $a['bas_version']);
});

// 4. Filter by query params
$latest          = isset($_GET['latest']) && $_GET['latest'];
$specificVersion = $_GET['bas_version'] ?? null;

if ($specificVersion) {
    $versions = array_values(array_filter($versions, function ($v) use ($specificVersion) {
        return $v['bas_version'] === $specificVersion;
    }));
}

$latestEntry = !empty($versions) ? $versions[0] : null;

// 5. Output
$output = [
    'success'    => true,
    'count'      => count($versions),
    'latest'     => $latestEntry,
    'updated_at' => date('Y-m-d H:i:s'),
    'versions'   => $latest ? ($latestEntry ? [$latestEntry] : []) : $versions,
];

echo json_encode($output, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
