<#
  Instability Control - beta installer (2026-10-24)

  Installs (or updates) Instability Control for the current Windows user. No admin rights needed.

    Program folder : %LOCALAPPDATA%\Programs\InstabilityControl
    Your data      : %LOCALAPPDATA%\RaceEngineer   (memory, notes, cache - never touched by this installer)

  Run it again at any time to update: code and packages are refreshed, downloads that are already
  there (speech model, voices, team AI) are kept unless you ask for them again.

  Usual way: double-click "Install Instability Control.cmd" in this folder.

  Options (all optional):
    -VoicesZip <path>     use this voices.zip instead of downloading it
    -Tag <tag>            release tag to download voices.zip from (default below)
    -VoicesUrl <url>      full download link for voices.zip (overrides -Tag)
    -TeamAI ask|skip|vulkan|cuda|cpu   the optional local team AI (about 2.5 GB). Default: ask
    -Apollo ask|skip|install   the optional Apollo (streams this PC to the TV). Skipped by itself when Apollo or
                          Sunshine is already installed. Default: ask
    -ForceVoices          extract the voices again even if this version is already installed
    -InstallDir <path>    somewhere else than %LOCALAPPDATA%\Programs\InstabilityControl
    -NoShortcuts          don't create the Desktop / Start Menu shortcuts
    -Yes                  don't ask questions (team AI follows -TeamAI, Apollo follows -Apollo; ask = skip)
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\InstabilityControl'),
    [string]$Tag = '',   # empty = this copy's own version (VERSION file next to engineer\), e.g. v0.62.0-beta.2
    [string]$VoicesUrl = '',
    [string]$VoicesZip = '',
    [ValidateSet('ask', 'skip', 'vulkan', 'cuda', 'cpu')]
    [string]$TeamAI = 'ask',
    [ValidateSet('ask', 'skip', 'install')]
    [string]$Apollo = 'ask',
    [string]$LlamaBuild = 'b11826',
    [string]$PythonExe = '',
    [switch]$ForceVoices,
    [switch]$NoShortcuts,
    [switch]$Yes
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'       # Invoke-WebRequest is 10x slower with the progress bar on
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

$AppName   = 'Instability Control'
$SourceDir = Split-Path -Parent $PSScriptRoot  # the folder that holds engineer\ (this script is in installer\)
$VenvDir   = Join-Path $InstallDir 'venv_eng'
$DownDir   = Join-Path $InstallDir '_downloads'
$UserData  = Join-Path $env:LOCALAPPDATA 'RaceEngineer'

# ---- the speech-recognition model (official sherpa-onnx release, read by engineer\ptt.py from asr\*parakeet*)
$AsrName   = 'sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8'
$AsrUrl    = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$AsrName.tar.bz2"
$AsrSize   = 482468385
$AsrSha256 = '157c157bc51155e03e37d2466522a3a737dd9c72bb25f36eb18912964161e1ad'

# ---- the optional team AI (engineer\team.py looks for llm\bin\**\llama-server.exe and llm\models\*.gguf)
$GgufName   = 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
$GgufUrl    = "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/$GgufName"
$GgufSize   = 2497281120
$GgufSha256 = '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
$LlamaBase  = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaBuild"

# ---- the optional Apollo (Sunshine fork that streams this PC to the TV - Artemis / Moonlight on the TV side)
$ApolloApi  = 'https://api.github.com/repos/ClassicOldSong/Apollo/releases/latest'
$ApolloFrom = 'https://github.com/ClassicOldSong/Apollo/releases/download/'   # every download must start with this
$ApolloWeb  = 'https://localhost:47990'

# 2026-11-05: the voices come from the release of THIS version (a fixed tag broke installs once that release moved)
if (-not $Tag) {
    $Tag = 'v0.62.0-beta.2'
    $vf = Join-Path $SourceDir 'VERSION'
    if (Test-Path $vf) { $v = "$(Get-Content $vf -TotalCount 1)".Trim(); if ($v -match '^\d+\.\d+\.\d+') { $Tag = "v$v" } }
}
if (-not $VoicesUrl) {
    $VoicesUrl = "https://github.com/instabilitycontrolracing/instability-control/releases/download/$Tag/voices.zip"
}

# ------------------------------------------------------------------ helpers
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$LogFile = Join-Path $InstallDir 'install_log.txt'
Add-Content -Path $LogFile -Value ("`r`n===== install started {0} (from {1}) =====" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $SourceDir)

