<#
  Instability Control - uninstaller (beta, 2026-10-24)

  Removes the program folder, the shortcuts and the Apps & features entry.
  Asks before deleting your own data in %LOCALAPPDATA%\RaceEngineer (memory, notes, cache, Garage 61 key).
  Normally started by "Uninstall Instability Control.cmd" (it copies this file to %TEMP% first, so the
  whole program folder can be deleted).
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\InstabilityControl'),
    [switch]$Yes,              # don't ask: removes the program, KEEPS your data
    [switch]$DeleteUserData    # with -Yes: also delete %LOCALAPPDATA%\RaceEngineer
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$AppName  = 'Instability Control'
$UserData = Join-Path $env:LOCALAPPDATA 'RaceEngineer'
$InstallDir = [IO.Path]::GetFullPath($InstallDir.TrimEnd('\', '.') )
Set-Location $env:TEMP          # never sit inside the folder we are deleting

function Ask-YesNo([string]$Question, [bool]$Default = $false) {
    if ($Yes) { return $Default }
    $hint = '[y/N]'; if ($Default) { $hint = '[Y/n]' }
    $a = Read-Host "$Question $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $Default }
    return ($a.Trim().ToLower().StartsWith('y'))
}

Write-Host ''
Write-Host "  $AppName - uninstall" -ForegroundColor White
Write-Host "  Program folder: $InstallDir"

# safety: only ever delete a folder that really is an Instability Control install
if (-not (Test-Path (Join-Path $InstallDir 'engineer\app.py'))) {
    Write-Host "  That folder doesn't look like an $AppName install - nothing was deleted." -ForegroundColor Yellow
    exit 1
}
$docs = [Environment]::GetFolderPath('MyDocuments')
if ($InstallDir -ieq $env:LOCALAPPDATA -or $InstallDir -ieq $env:USERPROFILE -or $InstallDir -ieq $docs -or
    $InstallDir -ieq (Join-Path $docs 'CrewChiefVoices') -or $InstallDir.Length -lt 8) {
    Write-Host "  Refusing to delete $InstallDir (that is not a folder the installer made)." -ForegroundColor Yellow
    exit 1
}
if (-not (Ask-YesNo "  Remove $AppName from this PC?" $true)) { Write-Host '  Nothing was changed.'; exit 0 }

# 1. close it (the app and its team AI run from inside the program folder)
$root = $InstallDir.TrimEnd('\') + '\'
$procs = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } catch { $false } })
if ($procs.Count -gt 0) {
    Write-Host "  Closing $AppName..."
    $procs | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch { } }
    Start-Sleep -Seconds 2
}

# 2. ask about the user's own data BEFORE the program folder (and its settings file) is gone
$deleteData = $false
if (Test-Path $UserData) {
    if ($Yes) { $deleteData = [bool]$DeleteUserData }
    else {
        Write-Host ''
        Write-Host "  Your own data is in $UserData"
        Write-Host '  (what the team remembers about your driving, your notes, the Garage 61 key, the telemetry cache).'
        $deleteData = Ask-YesNo '  Delete your data too? Say no if you might install again.' $false
    }
}
$settings = Join-Path $InstallDir 'engineer_settings.json'
if (-not $deleteData -and (Test-Path $settings)) {
    New-Item -ItemType Directory -Force -Path $UserData | Out-Null
    Copy-Item $settings (Join-Path $UserData 'engineer_settings.backup.json') -Force
    Write-Host "  Your settings were saved to $UserData\engineer_settings.backup.json"
}

# 3. shortcuts, Windows-startup entry, Apps & features entry
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($l in @((Join-Path $startMenu "$AppName.lnk"), (Join-Path $startMenu "Uninstall $AppName.lnk"), (Join-Path $desktop "$AppName.lnk"))) {
    if (Test-Path $l) { Remove-Item $l -Force }
}
$startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Race Engineer.bat'
if ((Test-Path $startup) -and ((Get-Content $startup -Raw) -like "*$InstallDir*")) { Remove-Item $startup -Force }
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\InstabilityControl'
if (Test-Path $key) { Remove-Item $key -Recurse -Force }

# 4. the program folder
Write-Host '  Removing the program folder (voices, speech model, team AI)...'
try {
    Remove-Item $InstallDir -Recurse -Force
} catch {
    Start-Sleep -Seconds 3
    try { Remove-Item $InstallDir -Recurse -Force } catch {
        Write-Host "  Some files couldn't be removed (still in use?). Delete this folder by hand: $InstallDir" -ForegroundColor Yellow
    }
}

# 5. the user's data, only when they said yes
if ($deleteData -and (Test-Path $UserData)) {
    Remove-Item $UserData -Recurse -Force
    Write-Host '  Your data was deleted.'
} elseif (Test-Path $UserData) {
    Write-Host "  Your data was kept in $UserData"
}
Write-Host ''
Write-Host "  $AppName has been removed." -ForegroundColor Green
# Apollo (TV streaming) is left alone on purpose - other things may use it
Write-Host '  Apollo (TV streaming) was kept. To remove it too: Windows Settings > Apps > Apollo > Uninstall.'
exit 0
