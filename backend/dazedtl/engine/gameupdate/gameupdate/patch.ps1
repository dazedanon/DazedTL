#Requires -Version 5.1
param(
    [Parameter(Mandatory = $false)]
    [string]$GameRoot
)

$ErrorActionPreference = 'Stop'

if (-not $PSBoundParameters.ContainsKey('GameRoot') -or [string]::IsNullOrWhiteSpace($GameRoot)) {
    $GameRoot = (Get-Location).ProviderPath
}
else {
    $GameRoot = (Resolve-Path -LiteralPath $GameRoot).ProviderPath
}

$PatchBundleRoot = $PSScriptRoot

# Git for Windows' portable MinGit, the version DazedTL installs for itself,
# for players without Git when the forge's API refuses GameUpdate. Written by
# scripts/runtimes.mjs from scripts/mingit-version; the script carries the pin
# itself, so it works wherever a patch puts it.
$MinGitUrl = 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.2/MinGit-2.56.0.2-64-bit.zip'
$MinGitSha256 = 'da35e72aa21c005a5a0d298cfbae110bc1609a815730ea0dde84b01a1b3cd3be'

function Wait-ConsolePause {
    # Nobody can press a key for a run whose input is redirected, such as an
    # automated one; ReadKey would wait on the console forever.
    if ([Console]::IsInputRedirected) {
        return
    }
    Write-Host ''
    Write-Host 'Press any key to close this window...'
    try {
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
    catch {
        Read-Host 'Press Enter to close'
    }
}

function Get-DazedPatcherBannerGlyphs {
    return @{
        'A' = @('        ', '  AAA   ', ' A   A  ', ' AAAAA  ', ' A   A  ', ' A   A  ', '        ')
        'C' = @('        ', '  CCCC  ', ' C      ', ' C      ', ' C      ', '  CCCC  ', '        ')
        'D' = @('        ', ' DDDDD  ', ' D    D ', ' D    D ', ' D    D ', ' DDDDD  ', '        ')
        'E' = @('        ', ' EEEEE  ', ' E      ', ' EEE    ', ' E      ', ' EEEEE  ', '        ')
        'H' = @('        ', ' H   H  ', ' H   H  ', ' HHHHH  ', ' H   H  ', ' H   H  ', '        ')
        'P' = @('        ', ' PPPPP  ', ' P   P  ', ' PPPP   ', ' P      ', ' P      ', '        ')
        'R' = @('        ', ' RRRRR  ', ' R   R  ', ' RRRR   ', ' R  R   ', ' R   R  ', '        ')
        'T' = @('        ', ' TTTTT  ', '   T    ', '   T    ', '   T    ', '   T    ', '        ')
        'Z' = @('        ', ' ZZZZZ  ', '    Z   ', '   Z    ', '  Z     ', ' ZZZZZ  ', '        ')
    }
}

function Build-AsciiWordLines {
    param(
        [Parameter(Mandatory = $true)][string]$Word,
        [hashtable]$Glyphs
    )
    $letters = @(
        $Word.ToUpperInvariant().ToCharArray() | ForEach-Object { [string]$_ }
    )
    $rows = New-Object string[] 7
    for ($r = 0; $r -lt 7; $r++) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($letter in $letters) {
            if (-not $Glyphs.ContainsKey($letter)) {
                throw "Banner glyph missing for '$letter'."
            }
            $parts.Add($Glyphs[$letter][$r])
        }
        $rows[$r] = ($parts -join ' ')
    }
    return [string[]]$rows
}

function ConvertTo-LineStringArray {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return @() }
    if ($Value -is [string[]]) { return $Value }
    if ($Value -is [System.Collections.Generic.List[string]]) { return $Value.ToArray() }
    if ($Value -is [string]) {
        if ([string]::IsNullOrWhiteSpace([string]$Value)) { return @() }
        return ,[string]$Value
    }
    return [string[]](@($Value) | ForEach-Object { if ($null -eq $_) { '' } else { "$_" } })
}

function Pad-LineBlockToHeight {
    param(
        [Parameter(Mandatory = $true, Position = 0)][object]$Rows,
        [Parameter(Mandatory = $true, Position = 1)][int]$TargetHeight
    )
    [string[]]$lines = ConvertTo-LineStringArray -Value $Rows
    if ($lines.Count -eq 0 -and $TargetHeight -gt 0) {
        $blank = New-Object string[] $TargetHeight
        for ($i = 0; $i -lt $TargetHeight; $i++) { $blank[$i] = '' }
        return $blank
    }
    if ($lines.Count -ge $TargetHeight) {
        return [string[]]$lines
    }
    $padTotal = $TargetHeight - $lines.Count
    $padTop = [int][Math]::Floor($padTotal / 2)
    $padBot = $padTotal - $padTop
    $top = @()
    for ($i = 0; $i -lt $padTop; $i++) { $top += '' }
    $bot = @()
    for ($i = 0; $i -lt $padBot; $i++) { $bot += '' }
    return [string[]]($top + $lines + $bot)
}

function Get-EmbeddedIconAsciiCatLines {
    # Refresh via generate_icon_ascii.ps1 when assets/icon.png changes.
    $raw = @'
       #            %#
     %:.-@         #..=
   #:.-*:.:#     *..=*..-%
    *=.:.+#  %%  @*-:::+#
      *-#   +...=#  =-%
    %      #..==..:#                  %@
  %..*     -.:%%#=..=##*##%%     %*=:...+
*:.=+.:=   ..=%##%*:..::.....:=+:..-=*:.:
*=:--.=*   ..=%###%########*+=:.-+#%%%:.-
   -:%    #..=%###%%%%%###%%%%%#%%%#%*..+
         %..=%##-.=*=-*%#####%%%%%#%#:.:
         +.:###%+....:*%###:.=*=-*%%-..%
         -.:%#%+..:..=%####=....-#%%+..%
         *..*%##**%*-=###%=..:..=%#%*..#
          =..*%%%%#%%%#####*#%*-+%%%-..
           +..-*#%%%%######%%#%%%%*:..#
            %+...-+*##%%%%%%%%#*+-..=%
             %..:.....::---::....:*%
             :.:%%#*+=--::::-=+:.:*
            %..+%#%%%%%%%%%%%%%%+..-@    #-:::+@
            #..+%###############%#:.:%  #..=*:..#
             ..=%################%#:..% %..+%%-..@
            %..:%###%#%##%%#%#####%#:.-  *..*%*..+
           #....*%##-.+%%#:.+%##%#%%*..*  :.-%%:.-
          %..=..-%#%:..#%+..+%#%+::#%:.-  :.-%%:.-
          -.:%=..*%%*..+%:.:%#%#..:#%=.. #..+%*..+
          ..=%#..:%%#..-#..=%#%-..*%%=..*:.-%%-..@
          -.-%%+..+%%-.:+..+%%+..+%#%-....=%%-..#
          +..*%*..:%%=..=..*%%:..*%%#...=#%+:.:#
          ..-**..:+**=..:..+**+:..**+..=*=:..+
          +..............................:=#
            %%%%%%%%%%%%%%%%%%%%%%%%%%%%@
'@
    return [string[]]@($raw -split '\r?\n')
}

function Write-AsciiHeader {
    try {
        Write-Host ''
        $glyphs = Get-DazedPatcherBannerGlyphs
        $wordDazed = Build-AsciiWordLines -Word 'Dazed' -Glyphs $glyphs
        $wordPatcher = Build-AsciiWordLines -Word 'Patcher' -Glyphs $glyphs
        $titleCore = [System.Collections.Generic.List[string]]::new()
        foreach ($ln in $wordDazed) { $titleCore.Add($ln) }
        [void]$titleCore.Add('')
        foreach ($ln in $wordPatcher) { $titleCore.Add($ln) }
        $titleRows = $titleCore.ToArray()

        $catLines = @(Get-EmbeddedIconAsciiCatLines)

        $targetH = [Math]::Max($titleRows.Count, $catLines.Count)
        $titlePadded = Pad-LineBlockToHeight -Rows $titleRows -TargetHeight $targetH
        $catPadded = Pad-LineBlockToHeight -Rows $catLines -TargetHeight $targetH

        $titleWidth = 0
        foreach ($ln in $titlePadded) {
            $safe = if ($null -eq $ln) { '' } else { $ln }
            if ($safe.Length -gt $titleWidth) { $titleWidth = $safe.Length }
        }

        $gap = '    '
        for ($i = 0; $i -lt $targetH; $i++) {
            $ti = if ($null -eq $titlePadded[$i]) { '' } else { $titlePadded[$i] }
            $ci = if ($catPadded.Length -le $i -or $null -eq $catPadded[$i]) { '' } else { $catPadded[$i] }
            $left = if ($titleWidth -gt 0) { $ti.PadRight($titleWidth) } else { '' }
            Write-Host ($left + $gap + $ci)
        }
        Write-Host ''
    }
    catch {
        Write-Host ('[Banner skipped] ' + $_.Exception.Message)
    }
}

