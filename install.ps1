<#
WordScroll one-time setup.

Run this once (right-click -> "Run with PowerShell", or from a terminal:
powershell -ExecutionPolicy Bypass -File install.ps1). It creates the Python
virtual environment, installs both the backend and app dependencies, and
adds a "WordScroll" shortcut to your Desktop that launches the app from
then on - no compiled installer, since PyInstaller-built executables get
flagged by Windows Application Control on machines with strict policies
(see README.md's Packaging section). This runs everything through the
already-installed, already-trusted python.exe and node/electron instead.
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$appDir = Join-Path $root "app"

Write-Host "== WordScroll setup ==" -ForegroundColor Cyan
Write-Host ""

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found on PATH. Install Python 3.11+ from https://python.org (check 'Add python.exe to PATH' during install), then re-run this script."
}
Write-Host "Found Python: $($python.Source)"

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Error "npm not found on PATH. Install Node.js (LTS) from https://nodejs.org, then re-run this script."
}
Write-Host "Found npm: $($npm.Source)"
Write-Host ""

$venvPython = Join-Path $backend "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
    & python -m venv (Join-Path $backend "venv")
} else {
    Write-Host "Python virtual environment already exists - skipping creation."
}

Write-Host "Installing backend dependencies (this can take a few minutes the first time)..." -ForegroundColor Yellow
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $backend "requirements.txt")
Write-Host "Backend dependencies installed."
Write-Host ""

Write-Host "Installing app dependencies..." -ForegroundColor Yellow
Push-Location $appDir
& npm install
Pop-Location
Write-Host "App dependencies installed."
Write-Host ""

# Points straight at electron.exe - deliberately NOT at a .ps1/.bat wrapper.
# A shortcut that launches PowerShell first (even hidden) flashes a console
# window before the app appears, which reads as broken/scary to a
# non-technical operator, and double-clicking a .ps1 directly triggers
# Windows' "how do you want to open this file?" dialog since there's no
# default handler to run one. electron.exe itself is a normal windowed .exe
# with no console at all, so this is a clean, ordinary double-click.
$electron = Join-Path $appDir "node_modules\electron\dist\electron.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "WordScroll.lnk"
$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $electron
$shortcut.Arguments = "."
$shortcut.WorkingDirectory = $appDir
$shortcut.Description = "WordScroll - real-time scripture detection & display"
$iconPath = Join-Path $root "wordscroll.ico"
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "A 'WordScroll' shortcut was added to your Desktop - double-click it to launch the app from now on."
if (-not (Test-Path $iconPath)) {
    Write-Host "(Using Electron's default icon for now - drop a wordscroll.ico in this folder and re-run install.ps1 to brand it.)"
}
Write-Host "First-ever use of live transcription will download the Whisper speech model (~500MB, needs internet once)."