function Write-Log([string]$Text) { Add-Content -Path $LogFile -Value ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $Text) }
function Say([string]$Text)  { Write-Host $Text; Write-Log $Text }
function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan; Write-Log "==> $Text" }
function Ok([string]$Text)   { Write-Host "    OK  $Text" -ForegroundColor Green; Write-Log "OK  $Text" }
function Warn([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow; Write-Log "WARN  $Text" }
function Fail([string]$Text) {
    Write-Host ''
    Write-Host "STOPPED: $Text" -ForegroundColor Red
    Write-Log "FAILED  $Text"
    Write-Host "Details are in the log file: $LogFile"
    exit 1
}

function Ask-YesNo([string]$Question, [bool]$Default = $false) {
    if ($Yes) { return $Default }
    $hint = '[y/N]'; if ($Default) { $hint = '[Y/n]' }
    $a = Read-Host "$Question $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $Default }
    return ($a.Trim().ToLower().StartsWith('y'))
}

# Runs a program, copies everything it prints into the log (and on screen unless -Quiet), returns its exit code.
# (Windows PowerShell 5.1 turns a program's error output into script errors when $ErrorActionPreference is
#  Stop, so it is relaxed here, inside this function only.)
function Invoke-Exe([string]$Exe, [string[]]$Arguments, [switch]$Quiet) {
    Write-Log ("run: {0} {1}" -f $Exe, ($Arguments -join ' '))
    $ErrorActionPreference = 'Continue'
    & $Exe @Arguments 2>&1 | ForEach-Object {
        $line = "$_"
        Add-Content -Path $LogFile -Value "      $line"
        if (-not $Quiet) { Write-Host "      $line" -ForegroundColor DarkGray }
    }
    return $LASTEXITCODE
}

function Get-Sha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower() }

# Downloads $Url to $Dest (resuming a half-finished download), then checks the size and SHA-256 when known.
function Get-Download([string]$Url, [string]$Dest, [long]$Size = 0, [string]$Sha256 = '') {
    $part = "$Dest.part"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
    if ((Test-Path $part) -and $Size -gt 0 -and (Get-Item $part).Length -gt $Size) { Remove-Item $part -Force }
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    Write-Log "download: $Url -> $Dest"
    $done = $false
    if (Test-Path $curl) {
        for ($try = 1; $try -le 3 -and -not $done; $try++) {
            $ErrorActionPreference = 'Continue'
            & $curl -L --fail --retry 3 --retry-delay 5 -C - -o $part $Url     # shows its own progress bar
            $code = $LASTEXITCODE
            $ErrorActionPreference = 'Stop'
            Write-Log "curl exit $code (try $try)"
            if ($code -eq 0) { $done = $true }
            elseif ($code -eq 22) { break }                                # 404 / 403: retrying won't help
        }
    }
    if (-not $done) {
        try {
            if (Test-Path $part) { Remove-Item $part -Force }
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part
            $done = $true
        } catch {
            Write-Log "Invoke-WebRequest failed: $($_.Exception.Message)"
        }
    }
    if (-not $done) { return $false }
    $len = (Get-Item $part).Length
    if ($Size -gt 0 -and $len -ne $Size) {
        Warn "The download is the wrong size ($len bytes, expected $Size). It will be fetched again next time."
        Remove-Item $part -Force
        return $false
    }
    if ($Sha256) {
        Say '    checking the file is genuine (SHA-256)...'
        $h = Get-Sha256 $part
        if ($h -ne $Sha256.ToLower()) {
            Warn "The download doesn't match its checksum (got $h). It was deleted."
            Remove-Item $part -Force
            return $false
        }
    }
    if (Test-Path $Dest) { Remove-Item $Dest -Force }
    Move-Item $part $Dest
    return $true
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Icon, [string]$Description) {
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($Path)
    $s.TargetPath = $Target
    $s.Arguments = $Arguments
    $s.WorkingDirectory = $WorkDir
    if ($Icon -and (Test-Path $Icon)) { $s.IconLocation = "$Icon,0" }
    $s.Description = $Description
    $s.Save()
}

