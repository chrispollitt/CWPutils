<#
.SYNOPSIS
    Offloads large files/folders to OneDrive, leaves symlinks behind, and marks
    rarely used OneDrive files as "Free up space" (online-only).

.DESCRIPTION
    Phase 1 - Offload (skip with -SkipMove)
      * Looks at the immediate children of each -SourceRoots folder.
      * A file >= -MinSizeMB, or a folder whose total size >= -MinSizeMB, is moved
        into <OneDriveRoot>\<DestinationFolder>\... (same drive only, so the move
        is an instant rename) and a symlink is created at the old location:
        a file symlink for files, a directory symlink for folders.
      * If the symlink cannot be created, the move is rolled back.
      * Every action is appended to a CSV manifest (see -Apply output for the path).

    Phase 2 - Free up space (skip with -SkipFreeUp)
      * Marks files as online-only ("Free up space") when they have not been
        accessed/modified for -StaleDays days.
      * Only touches files OneDrive has finished syncing, and never files you have
        pinned with "Always keep on this device".

    Never deletes any of your data. The only removal is cleaning up a half-made
    symlink during a rollback.

    Runs in PREVIEW mode unless -Apply is given.

    Requirements: OneDrive Files On-Demand enabled; permission to create symlinks
    (run as administrator, or turn on Windows Developer Mode).

.EXAMPLE
    .\offload-to-onedrive.ps1 -SourceRoots "$env:USERPROFILE\Downloads","$env:USERPROFILE\Videos"
    Preview what would be moved and freed up.

.EXAMPLE
    .\offload-to-onedrive.ps1 -SourceRoots "$env:USERPROFILE\Downloads" -MinSizeMB 1000 -Apply

.EXAMPLE
    .\offload-to-onedrive.ps1 -SkipMove -FreeUpScope AllOneDrive -Apply
    Only run the "Free up space" phase, across the whole OneDrive.
