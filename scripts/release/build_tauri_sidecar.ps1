param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot/../.."
Set-Location $root

# Tauri's beforeBuildCommand only accepts a single shell command, so this wrapper
# chains the two existing release steps: frontend dist (embedded by the PyInstaller
# spec) must exist before the backend exe is built.
Write-Host "[chronos] === Step 1/2: frontend dist ==="
& "$PSScriptRoot/build_frontend_dist.ps1"

Write-Host "[chronos] === Step 2/2: backend exe + sidecar staging ==="
& "$PSScriptRoot/build_backend_exe.ps1"

Write-Host "[chronos] Tauri sidecar build pipeline complete."