# Lists a zip's entries so we can refuse anything that must never be installed (or that escapes the folder).
function Test-ZipSafe([string]$Zip) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        foreach ($e in $z.Entries) {
            $n = $e.FullName -replace '\\', '/'
            if ($n.StartsWith('/') -or $n -match '(^|/)\.\.(/|$)' -or $n -match '^[A-Za-z]:') { return "unsafe path in zip: $n" }
            if ($n -match '(?i)(^|/)(RaceControl|Clare)(/|$)' -or $n -match '(?i)engineer_settings\.json$' -or
                $n -match '(?i)[^/]*token[^/]*\.(txt|json|key|dat|ini)$' -or $n -match '(?i)\.ibt$' -or $n -match '(?i)(^|/)venv') { return "the zip contains something that is never shipped: $n" }
        }
        return ''
    } finally { $z.Dispose() }
}

function Expand-Zip([string]$Zip, [string]$Dest) {
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path $tar) {
        $code = Invoke-Exe $tar @('-xf', $Zip, '-C', $Dest) -Quiet
        if ($code -eq 0) { return }
        Warn "tar couldn't unpack it (exit $code), trying the slower way..."
    }
    Expand-Archive -Path $Zip -DestinationPath $Dest -Force
}

function Get-AppProcesses {
    $root = $InstallDir.TrimEnd('\') + '\'
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
    })
}

# ------------------------------------------------------------------ 0. hello
Write-Host ''
Write-Host "  $AppName - beta installer" -ForegroundColor White
Write-Host "  Installing to: $InstallDir"
Write-Host "  Log file:      $LogFile"

if (-not (Test-Path (Join-Path $SourceDir 'engineer\app.py'))) {
    Fail "This installer has to be run from inside the unzipped Instability Control folder (the one with the 'engineer' folder in it). Looked in: $SourceDir"
}
$Version = 'unknown'
if (Test-Path (Join-Path $SourceDir 'VERSION')) { $Version = "$(Get-Content (Join-Path $SourceDir 'VERSION') -TotalCount 1)".Trim() }
Say "  Version:       $Version"

$running = @(Get-AppProcesses)   # 2026-11-05: @() - an empty result is $null and .Count threw under StrictMode (broke every fresh install)
if ($running.Count -gt 0) {
    Warn "$AppName is running. Please close it (and its team AI) first."
    if (Ask-YesNo 'Close it now?' $true) {
        $running | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch { } }
        Start-Sleep -Seconds 2
    } else { Fail "Close $AppName and run the installer again." }
}

# ------------------------------------------------------------------ 1. Python 3.12
Step 'Looking for Python 3.12'
function Test-Python312([string]$Exe) {
    if (-not $Exe -or -not (Test-Path $Exe)) { return $false }
    $ErrorActionPreference = 'Continue'
    $v = & $Exe -c 'import sys; print(sys.version_info[0] * 100 + sys.version_info[1])' 2>$null
    return ("$v".Trim() -eq '312')
}
$py = ''
if ($PythonExe) { if (Test-Python312 $PythonExe) { $py = $PythonExe } else { Warn "$PythonExe is not Python 3.12" } }
if (-not $py) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $ErrorActionPreference = 'Continue'
        $p = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        $ErrorActionPreference = 'Stop'
        if ($p -and (Test-Python312 "$p".Trim())) { $py = "$p".Trim() }
    }
}
if (-not $py) {
    foreach ($c in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
                     (Join-Path $env:ProgramFiles 'Python312\python.exe'),
                     'C:\Python312\python.exe')) {
        if (Test-Python312 $c) { $py = $c; break }
    }
}
if (-not $py) {
    Write-Host ''
    Write-Host '  Python 3.12 is needed and was not found on this PC.' -ForegroundColor Yellow
    Write-Host '  1. Download "Windows installer (64-bit)" for Python 3.12 from:'
    Write-Host '        https://www.python.org/downloads/release/python-31210/' -ForegroundColor White
    Write-Host '  2. Run it with the normal options (Install Now). It also installs the "py" launcher.'
    Write-Host '  3. Then double-click "Install Instability Control.cmd" again.'
    Write-Log 'Python 3.12 not found - stopped.'
    exit 2
}
Ok "Python 3.12: $py"

