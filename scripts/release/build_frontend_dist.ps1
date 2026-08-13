param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot/../.."
Set-Location "$root/src/frontend"

if (-not (Test-Path "package.json")) {
  Write-Error "package.json not found in src/frontend; are you in the right repo?"
}

Write-Host "[chronos] Installing frontend dependencies..."
npm install

Write-Host "[chronos] Building frontend dist..."
npm run build

Write-Host "[chronos] Frontend dist built at src/frontend/dist"

