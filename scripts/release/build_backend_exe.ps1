param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Resolve-Path "$PSScriptRoot/../.."
Set-Location $root

if (-not (Test-Path "release/windows/chronos-win-portable.spec")) {
  Write-Error "PyInstaller spec file not found at release/windows/chronos-win-portable.spec"
}

Write-Host "[chronos] Syncing release extras (pyinstaller)..."
uv sync --extra release

Write-Host "[chronos] Building backend exe via PyInstaller..."
uv run --extra release pyinstaller --noconfirm --clean "release/windows/chronos-win-portable.spec"

Write-Host "[chronos] Backend exe built under dist/chronos/"

# --- Tauri sidecar packaging -------------------------------------------------
# PyInstaller's onedir output is chronos.exe plus a sibling _internal/ folder
# it depends on at runtime (bundled Python DLLs/data) -- it is NOT a single
# self-contained file. Tauri's externalBin convention only manages a single
# named binary, so the _internal/ folder is shipped separately as a bundled
# resource (see tauri.conf.json bundle.resources) and placed so it ends up
# beside the sidecar exe in the installed app (resourceDir() == the main exe's
# own directory on Windows, where sidecar binaries also land).
$targetTriple = (rustc -vV | Select-String '^host:\s*(\S+)').Matches[0].Groups[1].Value
Write-Host "[chronos] Packaging sidecar for target triple: $targetTriple"

$sidecarBinariesDir = "src-tauri/binaries"
$sidecarResourcesDir = "src-tauri/resources"
New-Item -ItemType Directory -Force -Path $sidecarBinariesDir | Out-Null

# Remove any stale _internal/ before copying: Copy-Item -Recurse nests the source
# folder INSIDE an already-existing destination folder instead of merging into it
# (e.g. resources/_internal/_internal/... ), so the destination must not pre-exist.
Remove-Item -Recurse -Force "$sidecarResourcesDir/_internal" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $sidecarResourcesDir | Out-Null

Copy-Item -Path "dist/chronos/chronos.exe" -Destination "$sidecarBinariesDir/chronos-$targetTriple.exe" -Force
Copy-Item -Path "dist/chronos/_internal" -Destination "$sidecarResourcesDir/_internal" -Recurse -Force

# First-run seeding source: the retired start.bat used to copy config.example.json
# to config/config.json (and mkdir data/) beside chronos.exe before launching it --
# the Tauri shell now does that same seeding (see src-tauri/src/lib.rs), reading
# this bundled copy via resource_dir(), which is the sidecar exe's own directory
# on Windows (same as bundle.resources destination "").
Copy-Item -Path "config/config.example.json" -Destination "$sidecarResourcesDir/config.example.json" -Force
Copy-Item -Path "config/model_catalog.json" -Destination "$sidecarResourcesDir/model_catalog.json" -Force

Write-Host "[chronos] Sidecar binary + resources staged under src-tauri/ for Tauri bundling"