#>
[CmdletBinding()]
param(
    [string[]]$SourceRoots,
    [string]$OneDriveRoot,
    [string]$DestinationFolder = 'Offloaded',
    [ValidateRange(1, 1048576)][int]$MinSizeMB = 500,
    [ValidateRange(1, 3650)][int]$StaleDays = 60,
    [ValidateSet('AccessOrWrite', 'WriteOnly')][string]$StaleBasis = 'AccessOrWrite',
    [ValidateSet('Offloaded', 'AllOneDrive')][string]$FreeUpScope = 'Offloaded',
    [string[]]$ExcludeFolders = @(
        (Join-Path $env:USERPROFILE 'OneDrive'),
        (Join-Path $env:USERPROFILE 'OneDrive - Local'),
        (Join-Path $env:USERPROFILE 'OneDrive - Pacific Community Resources Society'),
        (Join-Path $env:USERPROFILE 'OneDrive-Local'),
        (Join-Path $env:USERPROFILE 'OneDrive-PCRS'),
        (Join-Path $env:USERPROFILE 'cygwin-portable')
    ),
    [string[]]$ExcludePatterns = @('*.pst', '*.ost', '*.vhd', '*.vhdx', '*.vmdk', '*.mdf', '*.ldf', '*.sqlite', '*.db'),
    [switch]$SkipMove,
    [switch]$SkipFreeUp,
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Constants ---------------------------------------------------------------
$ATTR_REPARSE     = [int][System.IO.FileAttributes]::ReparsePoint
$ATTR_SYSTEM      = [int][System.IO.FileAttributes]::System
$ATTR_RECALL_OPEN = 0x00040000   # FILE_ATTRIBUTE_RECALL_ON_OPEN
$ATTR_PINNED      = 0x00080000   # FILE_ATTRIBUTE_PINNED   ("Always keep on this device")
$ATTR_UNPINNED    = 0x00100000   # FILE_ATTRIBUTE_UNPINNED ("Free up space")
$ATTR_RECALL_DATA = 0x00400000   # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (online-only)
$MaxRelativePath  = 380          # OneDrive's limit is ~400 characters

$stateDir = Join-Path $env:LOCALAPPDATA 'OffloadToOneDrive'
$manifest = Join-Path $stateDir 'moves.csv'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

# --- Helpers -----------------------------------------------------------------
function Test-IsUnder {
    param([string]$Path, [string]$Parent)
    $p = $Path.TrimEnd('\') + '\'
    $q = $Parent.TrimEnd('\') + '\'
    return $p.StartsWith($q, [StringComparison]::OrdinalIgnoreCase)
}

function Test-Excluded {
    param([string]$Name)
    foreach ($pattern in $ExcludePatterns) {
        if ($Name -like $pattern) { return $true }
    }
    return $false
}

function Format-GB {
    param([long]$Bytes)
    return ('{0,9:N2} GB' -f ($Bytes / 1GB))
}

# Walks a folder without following links. Returns total size, longest path seen,
# and the first reason (if any) the folder should not be moved as a unit.
function Measure-Tree {
    param([string]$Path)

    $result = [pscustomobject]@{ Bytes = [long]0; MaxPathLength = 0; Blocked = $null }
    $stack = [System.Collections.Generic.Stack[string]]::new()
    $stack.Push($Path)

    while ($stack.Count -gt 0) {
        $dir = $stack.Pop()
        try {
            $items = @([System.IO.DirectoryInfo]::new($dir).EnumerateFileSystemInfos())
        }
        catch {
            if (-not $result.Blocked) { $result.Blocked = "unreadable folder: $dir" }
            continue
        }

        foreach ($item in $items) {
            if ($item.FullName.Length -gt $result.MaxPathLength) {
                $result.MaxPathLength = $item.FullName.Length
            }
            if ($item.Name -eq '.git' -and -not $result.Blocked) {
                $result.Blocked = 'contains a git repository'
            }
            if (([int]$item.Attributes -band $ATTR_REPARSE) -ne 0) {
                if (-not $result.Blocked) { $result.Blocked = "contains a link/reparse point: $($item.FullName)" }
                continue
            }
            if ($item -is [System.IO.DirectoryInfo]) {
                $stack.Push($item.FullName)
            }
            else {
                if ((Test-Excluded $item.Name) -and -not $result.Blocked) {
                    $result.Blocked = "contains excluded file type: $($item.Name)"
                }
                $result.Bytes += $item.Length
            }
        }
    }
    return $result
}

function Get-DestinationPath {
    param([string]$SourceFullPath, [string]$OffloadRoot)

    $profileRoot = $env:USERPROFILE.TrimEnd('\')
    if (Test-IsUnder $SourceFullPath $profileRoot) {
        $relative = $SourceFullPath.Substring($profileRoot.Length + 1)
    }
    else {
        $relative = $SourceFullPath.Substring(0, 1) + '\' + $SourceFullPath.Substring(3)
    }
    return (Join-Path $OffloadRoot $relative)
}

function New-Symlink {
    param([string]$Link, [string]$Target, [bool]$IsDirectory)

    try {
        New-Item -ItemType SymbolicLink -Path $Link -Value $Target -ErrorAction Stop | Out-Null
        return
    }
    catch {
        $firstError = $_.Exception.Message
    }

    # Windows PowerShell 5.1 needs elevation even in Developer Mode; mklink does not.
    $mkArgs = @('/c', 'mklink')
    if ($IsDirectory) { $mkArgs += '/D' }
    $mkArgs += @($Link, $Target)
    $output = & cmd.exe @mkArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create symlink '$Link' -> '$Target'. New-Item: $firstError | mklink: $output"
    }
}

function Test-SymlinkCapability {
    $dir = Join-Path $stateDir 'preflight'
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $target = Join-Path $dir 'target.txt'
    $link = Join-Path $dir 'link.txt'
    Set-Content -LiteralPath $target -Value 'x'
    if (Test-Path -LiteralPath $link) { [System.IO.File]::Delete($link) }
    try {
        New-Symlink -Link $link -Target $target -IsDirectory $false
        return $true
    }
    catch {
        return $false
    }
    finally {
        if (Test-Path -LiteralPath $link) { [System.IO.File]::Delete($link) }
        Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    }
}

function Write-Manifest {
    param($Candidate, [string]$Status)
    [pscustomobject]@{
        Timestamp   = (Get-Date -Format 's')
        Source      = $Candidate.Source
        Destination = $Candidate.Destination
        Type        = if ($Candidate.IsDirectory) { 'Folder' } else { 'File' }
        Bytes       = $Candidate.Bytes
        Status      = $Status
    } | Export-Csv -LiteralPath $manifest -Append -NoTypeInformation
}

# --- Setup -------------------------------------------------------------------
if ($SkipMove -and $SkipFreeUp) { throw 'Nothing to do: both -SkipMove and -SkipFreeUp were given.' }

if (-not $OneDriveRoot) {
    $candidatesFound = @()
    foreach ($name in 'OneDriveCommercial', 'OneDrive', 'OneDriveConsumer') {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $candidatesFound += $value }
    }
    $candidatesFound += @(Get-ChildItem -LiteralPath $env:USERPROFILE -Directory -Filter 'OneDrive*' -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName })
    $found = @($candidatesFound | Where-Object { $_ -like '*PCRS*' } | Sort-Object -Unique)
    if ($found.Count -ne 1) {
        throw ("Could not pick a OneDrive folder containing 'PCRS' automatically (found: {0}). Pass -OneDriveRoot." -f
            $(if ($found.Count) { $found -join '; ' } else { 'none' }))
    }
    $OneDriveRoot = $found[0]
}
if (-not (Test-Path -LiteralPath $OneDriveRoot -PathType Container)) {
    throw "OneDrive folder not found: '$OneDriveRoot'"
}
$OneDriveRoot = [System.IO.Path]::GetFullPath($OneDriveRoot).TrimEnd('\')
$offloadRoot = Join-Path $OneDriveRoot $DestinationFolder

Write-Output ''
Write-Output ('Mode:        {0}' -f $(if ($Apply) { 'APPLY (changes will be made)' } else { 'PREVIEW (nothing will be changed)' }))
Write-Output "OneDrive:    $OneDriveRoot"
Write-Output "Offload to:  $offloadRoot"
Write-Output "Manifest:    $manifest"

if (-not (Get-Process -Name 'OneDrive' -ErrorAction SilentlyContinue)) {
    Write-Warning 'OneDrive does not appear to be running; nothing will upload or become online-only until it is.'
}

if ($StaleBasis -eq 'AccessOrWrite') {
    try {
        $flag = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name NtfsDisableLastAccessUpdate -ErrorAction Stop).NtfsDisableLastAccessUpdate
        if (([int]$flag -band 1) -eq 1) {
            Write-Warning 'NTFS last-access updates are disabled, so access times are not reliable. Staleness will effectively follow the last-modified time.'
        }
    }
    catch { }
}

# --- Phase 1: offload --------------------------------------------------------
$moved = 0; $moveFailed = 0; $movedBytes = [long]0

if (-not $SkipMove) {
    if (-not $SourceRoots) { throw '-SourceRoots is required unless -SkipMove is used.' }

    $minBytes = [long]$MinSizeMB * 1MB
    $forbidden = @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData,
        $env:APPDATA, $env:LOCALAPPDATA, $OneDriveRoot) + @($ExcludeFolders) | Where-Object { $_ }
    # A child that equals or contains any of these (or the profile itself) is never moved or scanned.
    $protectedPaths = @($forbidden) + @($env:USERPROFILE.TrimEnd('\'))
    $candidates = [System.Collections.Generic.List[object]]::new()
    $skipped = [System.Collections.Generic.List[string]]::new()

    foreach ($raw in $SourceRoots) {
        $root = [System.IO.Path]::GetFullPath($raw).TrimEnd('\')

        if ($root -notmatch '^[A-Za-z]:\\.+') { Write-Warning "Skipping '$raw': must be a folder on a local drive, not a drive root."; continue }
        if ($root -ieq $env:USERPROFILE.TrimEnd('\')) { Write-Warning "Skipping '$raw': refusing to scan the whole user profile."; continue }
        if ($forbidden | Where-Object { Test-IsUnder $root $_ }) { Write-Warning "Skipping '$raw': system, application-data, or OneDrive location."; continue }
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { Write-Warning "Skipping '$raw': folder not found."; continue }
        if ([System.IO.Path]::GetPathRoot($root) -ine [System.IO.Path]::GetPathRoot($OneDriveRoot)) {
            Write-Warning "Skipping '$raw': it is on a different drive than OneDrive (only same-drive moves are supported)."
            continue
        }

        foreach ($child in @([System.IO.DirectoryInfo]::new($root).EnumerateFileSystemInfos())) {
            $attrs = [int]$child.Attributes
            if (($attrs -band $ATTR_REPARSE) -ne 0) { continue }   # already a link (e.g. from a previous run)
            if (($attrs -band $ATTR_SYSTEM) -ne 0) { continue }
            $childPath = $child.FullName
            if ($protectedPaths | Where-Object { Test-IsUnder $_ $childPath }) { continue }   # is, or contains, an excluded folder

            $isDir = $child -is [System.IO.DirectoryInfo]
            if ($isDir) {
                $m = Measure-Tree $child.FullName
                $size = $m.Bytes; $maxLen = $m.MaxPathLength; $blocked = $m.Blocked
            }
            else {
                $size = [long]$child.Length; $maxLen = $child.FullName.Length; $blocked = $null
                if (Test-Excluded $child.Name) { $blocked = 'excluded file type' }
            }
            if ($size -lt $minBytes) { continue }

            if ($blocked) { $skipped.Add("$($child.FullName)  [$blocked]"); continue }

            $dest = Get-DestinationPath -SourceFullPath $child.FullName -OffloadRoot $offloadRoot
            if (Test-Path -LiteralPath $dest) { $skipped.Add("$($child.FullName)  [destination already exists]"); continue }
            $relativeLength = ($dest.Length - $OneDriveRoot.Length) + ($maxLen - $child.FullName.Length)
            if ($relativeLength -gt $MaxRelativePath) { $skipped.Add("$($child.FullName)  [path would be too long for OneDrive]"); continue }

            $candidates.Add([pscustomobject]@{
                    Source = $child.FullName; Destination = $dest; IsDirectory = $isDir; Bytes = $size
                })
        }
    }

    $candidates = @($candidates | Sort-Object Bytes -Descending)
    $totalBytes = [long]0
    foreach ($c in $candidates) { $totalBytes += $c.Bytes }

    Write-Output ''
    Write-Output "=== Phase 1: offload items >= $MinSizeMB MB ==="
    if ($candidates.Count -eq 0) { Write-Output 'No eligible files or folders found.' }
    foreach ($c in $candidates) {
        Write-Output ('{0} {1,-6} {2}' -f (Format-GB $c.Bytes), $(if ($c.IsDirectory) { 'folder' } else { 'file' }), $c.Source)
        Write-Output ('{0,18} -> {1}' -f '', $c.Destination)
    }
    if ($candidates.Count -gt 0) { Write-Output ('Total: {0} in {1} item(s).' -f (Format-GB $totalBytes).Trim(), $candidates.Count) }
    if ($skipped.Count -gt 0) {
        Write-Output ''
        Write-Output 'Skipped (large, but not safe to move automatically):'
        $skipped | ForEach-Object { Write-Output "  $_" }
    }

    if ($candidates.Count -gt 0) {
        $canLink = Test-SymlinkCapability
        if (-not $canLink) {
            $message = 'Cannot create symbolic links. Run as administrator, or enable Developer Mode (Settings > System > For developers).'
            if ($Apply) { throw $message }
            Write-Warning $message
        }

        if ($Apply) {
            foreach ($c in $candidates) {
                $didMove = $false
                try {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $c.Destination) -Force | Out-Null
                    if ($c.IsDirectory) { [System.IO.Directory]::Move($c.Source, $c.Destination) }
                    else { [System.IO.File]::Move($c.Source, $c.Destination) }
                    $didMove = $true

                    New-Symlink -Link $c.Source -Target $c.Destination -IsDirectory $c.IsDirectory
                    $linkItem = Get-Item -LiteralPath $c.Source -Force
                    if (-not $linkItem.LinkType) { throw 'Link verification failed.' }

                    $moved++; $movedBytes += $c.Bytes
                    Write-Output "Moved and linked: $($c.Source)"
                    Write-Manifest $c 'Moved+Linked'
                }
                catch {
                    $moveFailed++
                    $err = $_.Exception.Message
                    if (-not $didMove) {
                        Write-Warning "Not moved (unchanged): '$($c.Source)': $err"
                        Write-Manifest $c "Not moved: $err"
                        continue
                    }
                    try {
                        $partial = Get-Item -LiteralPath $c.Source -Force -ErrorAction SilentlyContinue
                        if ($partial -and $partial.LinkType) {
                            if ($c.IsDirectory) { [System.IO.Directory]::Delete($c.Source) }
                            else { [System.IO.File]::Delete($c.Source) }
                        }
                        if ($c.IsDirectory) { [System.IO.Directory]::Move($c.Destination, $c.Source) }
                        else { [System.IO.File]::Move($c.Destination, $c.Source) }
                        Write-Warning "Rolled back '$($c.Source)': $err"
                        Write-Manifest $c "Rolled back: $err"
                    }
                    catch {
                        Write-Error "ROLLBACK FAILED. Your data is safe at '$($c.Destination)' (intended original: '$($c.Source)'). $($_.Exception.Message)" -ErrorAction Continue
                        Write-Manifest $c 'NEEDS ATTENTION: moved but not linked'
                    }
                }
            }
        }
    }
}

# --- Phase 2: free up space --------------------------------------------------
$marked = 0; $markedBytes = [long]0; $markFailed = 0
$alreadyOnline = 0; $pinned = 0; $pendingSync = 0; $recent = 0

if (-not $SkipFreeUp) {
    $scopeRoot = if ($FreeUpScope -eq 'AllOneDrive') { $OneDriveRoot } else { $offloadRoot }
    $cutoff = [DateTime]::UtcNow.AddDays(-$StaleDays)

    Write-Output ''
    Write-Output "=== Phase 2: free up space for files unused for $StaleDays+ days ($FreeUpScope) ==="

    if (-not (Test-Path -LiteralPath $scopeRoot -PathType Container)) {
        Write-Output "Nothing to do yet: '$scopeRoot' does not exist."
    }
    else {
        $shown = 0
        $stack = [System.Collections.Generic.Stack[string]]::new()
        $stack.Push($scopeRoot)

        while ($stack.Count -gt 0) {
            $dir = $stack.Pop()
            try { $items = @([System.IO.DirectoryInfo]::new($dir).EnumerateFileSystemInfos()) }
            catch { Write-Warning "Could not read '$dir': $($_.Exception.Message)"; continue }

            foreach ($item in $items) {
                $attrs = [int]$item.Attributes

                if ($item -is [System.IO.DirectoryInfo]) {
                    # OneDrive folders are reparse points too; only skip real symlinks/junctions.
                    if (($attrs -band $ATTR_REPARSE) -ne 0) {
                        $dirInfo = Get-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
                        if ($dirInfo -and $dirInfo.LinkType) { continue }
                    }
                    $stack.Push($item.FullName)
                    continue
                }

                if (($attrs -band ($ATTR_RECALL_DATA -bor $ATTR_RECALL_OPEN -bor $ATTR_UNPINNED)) -ne 0) { $alreadyOnline++; continue }
                if (($attrs -band $ATTR_PINNED) -ne 0) { $pinned++; continue }
                # A finished-syncing OneDrive file is a placeholder (reparse point). A plain file is
                # still waiting to upload (or Files On-Demand is off), so leave it alone.
                if (($attrs -band $ATTR_REPARSE) -eq 0) { $pendingSync++; continue }

                if ($StaleBasis -eq 'WriteOnly') { $last = $item.LastWriteTimeUtc }
                elseif ($item.LastAccessTimeUtc -gt $item.LastWriteTimeUtc) { $last = $item.LastAccessTimeUtc }
                else { $last = $item.LastWriteTimeUtc }
                if ($last -gt $cutoff) { $recent++; continue }

                $fileInfo = Get-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
                if (-not $fileInfo -or $fileInfo.LinkType) { continue }   # never touch symlinks

                if ($Apply) {
                    $ok = $false
                    try {
                        $null = & attrib.exe '+U' '-P' $item.FullName 2>&1
                        $ok = ($LASTEXITCODE -eq 0)
                    }
                    catch { $ok = $false }
                    if ($ok) { $marked++; $markedBytes += $item.Length }
                    else { $markFailed++; Write-Warning "Could not mark: $($item.FullName)" }
                }
                else {
                    $marked++; $markedBytes += $item.Length
                    if ($shown -lt 25) {
                        Write-Output ("Would free up: {0} {1}" -f (Format-GB $item.Length), $item.FullName)
                        $shown++
                    }
                }
            }
        }
        if (-not $Apply -and $marked -gt $shown) { Write-Output "... and $($marked - $shown) more file(s)." }
    }
}

# --- Summary -----------------------------------------------------------------
Write-Output ''
Write-Output '=== Summary ==='
if (-not $SkipMove -and $Apply) {
    Write-Output ('Offloaded: {0} item(s), {1}; failed/rolled back: {2}.' -f $moved, (Format-GB $movedBytes).Trim(), $moveFailed)
}
if (-not $SkipFreeUp) {
    $verb = if ($Apply) { 'Marked online-only' } else { 'Would mark online-only' }
    Write-Output ('{0}: {1} file(s), about {2}{3}.' -f $verb, $marked, (Format-GB $markedBytes).Trim(), $(if ($markFailed) { "; $markFailed failed" } else { '' }))
    Write-Output ("Skipped: {0} not yet synced, {1} pinned, {2} already online-only, {3} used within {4} days." -f $pendingSync, $pinned, $alreadyOnline, $recent, $StaleDays)
    if ($pendingSync -gt 0) {
        Write-Output 'Files that are not yet synced become eligible after OneDrive finishes uploading. Re-run later with -SkipMove.'
    }
}
if (-not $Apply) {
    Write-Output ''
    Write-Output 'Preview only. Re-run with -Apply to make these changes.'
}
Write-Output ''