# ------------------------------------------------------------------ 2. program files
Step 'Copying the program'
$same = ((Resolve-Path $SourceDir).Path.TrimEnd('\') -ieq (Resolve-Path $InstallDir).Path.TrimEnd('\'))
if ($same) {
    Ok 'already running from the program folder - nothing to copy'
} else {
    $robo = Join-Path $env:SystemRoot 'System32\robocopy.exe'
    # /E = with sub-folders. No /MIR on purpose: downloaded data, generated icons and track logos stay.
    $code = Invoke-Exe $robo @((Join-Path $SourceDir 'engineer'), (Join-Path $InstallDir 'engineer'), '/E', '/XD', '__pycache__', '/XF', '*.pyc', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2') -Quiet
    if ($code -ge 8) { Fail "Couldn't copy the program files (robocopy code $code)." }
    $code = Invoke-Exe $robo @((Join-Path $SourceDir 'installer'), (Join-Path $InstallDir 'installer'), '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2') -Quiet
    if ($code -ge 8) { Fail "Couldn't copy the installer files (robocopy code $code)." }
    foreach ($f in @('VERSION', 'requirements.txt', 'LICENSE', 'LICENSE.txt', 'README.md', 'CREDITS.txt', 'CREDITS.md')) {
        $src = Join-Path $SourceDir $f
        if (Test-Path $src) { Copy-Item $src (Join-Path $InstallDir $f) -Force }
    }
    Ok 'program copied'
}

# ------------------------------------------------------------------ 3. Python packages
Step 'Setting up Python packages (the first time takes a few minutes)'
$venvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$venvPyw = Join-Path $VenvDir 'Scripts\pythonw.exe'
if ((Test-Path $venvPy) -and -not (Test-Python312 $venvPy)) {
    Warn 'The old Python environment is not 3.12 - making a new one.'
    Remove-Item $VenvDir -Recurse -Force
}
if (-not (Test-Path $venvPy)) {
    $code = Invoke-Exe $py @('-m', 'venv', $VenvDir)
    if ($code -ne 0 -or -not (Test-Path $venvPy)) { Fail "Couldn't create the Python environment in $VenvDir" }
}
$code = Invoke-Exe $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--upgrade', 'pip')
if ($code -ne 0) { Warn "Couldn't update pip (exit $code) - carrying on with the one there." }
$code = Invoke-Exe $venvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '-r', (Join-Path $InstallDir 'requirements.txt'))
if ($code -ne 0) { Fail 'Installing the Python packages failed (internet connection? see the log).' }
$code = Invoke-Exe $venvPy @('-c', 'import numpy, sounddevice, soundfile, pedalboard, PIL, yaml, sherpa_onnx, skia, irsdk, pypdf, qrcode, webview, clr; print(''imports ok'')') -Quiet
if ($code -ne 0) { Fail 'The Python packages are installed but one of them does not load (see the log).' }
Ok 'packages ready'

# ------------------------------------------------------------------ 4. speech recognition model
Step 'Speech recognition model (for talking to the team, about 480 MB)'
$asrDir = Join-Path $InstallDir "asr\$AsrName"
$asrOk = (Test-Path (Join-Path $asrDir 'tokens.txt')) -and
         (@(Get-ChildItem $asrDir -Filter 'encoder*.onnx' -ErrorAction SilentlyContinue).Count -gt 0) -and
         (@(Get-ChildItem $asrDir -Filter 'decoder*.onnx' -ErrorAction SilentlyContinue).Count -gt 0) -and
         (@(Get-ChildItem $asrDir -Filter 'joiner*.onnx'  -ErrorAction SilentlyContinue).Count -gt 0)
if ($asrOk) {
    Ok 'already installed'
} else {
    $tb = Join-Path $DownDir "$AsrName.tar.bz2"
    if (-not (Get-Download $AsrUrl $tb $AsrSize $AsrSha256)) {
        Warn "Couldn't download the speech model. Push-to-talk won't work until you run the installer again."
    } else {
        $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (-not (Test-Path $tar)) { Fail 'This Windows has no tar.exe (Windows 10 1803 or newer is needed).' }
        New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir 'asr') | Out-Null
        $code = Invoke-Exe $tar @('-xjf', $tb, '-C', (Join-Path $InstallDir 'asr')) -Quiet
        if ($code -ne 0 -or -not (Test-Path (Join-Path $asrDir 'tokens.txt'))) { Fail "Couldn't unpack the speech model (tar exit $code)." }
        Remove-Item $tb -Force
        Ok 'speech model installed'
    }
}

# ------------------------------------------------------------------ 5. voices
Step 'Voices (engineer, strategist, spotters)'
$marker = Join-Path $InstallDir 'voices_version.txt'
$have = ''; if (Test-Path $marker) { $have = "$(Get-Content $marker -TotalCount 1)".Trim() }
$haveVoices = (Test-Path (Join-Path $InstallDir 'Engineer1\vocab\manifest.json'))
$zip = ''
if ($VoicesZip) {
    if (-not (Test-Path $VoicesZip)) { Fail "voices zip not found: $VoicesZip" }
    $zip = (Resolve-Path $VoicesZip).Path
} else {
    $up1 = Split-Path -Parent $SourceDir; $up2 = Split-Path -Parent $up1
    foreach ($c in @((Join-Path $SourceDir 'voices.zip'), (Join-Path $up1 'voices.zip'), (Join-Path $up2 'voices.zip'),
                     (Join-Path $env:USERPROFILE 'Downloads\voices.zip'))) {
        if (Test-Path $c) { $zip = (Resolve-Path $c).Path; break }
    }
}
$want = $Version
if ($zip) { $want = "$Version (local zip $((Get-Item $zip).Length) bytes)" }
if ($haveVoices -and -not $ForceVoices -and ($have -eq $want -or (-not $zip -and $have.StartsWith($Version)))) {
    Ok "voices for $Version already installed (use -ForceVoices to unpack them again)"
} else {
    $sha = ''
    if ($zip) {
        Say "    using $zip"
        $sums = Join-Path (Split-Path -Parent $zip) 'SHA256SUMS.txt'
        if (Test-Path $sums) {
            $line = Get-Content $sums | Where-Object { $_ -match '\s\*?voices\.zip$' } | Select-Object -First 1
            if ($line) { $sha = ($line -split '\s+')[0] }
        }
        if ($sha) {
            Say '    checking voices.zip against SHA256SUMS.txt...'
            if ((Get-Sha256 $zip) -ne $sha.ToLower()) { Fail 'voices.zip does not match SHA256SUMS.txt - download it again.' }
            Ok 'checksum matches'
        }
    } else {
        Say "    downloading $VoicesUrl"
        $zip = Join-Path $DownDir 'voices.zip'
        $sumsFile = Join-Path $DownDir 'SHA256SUMS.txt'
        $sumsUrl = $VoicesUrl -replace '[^/]+$', 'SHA256SUMS.txt'
        if (Get-Download $sumsUrl $sumsFile) {
            $line = Get-Content $sumsFile | Where-Object { $_ -match '\s\*?voices\.zip$' } | Select-Object -First 1
            if ($line) { $sha = ($line -split '\s+')[0] }
        }
        if (-not (Get-Download $VoicesUrl $zip 0 $sha)) {
            if ($haveVoices) { Warn "Couldn't download the voices - keeping the ones already installed." ; $zip = '' }
            else {
                Fail ("Couldn't download the voices from $VoicesUrl. Check your internet connection, or download voices.zip " +
                      "from the GitHub release page yourself, put it next to the unzipped Instability Control folder " +
                      "(or in Downloads) and run the installer again.")
            }
        }
    }
    if ($zip) {
        $bad = Test-ZipSafe $zip
        if ($bad) { Fail $bad }
        Say '    unpacking (about 1 GB on disk)...'
        Expand-Zip $zip $InstallDir
        if (-not (Test-Path (Join-Path $InstallDir 'Engineer1\vocab\manifest.json'))) { Fail 'voices.zip did not contain Engineer1\vocab\manifest.json.' }
        Set-Content -Path $marker -Value $want
        if ($zip.StartsWith($DownDir)) { Remove-Item $zip -Force }
        Ok 'voices installed'
    }
}

# ------------------------------------------------------------------ 6. optional team AI
Step 'Team AI (optional - lets you chat with the engineer and mechanic off track)'
$llm = Join-Path $InstallDir 'llm'
$gguf = Join-Path $llm "models\$GgufName"
$haveServer = @(Get-ChildItem (Join-Path $llm 'bin') -Recurse -Filter 'llama-server.exe' -ErrorAction SilentlyContinue).Count -gt 0
$choice = $TeamAI
if ((Test-Path $gguf) -and $haveServer -and $choice -eq 'ask') {
    Ok 'already installed'
    $choice = 'skip'
}
if ($choice -eq 'ask') {
    if ($Yes) { $choice = 'skip' }
    else {
        Write-Host '    This is a big download: about 2.5 GB for the AI model, plus 25-660 MB for the program that runs it.'
        Write-Host '    Everything else works without it. You can add it later by running the installer again.'
        if (Ask-YesNo '    Download the team AI now?' $false) {
            Write-Host '      1 = Any graphics card - Vulkan (recommended, what the app is tuned for)'
            Write-Host '      2 = NVIDIA only - CUDA 12 (about 660 MB more to download)'
            Write-Host '      3 = No graphics card - CPU only (slow answers)'
            $n = Read-Host '    Pick 1, 2 or 3 [1]'
            switch ("$n".Trim()) { '2' { $choice = 'cuda' } '3' { $choice = 'cpu' } default { $choice = 'vulkan' } }
        } else { $choice = 'skip' }
    }
}
if ($choice -ne 'skip') {
    $zips = @()
    switch ($choice) {
        'vulkan' { $zips = @("llama-$LlamaBuild-bin-win-vulkan-x64.zip") }
        'cpu'    { $zips = @("llama-$LlamaBuild-bin-win-cpu-x64.zip") }
        'cuda'   { $zips = @("llama-$LlamaBuild-bin-win-cuda-12.4-x64.zip", 'cudart-llama-bin-win-cuda-12.4-x64.zip') }
    }
    $binDir = Join-Path $llm 'bin'
    $tmpBin = Join-Path $DownDir 'llama-bin'
    if (Test-Path $tmpBin) { Remove-Item $tmpBin -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tmpBin | Out-Null
    $okBin = $true
    foreach ($z in $zips) {
        Say "    downloading llama.cpp $LlamaBuild ($z)"
        $dz = Join-Path $DownDir $z
        if (-not (Get-Download "$LlamaBase/$z" $dz)) { $okBin = $false; break }
        Expand-Zip $dz $tmpBin
        Remove-Item $dz -Force
    }
    if ($okBin -and @(Get-ChildItem $tmpBin -Recurse -Filter 'llama-server.exe').Count -gt 0) {
        # only ONE build may sit under llm\bin: the app takes the first llama-server.exe it finds
        if (Test-Path $binDir) { Remove-Item $binDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $llm | Out-Null
        Move-Item $tmpBin $binDir
        Ok "llama.cpp ($choice) installed"
    } else {
        Warn "Couldn't get llama.cpp - the team AI stays off."
    }
    if (Test-Path $gguf) { Ok 'AI model already there' }
    else {
        Say "    downloading the AI model ($GgufName, 2.5 GB - this can take a while; it resumes if interrupted)"
        if (Get-Download $GgufUrl $gguf $GgufSize $GgufSha256) { Ok 'AI model installed' }
        else { Warn "Couldn't download the AI model. Run the installer again to resume." }
    }
} else {
    Say '    skipped'
}

# ------------------------------------------------------------------ 7. optional Apollo (PC -> TV streaming)
# Never stops the engineer install: every problem here is a warning. This script never touches Windows
# security or firewall settings and never handles Apollo's username/password - Apollo's own installer and
# web page do that, and the user answers any question they ask.
function Get-Prop($Obj, [string]$Name) {
    if ($null -eq $Obj) { return '' }
    $p = $Obj.PSObject.Properties[$Name]
    if ($p -and $null -ne $p.Value) { return "$($p.Value)" }
    return ''
}
function Find-StreamHost {
    foreach ($s in @('ApolloService', 'SunshineService')) {
        if (Get-Service -Name $s -ErrorAction SilentlyContinue) { return "$s (Windows service)" }
    }
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432) | Where-Object { $_ } | Select-Object -Unique
    foreach ($r in $roots) {
        foreach ($rel in @('Apollo\sunshine.exe', 'Apollo\apollo.exe', 'Sunshine\sunshine.exe')) {
            $p = Join-Path $r $rel
            if (Test-Path $p) { return $p }
        }
    }
    foreach ($k in @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                     'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
                     'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        foreach ($e in @(Get-ItemProperty -Path $k -ErrorAction SilentlyContinue)) {
            $name = Get-Prop $e 'DisplayName'
            if ($name -notmatch '(?i)^(Apollo|Sunshine)\b') { continue }
            # "Apollo" alone is not enough (Universal Audio has Apollo too): it has to be the streaming one
            $where = (Get-Prop $e 'Publisher') + ' ' + (Get-Prop $e 'InstallLocation') + ' ' + (Get-Prop $e 'DisplayIcon') + ' ' + (Get-Prop $e 'UninstallString')
            if ($where -match '(?i)ClassicOldSong|LizardByte|sunshine\.exe|\\Apollo\\|\\Sunshine\\') { return "$name (Settings > Apps)" }
        }
    }
    return ''
}

Step 'Apollo (optional - shows this PC on your TV)'
$apolloNew = $false
$apolloHave = ''
try {
    $apolloHave = Find-StreamHost
    $doApollo = $false
    if ($apolloHave) {
        Ok "already installed: $apolloHave"
    } elseif ($Apollo -eq 'install') {
        $doApollo = $true
    } elseif ($Apollo -eq 'ask' -and -not $Yes) {
        Write-Host '    Apollo lets you play this PC on your TV (free, small download). Windows asks for permission to install it.'
        Write-Host '    Not needed for the race engineer - say no if you are not sure.'
        $doApollo = Ask-YesNo '    Install Apollo now?' $false
    }
    if (-not $apolloHave -and -not $doApollo) { Say '    skipped (run the installer again to add it later)' }
    if ($doApollo) {
        Say '    finding the newest Apollo on GitHub...'
        $rel = Invoke-RestMethod -UseBasicParsing -Uri $ApolloApi -Headers @{ 'User-Agent' = 'InstabilityControl-installer'; 'Accept' = 'application/vnd.github+json' }
        $asset = @($rel.assets | Where-Object { (Get-Prop $_ 'name') -match '(?i)^Apollo[^/\\]*\.exe$' }) | Select-Object -First 1
        if (-not $asset) { throw 'the newest Apollo release has no Windows installer (.exe)' }
        $aName = Get-Prop $asset 'name'
        $aUrl  = Get-Prop $asset 'browser_download_url'
        $aSize = [long](Get-Prop $asset 'size')
        $aSha  = ''
        $dg = Get-Prop $asset 'digest'                          # GitHub's own checksum, e.g. "sha256:abc..."
        if ($dg -match '^sha256:([0-9a-fA-F]{64})$') { $aSha = $Matches[1] }
        if (-not $aUrl.StartsWith($ApolloFrom, [StringComparison]::OrdinalIgnoreCase) -or $aName -match '[\\/]') {
            throw "the download link is not from github.com/ClassicOldSong/Apollo: $aUrl"
        }
        Write-Log "Apollo release $(Get-Prop $rel 'tag_name'): $aUrl ($aSize bytes, sha256 '$aSha')"
        $exe = Join-Path $DownDir $aName
        Say "    downloading $aName ($([math]::Round($aSize / 1MB, 1)) MB)"
        if (-not (Get-Download $aUrl $exe $aSize $aSha)) { throw "couldn't download $aUrl" }
        try { $sig = Get-AuthenticodeSignature $exe; Write-Log ("Apollo installer signature: {0} {1}" -f $sig.Status, $sig.SignerCertificate.Subject) } catch { }

        Say '    installing Apollo - click Yes if Windows asks for permission...'
        $code = -1
        try {
            # NSIS installer: /S = silent, with Apollo's own default choices
            $p = Start-Process -FilePath $exe -ArgumentList '/S' -Verb RunAs -Wait -PassThru
            $code = $p.ExitCode
        } catch { Write-Log "Apollo silent install did not start: $($_.Exception.Message)" }
        Write-Log "Apollo silent install exit $code"
        $apolloHave = Find-StreamHost
        if (-not $apolloHave) {
            Warn 'The quiet install did not finish - opening the normal Apollo installer. Click Next / Install.'
            try {
                $p = Start-Process -FilePath $exe -Verb RunAs -Wait -PassThru
                Write-Log "Apollo installer (normal) exit $($p.ExitCode)"
            } catch { Write-Log "Apollo installer (normal) did not start: $($_.Exception.Message)" }
            $apolloHave = Find-StreamHost
        }
        if ($apolloHave) {
            $apolloNew = $true
            Ok 'Apollo installed'
            Remove-Item $exe -Force -ErrorAction SilentlyContinue
        } else {
            Warn "Apollo didn't install (permission refused?). The installer is kept here, double-click it to try again: $exe"
        }
    }
} catch {
    Warn "Apollo was not installed: $($_.Exception.Message). Everything else is fine - you can get it from https://github.com/ClassicOldSong/Apollo/releases"
}

# ------------------------------------------------------------------ 8. icon, uninstaller, shortcuts
Step 'Shortcuts and uninstaller'
$ico = Join-Path $InstallDir 'engineer\ui\assets\race_engineer.ico'
if (-not (Test-Path $ico)) {
    Push-Location $InstallDir
    try { $null = Invoke-Exe $venvPy @('-c', 'from engineer.app import ensure_icon; print(ensure_icon())') -Quiet } finally { Pop-Location }
}
if (-not (Test-Path $ico)) { $ico = $venvPyw }

$uninstPs1 = Join-Path $InstallDir 'uninstall.ps1'
Copy-Item (Join-Path $InstallDir 'installer\uninstall.ps1') $uninstPs1 -Force
$uninstCmd = Join-Path $InstallDir 'Uninstall Instability Control.cmd'
$cmdText = "@echo off`r`n" +
           "rem Copies the uninstaller out of the program folder first, so the whole folder can be removed.`r`n" +
           "copy /y `"%~dp0uninstall.ps1`" `"%TEMP%\ic_uninstall.ps1`" >nul`r`n" +
           "cd /d `"%TEMP%`" & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%TEMP%\ic_uninstall.ps1`" -InstallDir `"%~dp0.`" & pause & exit /b`r`n"
[IO.File]::WriteAllText($uninstCmd, $cmdText, [Text.Encoding]::ASCII)

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$desktop = [Environment]::GetFolderPath('Desktop')          # the real Desktop, also when OneDrive moved it
if (-not $NoShortcuts) {
    New-Shortcut (Join-Path $startMenu "$AppName.lnk") $venvPyw '-m engineer.app' $InstallDir $ico "$AppName - race engineer for iRacing"
    New-Shortcut (Join-Path $desktop "$AppName.lnk")   $venvPyw '-m engineer.app' $InstallDir $ico "$AppName - race engineer for iRacing"
    New-Shortcut (Join-Path $startMenu "Uninstall $AppName.lnk") $uninstCmd '' $env:TEMP '' "Remove $AppName"
    Ok 'Start Menu and Desktop shortcuts made'
}

# Apps & features entry (current user only, no admin)
try {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\InstabilityControl'
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name DisplayName -Value $AppName
    Set-ItemProperty -Path $key -Name DisplayVersion -Value $Version
    Set-ItemProperty -Path $key -Name Publisher -Value 'Instability Control'
    Set-ItemProperty -Path $key -Name InstallLocation -Value $InstallDir
    Set-ItemProperty -Path $key -Name DisplayIcon -Value $ico
    Set-ItemProperty -Path $key -Name UninstallString -Value "`"$uninstCmd`""
    Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord
    Ok 'listed in Settings > Apps'
} catch { Warn "Couldn't add the Apps & features entry: $($_.Exception.Message)" }

