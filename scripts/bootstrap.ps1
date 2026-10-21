# Starts DazedTL on Windows for START.bat. The first run downloads the pinned
# Node into .runtime; the launcher then installs everything else.
# START.bat is a single line, because cmd reads a batch file as it runs and an
# update's swap replaces it. That line ends with this script's result as an
# explicit exit code, since a bare `exit /b` would report success to `cmd /c`
# callers such as the live test.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = Split-Path -Parent $PSScriptRoot

function Fail($message) {
  Write-Host ''
  Write-Host "DazedTL could not start: $message" -ForegroundColor Red
  Read-Host 'Press Enter to close' | Out-Null
  exit 1
}

try {
  $version = (Get-Content -Raw (Join-Path $root '.node-version')).Trim()
  # Windows on Arm runs the x64 Node, matching the other x64 runtimes.
  $name = "node-v$version-win-x64"
  $runtime = Join-Path $root '.runtime'
  $node = Join-Path $runtime "$name\node.exe"
  if (-not (Test-Path $node)) {
    $line = Get-Content (Join-Path $root 'scripts\runtimes.lock') |
      Where-Object { $_.TrimEnd().EndsWith("/$name.zip") } | Select-Object -First 1
    if (-not $line) { Fail "there is no pinned Node for Windows." }
    $hash, $url = -split $line
    New-Item -ItemType Directory -Force $runtime | Out-Null
    $archive = Join-Path $runtime "$name.zip"
    Write-Host "Downloading Node $version..."
    # Up to three tries, as START.sh's curl --retry: a lost connection or a
    # busy server is tried again, a missing file fails at once.
    for ($try = 1; ; $try++) {
      try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
        break
      } catch {
        $status = [int]$_.Exception.Response.StatusCode
        if ($status -and $status -ne 408 -and $status -ne 429 -and $status -lt 500) { throw }
        $reason = $_.Exception.Message
        if ($try -ge 3) { throw "Node could not be downloaded ($reason) Check the internet connection, then start DazedTL again." }
        Write-Host "The Node download failed ($reason) Trying again..."
        Start-Sleep -Seconds (2 * $try)
      }
    }
    # .NET instead of Get-FileHash and Expand-Archive: started from a
    # PowerShell 7 terminal, Windows PowerShell inherits a module path whose
    # modules it cannot load.
    $sha256 = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($archive)
    try { $actual = ([BitConverter]::ToString($sha256.ComputeHash($stream)) -replace '-').ToLowerInvariant() }
    finally { $stream.Dispose() }
    if ($actual -ne $hash) {
      Remove-Item -Force $archive
      Fail 'the Node download did not match its pinned checksum. Try again.'
    }
    $staging = Join-Path $runtime "$name.partial"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    New-Item -ItemType Directory $staging | Out-Null
    # tar.exe ships with Windows 10 1803 and later and unpacks far faster.
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) { & $tar.Source -xf $archive -C $staging }
    if (-not $tar -or $LASTEXITCODE -ne 0) {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      [IO.Compression.ZipFile]::ExtractToDirectory($archive, $staging)
    }
    Move-Item (Join-Path $staging $name) (Join-Path $runtime $name)
    Remove-Item -Recurse -Force $staging, $archive
  }
} catch {
  Fail $_.Exception.Message
}

& $node (Join-Path $root 'scripts\start.mjs') --detach @args
if ($LASTEXITCODE -ne 0) {
  Read-Host 'Press Enter to close' | Out-Null
  exit $LASTEXITCODE
}
