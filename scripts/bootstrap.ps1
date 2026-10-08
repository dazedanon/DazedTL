# Starts DazedTL on Windows for START.bat. The first run downloads the pinned
# Node into .runtime; the launcher then installs everything else.
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
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
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