if (Test-Path $DownDir) {
    # kept when a download is half-finished (*.part) or an Apollo installer is waiting to be run again (*.exe)
    if (@(Get-ChildItem $DownDir -Recurse -File -Include '*.part', '*.exe').Count -eq 0) { Remove-Item $DownDir -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host ''
Write-Host "  All done. Start '$AppName' from the Desktop or the Start Menu." -ForegroundColor Green
Write-Host '  First time: open Settings in the app and type your first name, so the team knows what to call you.'
Write-Host "  Your memory and notes live in $UserData (kept when you update or uninstall, unless you say otherwise)."

# the Apollo walkthrough (same words as installer\APOLLO_QUICKSTART.txt)
$quick = Join-Path $InstallDir 'installer\APOLLO_QUICKSTART.txt'
if (-not (Test-Path $quick)) { $quick = Join-Path $PSScriptRoot 'APOLLO_QUICKSTART.txt' }
if ($apolloNew -and (Test-Path $quick)) {
    Write-Host ''
    Get-Content $quick | ForEach-Object { Write-Host "  $_" -ForegroundColor White }
    Write-Host "  (This text is saved in $quick)"
    Write-Log 'Apollo quick start shown'
    if (-not $Yes -and (Ask-YesNo "  Open the Apollo page ($ApolloWeb) now?" $true)) {
        try { Start-Process $ApolloWeb } catch { Warn "Couldn't open the browser - type $ApolloWeb into it." }
    }
} elseif ($apolloHave -and (Test-Path $quick)) {
    Write-Host "  TV streaming (Apollo) help: $quick"
}
Write-Log '===== install finished ====='
exit 0
