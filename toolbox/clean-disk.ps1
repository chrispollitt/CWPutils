<#
.SYNOPSIS
    Safe non-admin disk cleanup.

.DESCRIPTION
    Cleans:
      - User temp files
      - WinGet download leftovers
      - VS Code installer leftovers
      - Recycle Bin
      - Optional Edge cache storage

    Does NOT remove:
      - OneDrive data
      - Outlook data
      - Documents
      - Downloads
      - Browser profiles
      - Passwords
      - Cookies

.NOTES
    Runs in preview mode by default.
#>

param(
    [switch]$DoIt,
    [switch]$CleanEdge
)

$WhatIfPreference = -not $DoIt

function Get-FolderSizeGB {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return 0
    }

    try {
        $sum = (Get-ChildItem $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
            Measure-Object Length -Sum).Sum

        [Math]::Round(($sum / 1GB), 2)
    }
    catch {
        0
    }
}

function Remove-SafeFolder {
    param([string]$Path)

    if (Test-Path $Path) {
        Write-Host "Cleaning: $Path" -ForegroundColor Yellow

        Get-ChildItem $Path -Force -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -WhatIf:$WhatIfPreference
    }
}

Write-Host ""
Write-Host "=== SAFE DISK CLEANUP ===" -ForegroundColor Cyan

$tempFolders = @(
    "$env:TEMP",
    "$env:LOCALAPPDATA\Temp",
    "$env:LOCALAPPDATA\WinGet"
)

Write-Host ""
Write-Host "Potential cleanup areas:" -ForegroundColor Green

foreach ($folder in $tempFolders) {
    if (Test-Path $folder) {
        $size = Get-FolderSizeGB $folder
        "{0,-60} {1,8} GB" -f $folder, $size
    }
}

$vscode = Get-ChildItem "$env:LOCALAPPDATA\Temp" -Directory -ErrorAction SilentlyContinue |
    Where-Object Name -like "vscode*"

if ($vscode) {
    Write-Host ""
    Write-Host "VS Code installer remnants detected:"
    $vscode.FullName
}

if ($CleanEdge) {

    $edgeTargets = @(
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 1\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 1\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 2\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 2\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 3\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 3\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 4\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 4\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 5\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 5\Code Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 6\Cache",
        "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Profile 6\Code Cache"
    )

    Write-Host ""
    Write-Host "Edge cache targets:" -ForegroundColor Green

    foreach ($path in $edgeTargets) {
        if (Test-Path $path) {
            "{0,-80} {1,8} GB" -f $path, (Get-FolderSizeGB $path)
        }
    }
}

Write-Host ""
Write-Host "Starting cleanup..." -ForegroundColor Cyan

foreach ($folder in $tempFolders) {
    Remove-SafeFolder $folder
}

Get-ChildItem "$env:LOCALAPPDATA\Temp" -Directory -ErrorAction SilentlyContinue |
    Where-Object Name -like "vscode*" |
    ForEach-Object {
        Remove-SafeFolder $_.FullName
    }

if ($CleanEdge) {

    Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force

    Start-Sleep 2

    Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Edge\User Data" `
        -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {

            $cache1 = Join-Path $_.FullName "Cache"
            $cache2 = Join-Path $_.FullName "Code Cache"

            Remove-SafeFolder $cache1
            Remove-SafeFolder $cache2
        }
}

try {
    Clear-RecycleBin -Force -WhatIf:$WhatIfPreference
}
catch {
    Write-Warning "Could not empty Recycle Bin."
}

Write-Host ""
Write-Host "Done."
Write-Host ""

if (-not $DoIt) {
    Write-Host "Preview mode only." -ForegroundColor Yellow
    Write-Host "Run with: .\Safe-DiskCleanup.ps1 -DoIt"
    Write-Host ""
    Write-Host "To also clean Edge caches:"
    Write-Host "    .\Safe-DiskCleanup.ps1 -DoIt -CleanEdge"
}