function Write-BannerWrongFolder {
    Write-Host ''
    Write-Host '========================================'
    Write-Host 'ERROR: Wrong game root folder!'
    Write-Host '========================================'
    Write-Host ''
    Write-Host 'Game root cannot be the gameupdate folder itself.'
    Write-Host 'Run GameUpdate.bat from the game root (same folder as GameUpdate.bat).'
    Write-Host '========================================'
    Write-Host ''
}

function Test-WrongWorkingDirectory {
    param([string]$Root)
    return ($Root -and ((Split-Path -Leaf $Root) -ieq 'gameupdate'))
}

function Read-PatchConfig {
    param([string]$ConfigPath)
    $cfg = @{
        forge    = 'gitlab'
        host     = ''
        username = ''
        repo     = ''
        branch   = ''
    }
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        return $cfg
    }
    foreach ($rawLine in Get-Content -LiteralPath $ConfigPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $k = $line.Substring(0, $eq).Trim().ToLowerInvariant()
        $v = if ($eq -lt $line.Length - 1) { $line.Substring($eq + 1).Trim() } else { '' }
        switch ($k) {
            'forge' { $cfg.forge = $v }
            'provider' { $cfg.forge = $v }
            'host' { $cfg.host = $v }
            'username' { $cfg.username = $v }
            'owner' { $cfg.username = $v }
            'org' { $cfg.username = $v }
            'repo' { $cfg.repo = $v }
            'branch' { $cfg.branch = $v }
        }
    }
    return $cfg
}

function Resolve-PatchForge {
    param([Parameter(Mandatory = $true)][hashtable]$Cfg)

    $raw = ([string]$Cfg.forge).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($raw)) { $raw = 'gitlab' }

    $kind = switch -Regex ($raw) {
        '^(gitlab|gl|gitgud)$' { 'gitlab' }
        '^(github|gh)$' { 'github' }
        '^(forgejo|gitea|fj|codeberg)$' { 'forgejo' }
        default { $null }
    }
    if (-not $kind) {
        throw ("PATCH_ERR:CONFIG:Unknown forge='{0}'. Use gitlab, github, or forgejo." -f $Cfg.forge)
    }

    $hostName = ([string]$Cfg.host).Trim()
    $hostName = $hostName -replace '^https?://', ''
    $hostName = $hostName.TrimEnd('/')
    if ($hostName.Contains('/')) {
        $hostName = $hostName.Split('/')[0]
    }
    if ([string]::IsNullOrWhiteSpace($hostName)) {
        $hostName = switch ($kind) {
            'gitlab' { 'gitgud.io' }
            'github' { 'github.com' }
            'forgejo' { 'codeberg.org' }
        }
    }

    $webBase = "https://$hostName"
    $apiBase = switch ($kind) {
        'gitlab' { "$webBase/api/v4" }
        'github' {
            if ($hostName -eq 'github.com') { 'https://api.github.com' }
            else { "$webBase/api/v3" }
        }
        'forgejo' { "$webBase/api/v1" }
    }

    return @{
        kind     = $kind
        host     = $hostName
        webBase  = $webBase
        apiBase  = $apiBase
        username = ([string]$Cfg.username).Trim()
        repo     = ([string]$Cfg.repo).Trim()
        branch   = ([string]$Cfg.branch).Trim()
    }
}

function New-PatchApiHeaders {
    param([Parameter(Mandatory = $true)][hashtable]$Resolved)
    $headers = @{ 'User-Agent' = 'DazedMTL-Patcher-1.0' }
    if ($Resolved.kind -eq 'gitlab') {
        # GitGud lets an app's request past its Cloudflare challenge when it
        # carries this header, whatever its value; GitLab itself ignores it.
        $headers['X-Gitlab-Token'] = 'dazedtl-gameupdate'
    }
    if ($Resolved.kind -eq 'github') {
        $headers['Accept'] = 'application/vnd.github+json'
    }
    return $headers
}

function Get-PatchLatestSha {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Resolved,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )
    $ownerEnc = [uri]::EscapeDataString($Resolved.username)
    $repoEnc = [uri]::EscapeDataString($Resolved.repo)
    $branchEnc = [uri]::EscapeDataString($Resolved.branch)

    switch ($Resolved.kind) {
        'gitlab' {
            $id = [uri]::EscapeDataString($Resolved.username + '/' + $Resolved.repo)
            $uri = "$($Resolved.apiBase)/projects/$id/repository/branches/$branchEnc"
            return [string](Invoke-RestMethod -Uri $uri -Headers $Headers).commit.id
        }
        'github' {
            $uri = "$($Resolved.apiBase)/repos/$ownerEnc/$repoEnc/commits/$branchEnc"
            return [string](Invoke-RestMethod -Uri $uri -Headers $Headers).sha
        }
        'forgejo' {
            $uri = "$($Resolved.apiBase)/repos/$ownerEnc/$repoEnc/branches/$branchEnc"
            return [string](Invoke-RestMethod -Uri $uri -Headers $Headers).commit.id
        }
    }
}

function Get-PatchArchiveUrl {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Resolved,
        [Parameter(Mandatory = $true)][string]$Sha
    )
    $ownerEnc = [uri]::EscapeDataString($Resolved.username)
    $repoEnc = [uri]::EscapeDataString($Resolved.repo)
    $shaEnc = [uri]::EscapeDataString($Sha)

    switch ($Resolved.kind) {
        'gitlab' {
            $id = [uri]::EscapeDataString($Resolved.username + '/' + $Resolved.repo)
            return "$($Resolved.apiBase)/projects/$id/repository/archive.zip?sha=$shaEnc"
        }
        'github' {
            return "$($Resolved.apiBase)/repos/$ownerEnc/$repoEnc/zipball/$shaEnc"
        }
        'forgejo' {
            return "$($Resolved.apiBase)/repos/$ownerEnc/$repoEnc/archive/$shaEnc.zip"
        }
    }
}

function Get-PatchGitUrl {
    param([Parameter(Mandatory = $true)][hashtable]$Resolved)
    return "$($Resolved.webBase)/$($Resolved.username)/$($Resolved.repo).git"
}

