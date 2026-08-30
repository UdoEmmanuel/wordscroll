<#
Builds a clean distributable zip of WordScroll - everything needed to run
it on another PC, nothing that's specific to *this* one. Excludes:
  - backend/venv       (Python environment - recreated fresh by install.ps1)
  - app/node_modules   (npm packages - reinstalled fresh by install.ps1)
  - backend/data        (THIS PC's saved favorites/history/theme/queue - a
                          fresh install should start clean, not inherit it)
  - logs/, __pycache__  (transient/regenerable)
  - wordscroll-source.png (the raw icon source - only wordscroll.ico matters
                          at runtime)

Run this, then hand the resulting zip to a USB drive / OneDrive / Nearby
Share - see README.md's "Distribution" section for the full picture,
including how to update an existing install without losing its saved data.
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format "yyyy-MM-dd"
$zipPath = Join-Path $root "WordScroll-$stamp.zip"
$staging = Join-Path $env:TEMP "wordscroll-package-staging"

if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

Write-Host "Staging files..." -ForegroundColor Cyan

# app/ - source and package manifests only, not node_modules
New-Item -ItemType Directory -Path (Join-Path $staging "app") | Out-Null
Copy-Item (Join-Path $root "app\src") (Join-Path $staging "app\src") -Recurse
Copy-Item (Join-Path $root "app\package.json") (Join-Path $staging "app\")
$lock = Join-Path $root "app\package-lock.json"
if (Test-Path $lock) { Copy-Item $lock (Join-Path $staging "app\") }

# backend/ - Python source and bundled Bible data only, not venv/data/cache
New-Item -ItemType Directory -Path (Join-Path $staging "backend") | Out-Null
Copy-Item (Join-Path $root "backend\*.py") (Join-Path $staging "backend\")
Copy-Item (Join-Path $root "backend\bible_data") (Join-Path $staging "backend\bible_data") -Recurse
Copy-Item (Join-Path $root "backend\overlay") (Join-Path $staging "backend\overlay") -Recurse
Copy-Item (Join-Path $root "backend\requirements.txt") (Join-Path $staging "backend\")

# Root-level: setup/launch scripts, icon, docs
foreach ($f in @("install.ps1", "Start WordScroll.ps1", "wordscroll.ico", "README.md")) {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $staging $f) }
}

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "Compressing..." -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath

Remove-Item $staging -Recurse -Force

$sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Done: $zipPath ($sizeMB MB)" -ForegroundColor Green
Write-Host "Drop this on a USB drive, OneDrive, or Nearby Share to move it to another PC."
Write-Host "On that PC: unzip anywhere, then right-click install.ps1 -> Run with PowerShell."
