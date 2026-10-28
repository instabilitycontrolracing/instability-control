<#
  Instability Control - build the beta release files (run on the OWNER's PC only). beta (2026-10-24)

  Makes, in <Out> (default: Documents\CrewChiefVoices\dist):
    voices.zip                               engineer / strategist / built-in spotter voices, schedules, app images
    InstabilityControl-<version>-code.zip    the program, straight from the clean git copy (git archive HEAD)
    SHA256SUMS.txt                           checksums of both (the installer checks voices.zip against it)
    APOLLO_QUICKSTART.txt                    the short PC -> TV (Apollo) walkthrough (also inside the code zip)

  voices.zip is built from an ALLOW-LIST (only the folders below), then every file name is checked again and
  the build FAILS if anything personal slipped in (RaceControl, the Clare spotter, settings, tokens, .ibt, ...).

  Usage (PowerShell):
    powershell -NoProfile -ExecutionPolicy Bypass -File build_release.ps1
    ... -Data "D:\elsewhere\CrewChiefVoices" -Repo "D:\code\instability-control" -IncludeTrackLogos
#>
[CmdletBinding()]
param(
    [string]$Data = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'CrewChiefVoices'),
    [string]$Repo = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'InstabilityControl\instability-control'),
    [string]$Out = '',
    [string[]]$Spotters = @('Max', 'Jess', 'Leo'),
    [switch]$IncludeTrackLogos,      # engineer\ui\assets\tracks (third-party track logos) - off by default
    [switch]$SkipVoices,
    [switch]$AllowDirty              # build the code zip even if the git copy has uncommitted changes
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
if (-not $Out) { $Out = Join-Path $Data 'dist' }

function Step([string]$t) { Write-Host ''; Write-Host "==> $t" -ForegroundColor Cyan }
function Fail([string]$t) { Write-Host ''; Write-Host "BUILD FAILED: $t" -ForegroundColor Red; exit 1 }
function Ok([string]$t)   { Write-Host "    OK  $t" -ForegroundColor Green }

# Never ship these, wherever they are (checked on every path inside voices.zip, case-insensitive).
# Finding one of these FAILS the build:
$Critical = @(
    '(^|/)RaceControl(/|$)',            # the owner's personal race-control clips
    '(^|/)Clare(/|$)', 'spotter_Clare', # the owner's personal CrewChief spotter copy
    'engineer_settings[^/]*\.json$',    # settings (device names, remote key, ...)
    '[^/]*(token|secret|password|credential)[^/]*\.(txt|json|key|dat|ini|cfg)$', '\.key$', '\.pem$', '(^|/)\.env$',
    '\.ibt$',                           # telemetry
    '(^|/)venv',                        # Python environments
    'account_[^/]*\.json$',             # schedule data from the owner's iRacing login
    '(?i)TVoice', '(?i)(^|/)ref_[^/]*\.wav$', '(?i)(^|/)(baseline|stems|engine_tests)(/|$)'   # voice-cloning sources
)
# These are quietly left out (leftovers that don't belong in a release):
$Skip = @('(^|/)__pycache__(/|$)', '\.pyc$', '\.bak$', 'backup', '(^|/)_dev(/|$)', '(^|/)_old(/|$)',
          '(?:^|/)[^/]*_log\.txt$', '(^|/)_old[^/]*(/|$)', '(^|/)raw(/|$)', '(^|/)_ref\.wav$', '(?:^|/)[^/]*_err\.txt$', '(^|/)STATUS\.txt$')