function Invoke-Settled {
    <#
    Runs $Action until it succeeds, for about 30 seconds: antivirus scanners
    briefly lock new files, and a folder being removed stays until its last
    open file closes.
    #>
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [int]$Tries = 300
    )
    for ($attempt = 1; ; $attempt++) {
        try {
            return & $Action
        }
        catch {
            if ($attempt -ge $Tries) { throw }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Remove-SettledItem {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    Invoke-Settled -Action {
        if (Test-Path -LiteralPath $LiteralPath) {
            Remove-Item -LiteralPath $LiteralPath -Recurse -Force -ErrorAction Stop
        }
    }
}

function Remove-StaleGameUpdateTemp {
    <#
    A window closed mid-run leaves its temporary files; a later run removes
    the ones old enough that no other game's GameUpdate can still be using them.
    #>
    param([TimeSpan]$OlderThan = [TimeSpan]::FromHours(12))
    $cutoff = (Get-Date) - $OlderThan
    Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter 'gu_*' -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
        }
}

function New-GameUpdateTempPath {
    param([Parameter(Mandatory = $true)][string]$Kind)
    return Join-Path ([IO.Path]::GetTempPath()) ('gu_' + $Kind + '_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
}

function Enter-GameUpdateLock {
    <#
    Holds gameupdate\gameupdate.lock for the rest of the run, so two
    GameUpdate windows on one game never replace each other's files or Git.
    Windows releases it when the process ends, however it ends.
    #>
    param([Parameter(Mandatory = $true)][string]$BundleRoot)
    try {
        return New-Object System.IO.FileStream(
            (Join-Path $BundleRoot 'gameupdate.lock'),
            [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None,
            1, [IO.FileOptions]::DeleteOnClose)
    }
    catch {
        $cause = $_.Exception
        while ($cause.InnerException) { $cause = $cause.InnerException }
        # 32 and 33: Windows' sharing and lock violations, another run's hold.
        if (($cause.HResult -band 0xFFFF) -in 32, 33) {
            throw 'PATCH_ERR:BUSY:Another GameUpdate is already running for this game. Let it finish, then run GameUpdate again if needed.'
        }
        throw ('PATCH_ERR:FOLDER:GameUpdate can''t write in {0} ({1}). Move the game to a folder you can change, then run GameUpdate again.' -f $BundleRoot, $cause.Message)
    }
}

function Invoke-PatchHttpGet {
    # A GET whose HTTP status is an answer, not an error: 0 when nothing answered.
    param([Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers @{ 'User-Agent' = 'DazedMTL-Patcher-1.0' } -UseBasicParsing -TimeoutSec 60
        return @{ Status = [int]$response.StatusCode; Bytes = $response.RawContentStream.ToArray() }
    }
    catch {
        $response = $_.Exception.Response
        $status = if ($response) { [int]$response.StatusCode } else { 0 }
        return @{ Status = $status; Bytes = $null }
    }
}

function Get-AdvertisedSha {
    <#
    The branch's commit from Git's ref advertisement, a plain GET that needs no
    Git, read as pkt-lines: four hex digits of length, then "<sha> <ref>".
    Throws when the answer is definite (offline, no such public repository or
    branch); returns '' when the forge gave no usable answer, such as a
    challenge page, so Git itself has to ask.
    #>
    param([Parameter(Mandatory = $true)][hashtable]$Resolved)
    $web = "$($Resolved.webBase)/$($Resolved.username)/$($Resolved.repo)"
    $answer = Invoke-PatchHttpGet -Uri ((Get-PatchGitUrl -Resolved $Resolved) + '/info/refs?service=git-upload-pack')
    switch ($answer.Status) {
        0 { throw ('PATCH_ERR:NETWORK:Could not reach {0}. Check your internet connection, then run GameUpdate again.' -f $Resolved.host) }
        { $_ -in 401, 404 } { throw ('PATCH_ERR:REPO:{0} was not found or is not public. GameUpdate needs no account; ask the translator to check the repository.' -f $web) }
        { $_ -ge 500 } { throw ('PATCH_ERR:NETWORK:{0} is having problems (HTTP {1}). Try GameUpdate again later.' -f $Resolved.host, $answer.Status) }
        200 { }
        default { return '' }
    }
    # pkt-line lengths count bytes, so the body is read as latin1 and the
    # branch's name as its UTF-8 bytes.
    $latin1 = [Text.Encoding]::GetEncoding(28591)
    $body = $latin1.GetString($answer.Bytes)
    $ref = $latin1.GetString([Text.Encoding]::UTF8.GetBytes('refs/heads/' + $Resolved.branch))
    $offset = 0
    while ($offset + 4 -le $body.Length) {
        $size = 0
        if (-not [int]::TryParse($body.Substring($offset, 4), [Globalization.NumberStyles]::HexNumber, $null, [ref]$size) -or
            ($size -gt 0 -and $size -lt 4)) {
            return ''
        }
        if ($size -eq 0) {
            $offset += 4
            continue
        }
        $line = $body.Substring($offset + 4, [Math]::Min($size, $body.Length - $offset) - 4).Split([char]0)[0].Trim()
        $offset += $size
        if ($line -match '^([0-9a-f]{40,64}) (\S+)$' -and $Matches[2] -ceq $ref) {
            return $Matches[1]
        }
    }
    throw ("PATCH_ERR:REPO:Branch '{0}' was not found in {1}." -f $Resolved.branch, $web)
}

function Expand-VerifiedMinGit {
    <#
    Unpacks a downloaded MinGit ZIP into $Destination only when its SHA-256 is
    the pinned one, and marks the folder with it so later runs reuse it.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$Sha256,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $actual = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
        throw ('PATCH_ERR:GIT:The Git for Windows download does not match its pinned checksum (got {0}); it was not used.' -f $actual)
    }
    $partial = $Destination + '.partial'
    Remove-SettledItem -LiteralPath $partial
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $partial -Force
    Set-Content -LiteralPath (Join-Path $partial 'dazedtl-mingit.sha256') -Value $Sha256 -Encoding Ascii
    try {
        Remove-SettledItem -LiteralPath $Destination
        Invoke-Settled -Action { Rename-Item -LiteralPath $partial -NewName ([IO.Path]::GetFileName($Destination)) -ErrorAction Stop }
    }
    catch {
        throw ('PATCH_ERR:GIT:{0} could not be replaced ({1}). Close anything using it, such as a folder window or a virus scanner, then run GameUpdate again.' -f $Destination, $_.Exception.Message)
    }
}

function Save-MinGitZip {
    param([Parameter(Mandatory = $true)][string]$OutFile)
    Invoke-WebRequest -Uri $MinGitUrl -OutFile $OutFile -Headers @{ 'User-Agent' = 'DazedMTL-Patcher-1.0' } -UseBasicParsing
}

function Test-GameUpdateMinGit {
    param(
        [Parameter(Mandatory = $true)][string]$Git,
        [Parameter(Mandatory = $true)][string]$BundleRoot
    )
    $folder = (Join-Path $BundleRoot 'mingit') + [IO.Path]::DirectorySeparatorChar
    return $Git.StartsWith($folder, [StringComparison]::OrdinalIgnoreCase)
}

function Get-PatchGit {
    <#
    The Git that fetches the patch when the forge's API or archive download
    fails: Git on PATH, else the pinned MinGit, downloaded and checked once
    into gameupdate\mingit and reused after that. -Reinstall replaces a
    MinGit that failed to run.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [switch]$Reinstall
    )
    $onPath = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($onPath) {
        return $onPath.Source
    }
    $folder = Join-Path $BundleRoot 'mingit'
    $git = Join-Path $folder 'cmd\git.exe'
    $marker = Join-Path $folder 'dazedtl-mingit.sha256'
    if (-not $Reinstall -and (Test-Path -LiteralPath $git -PathType Leaf) -and (Test-Path -LiteralPath $marker -PathType Leaf) -and
        ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $MinGitSha256)) {
        return $git
    }
    if ($Reinstall) {
        Write-Host 'Downloading Git for Windows (MinGit, about 35 MB) again...'
    }
    else {
        Write-Host 'Git is not installed; downloading Git for Windows (MinGit, about 35 MB) once for GameUpdate...'
    }
    # Windows PowerShell's Expand-Archive takes only a file named .zip.
    $zip = (New-GameUpdateTempPath -Kind 'mingit') + '.zip'
    $prevPref = $ProgressPreference
    try {
        # Windows PowerShell's progress bar slows a download many times over.
        $ProgressPreference = 'SilentlyContinue'
        $watch = [Diagnostics.Stopwatch]::StartNew()
        Invoke-WithRetry -Name 'Download Git for Windows' -Attempts (Get-EnvInt -Name 'GAMEUPDATE_DL_ATTEMPTS' -Default 2) -Action {
            Save-MinGitZip -OutFile $zip
        } | Out-Null
        Write-Host ('Downloaded Git for Windows in {0:N0}s; checking and unpacking it...' -f $watch.Elapsed.TotalSeconds)
        Expand-VerifiedMinGit -ZipPath $zip -Sha256 $MinGitSha256 -Destination $folder
    }
    finally {
        $ProgressPreference = $prevPref
        if (Test-Path -LiteralPath $zip) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $zip
        }
    }
    return $git
}

function Invoke-WithPatchGit {
    <#
    Runs $Action with the patch's Git, retried. A MinGit that still fails,
    such as one a virus scanner damaged, is downloaded again once.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    # Invoke-WithRetry runs the block in its own scope, where $Action is its
    # own parameter, so the work goes by names it does not use.
    $patchWork = $Action
    $attempts = Get-EnvInt -Name 'GAMEUPDATE_DL_ATTEMPTS' -Default 2
    $patchGit = Get-PatchGit -BundleRoot $BundleRoot
    try {
        return Invoke-WithRetry -Name $Name -Attempts $attempts -Action { & $patchWork $patchGit }
    }
    catch {
        if ((Test-FinalPatchError -Message $_.Exception.Message) -or -not (Test-GameUpdateMinGit -Git $patchGit -BundleRoot $BundleRoot)) {
            throw
        }
        Write-Host ('Git for Windows failed ({0}); downloading it again...' -f (Format-PatchMessage -Message $_.Exception.Message))
    }
    $patchGit = Get-PatchGit -BundleRoot $BundleRoot -Reinstall
    try {
        return Invoke-WithRetry -Name $Name -Attempts $attempts -Action { & $patchWork $patchGit }
    }
    catch {
        throw ('{0} If this keeps happening, delete the gameupdate\mingit folder and run GameUpdate again.' -f $_.Exception.Message)
    }
}

