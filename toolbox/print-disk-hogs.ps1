# DiskHogs.ps1
# Find what's eating storage on a Windows 11 workstation

$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "=== DISK SUMMARY ===" -ForegroundColor Cyan

Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" |
    Select-Object DeviceID,
                  @{N='SizeGB';E={[math]::Round($_.Size/1GB,1)}},
                  @{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,1)}},
                  @{N='UsedGB';E={[math]::Round(($_.Size-$_.FreeSpace)/1GB,1)}} |
    Format-Table -Auto

$ProfilePath = $env:USERPROFILE

Write-Host ""
Write-Host "=== LARGEST FOLDERS IN PROFILE ===" -ForegroundColor Cyan

Get-ChildItem $ProfilePath -Directory -Force |
    ForEach-Object {
        [PSCustomObject]@{
            SizeGB = [math]::Round(
                (
                    Get-ChildItem $_.FullName -Recurse -Force -File -EA SilentlyContinue |
                    Measure-Object Length -Sum
                ).Sum / 1GB,2)
            Path = $_.FullName
        }
    } |
    Sort-Object SizeGB -Descending |
    Select-Object -First 20 |
    Format-Table -Auto

Write-Host ""
Write-Host "=== APPDATA BREAKDOWN ===" -ForegroundColor Cyan

$AppData = Join-Path $ProfilePath "AppData\Local"

Get-ChildItem $AppData -Directory -Force |
    ForEach-Object {
        [PSCustomObject]@{
            SizeGB = [math]::Round(
                (
                    Get-ChildItem $_.FullName -Recurse -Force -File -EA SilentlyContinue |
                    Measure-Object Length -Sum
                ).Sum / 1GB,2)
            Path = $_.Name
        }
    } |
    Sort-Object SizeGB -Descending |
    Select-Object -First 30 |
    Format-Table -Auto

Write-Host ""
Write-Host "=== EDGE STORAGE BREAKDOWN ===" -ForegroundColor Cyan

$EdgeRoot = Join-Path $ProfilePath "AppData\Local\Microsoft\Edge"

if (Test-Path $EdgeRoot)
{
    Get-ChildItem $EdgeRoot -Directory -Force |
        ForEach-Object {
            [PSCustomObject]@{
                SizeGB = [math]::Round(
                    (
                        Get-ChildItem $_.FullName -Recurse -Force -File -EA SilentlyContinue |
                        Measure-Object Length -Sum
                    ).Sum / 1GB,2)
                Path = $_.Name
            }
        } |
        Sort-Object SizeGB -Descending |
        Format-Table -Auto
}

Write-Host ""
Write-Host "=== EDGE USER DATA BREAKDOWN ===" -ForegroundColor Cyan

$EdgeUserData = Join-Path $EdgeRoot "User Data"

if (Test-Path $EdgeUserData)
{
    Get-ChildItem $EdgeUserData -Directory -Force |
        ForEach-Object {
            [PSCustomObject]@{
                SizeGB = [math]::Round(
                    (
                        Get-ChildItem $_.FullName -Recurse -Force -File -EA SilentlyContinue |
                        Measure-Object Length -Sum
                    ).Sum / 1GB,2)
                Path = $_.Name
            }
        } |
        Sort-Object SizeGB -Descending |
        Format-Table -Auto
}

Write-Host ""
Write-Host "=== ROOT FILES (C:\) ===" -ForegroundColor Cyan

Get-ChildItem C:\ -Force -File |
    Select-Object Name,
        @{N='SizeGB';E={[math]::Round($_.Length/1GB,2)}} |
    Sort-Object SizeGB -Descending |
    Format-Table -Auto

Write-Host ""
Write-Host "=== TOP 50 FILES ON PROFILE ===" -ForegroundColor Cyan

Get-ChildItem $ProfilePath -Recurse -Force -File -EA SilentlyContinue |
    Sort-Object Length -Descending |
    Select-Object -First 50 `
        FullName,
        @{N='SizeGB';E={[math]::Round($_.Length/1GB,3)}} |
    Format-Table -Auto

Write-Host ""
Write-Host "Done."

#######################################

$edge = "$env:LOCALAPPDATA\Microsoft\Edge\User Data"

Get-ChildItem $edge -Directory -Recurse |
ForEach-Object {
    $size = (
        Get-ChildItem $_.FullName -Recurse -File -EA SilentlyContinue |
        Measure-Object -Property Length -Sum
    ).Sum

    [PSCustomObject]@{
        GB   = [math]::Round($size / 1GB, 2)
        Path = $_.FullName
    }
} |
Sort-Object GB -Descending |
Select-Object -First 30 |
Format-Table -Auto