function Test-Match([string]$rel, [string[]]$rules) {
    $r = $rel -replace '\\', '/'
    foreach ($p in $rules) { if ($r -match "(?i)$p") { return $p } }
    return ''
}
function Test-Forbidden([string]$rel) { $h = Test-Match $rel $Critical; if (-not $h) { $h = Test-Match $rel $Skip }; return $h }
function Get-Rel([string]$base, [string]$full) { return ($full.Substring($base.TrimEnd('\', '/').Length + 1) -replace '\\', '/') }   # always a/b/c
$Junk = '(?i)(/|^)(Thumbs\.db|desktop\.ini|\.DS_Store)$'

# ---------------------------------------------------------------- version
Step 'Version'
if (-not (Test-Path (Join-Path $Repo '.git'))) { Fail "No git copy at $Repo (use -Repo)." }
$git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $git) { Fail 'git is not installed (or not on PATH).' }
$ErrorActionPreference = 'Continue'
$version = "$(& $git.Source -C $Repo show HEAD:VERSION 2>$null)".Trim()
if (-not $version) {
    $appPy = "$(& $git.Source -C $Repo show HEAD:engineer/app.py 2>$null)"
    $m = [regex]::Match($appPy, 'VERSION\s*=\s*"([^"]+)"')
    if ($m.Success) { $version = ($m.Groups[1].Value -replace '\s+', '-') }
}
$dirty = "$(& $git.Source -C $Repo status --porcelain 2>$null)".Trim()
$head = "$(& $git.Source -C $Repo rev-parse --short HEAD 2>$null)".Trim()
$ErrorActionPreference = 'Stop'
if (-not $version) { Fail 'No VERSION file and no VERSION = "..." in engineer/app.py at HEAD.' }
Ok "version $version (commit $head)"
if ($dirty -and -not $AllowDirty) { Fail "The git copy has uncommitted changes - commit them first (or use -AllowDirty; the zip is HEAD either way):`n$dirty" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# ---------------------------------------------------------------- code zip
Step 'Code zip (git archive HEAD)'
$codeZip = Join-Path $Out "InstabilityControl-$version-code.zip"
if (Test-Path $codeZip) { Remove-Item $codeZip -Force }
$ErrorActionPreference = 'Continue'
& $git.Source -C $Repo archive --format=zip "--prefix=InstabilityControl-$version/" -o $codeZip HEAD
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($code -ne 0 -or -not (Test-Path $codeZip)) { Fail "git archive failed (exit $code)." }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [IO.Compression.ZipFile]::OpenRead($codeZip)
try {
    $names = @($z.Entries | ForEach-Object { $_.FullName })
    foreach ($need in @('engineer/app.py', 'requirements.txt', 'installer/install.ps1', 'installer/Install Instability Control.cmd', 'installer/APOLLO_QUICKSTART.txt')) {
        if (-not ($names | Where-Object { $_ -eq "InstabilityControl-$version/$need" })) { Fail "the code zip has no $need - is it committed?" }
    }
    foreach ($n in $names) {
        $r = $n -replace '^[^/]+/', ''
        if ($r -match '(?i)(engineer_settings[^/]*\.json$|[^/]*token[^/]*\.(txt|json|key|dat|ini)$|\.ibt$|(^|/)RaceControl/|(^|/)Clare/|(^|/)venv)') { Fail "the code zip contains $n" }
    }
} finally { $z.Dispose() }
Ok "$codeZip ($([math]::Round((Get-Item $codeZip).Length / 1MB, 1)) MB)"
# the Apollo (PC -> TV) quick start also goes next to the zips, so testers can read it before installing
$quickSrc = Join-Path $Repo 'installer\APOLLO_QUICKSTART.txt'
if (Test-Path $quickSrc) { Copy-Item $quickSrc (Join-Path $Out 'APOLLO_QUICKSTART.txt') -Force; Ok 'APOLLO_QUICKSTART.txt' }

# ---------------------------------------------------------------- voices zip
$voicesZip = Join-Path $Out 'voices.zip'
if (-not $SkipVoices) {
    Step "Voices zip from $Data (allow-list)"
    if (-not (Test-Path (Join-Path $Data 'Engineer1\vocab\manifest.json'))) { Fail "No Engineer1\vocab\manifest.json under $Data (use -Data)." }

    # ALLOW-LIST: folder (relative to $Data) -> which files from it. Nothing else is ever looked at.
    $allow = New-Object System.Collections.ArrayList
    # only the finished clips the app plays: never the cloning source, reference clips, stems or engine tests
    [void]$allow.Add(@{ Dir = 'Engineer1\vocab';  Filter = '*'; Recurse = $true;  Need = $true })
    foreach ($eng in @('chatterbox', 'f5')) {
        foreach ($sub in @('f', 's')) { [void]$allow.Add(@{ Dir = "Strategist\$eng\$sub"; Filter = '*'; Recurse = $true; Need = $false }) }
        [void]$allow.Add(@{ Dir = "Strategist\$eng"; Filter = '*.json'; Recurse = $false; Need = $false })
    }
    foreach ($s in $Spotters) {
        if ($s -ieq 'Clare') { Fail 'Clare is the personal CrewChief spotter and is never shipped.' }
        [void]$allow.Add(@{ Dir = "Spotter\$s"; Filter = '*'; Recurse = $true; Need = $true })
    }
    # parsed public season schedules only: account_*.json comes from the owner's iRacing login, and the PDF is iRacing's
    [void]$allow.Add(@{ Dir = 'schedules'; Filter = '*_parsed.json'; Recurse = $false; Need = $false })
    [void]$allow.Add(@{ Dir = 'tools';     Filter = 'radio_preset.json'; Recurse = $false; Need = $false })
    # the app's own images and fonts (not in git): fonts are SIL OFL, dial/icon are ours
    # dial / icon come from the public git copy below (the owner's working copy may hold personal images)
    foreach ($f in @('*.ttf', '*.otf', '*.txt')) {
        [void]$allow.Add(@{ Dir = 'engineer\ui\assets'; Filter = $f; Recurse = $false; Need = $false })
    }
    [void]$allow.Add(@{ Dir = 'engineer\ui\ipad'; Filter = '*.png'; Recurse = $false; Need = $false })
    if ($IncludeTrackLogos) { [void]$allow.Add(@{ Dir = 'engineer\ui\assets\tracks'; Filter = '*.png'; Recurse = $false; Need = $false }) }
    foreach ($f in @('CREDITS*', 'LICENSE*')) { [void]$allow.Add(@{ Dir = ''; Filter = $f; Recurse = $false; Need = $false }) }

    $files = @{}
    foreach ($a in $allow) {
        $dir = $Data; if ($a.Dir) { $dir = Join-Path $Data $a.Dir }
        if (-not (Test-Path $dir -PathType Container)) {
            if ($a.Need) { Fail "missing folder: $dir" } else { continue }
        }
        $items = @(Get-ChildItem -Path $dir -Filter $a.Filter -File -Recurse:([bool]$a.Recurse) -Force -ErrorAction Stop)
        if ($a.Need -and $items.Count -eq 0) { Fail "empty folder: $dir" }
        foreach ($i in $items) {
            $rel = Get-Rel $Data $i.FullName
            if ($rel -match $Junk) { continue }
            $hit = Test-Match $rel $Critical
            if ($hit) { Fail "found something that must never ship: $($i.FullName)  (rule '$hit'). Move it out of $Data or rename it, then build again." }
            $hit = Test-Match $rel $Skip
            if ($hit) { Write-Host "    left out ($hit): $rel" -ForegroundColor DarkYellow; continue }
            $files[$rel] = $i.FullName
        }
    }
    foreach ($f in @('dial.png', 'race_engineer.png', 'race_engineer.ico')) {
        $pub = Join-Path $Repo "engineer\ui\assets\$f"
        if (Test-Path $pub) { $files["engineer/ui/assets/$f"] = $pub }
    }
    # the Strategist voice credit (CC BY 3.0) must travel with it
    $credits = @($files.Keys | Where-Object { $_ -match '(?i)(^|/)(CREDITS|LICENSE)[^/]*$' })
    $tmpCredits = $null
    if (-not ($credits | Where-Object { $_ -match '(?i)^(Strategist/)?CREDITS' })) {
        $tmpCredits = Join-Path $env:TEMP 'ic_CREDITS.txt'
        $txt = "Instability Control - voice credits`r`n`r`n" +
               "Strategist voice: based on a voice recording by tender_buttons, licensed under Creative Commons`r`n" +
               "Attribution 3.0 (CC BY 3.0) - https://creativecommons.org/licenses/by/3.0/`r`n" +
               "The Strategist clips were rendered from it for Instability Control.`r`n"
        [IO.File]::WriteAllText($tmpCredits, $txt, [Text.Encoding]::ASCII)
        $files['CREDITS.txt'] = $tmpCredits
        Write-Host '    no CREDITS file found - wrote CREDITS.txt (CC BY 3.0, tender_buttons). Check the wording.' -ForegroundColor Yellow
    }

    # FINAL CHECK: every path again, plus personal text in the schedule files
    $problems = @()
    foreach ($rel in $files.Keys) {
        $hit = Test-Forbidden $rel
        if ($hit) { $problems += "$rel  (rule $hit)" }
        if ($rel -match '(?i)^Spotter/([^/]+)/') {
            if ($Spotters -notcontains $Matches[1]) { $problems += "$rel  (spotter not on the list)" }
        }
    }
    foreach ($rel in @($files.Keys | Where-Object { $_ -match '(?i)^schedules/.*\.json$' })) {
        $t = [IO.File]::ReadAllText($files[$rel])
        # private words (your name, username...) live in a local file that is never committed, one per line
        $priv = @($env:USERNAME, 'cust_id', 'custid', 'email')
        $pf = Join-Path $env:LOCALAPPDATA 'RaceEngineer\private_words.txt'
        if (Test-Path $pf) { $priv += @(Get-Content $pf | Where-Object { $_.Trim() }) }
        foreach ($w in ($priv | Where-Object { $_ })) {
            if ($t -match [regex]::Escape($w)) { $problems += "$rel  (contains '$w')" }
        }
    }
    if ($problems.Count -gt 0) { Fail ("these must not ship:`n  " + ($problems -join "`n  ") + "`n(If a schedule file is the problem, move it out of the schedules folder and build again.)") }

    $total = 0L; foreach ($v in $files.Values) { $total += (Get-Item $v).Length }
    $byTop = $files.Keys | Group-Object { ($_ -split '/')[0] + $(if ($_ -match '^Spotter/') { '/' + ($_ -split '/')[1] } else { '' }) }
    foreach ($g in $byTop) { Write-Host ("    {0,-22} {1,6} files" -f $g.Name, $g.Count) }
    Write-Host ("    total {0} files, {1:N0} MB before zipping" -f $files.Count, ($total / 1MB))

    if (Test-Path $voicesZip) { Remove-Item $voicesZip -Force }
    Add-Type -AssemblyName System.IO.Compression
    $fs = [IO.File]::Open($voicesZip, [IO.FileMode]::CreateNew)
    $zip = New-Object IO.Compression.ZipArchive($fs, [IO.Compression.ZipArchiveMode]::Create)
    try {
        $n = 0
        foreach ($rel in ($files.Keys | Sort-Object)) {
            $entry = $zip.CreateEntry(($rel -replace '\\', '/'), [IO.Compression.CompressionLevel]::Optimal)
            $entry.LastWriteTime = (Get-Item $files[$rel]).LastWriteTime
            $es = $entry.Open(); $src = [IO.File]::OpenRead($files[$rel])
            try { $src.CopyTo($es) } finally { $src.Dispose(); $es.Dispose() }
            $n++; if ($n % 500 -eq 0) { Write-Host "    zipped $n / $($files.Count)" }
        }
    } finally { $zip.Dispose(); $fs.Dispose() }
    if ($tmpCredits) { Remove-Item $tmpCredits -Force -ErrorAction SilentlyContinue }

    # re-open the finished zip and check it once more (what testers will actually get)
    $z = [IO.Compression.ZipFile]::OpenRead($voicesZip)
    try {
        foreach ($e in $z.Entries) { if (Test-Forbidden $e.FullName) { Fail "voices.zip contains $($e.FullName)" } }
        if (-not ($z.Entries | Where-Object { $_.FullName -eq 'Engineer1/vocab/manifest.json' })) { Fail 'voices.zip has no Engineer1/vocab/manifest.json' }
    } finally { $z.Dispose() }
    Ok "$voicesZip ($([math]::Round((Get-Item $voicesZip).Length / 1MB, 1)) MB)"
}

# ---------------------------------------------------------------- checksums
Step 'SHA-256 checksums'
$lines = @()
foreach ($f in @($voicesZip, $codeZip)) {
    if (Test-Path $f) { $lines += ('{0}  {1}' -f (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower(), (Split-Path -Leaf $f)) }
}
[IO.File]::WriteAllText((Join-Path $Out 'SHA256SUMS.txt'), (($lines -join "`n") + "`n"), [Text.Encoding]::ASCII)
$lines | ForEach-Object { Write-Host "    $_" }
Write-Host ''
Write-Host "  Release $version is ready in $Out" -ForegroundColor Green
Write-Host '  Upload voices.zip, the code zip and SHA256SUMS.txt to the GitHub release (tag v' -NoNewline
Write-Host "$version), or hand them to testers directly."
exit 0
