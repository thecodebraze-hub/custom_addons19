#Requires -Version 5.1
<#
.SYNOPSIS
    Build a clean Odoo Apps Store ZIP for cb_auto_backup_manager.
#>
$ErrorActionPreference = 'Stop'
$ModuleRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ModuleName = Split-Path -Leaf $ModuleRoot
$ManifestPath = Join-Path $ModuleRoot '__manifest__.py'
if (-not (Test-Path $ManifestPath)) {
    throw "Manifest not found: $ManifestPath"
}
$manifest = Get-Content $ManifestPath -Raw
if ($manifest -match "'version'\s*:\s*'([^']+)'") {
    $Version = $Matches[1]
} else {
    throw 'Could not read version from __manifest__.py'
}

$DescDir = Join-Path $ModuleRoot 'static\description'
$RequiredImages = @(
    'cover.png', 'banner.png', 'icon.png', 'developed_by.png',
    'screenshot_dashboard.png', 'screenshot_plan.png', 'screenshot_schedule.png',
    'screenshot_storage_list.png', 'screenshot_sftp.png', 'screenshot_google_drive.png',
    'screenshot_history.png', 'screenshot_verify.png', 'screenshot_restore_test.png',
    'screenshot_encryption.png'
)
$Cover = Join-Path $DescDir 'cover.png'
if (-not (Test-Path $Cover)) {
    Copy-Item (Join-Path $DescDir 'icon.png') $Cover -Force
}
foreach ($img in $RequiredImages) {
    $path = Join-Path $DescDir $img
    if (-not (Test-Path $path)) {
        Write-Warning "Missing $img - using cover.png placeholder. Replace before Apps Store submission."
        Copy-Item $Cover $path -Force
    }
}

$DistDir = Join-Path $ModuleRoot 'dist'
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
$ZipName = '{0}-{1}.zip' -f $ModuleName, $Version
$ZipPath = Join-Path $DistDir $ZipName
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

$ExcludePattern = '(\\__pycache__\\|\\\.git\\|\\\.venv\\|\\\.vscode\\|\\\.idea\\|\\dist\\|\.pyc$|\.pyo$|\.log$|\.zip$|\.enc$|\.env$|\.uploading$|\.part$)'
$TempRoot = Join-Path $env:TEMP ('odoo_apps_build_{0}' -f [guid]::NewGuid().ToString('N'))
$TempModule = Join-Path $TempRoot $ModuleName
New-Item -ItemType Directory -Force -Path $TempModule | Out-Null

Get-ChildItem -Path $ModuleRoot -Force | Where-Object {
    $_.Name -notin @('dist', '.git', '__pycache__', '.venv', 'venv')
} | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination (Join-Path $TempModule $_.Name) -Recurse -Force
}

Get-ChildItem -Path $TempModule -Recurse -Force | Where-Object {
    $_.FullName -match $ExcludePattern
} | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($TempRoot, $ZipPath)
Remove-Item $TempRoot -Recurse -Force

Write-Host "Built: $ZipPath"
Write-Host "Version: $Version | Price: USD 9.99 (set in manifest)"
Write-Host 'Next: upload at https://apps.odoo.com and replace screenshot placeholders if warnings appeared.'