function Invoke-PatchGit {
    # No prompt for a login a public patch never needs: a missing repository
    # fails instead of waiting on a credential helper.
    param(
        [Parameter(Mandatory = $true)][string]$Git,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$ExitCodes = @(0)
    )
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'
    # Windows PowerShell turns Git's messages on a redirected stderr into
    # errors; the exit code alone says whether it worked.
    $ErrorActionPreference = 'Continue'
    $output = & $Git -c credential.helper= -c core.longpaths=true @Arguments
    if ($LASTEXITCODE -notin $ExitCodes) {
        # The command's name, past options such as -C <folder>.
        $command = ''
        for ($i = 0; $i -lt $Arguments.Count; $i++) {
            if ($Arguments[$i] -in '-C', '-c') { $i++; continue }
            $command = $Arguments[$i]
            break
        }
        throw ('PATCH_ERR:GIT:git {0} failed with exit code {1}.' -f $command, $LASTEXITCODE)
    }
    return $output
}

function Get-GitLatestSha {
    param(
        [Parameter(Mandatory = $true)][string]$Git,
        [Parameter(Mandatory = $true)][hashtable]$Resolved
    )
    $url = Get-PatchGitUrl -Resolved $Resolved
    $line = @(Invoke-PatchGit -Git $Git -Arguments @('ls-remote', $url, ('refs/heads/' + $Resolved.branch)))[0]
    $sha = if ($line) { ([string]$line).Split("`t")[0].Trim() } else { '' }
    if ($sha -notmatch '^[0-9a-f]{40,64}$') {
        throw ("PATCH_ERR:GIT:Git could not read branch '{0}' from {1}." -f $Resolved.branch, $url)
    }
    return $sha
}

function Save-GitPatchZip {
    <#
    Fetches only the branch's newest commit into a temporary repository and
    packs its files the way the forges' archives do: git archive, so
    export-ignore rules apply, under one root folder, with no line-ending
    conversion. Returns the commit it packed.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Git,
        [Parameter(Mandatory = $true)][hashtable]$Resolved,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    $repoDir = New-GameUpdateTempPath -Kind 'git'
    try {
        Invoke-PatchGit -Git $Git -Arguments @('init', '-q', $repoDir) | Out-Null
        Invoke-PatchGit -Git $Git -Arguments @(
            '-C', $repoDir, 'fetch', '--depth', '1', '--no-tags',
            (Get-PatchGitUrl -Resolved $Resolved), ('refs/heads/' + $Resolved.branch)
        ) | Out-Null
        $sha = ([string](Invoke-PatchGit -Git $Git -Arguments @('-C', $repoDir, 'rev-parse', 'FETCH_HEAD'))).Trim()
        # Git LFS's own filter stays off, so its files come out as the pointer
        # files the unpacked patch is checked for.
        Invoke-PatchGit -Git $Git -Arguments @(
            '-C', $repoDir, '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
            '-c', 'filter.lfs.smudge=', '-c', 'filter.lfs.process=', '-c', 'filter.lfs.required=false',
            'archive', '--format=zip', '--prefix=patch/', '-o', $OutFile, 'FETCH_HEAD'
        ) | Out-Null
        return $sha
    }
    finally {
        if (Test-Path -LiteralPath $repoDir) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $repoDir
        }
    }
}

function Get-PatchPathLimit {
    <#
    The longest full paths a patch's files and folders may have: Windows'
    259 characters for a file and 247 for a folder, unless this PowerShell
    can make longer ones. Whether it can depends on the PowerShell, Windows'
    version and its LongPathsEnabled setting, so it makes a deep folder and
    file in the temporary folder once and sees.
    #>
    if ($null -eq $script:PatchPathLimit) {
        $probe = New-GameUpdateTempPath -Kind 'long'
        try {
            $deep = $probe
            foreach ($part in 'a', 'b', 'c') {
                $deep = Join-Path $deep ($part * 100)
            }
            [void][IO.Directory]::CreateDirectory($deep)
            [IO.File]::WriteAllText((Join-Path $deep 'probe.txt'), '')
            $script:PatchPathLimit = @{ File = [int]::MaxValue; Folder = [int]::MaxValue }
        }
        catch {
            $script:PatchPathLimit = @{ File = 259; Folder = 247 }
        }
        finally {
            try { [IO.Directory]::Delete($probe, $true) } catch { }
        }
    }
    return $script:PatchPathLimit
}

