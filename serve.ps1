# ---------------------------------------------------------------------------
# Drought Intelligence Explorer - local file server
#
# Browsers block data loading over file:// (CORS), so the app must be served
# over http. This script uses only built-in Windows components - nothing to
# install. It picks the first free port in 8471-8480, serves the folder it
# lives in, and opens the app in the default browser.
#
# Usage (normally started by "Start Drought Explorer.bat"):
#   powershell -NoProfile -ExecutionPolicy Bypass -File serve.ps1 [-NoOpen]
# ---------------------------------------------------------------------------

param(
  # Skip opening the browser (used for automated tests).
  [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Pick the first free port. An instance that is already running wins.
$port = $null
foreach ($p in 8471..8480) {
  $probe = New-Object System.Net.HttpListener
  $probe.Prefixes.Add("http://localhost:$p/")
  try { $probe.Start(); $probe.Stop(); $port = $p; break } catch { }
}
if (-not $port) {
  Write-Host ""
  Write-Host "  ERROR: no free port in 8471-8480." -ForegroundColor Red
  Write-Host "  Close other copies of the Drought Explorer server and try again."
  exit 1
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")
$listener.Start()

Write-Host ""
Write-Host "  Drought Intelligence Explorer is running:" -ForegroundColor Green
Write-Host "  http://localhost:$port" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Keep this window open while using the app."
Write-Host "  Closing this window (or pressing Ctrl+C) stops the app."
Write-Host ""

if (-not $NoOpen) { Start-Process "http://localhost:$port/index.html" }

$types = @{
  '.html' = 'text/html; charset=utf-8'
  '.js'   = 'text/javascript; charset=utf-8'
  '.mjs'  = 'text/javascript; charset=utf-8'
  '.css'  = 'text/css; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.map'  = 'application/json'
  '.csv'  = 'text/csv; charset=utf-8'
  '.md'   = 'text/markdown; charset=utf-8'
  '.png'  = 'image/png'
  '.jpg'  = 'image/jpeg'
  '.jpeg' = 'image/jpeg'
  '.webp' = 'image/webp'
  '.svg'  = 'image/svg+xml'
  '.ico'  = 'image/x-icon'
  '.woff'  = 'font/woff'
  '.woff2' = 'font/woff2'
}

# Only serve files inside the app folder (no directory traversal).
$rootPrefix = $root.TrimEnd('\') + '\'

while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  try {
    $rel = [Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath).TrimStart('/')
    if ($rel -eq '') { $rel = 'index.html' }
    $file = Join-Path $root $rel
    if ((Test-Path $file -PathType Leaf) -and
        ((Resolve-Path $file).Path.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
      $ext = [System.IO.Path]::GetExtension($file).ToLowerInvariant()
      $mime = if ($types.ContainsKey($ext)) { $types[$ext] } else { 'application/octet-stream' }
      $bytes = [System.IO.File]::ReadAllBytes($file)
      $ctx.Response.ContentType = $mime
      $ctx.Response.ContentLength64 = $bytes.Length
      $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    } else {
      $ctx.Response.StatusCode = 404
      $msg = [System.Text.Encoding]::UTF8.GetBytes('404 - not found: ' + $rel)
      $ctx.Response.OutputStream.Write($msg, 0, $msg.Length)
    }
  } catch {
    try { $ctx.Response.StatusCode = 500 } catch { }
  } finally {
    try { $ctx.Response.OutputStream.Close() } catch { }
  }
}
