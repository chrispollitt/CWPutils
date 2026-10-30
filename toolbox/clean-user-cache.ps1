[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Apply,
    [switch]$ScheduledRun,
    [ValidateRange(1, 365)]
    [int]$MinimumAgeDays = 7,
    [ValidateRange(30, 3650)]
    [int]$ArchiveAgeDays = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$taskName = 'CWPutils User Cache Cleanup'
$taskDescription = 'Created by clean-user-cache.ps1 for per-user temporary and browser-cache cleanup.'

if (($Install -and $Uninstall) -or (($Install -or $Uninstall) -and ($Apply -or $ScheduledRun))) {
    throw 'Choose either -Install, -Uninstall, or cleanup mode.'
}
if ($ScheduledRun -and -not $Apply) {
    throw '-ScheduledRun can only be used with -Apply.'
}

if ($Install) {
    if (-not $PSCommandPath) {
        throw 'Save this script to a file before installing the scheduled task.'
    }

    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        throw "A task named '$taskName' already exists. Inspect it before replacing or removing it."
    }

    $powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powerShell -PathType Leaf)) {
        throw "Windows PowerShell was not found at '$powerShell'."
    }

    $scriptPath = (Get-Item -LiteralPath $PSCommandPath -ErrorAction Stop).FullName
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Apply -ScheduledRun -MinimumAgeDays {1} -ArchiveAgeDays {2} -Confirm:$false' -f $scriptPath, $MinimumAgeDays, $ArchiveAgeDays
    $action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -Daily -At '7:00PM'
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Description $taskDescription `
        -ErrorAction Stop | Out-Null
    Write-Output "Installed '$taskName' for this user, scheduled daily at 7:00 PM."
    return
}

if ($Uninstall) {
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $existingTask) {
        Write-Output "No '$taskName' task was found."
        return
    }
    if ($existingTask.Description -ne $taskDescription) {
        throw "Refusing to remove '$taskName': its description does not identify this script."
    }

    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Write-Output "Removed '$taskName'."
    return
}

function Test-SafeDirectory {
    param([Parameter(Mandatory)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $directory = [System.IO.DirectoryInfo]::new($fullPath)
    while ($null -ne $directory) {
        try {
            $item = Get-Item -LiteralPath $directory.FullName -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Skipping inaccessible directory '$($directory.FullName)': $($_.Exception.Message)"
            return $false
        }

        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            Write-Warning "Skipping path beneath a link or reparse point: '$($directory.FullName)'"
            return $false
        }
        $directory = $directory.Parent
    }

    return Test-Path -LiteralPath $fullPath -PathType Container
}

function Get-SafeFiles {
    param([Parameter(Mandatory)][string]$Path)

    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push($Path)
    while ($pending.Count -gt 0) {
        $currentPath = $pending.Pop()
        try {
            Get-ChildItem -LiteralPath $currentPath -Force -ErrorAction Stop | ForEach-Object {
                $child = $_
                if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
                    if ($child.PSIsContainer) {
                        $pending.Push($child.FullName)
                    }
                    else {
                        $child
                    }
                }
            }
        }
        catch {
            Write-Warning "Could not enumerate '$currentPath': $($_.Exception.Message)"
        }
    }
}

function Add-CacheTarget {
    param(
        [Parameter(Mandatory)][System.Collections.Generic.List[object]]$Targets,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return
    }

    if (Test-SafeDirectory -Path $Path) {
        $Targets.Add([pscustomobject]@{
            Path = [System.IO.Path]::GetFullPath($Path)
            Description = $Description
        })
    }
}

function Get-StreamSha256 {
    param([Parameter(Mandatory)][System.IO.Stream]$Stream)

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha256.ComputeHash($Stream)).Replace('-', '')
    }
    finally {
        $sha256.Dispose()
    }
}

function New-VerifiedArchive {
    param(
        [Parameter(Mandatory)][System.IO.FileInfo[]]$Files,
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$DestinationDirectory
    )

    Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop

    $archiveName = 'ARCHIVE-OldFiles-{0}.zip' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
    $archivePath = Join-Path $DestinationDirectory $archiveName
    $temporaryPath = Join-Path $DestinationDirectory ('.{0}.{1}.tmp' -f $archiveName, [Guid]::NewGuid().ToString('N'))
    $sourcePrefix = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd('\') + '\'
    $expectedHashes = @{}

    try {
        $archive = [System.IO.Compression.ZipFile]::Open(
            $temporaryPath,
            [System.IO.Compression.ZipArchiveMode]::Create
        )
        try {
            foreach ($file in $Files) {
                $relativePath = $file.FullName.Substring($sourcePrefix.Length).Replace('\', '/')
                $entry = $archive.CreateEntry($relativePath, [System.IO.Compression.CompressionLevel]::Optimal)
                $sourceStream = [System.IO.File]::OpenRead($file.FullName)
                $entryStream = $entry.Open()
                $sha256 = [System.Security.Cryptography.SHA256]::Create()
                try {
                    $buffer = New-Object byte[] 81920
                    while (($bytesRead = $sourceStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $entryStream.Write($buffer, 0, $bytesRead)
                        [void]$sha256.TransformBlock($buffer, 0, $bytesRead, $buffer, 0)
                    }
                    [void]$sha256.TransformFinalBlock([byte[]]@(), 0, 0)
                    $expectedHashes[$relativePath] = [BitConverter]::ToString($sha256.Hash).Replace('-', '')
                }
                finally {
                    $sha256.Dispose()
                    $entryStream.Dispose()
                    $sourceStream.Dispose()
                }
            }
        }
        finally {
            $archive.Dispose()
        }

        $readArchive = [System.IO.Compression.ZipFile]::OpenRead($temporaryPath)
        try {
            if ($readArchive.Entries.Count -ne $expectedHashes.Count) {
                throw 'The ZIP entry count did not match the selected source files.'
            }
            foreach ($entry in $readArchive.Entries) {
                if (-not $expectedHashes.ContainsKey($entry.FullName)) {
                    throw "Unexpected ZIP entry '$($entry.FullName)'."
                }
                $entryStream = $entry.Open()
                try {
                    $actualHash = Get-StreamSha256 -Stream $entryStream
                }
                finally {
                    $entryStream.Dispose()
                }
                if ($actualHash -ne $expectedHashes[$entry.FullName]) {
                    throw "ZIP verification failed for '$($entry.FullName)'."
                }
            }
        }
        finally {
            $readArchive.Dispose()
        }

        [System.IO.File]::Move($temporaryPath, $archivePath)
        return [pscustomobject]@{
            Path = $archivePath
            ExpectedHashes = $expectedHashes
            SourcePrefix = $sourcePrefix
        }
    }
    catch {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            try {
                Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction Stop
            }
            catch {
                Write-Warning "Could not remove incomplete temporary archive '$temporaryPath': $($_.Exception.Message)"
            }
        }
        throw "Could not create and verify the archive: $($_.Exception.Message)"
    }
}

$targets = [System.Collections.Generic.List[object]]::new()
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$roamingAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)

if ($localAppData) {
    Add-CacheTarget -Targets $targets `
        -Path (Join-Path $localAppData 'Temp') `
        -Description 'user temporary files'

    $chromiumBrowsers = @(
        @{
            Name = 'Google Chrome'
            UserData = Join-Path $localAppData 'Google\Chrome\User Data'
            Process = 'chrome'
        },
        @{
            Name = 'Microsoft Edge'
            UserData = Join-Path $localAppData 'Microsoft\Edge\User Data'
            Process = 'msedge'
        }
    )
    $chromiumCacheNames = @('Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'GrShaderCache', 'ShaderCache', 'Media Cache')

    foreach ($browser in $chromiumBrowsers) {
        $userData = $browser.UserData
        if (-not (Test-Path -LiteralPath $userData -PathType Container)) {
            continue
        }
        if (-not (Test-SafeDirectory -Path $userData)) {
            continue
        }

        $running = @(Get-Process -Name $browser.Process -ErrorAction SilentlyContinue)
        if ($running.Count -gt 0) {
            Write-Output "Skipping $($browser.Name) caches because $($browser.Process) is running."
            continue
        }

        try {
            $profiles = Get-ChildItem -LiteralPath $userData -Directory -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Could not enumerate $($browser.Name) profiles: $($_.Exception.Message)"
            continue
        }

        foreach ($profile in $profiles) {
            if (($profile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Write-Warning "Skipping linked browser profile '$($profile.FullName)'."
                continue
            }
            foreach ($cacheName in $chromiumCacheNames) {
                Add-CacheTarget -Targets $targets `
                    -Path (Join-Path $profile.FullName $cacheName) `
                    -Description "$($browser.Name) cache ($($profile.Name))"
            }
        }
    }
}

if ($roamingAppData) {
    $firefoxProfiles = Join-Path $roamingAppData 'Mozilla\Firefox\Profiles'
    if ((Test-Path -LiteralPath $firefoxProfiles -PathType Container) -and (Test-SafeDirectory -Path $firefoxProfiles)) {
        $firefoxRunning = @(Get-Process -Name 'firefox' -ErrorAction SilentlyContinue)
        if ($firefoxRunning.Count -gt 0) {
            Write-Output 'Skipping Firefox caches because firefox is running.'
        }
        else {
            try {
                $profiles = Get-ChildItem -LiteralPath $firefoxProfiles -Directory -Force -ErrorAction Stop
            }
            catch {
                Write-Warning "Could not enumerate Firefox profiles: $($_.Exception.Message)"
                $profiles = @()
            }

            foreach ($profile in $profiles) {
                if (($profile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                    Write-Warning "Skipping linked Firefox profile '$($profile.FullName)'."
                    continue
                }
                Add-CacheTarget -Targets $targets `
                    -Path (Join-Path $profile.FullName 'cache2') `
                    -Description "Firefox cache ($($profile.Name))"
            }
        }
    }
}

$cutoff = [DateTime]::UtcNow.AddDays(-$MinimumAgeDays)
$counts = @{
    Listed = 0
    Deleted = 0
    Failed = 0
    WouldDelete = 0
}
$previewLimit = 25
$mode = if ($Apply) { 'cleanup' } else { 'preview only' }
Write-Output "Mode: $mode. Eligible files must be older than $MinimumAgeDays day(s), before $($cutoff.ToLocalTime())."

foreach ($target in $targets) {
    Get-SafeFiles -Path $target.Path | ForEach-Object {
        $file = $_
        if ($file.LastWriteTimeUtc -le $cutoff) {
            $counts.Listed++
            if (-not $Apply) {
                if ($counts.Listed -le $previewLimit) {
                    Write-Output "Would delete [$($target.Description)]: $($file.FullName)"
                }
            }
            elseif ($PSCmdlet.ShouldProcess($file.FullName, "Delete old file from $($target.Description)")) {
                try {
                    Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
                    $counts.Deleted++
                }
                catch {
                    $counts.Failed++
                    Write-Warning "Could not delete '$($file.FullName)': $($_.Exception.Message)"
                }
            }
            elseif ($WhatIfPreference) {
                $counts.WouldDelete++
            }
        }
    }
}

if (-not $Apply) {
    if ($counts.Listed -gt $previewLimit) {
        Write-Output "... and $($counts.Listed - $previewLimit) more eligible file(s)."
    }
    Write-Output "Preview found $($counts.Listed) eligible file(s) in $($targets.Count) safe cache location(s). Nothing was deleted."
}
else {
    if ($WhatIfPreference) {
        Write-Output "WhatIf complete: $($counts.WouldDelete) file(s) would be deleted; none were deleted."
    }
    else {
        Write-Output "Cleanup complete: deleted $($counts.Deleted) file(s); $($counts.Failed) could not be deleted."
    }
}

$archiveRoot = Join-Path $env:USERPROFILE 'OneDrive - Local\Documents\!Office\Clients\!ARCHIVE'
$archiveCutoff = [DateTime]::UtcNow.AddDays(-$ArchiveAgeDays)
if (Test-Path -LiteralPath $archiveRoot -PathType Container) {
    if (Test-SafeDirectory -Path $archiveRoot) {
        $archiveFiles = @(
            Get-SafeFiles -Path $archiveRoot |
                Where-Object { $_.LastAccessTimeUtc -le $archiveCutoff }
        )
        $archiveDestination = Split-Path -Parent $archiveRoot
        $safeDestination = Test-SafeDirectory -Path $archiveDestination

        if ($archiveFiles.Count -eq 0) {
            Write-Output "No files in '$archiveRoot' have a last-access time older than $ArchiveAgeDays day(s)."
        }
        elseif (-not $safeDestination) {
            Write-Warning "Skipping archive creation because the destination '$archiveDestination' is not a safe directory."
        }
        elseif (-not $Apply) {
            Write-Output "Archive preview: $($archiveFiles.Count) file(s) last accessed before $($archiveCutoff.ToLocalTime()) would be archived to '$archiveDestination'."
            foreach ($file in ($archiveFiles | Select-Object -First 25)) {
                Write-Output "Would archive and then remove: $($file.FullName)"
            }
            if ($archiveFiles.Count -gt 25) {
                Write-Output "... and $($archiveFiles.Count - 25) more file(s)."
            }
            Write-Output 'No archive was created and no originals were removed.'
        }
        elseif ($PSCmdlet.ShouldProcess(
            (Join-Path $archiveDestination 'ARCHIVE-OldFiles-*.zip'),
            "Create and verify a ZIP of $($archiveFiles.Count) files, then remove unchanged originals"
        )) {
            try {
                $archive = New-VerifiedArchive `
                    -Files $archiveFiles `
                    -SourceRoot $archiveRoot `
                    -DestinationDirectory $archiveDestination
            }
            catch {
                Write-Error $_
                return
            }

            $removed = 0
            $retained = 0
            foreach ($file in $archiveFiles) {
                $relativePath = $file.FullName.Substring($archive.SourcePrefix.Length).Replace('\', '/')
                try {
                    $currentFile = Get-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
                    if (($currentFile.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                        Write-Warning "Retaining '$($file.FullName)' because it became a link after archiving."
                        $retained++
                        continue
                    }
                    $currentHash = Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop
                    if ($currentHash.Hash -ne $archive.ExpectedHashes[$relativePath]) {
                        Write-Warning "Retaining '$($file.FullName)' because it changed after archiving."
                        $retained++
                        continue
                    }

                    Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
                    $removed++
                }
                catch {
                    Write-Warning "Could not remove archived original '$($file.FullName)': $($_.Exception.Message)"
                    $retained++
                }
            }

            Write-Output "Created and verified '$($archive.Path)'. Removed $removed unchanged original file(s); retained $retained."
        }
    }
}
else {
    Write-Output "Archive folder not found; skipping old-file archiving: '$archiveRoot'."
}