function Expand-PatchZip {
    <#
    Unpacks a patch archive's files into $Destination without the archive's
    own root folder, such as GitLab's <repo>-<sha>-<sha>, which would push deep
    patch paths past Windows' 260-character limit. Refuses before unpacking
    anything when a file or folder would not fit there or in $GameRoot.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$ZipPath,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$GameRoot
    )
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $roots = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/').Split('/')[0] } | Select-Object -Unique)
        if ($roots.Count -ne 1) {
            throw ('PATCH_ERR:ZIP:Expected one root folder in archive, found {0}.' -f $roots.Count)
        }
        $base = [IO.Path]::GetFullPath($Destination).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $game = $GameRoot.TrimEnd('\', '/')
        $folder = [Math]::Max($base.Length - 1, $game.Length)
        $limit = Get-PatchPathLimit
        $files = foreach ($entry in $archive.Entries) {
            $relative = $entry.FullName.Replace('\', '/').Substring($roots[0].Length).TrimStart('/')
            if (-not $relative) { continue }
            # A file, and the folder an entry is or lies in, which Windows
            # limits further.
            $path = $relative.TrimEnd('/')
            $isFolder = $relative.EndsWith('/')
            $parent = if ($isFolder) { $path } elseif ($path.Contains('/')) { $path.Substring(0, $path.LastIndexOf('/')) } else { '' }
            $tooLong = $null
            if (-not $isFolder -and $folder + 1 + $path.Length -gt $limit.File) {
                $tooLong = $path
                $allowed = $limit.File
            }
            elseif ($parent -and $folder + 1 + $parent.Length -gt $limit.Folder) {
                $tooLong = $parent + '/'
                $allowed = '{0} for a folder' -f $limit.Folder
            }
            if ($tooLong) {
                if ($game.Length -lt $base.Length - 1) {
                    throw ('PATCH_ERR:PATH:This patch has files too deep for Windows'' temporary folder, such as {0} ({1} characters there; Windows allows {2}). Set the TEMP variable to a shorter folder, such as C:\Temp, then run GameUpdate again.' -f `
                        $tooLong, ($base.Length + $tooLong.TrimEnd('/').Length), $allowed)
                }
                throw ('PATCH_ERR:PATH:This patch has files too deep for this folder, such as {0} ({1} characters with the game''s folder; Windows allows {2}). Move the game to a shorter folder, such as C:\Games\{3}, then run GameUpdate again.' -f `
                    $tooLong, ($game.Length + 1 + $tooLong.TrimEnd('/').Length), $allowed, (Split-Path -Leaf $game))
            }
            @{ Entry = $entry; Relative = $relative }
        }
        foreach ($file in $files) {
            $target = [IO.Path]::GetFullPath((Join-Path $base $file.Relative))
            if (-not $target.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) {
                throw ('PATCH_ERR:ZIP:The archive holds a path outside its folder: {0}' -f $file.Entry.FullName)
            }
            if ($file.Entry.FullName.EndsWith('/')) {
                [void][IO.Directory]::CreateDirectory($target)
                continue
            }
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
            [IO.Compression.ZipFileExtensions]::ExtractToFile($file.Entry, $target, $true)
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Assert-NoLfsPointers {
    <#
    Files kept in Git LFS arrive as small pointer files from Git, and from a
    forge whose archives leave LFS out; never put those in a game.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Folder,
        [Parameter(Mandatory = $true)][hashtable]$Resolved
    )
    foreach ($file in Get-ChildItem -LiteralPath $Folder -Recurse -File -Force | Where-Object { $_.Length -lt 1024 }) {
        $reader = New-Object IO.StreamReader($file.FullName)
        try {
            $first = $reader.ReadLine()
        }
        finally {
            $reader.Dispose()
        }
        if ($first -ceq 'version https://git-lfs.github.com/spec/v1') {
            throw ('PATCH_ERR:LFS:This patch keeps files in Git LFS, such as {0}, which GameUpdate can''t download. Download it from {1}/{2}/{3} instead.' -f `
                $file.FullName.Substring($Folder.TrimEnd('\', '/').Length + 1), $Resolved.webBase, $Resolved.username, $Resolved.repo)
        }
    }
}

function Invoke-SrpgUnpacker {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $ExePath @Arguments
        return $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

function Test-WolfLooseDataReady {
    param([Parameter(Mandatory = $true)][string]$DataDir)
    if (-not (Test-Path -LiteralPath $DataDir -PathType Container)) {
        return $false
    }
    $markers = @(
        (Join-Path $DataDir 'BasicData\CommonEvent.dat'),
        (Join-Path $DataDir 'CommonEvent.dat')
    )
    foreach ($marker in $markers) {
        if (Test-Path -LiteralPath $marker -PathType Leaf) {
            return $true
        }
    }
    if (@(Get-ChildItem -LiteralPath $DataDir -Filter '*.mps' -File -ErrorAction SilentlyContinue).Count -gt 0) {
        return $true
    }
    $basic = Join-Path $DataDir 'BasicData'
    if (Test-Path -LiteralPath $basic -PathType Container) {
        if (@(Get-ChildItem -LiteralPath $basic -Filter '*.dat' -File -ErrorAction SilentlyContinue).Count -gt 0) {
            return $true
        }
    }
    return $false
}

function Test-WolfGameRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    foreach ($name in @('Data.wolf', 'data.wolf')) {
        if (Test-Path -LiteralPath (Join-Path $Root $name) -PathType Leaf) {
            return $true
        }
    }
    foreach ($name in @('Data', 'data')) {
        if (Test-WolfLooseDataReady -DataDir (Join-Path $Root $name)) {
            return $true
        }
    }
    return $false
}

function Find-UberWolfCli {
    param([Parameter(Mandatory = $true)][string]$Root)
    $candidates = @(
        (Join-Path $Root 'UberWolfCli.exe'),
        (Join-Path $Root 'gameupdate\UberWolfCli.exe')
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            return $path
        }
    }
    return $null
}

function Invoke-WolfPreSetup {
    <#
    WOLF installs often ship Data.wolf, which overrides loose patched Data/ files.
    Unpack once with UberWolfCli (bundled in the patch repo), then retire Data.wolf
    so GameUpdate can copy injected .mps/.dat on top.
    #>
    param([Parameter(Mandatory = $true)][string]$Root)

    $dataWolf = $null
    foreach ($name in @('Data.wolf', 'data.wolf')) {
        $candidate = Join-Path $Root $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $dataWolf = $candidate
            break
        }
    }
    if (-not $dataWolf) {
        return
    }

    $dataDir = Join-Path $Root 'Data'
    if (-not (Test-Path -LiteralPath $dataDir -PathType Container)) {
        $dataDirAlt = Join-Path $Root 'data'
        if (Test-Path -LiteralPath $dataDirAlt -PathType Container) {
            $dataDir = $dataDirAlt
        }
    }

    if (Test-WolfLooseDataReady -DataDir $dataDir) {
        $bak = "$dataWolf.bak"
        if (-not (Test-Path -LiteralPath $bak)) {
            Write-Host '[Pre-Setup] Loose Data/ already present; retiring Data.wolf -> Data.wolf.bak'
            Rename-Item -LiteralPath $dataWolf -NewName ([IO.Path]::GetFileName($bak)) -Force
        }
        else {
            Write-Host '[Pre-Setup] Loose Data/ already present; removing leftover Data.wolf'
            Remove-Item -LiteralPath $dataWolf -Force
        }
        return
    }

    $cli = Find-UberWolfCli -Root $Root
    if (-not $cli) {
        Write-Host '[Pre-Setup] Data.wolf found but UberWolfCli.exe is missing.'
        Write-Host '            Unpack Data.wolf once with UberWolf (https://github.com/Sinflower/UberWolf/releases), then run GameUpdate again.'
        return
    }

    Write-Host '[Pre-Setup] Unpacking Data.wolf with UberWolfCli (one-time)...'
    $code = Invoke-SrpgUnpacker -ExePath $cli -WorkingDirectory $Root -Arguments @('-o', $dataWolf)
    if ($code -ne 0) {
        Write-Host ('[Pre-Setup] ERROR: UberWolfCli exited with code {0}.' -f $code)
        return
    }

    # UberWolf writes next to the archive as <stem>/ (Data/). Also accept data.wolf~ leftovers.
    $unpacked = Join-Path $Root 'Data'
    if (-not (Test-Path -LiteralPath $unpacked -PathType Container)) {
        $unpacked = Join-Path $Root 'data'
    }
    if (-not (Test-WolfLooseDataReady -DataDir $unpacked)) {
        foreach ($alt in @('data.wolf~', 'Data.wolf~', 'Data~', 'data~')) {
            $altPath = Join-Path $Root $alt
            if (Test-Path -LiteralPath $altPath -PathType Container) {
                Write-Host ("[Pre-Setup] Promoting {0} -> Data\" -f $alt)
                if (Test-Path -LiteralPath (Join-Path $Root 'Data')) {
                    Remove-FileOrDirectoryViaCmd -LiteralPath (Join-Path $Root 'Data')
                }
                Rename-Item -LiteralPath $altPath -NewName 'Data' -Force
                $unpacked = Join-Path $Root 'Data'
                break
            }
        }
    }

    if (-not (Test-WolfLooseDataReady -DataDir $unpacked)) {
        Write-Host '[Pre-Setup] ERROR: Unpack finished but loose Data/ still looks empty.'
        return
    }

    $bak = "$dataWolf.bak"
    if (Test-Path -LiteralPath $dataWolf -PathType Leaf) {
        if (-not (Test-Path -LiteralPath $bak)) {
            Write-Host '[Pre-Setup] Retiring Data.wolf -> Data.wolf.bak'
            Rename-Item -LiteralPath $dataWolf -NewName ([IO.Path]::GetFileName($bak)) -Force
        }
        else {
            Write-Host '[Pre-Setup] Removing Data.wolf so loose Data/ takes priority'
            Remove-Item -LiteralPath $dataWolf -Force
        }
    }
    Write-Host '[Pre-Setup] Wolf Data/ is ready for patching.'
}

function Invoke-SrpgPreSetup {
    param([string]$Root)
    $unpacker = Join-Path $Root 'SRPG_Unpacker.exe'
    $dts = Join-Path $Root 'data.dts'
    $dataDir = Join-Path $Root 'data'
    $projectDat = Join-Path $dataDir 'project.dat'
    $patchDir = Join-Path $Root 'patch'

    if (-not (Test-Path -LiteralPath $dts)) {
        return
    }
    if (-not (Test-Path -LiteralPath $unpacker)) {
        Write-Host '[Pre-Setup] SRPG_Unpacker.exe not found; skipping data setup.'
        return
    }

    $shouldUnpack =
        -not (Test-Path -LiteralPath $dataDir) -or
        -not (Test-Path -LiteralPath $projectDat)

    $runUnpackBlock = {
        if (Test-Path -LiteralPath $dts) {
            Write-Host '[Pre-Setup] Unpacking data.dts to data\'
            $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('-o', 'data', 'data.dts')
            if ($code -ne 0) {
                Write-Host '[Pre-Setup] ERROR: Unpack failed. Continuing.'
            }
        }
        else {
            Write-Host '[Pre-Setup] Skipping unpack: data.dts missing.'
        }

        if (-not (Test-Path -LiteralPath $patchDir)) {
            if (Test-Path -LiteralPath $projectDat) {
                Write-Host '[Pre-Setup] Creating patch folder from data\project.dat'
                $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-c')
                if ($code -ne 0) {
                    Write-Host '[Pre-Setup] ERROR: Create Patch failed. Continuing.'
                }
            }
            else {
                Write-Host '[Pre-Setup] Skipping create patch: data\project.dat not found.'
            }
        }
    }

    if ($shouldUnpack) {
        & $runUnpackBlock
    }
    else {
        if (-not (Test-Path -LiteralPath $patchDir)) {
            if (Test-Path -LiteralPath $projectDat) {
                Write-Host '[Pre-Setup] Creating patch folder from data\project.dat'
                $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-c')
                if ($code -ne 0) {
                    Write-Host '[Pre-Setup] ERROR: Create Patch failed. Continuing.'
                }
            }
            else {
                Write-Host '[Pre-Setup] Skipping create patch: data\project.dat not found.'
            }
        }
    }
}

function Get-EnvInt {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Default
    )
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    $parsed = 0
    if ([int]::TryParse([string]$raw, [ref]$parsed) -and $parsed -gt 0) { return $parsed }
    return $Default
}

function Test-FinalPatchError {
    # Errors that another attempt or another way of downloading cannot change.
    param([string]$Message)
    return $Message -match '^PATCH_ERR:(LFS|PATH|REPO):'
}

function Format-PatchMessage {
    # GameUpdate's own errors carry a PATCH_ERR:<kind>: tag for the script;
    # players see the message after it.
    param([string]$Message)
    return $Message -replace '^PATCH_ERR:[A-Z]+:', ''
}

function Invoke-WithRetry {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$Attempts = 2,
        [int]$DelaySeconds = 2
    )
    $lastErr = $null
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            return & $Action
        }
        catch {
            $lastErr = $_
            if (Test-FinalPatchError -Message $_.Exception.Message) {
                throw
            }
            if ($i -lt $Attempts) {
                Write-Host ("{0} failed ({1}/{2}): {3} Retrying..." -f $Name, $i, $Attempts, (Format-PatchMessage -Message $_.Exception.Message))
                Start-Sleep -Seconds $DelaySeconds
            }
        }
    }
    throw $lastErr
}

function Get-InvalidZipDownloadHint {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $item = Get-Item -LiteralPath $LiteralPath -ErrorAction SilentlyContinue
    if (-not $item) {
        return '(downloaded file missing)'
    }
    $len = $item.Length
    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add("File size: $len bytes.")
    if ($len -eq 0) {
        $parts.Add('Empty file often means the window was closed during download, the connection dropped, or security software blocked the file. Run again and let it finish.')
        return ($parts -join ' ')
    }

    $peekSize = [Math]::Min([int64]$len, 6144)
    $buf = New-Object byte[] $peekSize
    $fs = [System.IO.File]::OpenRead($LiteralPath)
    try {
        [void]$fs.Read($buf, 0, $peekSize)
    }
    finally {
        $fs.Dispose()
    }

    $text = [System.Text.Encoding]::UTF8.GetString($buf)
    if ($text -match '(?i)<!DOCTYPE\s+html|<html[\s>]') {
        $parts.Add('Body looks like HTML (often an error page or block). Check username/repo/branch in patch-config.txt and network.')
    }
    elseif ($text.TrimStart().StartsWith('{')) {
        try {
            $j = ($text.TrimStart() | ConvertFrom-Json)
            if ($j.message) {
                $parts.Add("GitLab JSON: $($j.message)")
            }
            else {
                $parts.Add('Body starts with JSON (likely an API error, not a ZIP).')
            }
        }
        catch {
            $parts.Add('Body starts with `{` but was not parseable JSON (truncated or wrong encoding).')
        }
    }
    else {
        $flat = ($text -replace '[\r\n]+', ' ')
        $take = [Math]::Min(200, $flat.Length)
        if ($take -gt 0) {
            $parts.Add(('UTF-8 preview: ' + $flat.Substring(0, $take)))
        }
    }

    return ($parts -join ' ')
}

$script:GameUpdateConsoleCloseHelperLoaded = $false
function Initialize-GameUpdateConsoleCloseHelper {
    if ($script:GameUpdateConsoleCloseHelperLoaded) { return }
    $script:GameUpdateConsoleCloseHelperLoaded = $true
    $script:GameUpdateConsoleCloseHelperWorks = $false
    if ($env:OS -ne 'Windows_NT') { return }

    try {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;

namespace GameUpdate {
    public static class ConsoleCloseHelper {
        private static HandlerRoutine _handler;

        public static void Register() {
            _handler = Handle;
            SetConsoleCtrlHandler(_handler, true);
        }

        public static void Unregister() {
            if (_handler != null) {
                SetConsoleCtrlHandler(_handler, false);
                _handler = null;
            }
        }

        private static bool Handle(uint ctrlType) {
            const uint CTRL_CLOSE_EVENT = 2;
            const uint CTRL_LOGOFF_EVENT = 5;
            const uint CTRL_SHUTDOWN_EVENT = 6;
            if (ctrlType != CTRL_CLOSE_EVENT && ctrlType != CTRL_LOGOFF_EVENT && ctrlType != CTRL_SHUTDOWN_EVENT) {
                return false;
            }
            try {
                string path = Environment.GetEnvironmentVariable("GAMEUPDATE_REPO_ZIP_PATH");
                if (!string.IsNullOrEmpty(path) && File.Exists(path)) {
                    File.Delete(path);
                }
            }
            catch { }
            return false;
        }

        private delegate bool HandlerRoutine(uint ctrlType);

        [DllImport("Kernel32.dll", SetLastError = true)]
        private static extern bool SetConsoleCtrlHandler(HandlerRoutine handler, bool add);
    }
}
'@ -ErrorAction Stop
        $script:GameUpdateConsoleCloseHelperWorks = $true
    }
    catch {
        $script:GameUpdateConsoleCloseHelperWorks = $false
    }
}

function Invoke-PatchArchiveDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][hashtable]$Headers
    )

    if (Test-Path -LiteralPath $OutFile) {
        Remove-Item -LiteralPath $OutFile -Force
    }

    $outFull = [System.IO.Path]::GetFullPath($OutFile)
    Initialize-GameUpdateConsoleCloseHelper

    $prevPref = $ProgressPreference
    $completed = $false
    $registeredCloseHandler = $false
    try {
        if ($script:GameUpdateConsoleCloseHelperWorks) {
            $env:GAMEUPDATE_REPO_ZIP_PATH = $outFull
            [GameUpdate.ConsoleCloseHelper]::Register()
            $registeredCloseHandler = $true
        }

        $ProgressPreference = 'Continue'
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Headers $Headers -UseBasicParsing
        $completed = $true
    }
    finally {
        $ProgressPreference = $prevPref

        if ($registeredCloseHandler) {
            try {
                [GameUpdate.ConsoleCloseHelper]::Unregister()
            }
            catch { }
            Remove-Item env:GAMEUPDATE_REPO_ZIP_PATH -ErrorAction SilentlyContinue
        }

        if (-not $completed -and (Test-Path -LiteralPath $OutFile)) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $OutFile
        }
    }
}

function Remove-FileOrDirectoryViaCmd {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) {
        return
    }
    $full = (Resolve-Path -LiteralPath $LiteralPath).ProviderPath
    $item = Get-Item -LiteralPath $LiteralPath
    if ($item.PSIsContainer) {
        cmd.exe /c "rd /s /q `"$full`"" | Out-Null
    }
    else {
        cmd.exe /c "del /f /q `"$full`"" | Out-Null
    }
}

function Remove-DownloadedRepoZip {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    Remove-FileOrDirectoryViaCmd -LiteralPath $LiteralPath
}

function Get-PatchUndoFolder {
    <#
    Where Copy-PatchFiles keeps what it changed: on the game's own drive, so
    setting a game file aside is a rename that needs no space. DazedTL keeps
    it out of patches (gameupdate_local in project_preparation.py).
    #>
    param([Parameter(Mandatory = $true)][string]$BundleRoot)
    return Join-Path $BundleRoot 'undo'
}

function Undo-PatchFiles {
    <#
    Puts the game back as it was before a Copy-PatchFiles that did not
    finish, from its journal, newest change first: moves each game file it
    set aside back, removes each file it added, and each folder it added once
    that is empty. Each step checks what is there first, so running it again
    after it stopped finishes it. Throws when a file can't be put back,
    keeping the journal for the next run.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$BundleRoot
    )
    $undo = Get-PatchUndoFolder -BundleRoot $BundleRoot
    $journal = Join-Path $undo 'journal.txt'
    if ([IO.File]::Exists($journal)) {
        Write-Host 'Putting the game back as it was...'
        # A line cut short, when the run ended while writing it, has no
        # newline, and the change it names was never made.
        $lines = [IO.File]::ReadAllText($journal, (New-Object Text.UTF8Encoding($false))).Split("`n")
        $left = New-Object Collections.Generic.List[string]
        for ($i = $lines.Count - 2; $i -ge 0; $i--) {
            $kind, $relative = $lines[$i] -split ' ', 2
            if ($kind -eq 'moved') {
                $number, $relative = $relative -split ' ', 2
            }
            if (-not $relative) {
                continue
            }
            $path = Join-Path $Root $relative
            try {
                if ($kind -eq 'moved') {
                    $copy = Join-Path $undo $number
                    if ([IO.File]::Exists($copy)) {
                        Invoke-Settled -Tries 50 -Action {
                            if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) }
                            [IO.File]::Move($copy, $path)
                        }
                    }
                }
                elseif ([IO.Directory]::Exists($path)) {
                    # Another program may have put files in it since; an
                    # empty folder changes nothing for the game.
                    try { [IO.Directory]::Delete($path) } catch { }
                }
                elseif ([IO.File]::Exists($path)) {
                    Invoke-Settled -Tries 50 -Action { [IO.File]::Delete($path) }
                }
            }
            catch {
                $left.Add(('{0} ({1})' -f $relative, $_.Exception.Message))
            }
        }
        if ($left.Count -gt 0) {
            throw ('PATCH_ERR:UNDO:GameUpdate could not put back {0}. Close the game, then run GameUpdate again to finish putting it back.' -f ($left -join '; '))
        }
        # Once the journal is gone the game is as it was; the rest of the
        # folder is only left over.
        [IO.File]::Delete($journal)
        Write-Host 'The game was left as it was before this update.'
    }
    if ([IO.Directory]::Exists($undo)) {
        Remove-SettledItem -LiteralPath $undo
    }
}

function Copy-PatchFiles {
    <#
    Copies the unpacked patch in $Stage into $Root all or nothing. Before each
    change it writes the change to a journal in Get-PatchUndoFolder: each game
    file the patch replaces is moved there, and each file and folder it adds
    is listed. When a copy fails, such as on a file the running game holds or
    a full disk, or the run is stopped, Undo-PatchFiles puts the game back
    before the error goes on; when the window was closed, the next run does.
    Files named in $Skip stay out.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [string[]]$Skip = @()
    )
    $stageFolder = [IO.Path]::GetFullPath($Stage).TrimEnd('\', '/')
    $undo = Get-PatchUndoFolder -BundleRoot $BundleRoot
    $journalPath = Join-Path $undo 'journal.txt'
    [void][IO.Directory]::CreateDirectory($undo)
    $journal = New-Object IO.StreamWriter($journalPath, $false, (New-Object Text.UTF8Encoding($false)))
    $journal.AutoFlush = $true
    $journal.NewLine = "`n"
    # Moved files are named by their order, so their paths stay short.
    $moved = 0
    $copied = $false
    try {
        foreach ($source in [IO.Directory]::EnumerateFiles($stageFolder, '*', [IO.SearchOption]::AllDirectories)) {
            if ([IO.Path]::GetFileName($source) -in $Skip) {
                continue
            }
            $relative = $source.Substring($stageFolder.Length + 1)
            $destination = Join-Path $Root $relative
            $folders = New-Object Collections.Generic.List[string]
            $folder = [IO.Path]::GetDirectoryName($relative)
            while ($folder -and -not [IO.Directory]::Exists((Join-Path $Root $folder))) {
                $folders.Insert(0, $folder)
                $folder = [IO.Path]::GetDirectoryName($folder)
            }
            foreach ($folder in $folders) {
                $journal.WriteLine('added ' + $folder)
                [void][IO.Directory]::CreateDirectory((Join-Path $Root $folder))
            }
            if ([IO.Directory]::Exists($destination)) {
                throw ('PATCH_ERR:APPLY:This patch has a file where the game has a folder: {0}' -f $relative)
            }
            if ([IO.File]::Exists($destination)) {
                $journal.WriteLine(('moved {0} {1}' -f $moved, $relative))
                [IO.File]::Move($destination, (Join-Path $undo $moved))
                $moved++
            }
            else {
                $journal.WriteLine('added ' + $relative)
            }
            [IO.File]::Copy($source, $destination)
        }
        $copied = $true
    }
    finally {
        # Here rather than in a catch, so a stopped run is undone too.
        $journal.Dispose()
        if ($copied) {
            [IO.File]::Delete($journalPath)
            try { Remove-SettledItem -LiteralPath $undo } catch { }
        }
        else {
            try {
                Undo-PatchFiles -Root $Root -BundleRoot $BundleRoot
            }
            catch {
                Write-Host ('ERROR: ' + (Format-PatchMessage -Message $_.Exception.Message))
            }
        }
    }
}

function Invoke-PatchDownloadExtract {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$StateFilePath,
        [Parameter(Mandatory = $true)][hashtable]$Resolved,
        [Parameter(Mandatory = $true)][string]$BundleRoot
    )

    if ($PSVersionTable.PSEdition -ne 'Core') {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        }
        catch {}
    }

    Set-Location -LiteralPath $Root

    $headers = New-PatchApiHeaders -Resolved $Resolved
    $dlAttempts = Get-EnvInt -Name 'GAMEUPDATE_DL_ATTEMPTS' -Default 2

    # The forge's API first. When it fails, such as with a 403 or a challenge
    # page in place of its answer, the ref advertisement, which needs no Git;
    # Git itself asks only when that gives no answer either.
    $useGit = $false
    try {
        $latestSha = Invoke-WithRetry -Name 'Resolve latest patch SHA' -Attempts $dlAttempts -Action {
            $sha = ([string](Get-PatchLatestSha -Resolved $Resolved -Headers $headers)).Trim()
            if ($sha -notmatch '^[0-9a-f]{40,64}$') { throw 'PATCH_ERR:API:Latest commit SHA response was empty.' }
            $sha
        }
    }
    catch {
        Write-Host ('Resolve latest patch SHA failed ({0}); reading the branch from the repository instead.' -f (Format-PatchMessage -Message $_.Exception.Message))
        $useGit = $true
        $latestSha = Get-AdvertisedSha -Resolved $Resolved
        if (-not $latestSha) {
            $latestSha = Invoke-WithPatchGit -BundleRoot $BundleRoot -Name 'Ask Git for the latest patch commit' -Action {
                param($git)
                Get-GitLatestSha -Git $git -Resolved $Resolved
            }
        }
    }

    $previousSha = ''
    if (Test-Path -LiteralPath $StateFilePath) {
        $previousSha = (Get-Content -LiteralPath $StateFilePath -Raw).Trim()
    }
    else {
        Write-Host 'First run: comparing with remote...'
    }
    if ($previousSha -eq $latestSha) {
        return 10
    }

    $zipPath = Join-Path $Root ('dazedmtl_patch_' + [Guid]::NewGuid().ToString('N') + '.zip')
    $stage = New-GameUpdateTempPath -Kind 'patch'
    try {
        if (-not $useGit) {
            try {
                Write-Host ('Downloading patch... ' + $zipPath)
                $archiveUrl = Get-PatchArchiveUrl -Resolved $Resolved -Sha $latestSha
                $dlSw = [System.Diagnostics.Stopwatch]::StartNew()
                Invoke-WithRetry -Name 'Download archive with Invoke-WebRequest' -Attempts $dlAttempts -Action {
                    Invoke-PatchArchiveDownload -Url $archiveUrl -OutFile $zipPath -Headers $headers
                } | Out-Null
                $dlSw.Stop()
                $bytes = (Get-Item -LiteralPath $zipPath).Length
                if ($bytes -eq 0) {
                    $hint = Get-InvalidZipDownloadHint -LiteralPath $zipPath
                    throw "PATCH_ERR:ZIP:Download is empty (0 bytes). $hint"
                }

                $secs = [Math]::Max($dlSw.Elapsed.TotalSeconds, 0.001)
                $mbps = ($bytes / 1MB) / $secs
                Write-Host ("Download complete: {0:N1} MB in {1:N1}s ({2:N1} MB/s)" -f ($bytes / 1MB), $secs, $mbps)

                $zipHeaderBad = $false
                $zipHeaderHint = ''
                $fs = [System.IO.File]::OpenRead($zipPath)
                try {
                    $hdr = New-Object byte[] 4
                    if ($fs.Read($hdr, 0, 4) -lt 4 -or $hdr[0] -ne 0x50 -or $hdr[1] -ne 0x4B) {
                        $zipHeaderBad = $true
                        $zipHeaderHint = Get-InvalidZipDownloadHint -LiteralPath $zipPath
                    }
                }
                finally {
                    $fs.Dispose()
                }
                if ($zipHeaderBad) {
                    throw "PATCH_ERR:ZIP:Download is not a valid ZIP (missing PK header). $zipHeaderHint"
                }
                Expand-PatchZip -ZipPath $zipPath -Destination $stage -GameRoot $Root
            }
            catch {
                if (Test-FinalPatchError -Message $_.Exception.Message) {
                    throw
                }
                Write-Host ('The archive could not be downloaded or unpacked ({0}); trying Git instead.' -f (Format-PatchMessage -Message $_.Exception.Message))
                $useGit = $true
                Remove-SettledItem -LiteralPath $stage
            }
            finally {
                if (Test-Path -LiteralPath $zipPath) {
                    Remove-DownloadedRepoZip -LiteralPath $zipPath
                }
            }
        }
        if ($useGit) {
            Write-Host 'Downloading patch with Git...'
            $latestSha = Invoke-WithPatchGit -BundleRoot $BundleRoot -Name 'Fetch the patch with Git' -Action {
                param($git)
                if (Test-Path -LiteralPath $zipPath) {
                    Remove-DownloadedRepoZip -LiteralPath $zipPath
                }
                Save-GitPatchZip -Git $git -Resolved $Resolved -OutFile $zipPath
            }
            Expand-PatchZip -ZipPath $zipPath -Destination $stage -GameRoot $Root
            Remove-DownloadedRepoZip -LiteralPath $zipPath
        }
        Assert-NoLfsPointers -Folder $stage -Resolved $Resolved

        Write-Host 'Applying patch...'
        $isWolfGame = Test-WolfGameRoot -Root $Root
        $wolfOnlyNames = @('UberWolfCli.exe', 'UberWolfCli.LICENSE.txt')

        if ($isWolfGame) {
            # Stage UberWolfCli before unpack so packed WOLF games can
            # convert Data.wolf -> Data/ before English files land. This
            # stays outside Copy-PatchFiles' undo: the loose Data/ it unpacks
            # is the same game, which a later run would unpack again.
            foreach ($cliName in $wolfOnlyNames) {
                $stagedCli = Join-Path $stage $cliName
                $destCli = Join-Path $Root $cliName
                if ((Test-Path -LiteralPath $stagedCli -PathType Leaf) -and
                    -not (Test-Path -LiteralPath $destCli -PathType Leaf)) {
                    Copy-Item -LiteralPath $stagedCli -Destination $destCli -Force
                }
            }
            Invoke-WolfPreSetup -Root $Root
        }

        # WOLF-only tools never leak into RPG Maker, SRPG, or other game
        # roots through a downloaded patch archive.
        $skip = if ($isWolfGame) { @() } else { $wolfOnlyNames }
        Copy-PatchFiles -Stage $stage -Root $Root -BundleRoot $BundleRoot -Skip $skip
    }
    finally {
        if (Test-Path -LiteralPath $zipPath) {
            Remove-DownloadedRepoZip -LiteralPath $zipPath
        }
        if (Test-Path -LiteralPath $stage) {
            Remove-FileOrDirectoryViaCmd -LiteralPath $stage
        }
    }

    Set-Content -LiteralPath $StateFilePath -Value $latestSha -Encoding Ascii
    return 0
}

function Invoke-SrpgPostApply {
    param([string]$Root)
    $unpacker = Join-Path $Root 'SRPG_Unpacker.exe'
    $dts = Join-Path $Root 'data.dts'
    $projectDat = Join-Path $Root 'data\project.dat'
    $dataDir = Join-Path $Root 'data'

    if (-not (Test-Path -LiteralPath $dts)) {
        return
    }
    if (-not (Test-Path -LiteralPath $unpacker)) {
        Write-Host 'SRPG_Unpacker.exe not found in root; skipping SRPG patch steps.'
        return
    }

    if (Test-Path -LiteralPath $projectDat) {
        Write-Host 'Applying patch to data\project.dat...'
        $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('.\data\project.dat', '-a')
        if ($code -ne 0) {
            Write-Host 'ERROR: Apply Patch failed.'
        }
    }
    else {
        Write-Host 'ERROR: data\project.dat not found; cannot apply patch.'
    }

    if (Test-Path -LiteralPath $dataDir) {
        Write-Host 'Packing data folder to data.dts...'
        $code = Invoke-SrpgUnpacker -ExePath $unpacker -WorkingDirectory $Root -Arguments @('-o', 'data.dts', 'data')
        if ($code -ne 0) {
            Write-Host 'WARNING: Pack failed.'
        }
    }
    else {
        Write-Host 'Step 4: Skipping pack - data folder not found.'
    }
}

function Remove-StalePatchZipArtifactsInGameRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Get-ChildItem -LiteralPath $Root -Filter 'dazedmtl_patch_*.zip' -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-FileOrDirectoryViaCmd -LiteralPath $_.FullName
        }
}

