<?php
/**
 * Private Browser Engine Repository API
 * Scans 'apps/' folder and returns JSON list with download URLs.
 */
header('Content-Type: application/json');

$appsDir = "apps";
$versions = [];

if (is_dir($appsDir)) {
    $dirs = scandir($appsDir);
    foreach ($dirs as $dir) {
        if ($dir === '.' || $dir === '..') continue;
        
        $versionPath = $appsDir . DIRECTORY_SEPARATOR . $dir;
        $jsonPath = $versionPath . DIRECTORY_SEPARATOR . 'browser_versions.json';
        $zipName = "bas_$dir.zip";
        $zipPath = $versionPath . DIRECTORY_SEPARATOR . $zipName;
        
        if (is_dir($versionPath)) {
            $data = [];
            if (file_exists($jsonPath)) {
                $data = json_decode(file_get_contents($jsonPath), true);
            } else {
                // Mock if missing (using folder name as BAS version)
                $data = [[
                    "browser_version" => "Unknown", 
                    "bas_version" => $dir,
                    "architecture" => "x64"
                ]];
            }

            foreach ($data as $v) {
                // Only list if the ZIP actually exists on server
                if (file_exists($zipPath)) {
                    $protocol = isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] === 'on' ? "https" : "http";
                    $host = $_SERVER['HTTP_HOST'];
                    $dirUrl = rtrim(dirname($_SERVER['PHP_SELF']), '/\\');
                    
                    $v['download_url'] = "$protocol://$host$dirUrl/apps/$dir/$zipName";
                    $v['is_private'] = true;
                    $versions[] = $v;
                }
            }
        }
    }
}

// Order: Latest first
usort($versions, function ($a, $b) {
    return version_compare($b['bas_version'], $a['bas_version']);
});

echo json_encode([
    'success' => true,
    'count' => count($versions),
    'versions' => $versions
], JSON_PRETTY_PRINT);
