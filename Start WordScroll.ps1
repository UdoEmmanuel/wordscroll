<#
Optional: launches WordScroll from a terminal, for watching startup output
live (e.g. while troubleshooting). NOT what the Desktop shortcut uses -
that points straight at electron.exe (see install.ps1) so double-clicking
it is an ordinary silent app launch with no PowerShell console involved.
Persistent logging to logs/ happens inside the app itself either way (see
app/src/main.js) - this script's terminal output is just a live view on
top of that, not the only place logs go.
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "app"
$electron = Join-Path $appDir "node_modules\electron\dist\electron.exe"

if (-not (Test-Path $electron)) {
    Write-Error "WordScroll isn't set up yet. Run install.ps1 first (see README.md)."
    exit 1
}

Push-Location $appDir
& $electron "."
Pop-Location