function Remove-PatchTempArtifacts {
    param([string]$Root)
    $zipPath = Join-Path $Root 'repo.zip'
    $legacyTmp = Join-Path $Root '_patch_extract_tmp'

    Remove-StalePatchZipArtifactsInGameRoot -Root $Root

    if (Test-Path -LiteralPath $zipPath) {
        Write-Host '  Removing repo.zip...'
        Remove-FileOrDirectoryViaCmd -LiteralPath $zipPath
    }
    if (Test-Path -LiteralPath $legacyTmp) {
        Write-Host '  Removing _patch_extract_tmp - using rd /s /q (avoids PowerShell hangs on huge folders).'
        Remove-FileOrDirectoryViaCmd -LiteralPath $legacyTmp
    }
}

try {
    if (Test-WrongWorkingDirectory -Root $GameRoot) {
        Write-BannerWrongFolder
        Wait-ConsolePause
        exit 1
    }

    Write-AsciiHeader

    # Before anything touches the game, so a second run changes nothing the
    # first is using; held until the process ends.
    $gameUpdateLock = Enter-GameUpdateLock -BundleRoot $PatchBundleRoot
    Remove-StaleGameUpdateTemp
    # An update stopped partway, such as by a closed window, is undone first.
    Undo-PatchFiles -Root $GameRoot -BundleRoot $PatchBundleRoot
    Remove-StalePatchZipArtifactsInGameRoot -Root $GameRoot

    $configPath = Join-Path $PatchBundleRoot 'patch-config.txt'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Write-Host 'patch-config.txt not found next to patch.ps1 - skipping patch.'
        Wait-ConsolePause
        exit 0
    }

    $cfg = Read-PatchConfig -ConfigPath $configPath

    if ([string]::IsNullOrWhiteSpace($cfg.username)) {
        Write-Host "ERROR: 'username=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($cfg.repo)) {
        Write-Host "ERROR: 'repo=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }
    if ([string]::IsNullOrWhiteSpace($cfg.branch)) {
        Write-Host "ERROR: 'branch=' is missing in patch-config.txt"
        Wait-ConsolePause
        exit 1
    }

    try {
        $resolved = Resolve-PatchForge -Cfg $cfg
    }
    catch {
        Write-Host ('ERROR: ' + (Format-PatchMessage -Message $_.Exception.Message))
        Wait-ConsolePause
        exit 1
    }

    Write-Host ('Pulling patch from {0}/{1}/{2} ({3}, branch: {4})' -f `
        $resolved.webBase, $resolved.username, $resolved.repo, $resolved.kind, $resolved.branch)

    Invoke-WolfPreSetup -Root $GameRoot
    Invoke-SrpgPreSetup -Root $GameRoot

    $stateFile = Join-Path $PatchBundleRoot 'previous_patch_sha.txt'

    $patchDlExit = 1
    try {
        $patchDlExit = Invoke-PatchDownloadExtract -Root $GameRoot -StateFilePath $stateFile `
            -Resolved $resolved -BundleRoot $PatchBundleRoot
    }
    catch {
        Write-Host ''
        Write-Host ('ERROR: ' + (Format-PatchMessage -Message $_.Exception.Message))
        # GameUpdate's own errors say what happened; a script position helps
        # only with an unexpected one.
        if ($_.Exception.Message -notlike 'PATCH_ERR:*' -and $_.InvocationInfo.PositionMessage) {
            Write-Host $_.InvocationInfo.PositionMessage
        }
        Remove-PatchTempArtifacts -Root $GameRoot
        Wait-ConsolePause
        exit 1
    }

    if ($patchDlExit -eq 10) {
        Write-Host 'Already up to date.'
        Wait-ConsolePause
        exit 0
    }

    if ($patchDlExit -ne 0) {
        Write-Host 'Download or extraction failed!'
        Remove-PatchTempArtifacts -Root $GameRoot
        Wait-ConsolePause
        exit 1
    }

    Invoke-SrpgPostApply -Root $GameRoot
    # Safety: if Data/ is ready (from unpack or patch files) but Data.wolf
    # remains, retire it so the archive does not override loose English files.
    Invoke-WolfPreSetup -Root $GameRoot

    Write-Host 'Cleaning up...'
    Remove-PatchTempArtifacts -Root $GameRoot
    Write-Host 'Done.'

    Wait-ConsolePause
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('ERROR: ' + (Format-PatchMessage -Message $_.Exception.Message))
    Wait-ConsolePause
    exit 1
}
