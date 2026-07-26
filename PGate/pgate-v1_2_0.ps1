<#
.SYNOPSIS
    Parallel remote command propagation for Windows LANs (PowerShell port of pgate.pl).
.DESCRIPTION
    Discovers Windows machines on the local network with nmap, runs a command against all
    of them in parallel over native PowerShell Remoting (WinRM), and prints each machine's
    output in order once every machine has finished, with a per-machine status.

    If nmap is not found, PGate can automatically install it via winget (requires admin).
.EXAMPLE
    .\pgate.ps1 -Command "Get-Service spooler"
.EXAMPLE
    .\pgate.ps1 -Setup
.EXAMPLE
    .\pgate.ps1 -GenerateBootstrap -ManagementHost 192.168.1.50
.EXAMPLE
    .\pgate.ps1 -Rediscover
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Run', Position = 0)]
    [string]$Command,

    [Parameter(ParameterSetName = 'Run')]
    [scriptblock]$ScriptBlock,

    [Parameter(ParameterSetName = 'Run')]
    [string]$FilePath,

    [Parameter(ParameterSetName = 'Run')]
    [string[]]$Targets,

    [Parameter(ParameterSetName = 'Run')]
    [switch]$Rediscover,

    [Parameter(ParameterSetName = 'Run')]
    [switch]$ListSavedHosts,

    [Parameter(ParameterSetName = 'Run')]
    [pscredential]$Credential,

    [Parameter(ParameterSetName = 'Run')]
    [int]$ThrottleLimit,

    [Parameter(ParameterSetName = 'Run')]
    [int]$TimeoutSeconds,

    [Parameter(ParameterSetName = 'Run')]
    [int]$MaxRetries = 0,

    [Parameter(ParameterSetName = 'Run')]
    [ValidateSet('Text', 'Json', 'Csv')]
    [string]$OutputFormat = 'Text',

    [Parameter(ParameterSetName = 'Run')]
    [switch]$Force,

    [Parameter(ParameterSetName = 'Setup', Mandatory)]
    [switch]$Setup,

    [Parameter(ParameterSetName = 'Bootstrap', Mandatory)]
    [switch]$GenerateBootstrap,

    [Parameter(ParameterSetName = 'Bootstrap')]
    [string]$BootstrapOutputPath = ".\Enable-PGateRemoting.ps1",

    [Parameter(ParameterSetName = 'Bootstrap')]
    [string]$ManagementHost,

    [Parameter(ParameterSetName = 'Run')]
    [switch]$AutoInstallNmap,

    [Parameter(ParameterSetName = 'Help')]
    [switch]$Help,

    [Parameter(ParameterSetName = 'Version')]
    [switch]$Version
)

# Script Version
$ScriptVersion = "1.2.0"

# Error handling: stop on all errors, strict mode, consistent encoding
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['*:ErrorAction'] = 'Stop'
Set-StrictMode -Version Latest

# --- Path Configuration ---
$script:ConfigDir = Join-Path $env:USERPROFILE ".pgate"
$script:ConfigPath = Join-Path $ConfigDir "config.json"
$script:HostsCachePath = Join-Path $ConfigDir "hosts.json"
$script:UnreachableHostsCachePath = Join-Path $ConfigDir "unreachable_hosts.json"
$script:CredentialPath = Join-Path $ConfigDir "cred.xml"
$script:LogDir = Join-Path $ConfigDir "logs"

# Ensure config directory exists with proper ACLs
try {
    if (-not (Test-Path $ConfigDir)) {
        $dir = New-Item -ItemType Directory -Path $ConfigDir -Force
        # Restrict access to current user only (security hardening)
        $acl = Get-Acl $ConfigDir
        $acl.SetAccessRuleProtection($true, $false)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
            "FullControl",
            "ContainerInherit,ObjectInherit",
            "None",
            "Allow"
        )
        $acl.AddAccessRule($rule)
        Set-Acl $ConfigDir $acl
    }
} catch {
    Write-Warning "Could not secure config directory: $_"
}

# --- Help and Version Handling ---

function Show-PGateHelp {
    Write-Host "PGate v$ScriptVersion - Parallel remote command propagation for Windows LANs" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "USAGE:"
    Write-Host "  .\pgate.ps1 -Command '<command>' [-Targets <name,...>] [-Rediscover] [-MaxRetries <n>]"
    Write-Host "  .\pgate.ps1 -ScriptBlock { <script> }"
    Write-Host "  .\pgate.ps1 -FilePath .\script.ps1"
    Write-Host "  .\pgate.ps1 -Setup"
    Write-Host "  .\pgate.ps1 -GenerateBootstrap [-ManagementHost <ip>] [-BootstrapOutputPath <path>]"
    Write-Host "  .\pgate.ps1 -Rediscover          # Run network discovery standalone and save cache"
    Write-Host "  .\pgate.ps1 -ListSavedHosts      # Show cached targetable hosts and known-unreachable hosts"
    Write-Host "  .\pgate.ps1 -Command '<command>' -AutoInstallNmap   # Install nmap via winget if missing"
    Write-Host ""
    Write-Host "FLAGS:"
    Write-Host "  -Help                Show this help message."
    Write-Host "  -Version             Show the current script version."
    Write-Host ""
    Write-Host "PARAMETERS:"
    Write-Host "  -Command             The PowerShell command string to run on targets."
    Write-Host "  -ScriptBlock         A PowerShell scriptblock to run on targets."
    Write-Host "  -FilePath            Path to a local script file to run on targets."
    Write-Host "  -Targets             Comma-separated list of hostnames/IPs. Skips discovery."
    Write-Host "  -Rediscover          Ignores cached hosts and forces a new nmap scan."
    Write-Host "  -ListSavedHosts      List cached targetable hosts and known-unreachable hosts, then exit."
    Write-Host "  -Credential          PSCredential object for remote authentication."
    Write-Host "  -ThrottleLimit       Override configured max parallel connections (1-256)."
    Write-Host "  -TimeoutSeconds      Override configured per-machine timeout (min 10)."
    Write-Host "  -MaxRetries          Number of times to retry failed/timed-out hosts (0-5)."
    Write-Host "  -OutputFormat        Text (default), Json, or Csv - shape of the per-host results printed to stdout."
    Write-Host "  -Force               Skip the confirmation prompt for commands that look destructive."
    Write-Host "  -Setup               Run the interactive first-time setup wizard."
    Write-Host "  -GenerateBootstrap   Create a script to enable WinRM on target machines."
    Write-Host "  -ManagementHost      IP of this machine, injected into the bootstrap script."
    Write-Host "                       Defaults to this machine's local IP if omitted; falls back to '*' only if auto-detection fails."
    Write-Host "  -BootstrapOutputPath Where to save the generated bootstrap script."
    Write-Host "  -AutoInstallNmap     Attempt to install nmap via winget if missing (Requires Admin)."
    Write-Host ""
}

# Handle -Version
if ($Version) {
    Write-Host "PGate v$ScriptVersion"
    exit 0
}

# Handle -Help or No Arguments
if ($Help -or $PSBoundParameters.Count -eq 0) {
    Show-PGateHelp
    exit 0
}

# --- Utility Functions ---

function Write-PGateLog {
    param([string]$Message, [string]$Level = 'Info')
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$timestamp] [$Level] $Message"
    if ($Level -eq 'Error') { Write-Error $Message }
    elseif ($Level -eq 'Warn') { Write-Warning $Message }
    else { Write-Host $line }
}

function Test-ValidScriptBlock {
    param([string]$Code)
    try {
        $null = [scriptblock]::Create($Code)
        return $true
    } catch {
        return $false
    }
}

function Get-PGateDestructiveKeywordMatches {
    # Best-effort heuristic, not a security boundary: a simple keyword scan over the
    # literal command text so a fat-fingered or copy-pasted destructive command gets
    # one last "are you sure?" before it fans out to every target machine. Trivially
    # bypassed by obfuscation or variable-built commands - it's a safety net, not a guard.
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) { return @() }

    $patterns = @(
        'Remove-Item', 'Remove-\w+', 'Clear-Disk\w*', 'Clear-Content', 'Format-Volume',
        'Stop-Computer', 'Restart-Computer', 'Stop-Service', 'Restart-Service',
        'Disable-\w+', 'Uninstall-\w+', 'Set-ExecutionPolicy', 'Set-Disk\w*',
        'diskpart(\.exe)?', 'shutdown(\.exe)?', 'format\s+[a-z]:', 'reg(\.exe)?\s+delete',
        '\brd\s+/s\b', '\brmdir\s+/s\b', '\bdel\s+/[a-z]*[sq]', 'Remove-LocalUser', 'Remove-ADUser'
    )

    $hits = [System.Collections.Generic.List[string]]::new()
    foreach ($p in $patterns) {
        foreach ($m in [regex]::Matches($Text, $p, 'IgnoreCase')) {
            $hits.Add($m.Value)
        }
    }
    return @($hits | Select-Object -Unique)
}

function Test-IsAdmin {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-WingetAvailable {
    try {
        $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetCmd) { return $wingetCmd.Source }

        # Check common alternative locations
        $altPaths = @(
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe",
            "$env:ProgramFiles\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe"
        )
        foreach ($path in $altPaths) {
            $found = Get-Item $path -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
        return $null
    } catch {
        return $null
    }
}

function Install-NmapViaWinget {
    param(
        [switch]$Silent,
        [switch]$AcceptAgreements
    )

    $winget = Test-WingetAvailable
    if (-not $winget) {
        throw "winget is not available on this system. Install winget (App Installer) from the Microsoft Store, or install nmap manually from https://nmap.org/download.html"
    }

    if (-not (Test-IsAdmin)) {
        throw "Admin privileges are required to install nmap via winget. Run PowerShell as Administrator, or install nmap manually."
    }

    Write-Host "Installing nmap via winget..." -ForegroundColor Cyan

    $wingetArgs = @('install', '-e', '--id', 'Insecure.Nmap', '--disable-interactivity')

    if ($AcceptAgreements) {
        $wingetArgs += @('--accept-package-agreements', '--accept-source-agreements')
    }

    if ($Silent) {
        $wingetArgs += @('--silent')
    }

    try {
        $proc = Start-Process -FilePath $winget -ArgumentList $wingetArgs -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -ne 0) {
            throw "winget install exited with code $($proc.ExitCode)"
        }
    } catch {
        throw "Failed to install nmap via winget: $_"
    }

    # Refresh PATH so we can find it immediately
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

    # Verify installation
    $nmapPath = Resolve-NmapPath -ConfiguredPath $null
    if (-not $nmapPath) {
        throw "nmap was reported as installed but cannot be found in PATH. Try restarting your PowerShell session."
    }

    Write-Host "nmap installed successfully at: $nmapPath" -ForegroundColor Green
    return $nmapPath
}

function Resolve-NmapPath {
    param([string]$ConfiguredPath)

    # Validate configured path first
    if ($ConfiguredPath) {
        if (Test-Path $ConfiguredPath -PathType Leaf) {
            # Verify it's actually nmap by checking version
            try {
                $ver = & $ConfiguredPath --version 2>$null | Select-Object -First 1
                if ($ver -match 'Nmap') { return (Resolve-Path $ConfiguredPath).Path }
            } catch {}
        }
        Write-Warning "Configured nmap path invalid: $ConfiguredPath"
    }

    # Check PATH
    $cmd = Get-Command nmap.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    # Check standard locations
    $candidates = @(
        "$env:ProgramFiles\Nmap\nmap.exe",
        "${env:ProgramFiles(x86)}\Nmap\nmap.exe",
        "$env:LOCALAPPDATA\Nmap\nmap.exe",
        "$env:ProgramData\chocolatey\bin\nmap.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate -PathType Leaf) {
            try {
                $ver = & $candidate --version 2>$null | Select-Object -First 1
                if ($ver -match 'Nmap') { return (Resolve-Path $candidate).Path }
            } catch {}
        }
    }
    return $null
}

function Get-NetworkCidr {
    param(
        [Parameter(Mandatory)][string]$IPAddress,
        [Parameter(Mandatory)][int]$PrefixLength
    )

    try {
        $ip = [System.Net.IPAddress]::Parse($IPAddress)
        if ($ip.AddressFamily -ne 'InterNetwork') {
            throw "Only IPv4 addresses are supported"
        }
        $ipBytes = $ip.GetAddressBytes()
        [Array]::Reverse($ipBytes)
        $ipUInt = [BitConverter]::ToUInt32($ipBytes, 0)
        $maskUInt = if ($PrefixLength -le 0) { 0 } else { [UInt32]::MaxValue -shl (32 - $PrefixLength) }
        $networkUInt = $ipUInt -band $maskUInt
        $networkBytes = [BitConverter]::GetBytes($networkUInt)
        [Array]::Reverse($networkBytes)
        $networkIp = [System.Net.IPAddress]::new($networkBytes)
        return "{0}/{1}" -f $networkIp.ToString(), $PrefixLength
    } catch {
        Write-Warning "Failed to calculate CIDR for $IPAddress/$PrefixLength : $_"
        return $null
    }
}

function Get-DefaultRouteSubnet {
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } |
            Sort-Object -Property RouteMetric, InterfaceMetric | 
            Select-Object -First 1

        if (-not $route) { 
            Write-Warning "No default route found"
            return $null 
        }

        $ip = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { 
                $_.PrefixOrigin -ne 'WellKnown' -and 
                $_.IPAddress -notlike '169.254.*' -and
                $_.IPAddress -ne '127.0.0.1'
            } | 
            Select-Object -First 1

        if (-not $ip) { 
            Write-Warning "No valid IPv4 address on default route interface"
            return $null 
        }

        return Get-NetworkCidr -IPAddress $ip.IPAddress -PrefixLength $ip.PrefixLength
    } catch {
        Write-Warning "Failed to get default route subnet: $_"
        return $null
    }
}

function Get-PrimaryLocalIPAddress {
    # Best guess at "this machine's LAN IP": the address on the default-route interface.
    # Used to default -ManagementHost for -GenerateBootstrap so TrustedHosts gets a
    # specific IP instead of falling back to '*' (which trusts every host).
    try {
        $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } |
            Sort-Object -Property RouteMetric, InterfaceMetric |
            Select-Object -First 1

        if (-not $route) { return $null }

        $ip = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.PrefixOrigin -ne 'WellKnown' -and
                $_.IPAddress -notlike '169.254.*' -and
                $_.IPAddress -ne '127.0.0.1'
            } |
            Select-Object -First 1

        if (-not $ip) { return $null }
        return $ip.IPAddress
    } catch {
        return $null
    }
}

function Get-AllLocalSubnets {
    try {
        $results = @()
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | 
            Where-Object {
                $_.IPAddress -notlike '169.254.*' -and 
                $_.IPAddress -ne '127.0.0.1' -and
                $_.InterfaceAlias -notmatch 'Loopback|vEthernet.*\(Internal\)|Docker|Hyper-V|VirtualBox|VMware' -and
                $_.PrefixLength -gt 0 -and $_.PrefixLength -lt 32
            }

        foreach ($ip in $ips) {
            $cidr = Get-NetworkCidr -IPAddress $ip.IPAddress -PrefixLength $ip.PrefixLength
            if ($cidr) { $results += $cidr }
        }
        return $results | Select-Object -Unique
    } catch {
        Write-Warning "Failed to enumerate local subnets: $_"
        return @()
    }
}

function Get-LocalMachineIdentifiers {
    # Used to exclude this machine from discovered/remote target lists - it'll always
    # show up in a subnet sweep, but running Invoke-Command against yourself is
    # redundant at best and can behave inconsistently (loopback WinRM quirks) at worst.
    $ips = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    [void]$ips.Add('127.0.0.1')
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object {
            [void]$ips.Add($_.IPAddress)
        }
    } catch {
        Write-Warning "Failed to enumerate local IP addresses: $_"
    }

    return [pscustomobject]@{
        Hostname = $env:COMPUTERNAME
        IPs      = $ips
    }
}

# --- Configuration Management ---

function Initialize-PGateConfig {
    Write-Host ""
    Write-Host "=== PGate first-run setup ===" -ForegroundColor Cyan
    Write-Host "(Answers are saved to $ConfigPath - rerun with -Setup any time to change them.)" -ForegroundColor DarkGray
    Write-Host ""

    # Check for nmap and offer auto-install
    $nmapAuto = Resolve-NmapPath -ConfiguredPath $null
    $nmapPath = $null

    if ($nmapAuto) {
        Write-Host "Found nmap at: $nmapAuto" -ForegroundColor Green
        $nmapPath = $nmapAuto
    } else {
        Write-Host "nmap was not found on this system." -ForegroundColor Yellow

        $winget = Test-WingetAvailable
        if ($winget) {
            if (Test-IsAdmin) {
                do {
                    $installAns = Read-Host "Install nmap automatically via winget? (Y/n, default Y)"
                    if ([string]::IsNullOrWhiteSpace($installAns)) { $installAns = 'Y' }
                } while ($installAns -notmatch '^[YyNn]$')

                if ($installAns -match '^[Yy]$') {
                    try {
                        $nmapPath = Install-NmapViaWinget -Silent -AcceptAgreements
                    } catch {
                        Write-Warning "Auto-install failed: $_"
                    }
                }
            } else {
                Write-Host "winget is available but you are not running as Administrator." -ForegroundColor Yellow
                Write-Host "Run this setup again as Administrator to auto-install, or install nmap manually." -ForegroundColor DarkGray
            }
        } else {
            Write-Host "winget is not available. Install nmap manually from https://nmap.org/download.html" -ForegroundColor Yellow
        }

        if (-not $nmapPath) {
            do {
                $nmapPath = Read-Host "Path to nmap.exe"
            } while (-not (Test-Path $nmapPath -PathType Leaf))
        }
    }

    # Ensure the local WinRM service is running and set to auto-start. This machine
    # never needs to accept inbound WinRM connections, but the WSMan:\ provider still
    # needs the service running just to manage this machine's own client settings
    # (e.g. TrustedHosts) - without it, every real -Command run needs this fixed by hand.
    Write-Host ""
    try {
        $winrmSvc = Get-Service WinRM -ErrorAction Stop
        if ($winrmSvc.StartType -eq 'Automatic' -and $winrmSvc.Status -eq 'Running') {
            Write-Host "Local WinRM service is already running and set to auto-start." -ForegroundColor Green
        } elseif (Test-IsAdmin) {
            if ($winrmSvc.StartType -ne 'Automatic') { Set-Service WinRM -StartupType Automatic -ErrorAction Stop }
            if ($winrmSvc.Status -ne 'Running') { Start-Service WinRM -ErrorAction Stop }
            Write-Host "Local WinRM service set to auto-start and running." -ForegroundColor Green
        } else {
            Write-Host "This machine's local WinRM service isn't set to auto-start." -ForegroundColor Yellow
            Write-Host "Run this once, elevated, on this machine: Set-Service WinRM -StartupType Automatic; Start-Service WinRM" -ForegroundColor DarkGray
        }
    } catch {
        Write-Warning "Could not check/configure the local WinRM service: $_"
    }

    # Scope selection with validation
    do {
        Write-Host ""
        Write-Host "a) Which machines should PGate scan for?"
        Write-Host "   [1] Just this subnet (the network this PC's default route is on)"
        Write-Host "   [2] All subnets this PC is directly connected to (multi-NIC / VLANs)"
        $scopeAns = Read-Host "   Choice (default 1)"
        if ([string]::IsNullOrWhiteSpace($scopeAns)) { $scopeAns = '1' }
    } while ($scopeAns -notmatch '^[12]$')
    $scanScope = if ($scopeAns -eq '2') { 'AllLanSubnets' } else { 'CurrentSubnetOnly' }

    Write-Host ""
    $osAns = Read-Host "b) Restrict to which Windows OS/version? e.g. 'Windows 10', 'Windows 11', or 'Any' (default: Any)"
    $osFilter = if ([string]::IsNullOrWhiteSpace($osAns)) { 'Any' } else { $osAns.Trim() }

    Write-Host ""
    do {
        $saveAns = Read-Host "c) Save the discovered machine list so future runs skip re-scanning? (Y/n, default Y)"
        if ([string]::IsNullOrWhiteSpace($saveAns)) { $saveAns = 'Y' }
    } while ($saveAns -notmatch '^[YyNn]$')
    $saveHosts = $saveAns -match '^[Yy]$'

    Write-Host ""
    do {
        Write-Host "d) How should PGate authenticate to remote machines?"
        Write-Host "   [1] Current logged-in user / domain identity (typical for a domain-joined LAN)"
        Write-Host "   [2] A saved credential (typical for workgroup / local-account machines)"
        $credAns = Read-Host "   Choice (default 1)"
        if ([string]::IsNullOrWhiteSpace($credAns)) { $credAns = '1' }
    } while ($credAns -notmatch '^[12]$')
    $credentialMode = if ($credAns -eq '2') { 'SavedCredential' } else { 'CurrentUser' }

    # Safe integer parsing for throttle limit
    Write-Host ""
    $throttleLimit = 0
    do {
        $throttleAns = Read-Host "e) Max machines to contact in parallel? (default 32, max 256)"
        if ([string]::IsNullOrWhiteSpace($throttleAns)) { $throttleAns = '32' }
        $isValid = [int]::TryParse($throttleAns, [ref]$throttleLimit)
        if (-not $isValid) { Write-Warning "Please enter a valid number." }
    } while (-not $isValid -or $throttleLimit -lt 1 -or $throttleLimit -gt 256)

    # Safe integer parsing for timeout seconds
    Write-Host ""
    $timeoutSeconds = 0
    do {
        $timeoutAns = Read-Host "f) Per-machine timeout in seconds? (default 60, min 10)"
        if ([string]::IsNullOrWhiteSpace($timeoutAns)) { $timeoutAns = '60' }
        $isValid = [int]::TryParse($timeoutAns, [ref]$timeoutSeconds)
        if (-not $isValid) { Write-Warning "Please enter a valid number." }
    } while (-not $isValid -or $timeoutSeconds -lt 10)

    Write-Host ""
    do {
        $logAns = Read-Host "g) Log each run's results to a file under $LogDir ? (Y/n, default Y)"
        if ([string]::IsNullOrWhiteSpace($logAns)) { $logAns = 'Y' }
    } while ($logAns -notmatch '^[YyNn]$')
    $logResults = $logAns -match '^[Yy]$'

    $config = [pscustomobject]@{
        ScanScope           = $scanScope
        OsFilter            = $osFilter
        SaveDiscoveredHosts = $saveHosts
        NmapPath            = $nmapPath
        CredentialMode      = $credentialMode
        ThrottleLimit       = $throttleLimit
        TimeoutSeconds      = $timeoutSeconds
        LogResults          = $logResults
        Version             = 2  # Config schema version for future migrations
    }

    try {
        $config | ConvertTo-Json -Depth 4 | Set-Content -Path $ConfigPath -Encoding UTF8 -Force
        Write-Host ""
        Write-Host "Saved config to $ConfigPath" -ForegroundColor Green
        Write-Host ""
    } catch {
        throw "Failed to save config: $_"
    }

    # Run initial discovery as part of setup
    Write-Host ""
    do {
        $discoverAns = Read-Host "h) Run a network discovery scan now? (Y/n, default Y)"
        if ([string]::IsNullOrWhiteSpace($discoverAns)) { $discoverAns = 'Y' }
    } while ($discoverAns -notmatch '^[YyNn]$')

    if ($discoverAns -match '^[Yy]$') {
        Write-Host ""
        try {
            $machines = Invoke-PGateDiscovery -Config $config
            $machineCount = if ($machines) { @($machines).Count } else { 0 }
            
            if ($config.SaveDiscoveredHosts -and $machineCount -gt 0) {
                Save-HostsCache -Machines $machines
                Write-Host "Discovered and cached $machineCount machine(s)." -ForegroundColor Green
            } elseif ($machineCount -gt 0) {
                Write-Host "Discovered $machineCount machine(s). (Cache saving disabled in config)." -ForegroundColor Green
            } else {
                Write-Host "No machines discovered." -ForegroundColor Yellow
            }
        } catch {
            Write-Warning "Initial discovery failed: $_"
        }
    }

    # Offer to generate the bootstrap script - target machines need Enable-PGateRemoting.ps1
    # run on them once before this machine can reach them at all, so it's easy to miss if
    # it isn't offered right here at setup time.
    Write-Host ""
    do {
        $bootstrapAns = Read-Host "i) Generate the bootstrap script (Enable-PGateRemoting.ps1) now, to enable remoting on target machines? (Y/n, default Y)"
        if ([string]::IsNullOrWhiteSpace($bootstrapAns)) { $bootstrapAns = 'Y' }
    } while ($bootstrapAns -notmatch '^[YyNn]$')

    if ($bootstrapAns -match '^[Yy]$') {
        Write-Host ""
        try {
            New-PGateBootstrapScript
        } catch {
            Write-Warning "Bootstrap script generation failed: $_"
        }
    }

    return $config
}

function Get-PGateConfig {
    if (-not (Test-Path $ConfigPath)) { throw "Config file not found. Run with -Setup first." }

    try {
        $config = Get-Content -Path $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

        # Validate required fields exist
        $required = @('ScanScope', 'OsFilter', 'NmapPath', 'CredentialMode', 'ThrottleLimit', 'TimeoutSeconds')
        foreach ($field in $required) {
            if (-not $config.PSObject.Properties[$field]) {
                throw "Config missing required field: $field. Re-run with -Setup."
            }
        }

        # Validate nmap still exists
        $nmap = Resolve-NmapPath -ConfiguredPath $config.NmapPath
        if (-not $nmap) {
            throw "nmap.exe no longer found at configured path. Re-run with -Setup."
        }
        $config.NmapPath = $nmap  # Update to resolved path

        return $config
    } catch {
        if ($_.Exception.Message -match 'ConvertFrom-Json') {
            throw "Config file is corrupted. Re-run with -Setup."
        }
        throw
    }
}

function Save-HostsCache {
    param($Machines)
    try {
        # An empty array piped into ConvertTo-Json produces zero pipeline objects, so
        # Set-Content never runs and silently leaves the old file in place - build the
        # JSON directly instead of relying on the pipeline for the empty case.
        $json = if (@($Machines).Count -eq 0) { '[]' } else { $Machines | ConvertTo-Json -Depth 4 }
        Set-Content -Path $HostsCachePath -Value $json -Encoding UTF8 -Force
    } catch {
        Write-Warning "Failed to save hosts cache: $_"
    }
}

function Get-HostsCache {
    if (-not (Test-Path $HostsCachePath)) { return @() }

    try {
        $content = Get-Content -Path $HostsCachePath -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($content)) { return @() }

        $cache = $content | ConvertFrom-Json
        # Handle both single object and array
        if ($cache -is [array]) { return $cache }
        if ($cache -is [PSCustomObject]) { return @($cache) }
        return @()
    } catch {
        Write-Warning "Hosts cache corrupted, will rediscover. Error: $_"
        Remove-Item $HostsCachePath -Force -ErrorAction SilentlyContinue
        return @()
    }
}

function Save-UnreachableHostsCache {
    param($Machines)
    try {
        # See Save-HostsCache: an empty array piped into ConvertTo-Json yields zero
        # pipeline objects, so Set-Content never runs and the old file survives untouched.
        $json = if (@($Machines).Count -eq 0) { '[]' } else { $Machines | ConvertTo-Json -Depth 4 }
        Set-Content -Path $UnreachableHostsCachePath -Value $json -Encoding UTF8 -Force
    } catch {
        Write-Warning "Failed to save unreachable hosts cache: $_"
    }
}

function Get-UnreachableHostsCache {
    if (-not (Test-Path $UnreachableHostsCachePath)) { return @() }

    try {
        $content = Get-Content -Path $UnreachableHostsCachePath -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($content)) { return @() }

        $cache = $content | ConvertFrom-Json
        # Handle both single object and array
        if ($cache -is [array]) { return $cache }
        if ($cache -is [PSCustomObject]) { return @($cache) }
        return @()
    } catch {
        Write-Warning "Unreachable hosts cache corrupted, resetting. Error: $_"
        Remove-Item $UnreachableHostsCachePath -Force -ErrorAction SilentlyContinue
        return @()
    }
}

function Sync-PGateUnreachableCache {
    # Refreshes the unreachable-hosts cache: entries in $UnreachableEntries are added
    # (replacing any stale entry with the same key), and any existing entry for a host
    # in $ReachableNames is dropped, since it just answered over WinRM again.
    param(
        [string[]]$ReachableNames = @(),
        [object[]]$UnreachableEntries = @()
    )

    $existing = @(Get-UnreachableHostsCache)
    if ($existing.Count -eq 0 -and @($UnreachableEntries).Count -eq 0) { return }

    $reachableSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$ReachableNames, [System.StringComparer]::OrdinalIgnoreCase)
    $refreshedKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($e in $UnreachableEntries) {
        $key = if ($e.Hostname) { $e.Hostname } else { $e.IPAddress }
        if ($key) { [void]$refreshedKeys.Add($key) }
    }

    $kept = @($existing | Where-Object {
        $key = if ($_.Hostname) { $_.Hostname } else { $_.IPAddress }
        $key -and -not $reachableSet.Contains($key) -and -not $refreshedKeys.Contains($key)
    })

    $updated = @($kept + $UnreachableEntries)
    if ($updated.Count -ne $existing.Count -or @($UnreachableEntries).Count -gt 0) {
        Save-UnreachableHostsCache -Machines $updated
    }
}

function Get-PGateTargetableMachines {
    # Excludes the local machine and anything already recorded as unreachable, so the
    # targetable discovery cache and the unreachable cache never overlap.
    param([array]$Machines)

    $localIds = Get-LocalMachineIdentifiers
    $unreachableKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($u in @(Get-UnreachableHostsCache)) {
        $key = if ($u.Hostname) { $u.Hostname } else { $u.IPAddress }
        if ($key) { [void]$unreachableKeys.Add($key) }
    }

    return @($Machines | Where-Object {
        $isLocal = ($_.IPAddress -and $localIds.IPs.Contains($_.IPAddress)) -or ($_.Hostname -and $_.Hostname -eq $localIds.Hostname)
        $isKnownUnreachable = ($_.Hostname -and $unreachableKeys.Contains($_.Hostname)) -or ($_.IPAddress -and $unreachableKeys.Contains($_.IPAddress))
        -not $isLocal -and -not $isKnownUnreachable
    })
}

function Sync-PGateLocalTrustedHosts {
    # For non-domain (workgroup) targets, Invoke-Command's NTLM auth is refused unless
    # THIS machine's own WinRM client has the target in ITS OWN TrustedHosts list -
    # the target's TrustedHosts (set by Enable-PGateRemoting.ps1) governs the opposite
    # direction and has no bearing on outbound connections initiated from here. Test-WSMan
    # doesn't hit this (it's an unauthenticated identify request), only real command
    # execution does, which is why -Rediscover can mark a host reachable while -Command
    # still fails against it until this is fixed.
    #
    # The WSMan:\ provider itself talks to a local WinRM endpoint even for purely
    # client-side settings, so the local WinRM service also has to be running (not
    # listening for inbound connections - just running) or every Get-Item/Set-Item
    # under WSMan:\localhost\ fails with a "client cannot connect" error, which looks
    # like a permissions problem but isn't.
    param([string[]]$TargetNames)

    $names = @($TargetNames | Where-Object { $_ } | Select-Object -Unique)
    if ($names.Count -eq 0) { return }

    try {
        $svc = Get-Service WinRM -ErrorAction Stop
        # Also fix the startup type, not just the current run's state, so this doesn't
        # need re-fixing (or silently degrade to warnings again) after every reboot.
        if ($svc.StartType -ne 'Automatic') {
            Set-Service WinRM -StartupType Automatic -ErrorAction Stop
        }
        if ($svc.Status -ne 'Running') {
            Start-Service WinRM -ErrorAction Stop
        }
    } catch {
        Write-Warning "Local WinRM service isn't running/auto-starting, so this machine can't manage its own WinRM client settings: $_"
        Write-Warning "Run this once, elevated, on THIS machine: Set-Service WinRM -StartupType Automatic; Start-Service WinRM"
        return
    }

    # On a machine where the WinRM client has never been configured, the WSMan:\ item
    # doesn't exist yet at all (not merely empty) - treat that the same as "no hosts
    # trusted yet" rather than bailing out before ever attempting Set-Item.
    $current = ''
    try {
        $current = (Get-Item WSMan:\localhost\Client\TrustedHosts -ErrorAction Stop).Value
    } catch {
        if ($_.CategoryInfo.Category -ne 'ObjectNotFound') {
            Write-Warning "Could not read local WinRM TrustedHosts: $_"
            return
        }
    }

    if ($current -eq '*') { return }

    $currentList = @()
    if ($current) { $currentList = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
    $currentSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$currentList, [System.StringComparer]::OrdinalIgnoreCase)

    $missing = @($names | Where-Object { -not $currentSet.Contains($_) })
    if ($missing.Count -eq 0) { return }

    $newValue = @($currentList + $missing) -join ','

    try {
        Set-Item WSMan:\localhost\Client\TrustedHosts -Value $newValue -Force -ErrorAction Stop
        Write-Host "Added $($missing.Count) host(s) to this machine's local WinRM TrustedHosts (needed for non-domain remoting): $($missing -join ', ')" -ForegroundColor DarkGray
    } catch {
        Write-Warning "Could not update local WinRM TrustedHosts automatically (requires an elevated PowerShell session): $_"
        Write-Warning "Run this once, elevated, on THIS machine: Set-Item WSMan:\localhost\Client\TrustedHosts -Value '$newValue' -Force"
    }
}

function Test-PGateFastPing {
    # Cheap pre-check before spending a full WinRM handshake/timeout on a dead host.
    # -w 10 is a 10ms wait, so this is only meaningful for hosts on the local LAN.
    param([string]$ComputerName)
    try {
        & ping.exe -n 1 -w 10 -4 $ComputerName *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Test-PGateWinRMReachable {
    # Lightweight WinRM connectivity probe used by -Rediscover to classify freshly
    # discovered machines without waiting for an actual -Command run. Test-WSMan
    # performs an unauthenticated WS-Identify request, so it fails fast (no listener,
    # firewalled, etc.) the same way Invoke-Command would for these hosts in practice.
    param([string]$ComputerName)
    try {
        $null = Test-WSMan -ComputerName $ComputerName -ErrorAction Stop
        return [pscustomobject]@{ Reachable = $true; Error = $null }
    } catch {
        return [pscustomobject]@{ Reachable = $false; Error = $_.Exception.Message }
    }
}

# --- Discovery Engine ---

function Invoke-PGateDiscovery {
    param($Config)

    $nmap = Resolve-NmapPath -ConfiguredPath $Config.NmapPath
    if (-not $nmap) {
        throw "nmap.exe not found. Install Nmap for Windows (https://nmap.org/download.html) or set its path via -Setup."
    }

    # Determine subnets
    $subnets = if ($Config.ScanScope -eq 'AllLanSubnets') { 
        @(Get-AllLocalSubnets) 
    } else { 
        @(Get-DefaultRouteSubnet) 
    }
    $subnets = @($subnets | Where-Object { $_ })

    if (-not $subnets) { throw "Could not determine local subnet(s) to scan." }

    Write-Host "Scanning: $($subnets -join ', ')" -ForegroundColor Cyan

    # Use process-specific temp files with collision avoidance
    $tempBase = Join-Path $env:TEMP "pgate_$PID`_$(Get-Random -Minimum 1000 -Maximum 9999)"
    $pingXml = "${tempBase}_ping.xml"
    $osXml = "${tempBase}_os.xml"

    try {
        # Phase 1: Host discovery
        Write-Host "Phase 1: Host discovery..." -ForegroundColor DarkGray
        $pingArgs = @('-sn', '-oX', $pingXml, '--stats-every', '30s') + $subnets
        $pingOutput = & $nmap @pingArgs 2>&1
        $pingExit = $LASTEXITCODE

        if ($pingExit -ne 0 -and $pingExit -ne 1) {
            # nmap exit 1 means no hosts found, which is OK
            throw "nmap host discovery failed (exit $pingExit): $($pingOutput -join "`n")"
        }

        if (-not (Test-Path $pingXml -PathType Leaf)) {
            throw "nmap did not produce expected XML output"
        }

        # Parse ping results with namespace handling
        [xml]$pingDoc = $null
        try {
            $pingDoc = [xml](Get-Content $pingXml -Raw -Encoding UTF8)
        } catch {
            throw "Failed to parse nmap ping XML: $_"
        }

        # XPath traversal: SelectNodes returns an empty node list (never throws under
        # StrictMode) when nmap finds zero hosts, unlike the dot-property adapter which
        # only exposes .host when at least one <host> element exists.
        $liveHosts = @()
        if ($pingDoc.nmaprun) {
            $liveHosts = @($pingDoc.SelectNodes('//host') | ForEach-Object {
                $addrNode = $_.address | Where-Object { $_.addrtype -eq 'ipv4' -and $_.addr -notmatch '^0\.0\.0\.' } | Select-Object -First 1
                if ($addrNode) { $addrNode.addr }
            } | Where-Object { $_ })
        }

        if (-not $liveHosts) {
            Write-Warning "nmap found no live hosts on: $($subnets -join ', ')"
            return @()
        }

        # Exclude this machine - it always answers its own subnet's ping sweep, but it
        # isn't a "remote" target.
        $localIds = Get-LocalMachineIdentifiers
        $liveHosts = @($liveHosts | Where-Object { -not $localIds.IPs.Contains($_) })

        if (-not $liveHosts) {
            Write-Warning "nmap found no live (non-local) hosts on: $($subnets -join ', ')"
            return @()
        }

        Write-Host "Found $($liveHosts.Count) live host(s)" -ForegroundColor Cyan

        # Limit OS scan to reasonable batch size to avoid nmap command-line length limits
        $batchSize = 256
        $allMachines = [System.Collections.Generic.List[object]]::new()

        for ($i = 0; $i -lt $liveHosts.Count; $i += $batchSize) {
            $batch = $liveHosts[$i..([Math]::Min($i + $batchSize - 1, $liveHosts.Count - 1))]
            Write-Host "Phase 2: OS fingerprinting batch $($i/$batchSize + 1)/$([Math]::Ceiling($liveHosts.Count/$batchSize))..." -ForegroundColor DarkGray

            # Added performance flags for Nmap
            $osArgs = @(
                '-p445', 
                '--script', 'smb-os-discovery', 
                '-oX', $osXml, 
                '--stats-every', '30s',
                '-T4',              # Aggressive timing template
                '--min-hostgroup', '64', # Scan hosts in parallel groups
                '--max-retries', '2'     # Don't waste time on unresponsive hosts
            ) + $batch
            
            $osOutput = & $nmap @osArgs 2>&1
            $osExit = $LASTEXITCODE

            if ($osExit -ne 0 -and $osExit -ne 1) {
                Write-Warning "nmap OS scan failed for batch (exit $osExit), continuing..."
                continue
            }

            if (-not (Test-Path $osXml -PathType Leaf)) {
                Write-Warning "nmap OS scan produced no XML for batch, continuing..."
                continue
            }

            [xml]$osDoc = $null
            try {
                $osDoc = [xml](Get-Content $osXml -Raw -Encoding UTF8)
            } catch {
                Write-Warning "Failed to parse OS scan XML for batch: $_"
                continue
            }

            # Safer XML traversal for OS docs (XPath, see Phase 1 comment above)
            if ($osDoc.nmaprun) {
                foreach ($h in @($osDoc.SelectNodes('//host'))) {
                    $addrNode = $h.address | Where-Object { $_.addrtype -eq 'ipv4' } | Select-Object -First 1
                    if (-not $addrNode) { continue }
                    
                    $addr = $addrNode.addr
                    # Use XPath rather than the dot-property adapter: an empty <hostnames/>
                    # element (no name resolved for this host) comes back as a bare empty
                    # string from the adapter, and StrictMode throws on ''.hostname.
                    $hostnameNode = $h.SelectSingleNode('.//hostnames/hostname')
                    $hostname = if ($hostnameNode) { $hostnameNode.name } else { $null }

                    $osLine = $null
                    try {
                        $scriptNode = $h.SelectSingleNode(".//script[@id='smb-os-discovery']")
                        if ($scriptNode -and $scriptNode.output -match 'OS:\s*(.+)') { 
                            $osLine = $Matches[1].Trim() 
                        }
                    } catch { 
                        # XPath might fail on malformed XML, skip OS detection for this host
                    }

                    # Skip the local machine (belt-and-suspenders: the IP-based filter above
                    # runs before this NetBIOS name is even known, e.g. if nmap saw us via an
                    # interface Get-NetIPAddress didn't enumerate at scan time).
                    if ($localIds.IPs.Contains($addr) -or ($hostname -and $hostname -eq $localIds.Hostname)) {
                        continue
                    }

                    # Always include the host - IPAddress alone is enough to target or cache
                    # it, even when nmap couldn't resolve a hostname or fingerprint the OS
                    # (e.g. port 445 closed/filtered on that host).
                    $allMachines.Add([pscustomobject]@{
                        IPAddress = $addr
                        Hostname  = $hostname
                        OSInfo    = $osLine
                        DiscoveredAt = (Get-Date -Format 'o')
                    })
                }
            }

            # Clean up batch XML
            Remove-Item $osXml -Force -ErrorAction SilentlyContinue
        }

        $machines = $allMachines.ToArray()

        # Strict mode safe string checking
        if (-not [string]::IsNullOrWhiteSpace($Config.OsFilter) -and $Config.OsFilter -ne 'Any') {
            $beforeCount = $machines.Count
            $machines = @($machines | Where-Object { $_.OSInfo -like "*$($Config.OsFilter)*" })
            Write-Host "OS filter '$($Config.OsFilter)' matched $($machines.Count)/$beforeCount machines" -ForegroundColor DarkGray
        }

        return $machines
    }
    finally {
        # Aggressive cleanup of temp files
        @($pingXml, $osXml, "${tempBase}*") | ForEach-Object {
            Get-Item $_ -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Credential Management ---

function Get-PGateCredential {
    param($Config, $ExplicitCredential)

    if ($ExplicitCredential) { return $ExplicitCredential }

    if ($Config.CredentialMode -eq 'SavedCredential') {
        if (Test-Path $CredentialPath -PathType Leaf) {
            try {
                $cred = Import-Clixml -Path $CredentialPath
                # Validate it's actually a credential object
                if ($cred -is [pscredential]) { return $cred }
                Write-Warning "Saved credential file is corrupted. Will prompt for new credential."
                Remove-Item $CredentialPath -Force -ErrorAction SilentlyContinue
            } catch {
                Write-Warning "Failed to import saved credential: $_. Will prompt for new credential."
                # NOTE: DPAPI ties credentials to the user/machine. If moving configs, this will fail.
                Remove-Item $CredentialPath -Force -ErrorAction SilentlyContinue
            }
        }

        $cred = Get-Credential -Message "Credential PGate should use for remote machines"
        if (-not $cred) { throw "Credential prompt cancelled or failed." }

        try {
            $cred | Export-Clixml -Path $CredentialPath -Force
            # Secure the credential file
            $acl = Get-Acl $CredentialPath
            $acl.SetAccessRuleProtection($true, $false)
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
                "FullControl",
                "None",
                "None",
                "Allow"
            )
            $acl.AddAccessRule($rule)
            Set-Acl $CredentialPath $acl
        } catch {
            Write-Warning "Could not secure credential file: $_"
        }

        return $cred
    }
    return $null
}

# --- Bootstrap Generation ---

function New-PGateBootstrapScript {
    param(
        [string]$ManagementHost,
        [string]$BootstrapOutputPath = ".\Enable-PGateRemoting.ps1"
    )

    $mgmtHostValue = if ($ManagementHost) {
        $ManagementHost
    } else {
        $autoIp = Get-PrimaryLocalIPAddress
        if ($autoIp) {
            Write-Host "No -ManagementHost given - defaulting to this machine's local IP: $autoIp" -ForegroundColor DarkGray
            $autoIp
        } else {
            Write-Warning "Could not auto-detect this machine's local IP; falling back to '*' (trusts all hosts)."
            "*"
        }
    }

    # Validate ManagementHost if provided
    if ($ManagementHost -and $ManagementHost -ne '*') {
        try {
            $null = [System.Net.IPAddress]::Parse($ManagementHost)
        } catch {
            throw "Invalid ManagementHost IP address: $ManagementHost"
        }
    }

    $bootstrap = @"
#Requires -RunAsAdministrator
#Requires -Version 5.1
<#
.SYNOPSIS
    Enable PowerShell Remoting for PGate management.
.DESCRIPTION
    Run this ONCE, locally and elevated, on each Windows 10/11 machine PGate should be
    able to reach. It enables PowerShell Remoting (WinRM) and firewall access so the
    management PC can run remote commands against this machine afterward.
    Generated by pgate.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm')
.NOTES
    Safety: This script creates a system restore point before making changes.
#>
[CmdletBinding()]
param()

`$ErrorActionPreference = 'Stop'

# Create restore point for safety
try {
    Write-Host "Creating system restore point..." -ForegroundColor DarkGray
    Checkpoint-Computer -Description "PGate Remoting Enable" -RestorePointType "MODIFY_SETTINGS" -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Could not create restore point (non-fatal): `$_"
}

Write-Host "Enabling PowerShell Remoting..." -ForegroundColor Cyan
try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck
} catch {
    Write-Error "Failed to enable PSRemoting: `$_"
    exit 1
}

Write-Host "Configuring WinRM service..." -ForegroundColor Cyan
try {
    Set-Service WinRM -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service WinRM -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Could not configure WinRM service startup: `$_"
}

Write-Host "Opening firewall for WinRM..." -ForegroundColor Cyan
try {
    Get-NetFirewallRule -Name "WINRM-HTTP-In-TCP*" -ErrorAction SilentlyContinue | 
        Set-NetFirewallRule -Enabled True -Profile Any -ErrorAction Stop
} catch {
    Write-Warning "Could not configure firewall rules automatically. You may need to allow port 5985 manually."
}

# Also ensure WinRM HTTPS rule exists if applicable
try {
    Get-NetFirewallRule -Name "WINRM-HTTPS-In-TCP*" -ErrorAction SilentlyContinue |
        Set-NetFirewallRule -Enabled True -Profile Any -ErrorAction SilentlyContinue
} catch {}

# PGate's fast-ping pre-check (ping -n 1 -w 10 -4) needs inbound ICMP echo replies,
# which Windows Firewall blocks by default even when File and Printer Sharing is on.
Write-Host "Opening firewall for ICMP echo requests (ping)..." -ForegroundColor Cyan
try {
    Enable-NetFirewallRule -DisplayName "File and Printer Sharing (Echo Request - ICMPv4-In)" -ErrorAction Stop
    Write-Host "ICMPv4 Echo Request rule enabled." -ForegroundColor Green
} catch {
    Write-Warning "Could not enable the ICMPv4 Echo Request firewall rule automatically: `$_"
    Write-Warning "PGate's fast-ping pre-check will treat this machine as unreachable until inbound ping is allowed."
}

`$inDomain = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).PartOfDomain
if (-not `$inDomain) {
    Write-Host "Workgroup machine detected - configuring remoting without a domain..." -ForegroundColor Cyan

    # Disable UAC remote restrictions
    try {
        New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' ``
            -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force | Out-Null
    } catch {
        Write-Error "Failed to disable UAC remote restrictions: `$_"
        exit 1
    }

    # Configure TrustedHosts safely
    try {
        `$currentTrusted = (Get-Item WSMan:\localhost\Client\TrustedHosts -ErrorAction SilentlyContinue).Value
        `$desiredValue = "$mgmtHostValue"

        if (`$currentTrusted -and `$currentTrusted -ne '*' -and `$desiredValue -ne '*') {
            # Append rather than overwrite if both are specific hosts
            if (`$currentTrusted -notmatch [regex]::Escape(`$desiredValue)) {
                `$newValue = "`$currentTrusted,`$desiredValue"
                Set-Item WSMan:\localhost\Client\TrustedHosts -Value `$newValue -Force
                Write-Host "Added '$mgmtHostValue' to existing TrustedHosts list." -ForegroundColor Green
            } else {
                Write-Host "'$mgmtHostValue' already in TrustedHosts list." -ForegroundColor Green
            }
        } else {
            Set-Item WSMan:\localhost\Client\TrustedHosts -Value `$desiredValue -Force
            Write-Host "Set TrustedHosts to '$mgmtHostValue'." -ForegroundColor Green
        }

        Write-Host "Current TrustedHosts: `$((Get-Item WSMan:\localhost\Client\TrustedHosts).Value)" -ForegroundColor DarkGray
    } catch {
        Write-Error "Failed to configure TrustedHosts: `$_"
        exit 1
    }
} else {
    Write-Host "Domain-joined machine detected - using Kerberos authentication." -ForegroundColor Green
}

# Restart WinRM to apply all changes
Write-Host "Restarting WinRM service..." -ForegroundColor Cyan
try {
    Restart-Service WinRM -Force
    Start-Sleep -Seconds 2
    `$status = Get-Service WinRM
    if (`$status.Status -ne 'Running') {
        throw "WinRM service is not running after restart"
    }
} catch {
    Write-Error "Failed to restart WinRM: `$_"
    exit 1
}

# Verify remoting is actually working
Write-Host "Verifying remoting configuration..." -ForegroundColor Cyan
try {
    `$test = Test-WSMan -ErrorAction Stop
    Write-Host "WinRM is responding. Auth: `$(`$test.ProductVersion)" -ForegroundColor Green
} catch {
    Write-Warning "WinRM self-test failed: `$_"
}

Write-Host "" 
Write-Host "Done. This machine (`$env:COMPUTERNAME) can now be reached by PGate." -ForegroundColor Green
Write-Host "Run 'Disable-PSRemoting' to reverse these changes." -ForegroundColor DarkGray
"@

    try {
        # Ensure directory exists
        $bootstrapDir = Split-Path $BootstrapOutputPath -Parent
        if ($bootstrapDir -and -not (Test-Path $bootstrapDir)) {
            New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null
        }

        Set-Content -Path $BootstrapOutputPath -Value $bootstrap -Encoding UTF8 -Force
        Write-Host "Bootstrap script written to $BootstrapOutputPath" -ForegroundColor Green
        Write-Host "Copy it to each target machine and run it once from an elevated PowerShell prompt." -ForegroundColor Green
    } catch {
        throw "Failed to write bootstrap script: $_"
    }
}

if ($GenerateBootstrap) {
    try {
        New-PGateBootstrapScript -ManagementHost $ManagementHost -BootstrapOutputPath $BootstrapOutputPath
    } catch {
        Write-Error "$_"
        exit 1
    }
    return
}

# --- List Saved Hosts Only ---

function Show-PGateSavedHosts {
    $saved = @(Get-HostsCache)
    $unreachable = @(Get-UnreachableHostsCache)

    Write-Host "=== Saved targetable hosts ($($saved.Count)) ===" -ForegroundColor Cyan
    if ($saved.Count -eq 0) {
        Write-Host "  (none - run -Rediscover or a normal scan first)" -ForegroundColor DarkGray
    } else {
        foreach ($m in $saved) {
            $label = if ($m.Hostname) { $m.Hostname } else { $m.IPAddress }
            $ipPart = if ($m.Hostname -and $m.IPAddress) { " ($($m.IPAddress))" } else { "" }
            $osPart = if ($m.OSInfo) { " - $($m.OSInfo)" } else { "" }
            Write-Host "  $label$ipPart$osPart" -ForegroundColor Green
        }
    }

    Write-Host ""
    Write-Host "=== Unreachable hosts ($($unreachable.Count)) ===" -ForegroundColor Cyan
    if ($unreachable.Count -eq 0) {
        Write-Host "  (none)" -ForegroundColor DarkGray
    } else {
        foreach ($m in $unreachable) {
            $label = if ($m.Hostname) { $m.Hostname } else { $m.IPAddress }
            Write-Host "  $label" -ForegroundColor Red
        }
    }
}

if ($ListSavedHosts) {
    Show-PGateSavedHosts
    exit 0
}

# --- Setup Only ---

if ($Setup) {
    try {
        Initialize-PGateConfig | Out-Null
    } catch {
        Write-Error "Setup failed: $_"
        exit 1
    }
    return
}

# --- Normal Run ---

# Load or create config
$config = $null
try {
    if (Test-Path $ConfigPath -PathType Leaf) { 
        $config = Get-PGateConfig 
    } else { 
        $config = Initialize-PGateConfig 
    }
} catch {
    Write-Error "Configuration error: $_"
    exit 1
}

# Validate input parameters
# Safe array wrapping for strict mode
$specified = @($Command, $ScriptBlock, $FilePath) | Where-Object { $_ }
if (@($specified).Count -gt 1) { 
    Write-Error "Specify only one of -Command, -ScriptBlock, -FilePath."
    exit 1
}

# Handle standalone -Rediscover with no execution parameters
if (@($specified).Count -eq 0) {
    if ($Rediscover) {
        Write-Host "Running standalone discovery..." -ForegroundColor Cyan
        try {
            $machines = Invoke-PGateDiscovery -Config $config
            $machineCount = if ($machines) { @($machines).Count } else { 0 }

            if ($machineCount -eq 0) {
                Write-Host "No machines discovered." -ForegroundColor Yellow
                Write-Host ""
                Show-PGateSavedHosts
                exit 0
            }

            Write-Host "Testing WinRM reachability on $machineCount machine(s)..." -ForegroundColor DarkGray
            $reachable = [System.Collections.Generic.List[object]]::new()
            $unreachableEntries = [System.Collections.Generic.List[object]]::new()

            foreach ($m in $machines) {
                $name = if ($m.Hostname) { $m.Hostname } else { $m.IPAddress }
                $probe = Test-PGateWinRMReachable -ComputerName $name
                if ($probe.Reachable) {
                    $reachable.Add($m)
                } else {
                    $unreachableEntries.Add([pscustomobject]@{
                        Hostname    = $m.Hostname
                        IPAddress   = $m.IPAddress
                        OSInfo      = $m.OSInfo
                        LastError   = $probe.Error
                        LastAttempt = (Get-Date -Format 'o')
                    })
                }
            }

            $reachableNames = @($reachable | ForEach-Object { if ($_.Hostname) { $_.Hostname } else { $_.IPAddress } })

            if ($config.SaveDiscoveredHosts) {
                Save-HostsCache -Machines $reachable.ToArray()
                Sync-PGateUnreachableCache -ReachableNames $reachableNames -UnreachableEntries $unreachableEntries.ToArray()
                Write-Host "Discovered $machineCount machine(s): $($reachable.Count) reachable (cached), $($unreachableEntries.Count) unreachable." -ForegroundColor Green
            } else {
                Write-Host "Discovered $machineCount machine(s): $($reachable.Count) reachable, $($unreachableEntries.Count) unreachable. (Cache saving disabled in config)." -ForegroundColor Green
            }
            Write-Host ""
            Show-PGateSavedHosts
            exit 0
        } catch {
            Write-Error "Standalone discovery failed: $_"
            exit 1
        }
    }
    
    # Show help if no execution parameters were provided
    Show-PGateHelp
    exit 0
}

# Validate command syntax if provided as string
if ($Command -and -not (Test-ValidScriptBlock $Command)) {
    Write-Error "The provided -Command contains invalid PowerShell syntax."
    exit 1
}

# Validate file path if provided
if ($FilePath) {
    if (-not (Test-Path $FilePath -PathType Leaf)) {
        Write-Error "Script file not found: $FilePath"
        exit 1
    }
    # Test parse the script
    try {
        $null = [System.Management.Automation.PSParser]::Tokenize((Get-Content $FilePath -Raw), [ref]$null)
    } catch {
        Write-Error "Script file has syntax errors: $_"
        exit 1
    }
}

# Validate throttle and timeout overrides
if ($ThrottleLimit -and ($ThrottleLimit -lt 1 -or $ThrottleLimit -gt 256)) {
    Write-Error "ThrottleLimit must be between 1 and 256"
    exit 1
}
if ($TimeoutSeconds -and $TimeoutSeconds -lt 10) {
    Write-Error "TimeoutSeconds must be at least 10"
    exit 1
}
if ($MaxRetries -lt 0 -or $MaxRetries -gt 5) {
    Write-Error "MaxRetries must be between 0 and 5"
    exit 1
}

# --- Auto-install nmap if requested or if missing during discovery ---

function Ensure-NmapAvailable {
    param(
        [switch]$AutoInstall,
        [string]$ConfiguredPath
    )

    $nmap = Resolve-NmapPath -ConfiguredPath $ConfiguredPath
    if ($nmap) { return $nmap }

    if (-not $AutoInstall) {
        return $null
    }

    Write-Host "nmap not found. Attempting auto-install via winget..." -ForegroundColor Yellow

    $winget = Test-WingetAvailable
    if (-not $winget) {
        Write-Warning "winget is not available. Cannot auto-install nmap."
        return $null
    }

    if (-not (Test-IsAdmin)) {
        Write-Warning "Auto-install requires Administrator privileges. Run as Administrator or install nmap manually."
        return $null
    }

    try {
        return Install-NmapViaWinget -Silent -AcceptAgreements
    } catch {
        Write-Warning "Auto-install failed: $_"
        return $null
    }
}

# Pre-check nmap availability
$nmapPath = Ensure-NmapAvailable -AutoInstall:$AutoInstallNmap -ConfiguredPath $config.NmapPath
if (-not $nmapPath -and -not $Targets) {
    # Discovery requires nmap; execution-only with explicit targets does not
    Write-Error "nmap is required for network discovery but was not found. Run with -AutoInstallNmap (as Admin), install manually, or provide explicit -Targets."
    exit 1
}

# Update config with resolved nmap path if it changed
if ($nmapPath -and $nmapPath -ne $config.NmapPath) {
    $config.NmapPath = $nmapPath
    try {
        $config | ConvertTo-Json -Depth 4 | Set-Content -Path $ConfigPath -Encoding UTF8 -Force
    } catch {
        Write-Warning "Could not update config with new nmap path: $_"
    }
}

# Resolve targets
$targetList = @()
$machines = $null  # Populated only in the discovery branch below; referenced later when pruning the hosts cache
if ($Targets) {
    # Validate each target
    foreach ($t in $Targets) {
        if ([string]::IsNullOrWhiteSpace($t)) { continue }
        # Basic validation: not empty, no invalid chars
        if ($t -match '[<>|&;]') {
            Write-Warning "Skipping invalid target name: $t"
            continue
        }
        $targetList += $t.Trim()
    }
    if (-not $targetList) {
        Write-Error "No valid targets specified."
        exit 1
    }
} else {
    if (-not $Rediscover -and $config.SaveDiscoveredHosts -and (Test-Path $HostsCachePath -PathType Leaf)) {
        $machines = Get-HostsCache
        # Safe array count check
        if ($machines -and @($machines).Count -gt 0) {
            Write-Host "Using cached host list ($(@($machines).Count) machine(s)). Use -Rediscover to rescan." -ForegroundColor DarkGray
        }
    }

    # Safe array count check to prevent StrictMode null .Count crashes
    if (-not $machines -or @($machines).Count -eq 0) {
        try {
            $machines = Invoke-PGateDiscovery -Config $config
            if ($config.SaveDiscoveredHosts -and $machines) { 
                Save-HostsCache -Machines $machines 
            }
        } catch {
            Write-Error "Discovery failed: $_"
            exit 1
        }
    }

    # Exclude the local machine and anything already known to be unreachable - a
    # safety net for caches saved before/without these filters (fresh discovery and
    # -Rediscover already keep both kinds out at the source).
    $filteredMachines = @(Get-PGateTargetableMachines -Machines $machines)
    if ($filteredMachines.Count -lt @($machines).Count -and $config.SaveDiscoveredHosts) {
        Save-HostsCache -Machines $filteredMachines
    }
    $machines = $filteredMachines

    # Safe array count check
    if (-not $machines -or @($machines).Count -eq 0) {
        Write-Warning "No target machines found."
        exit 0
    }

    $targetList = @($machines | ForEach-Object {
        if ($_.Hostname) { $_.Hostname } else { $_.IPAddress }
    } | Where-Object { $_ } | Select-Object -Unique)
}

# Resolve runtime parameters
$throttle = if ($ThrottleLimit) { $ThrottleLimit } else { $config.ThrottleLimit }
$timeout = if ($TimeoutSeconds) { $TimeoutSeconds } else { $config.TimeoutSeconds }

# Get credentials
try {
    $cred = Get-PGateCredential -Config $config -ExplicitCredential $Credential
} catch {
    Write-Error "Credential error: $_"
    exit 1
}

# --- Destructive Command Confirmation ---

$commandText = if ($FilePath) { Get-Content -Path $FilePath -Raw } elseif ($ScriptBlock) { $ScriptBlock.ToString() } else { $Command }
$destructiveHits = @(Get-PGateDestructiveKeywordMatches -Text $commandText)

if ($destructiveHits.Count -gt 0 -and -not $Force) {
    Write-Warning "This command looks like it may be destructive (matched: $($destructiveHits -join ', '))."
    $confirmAns = Read-Host "Run it against $(@($targetList).Count) machine(s)? (y/N)"
    if ($confirmAns -notmatch '^[Yy]$') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 1
    }
}

# --- Execution Engine ---

# Ensure this machine's own WinRM client trusts the targets - see Sync-PGateLocalTrustedHosts
# for why this (not anything on the target) is what Invoke-Command actually needs.
Sync-PGateLocalTrustedHosts -TargetNames $targetList

# Build invocation parameters
$icmParams = @{
    ComputerName  = $targetList
    ThrottleLimit = $throttle
    AsJob         = $true
    ErrorAction   = 'SilentlyContinue'
}
if ($cred) { $icmParams.Credential = $cred }
if ($FilePath) { $icmParams.FilePath = $FilePath }
elseif ($ScriptBlock) { $icmParams.ScriptBlock = $ScriptBlock }
else { 
    try {
        $icmParams.ScriptBlock = [scriptblock]::Create($Command)
    } catch {
        Write-Error "Failed to create script block from command: $_"
        exit 1
    }
}

Write-Host "Running on $(@($targetList).Count) machine(s) (timeout ${timeout}s, throttle $throttle, retries $MaxRetries)..." -ForegroundColor Cyan

# Initialize results tracking
$results = [ordered]@{}  # Must use ordered to maintain target order
foreach ($target in $targetList) {
    $results[$target] = [pscustomobject]@{ 
        Status   = 'PENDING'
        Output   = [System.Collections.Generic.List[object]]::new()
        Error    = 'Job not yet processed'
        Elapsed  = $null
        Attempts = 0
    }
}

# Execute with retry logic
$currentTargets = $targetList.Clone()
$attempt = 0
$maxAttempts = $MaxRetries + 1

# Safe array count check
while (@($currentTargets).Count -gt 0 -and $attempt -lt $maxAttempts) {
    $attempt++
    if ($attempt -gt 1) {
        Write-Host "Retry attempt $($attempt - 1)/$MaxRetries for $(@($currentTargets).Count) machine(s)..." -ForegroundColor Yellow
    }

    # Fast ping pre-check: skip the (much slower) WinRM connection attempt for hosts
    # that don't even answer a single ICMP echo, so a dead host fails/retries fast
    # instead of tying up a slot for the full WinRM $timeout.
    $pingTargets = [System.Collections.Generic.List[string]]::new()
    $nextTargets = [System.Collections.Generic.List[string]]::new()
    foreach ($t in $currentTargets) {
        if (Test-PGateFastPing -ComputerName $t) {
            $pingTargets.Add($t)
        } else {
            $results[$t].Attempts = $attempt
            if ($attempt -lt $maxAttempts) {
                $results[$t].Status = 'PENDING'
                $results[$t].Error = "Fast ping (ping -n 1 -w 10 -4) failed on attempt $attempt, will retry..."
                $nextTargets.Add($t)
            } else {
                $results[$t].Status = 'UNREACHABLE'
                $results[$t].Error = "Fast ping (ping -n 1 -w 10 -4) got no reply after $maxAttempts attempt(s)"
            }
        }
    }

    if ($pingTargets.Count -eq 0) {
        $currentTargets = $nextTargets.ToArray()
        if (@($currentTargets).Count -gt 0 -and $attempt -lt $maxAttempts) {
            Start-Sleep -Seconds ([Math]::Min(5 * $attempt, 15))
        }
        continue
    }

    $job = $null
    try {
        $icmParams['ComputerName'] = $pingTargets.ToArray()
        $job = Invoke-Command @icmParams
    } catch {
        Write-Error "Failed to invoke remote command: $_"
        exit 1
    }

    # Wait for completion with timeout
    $waitResult = $null
    try {
        $waitResult = Wait-Job -Job $job -Timeout $timeout -ErrorAction SilentlyContinue
    } catch {
        # Wait-Job can throw in edge cases
        Write-Warning "Wait-Job encountered an issue: $_"
    }

    # Process results for this attempt (retries from the fast-ping filter above are
    # already queued in $nextTargets; this section only adds to it)

    # Ensure child jobs exist before iterating
    if (-not $job.ChildJobs) {
        Write-Warning "No child jobs were created. All targets may be unreachable."
        foreach ($target in $pingTargets) {
            $results[$target].Status = 'UNREACHABLE'
            $results[$target].Error = 'No child job created - check WinRM connectivity'
            $results[$target].Attempts = $attempt
        }
        # Also finalize anything the fast-ping filter above queued for retry - the loop
        # is aborting here, so those hosts won't get another attempt to resolve them.
        foreach ($target in $nextTargets) {
            if ($results[$target].Status -eq 'PENDING') {
                $results[$target].Status = 'UNREACHABLE'
                $results[$target].Error = 'No child job created - check WinRM connectivity'
            }
        }
        break
    }

    foreach ($child in $job.ChildJobs) {
        $name = $child.Location
        if (-not $name) { 
            Write-Warning "Child job missing Location property, skipping"
            continue 
        }

        $results[$name].Attempts = $attempt

        # Calculate elapsed time safely
        $elapsed = $null
        try {
            if ($child.PSBeginTime -and $child.PSEndTime) {
                $elapsed = [math]::Round((New-TimeSpan -Start $child.PSBeginTime -End $child.PSEndTime).TotalSeconds, 1)
            } elseif ($child.PSBeginTime) {
                $elapsed = [math]::Round((New-TimeSpan -Start $child.PSBeginTime).TotalSeconds, 1)
            }
        } catch { 
            # Time calculation failed, non-critical
        }
        $results[$name].Elapsed = $elapsed

        if ($child.State -eq 'Running') {
            # Timeout occurred
            try {
                Stop-Job -Job $child -ErrorAction SilentlyContinue
                # Try to receive any partial output before it's lost
                $partial = Receive-Job -Job $child -ErrorAction SilentlyContinue
                if ($partial) {
                    $results[$name].Output.AddRange(@($partial))
                }
            } catch {}

            if ($attempt -lt $maxAttempts) {
                $results[$name].Status = 'PENDING'
                $results[$name].Error = "Timeout on attempt $attempt, will retry..."
                $nextTargets.Add($name)
            } else {
                $results[$name].Status = 'TIMEOUT'
                $results[$name].Error = "No response within ${timeout}s after $maxAttempts attempt(s)"
            }
            continue
        }

        # Receive output (do this BEFORE checking state to avoid losing it)
        $out = @()
        $err = $null
        try {
            $out = @(Receive-Job -Job $child -ErrorAction SilentlyContinue)
        } catch {
            $err = "Failed to receive job output: $_"
        }

        if ($child.State -eq 'Failed') {
            # Extract best error message
            $errMsg = $err
            # Safe array count check
            if (-not $errMsg -and $child.Error -and @($child.Error).Count -gt 0) { 
                try { $errMsg = $child.Error[0].ToString() } catch {} 
            }
            if (-not $errMsg -and $child.JobStateInfo.Reason) { 
                try { $errMsg = $child.JobStateInfo.Reason.Message } catch {} 
            }
            if (-not $errMsg) { $errMsg = "Connection failed" }

            # Check if retryable
            $retryable = $errMsg -match 'cannot connect|unreachable|timeout|RPC server|WinRM|access denied|logon failure'
            if ($retryable -and $attempt -lt $maxAttempts) {
                $results[$name].Status = 'PENDING'
                $results[$name].Error = "Failed on attempt $attempt, will retry..."
                $nextTargets.Add($name)
            } else {
                $results[$name].Status = 'UNREACHABLE'
                $results[$name].Error = $errMsg
                if ($out) { $results[$name].Output.AddRange(@($out)) }
            }
        } elseif ($child.Error -and @($child.Error).Count -gt 0) {
            # Job completed but with errors in the stream
            $results[$name].Status = 'ERROR'
            try { 
                $results[$name].Error = ($child.Error[0]).ToString() 
            } catch { 
                $results[$name].Error = "Remote execution error" 
            }
            if ($out) { $results[$name].Output.AddRange(@($out)) }
        } else {
            # Success
            $results[$name].Status = 'OK'
            $results[$name].Error = $null
            if ($out) { $results[$name].Output.AddRange(@($out)) }
        }
    }

    # Cleanup
    if ($job) {
        try {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    $currentTargets = $nextTargets.ToArray()

    # Brief pause between retries to let network settle
    # Safe array count check
    if (@($currentTargets).Count -gt 0 -and $attempt -lt $maxAttempts) {
        Start-Sleep -Seconds ([Math]::Min(5 * $attempt, 15))
    }
}

# Refresh the unreachable-hosts cache with what we learned this run, then re-derive
# the targetable discovery cache from it so the two lists never overlap (a host that's
# UNREACHABLE this run must not remain in the discovery cache). Unreachable tracking
# applies regardless of -Targets; re-saving the discovery cache only applies when we
# actually have $machines to re-save (i.e. not an explicit -Targets run).
#
# Only reclassify Saved -> Unreachable during an explicit -Rediscover: a single
# -Command run failing against a host (busy, transient network blip, long-running
# script tying up the WinRM session) shouldn't be enough to evict it from the
# discovery cache - that judgment is reserved for the deliberate rediscovery step.
if ($config.SaveDiscoveredHosts -and $Rediscover) {
    $unreachableThisRun = @($targetList | Where-Object { $results[$_].Status -eq 'UNREACHABLE' })
    $reachableThisRun   = @($targetList | Where-Object { $results[$_].Status -ne 'UNREACHABLE' })

    $newUnreachableEntries = @($unreachableThisRun | ForEach-Object {
        $target = $_
        $machineInfo = if ($machines) { @($machines | Where-Object { $_.Hostname -eq $target -or $_.IPAddress -eq $target }) | Select-Object -First 1 } else { $null }
        [pscustomobject]@{
            Hostname    = if ($machineInfo -and $machineInfo.Hostname) { $machineInfo.Hostname } else { $target }
            IPAddress   = if ($machineInfo) { $machineInfo.IPAddress } else { $null }
            OSInfo      = if ($machineInfo) { $machineInfo.OSInfo } else { $null }
            LastError   = $results[$target].Error
            LastAttempt = (Get-Date -Format 'o')
        }
    })

    Sync-PGateUnreachableCache -ReachableNames $reachableThisRun -UnreachableEntries $newUnreachableEntries

    if (-not $Targets -and $machines -and @($machines).Count -gt 0) {
        $stillTargetable = @(Get-PGateTargetableMachines -Machines $machines)
        if ($stillTargetable.Count -lt @($machines).Count) {
            Save-HostsCache -Machines $stillTargetable
            Write-Host "Removed $($unreachableThisRun.Count) unreachable host(s) from the discovery cache." -ForegroundColor DarkGray
        }
    }
}

# --- Output & Logging ---

$logLines = New-Object System.Collections.Generic.List[string]
$resultObjects = [System.Collections.Generic.List[object]]::new()
$successCount = 0
$failCount = 0

foreach ($target in $targetList) {
    $r = $results[$target]
    $color = switch ($r.Status) {
        'OK'      { 'Green' }
        'TIMEOUT' { 'Yellow' }
        'ERROR'   { 'Magenta' }
        default   { 'Red' }
    }

    if ($r.Status -eq 'OK') { $successCount++ } else { $failCount++ }

    $outputLines = @($r.Output | ForEach-Object { if ($_ -is [string]) { $_ } else { $_ | Out-String } })

    $resultObjects.Add([pscustomobject]@{
        Target   = $target
        Status   = $r.Status
        Elapsed  = $r.Elapsed
        Attempts = $r.Attempts
        Error    = $r.Error
        Output   = ($outputLines -join "`n")
    })

    $elapsedText = if ($r.Elapsed) { " ($($r.Elapsed)s)" } else { "" }
    $attemptText = if ($r.Attempts -gt 1) { " [attempts: $($r.Attempts)]" } else { "" }
    $header = "=== $target [$($r.Status)]$elapsedText$attemptText ==="

    if ($OutputFormat -eq 'Text') { Write-Host $header -ForegroundColor $color }
    $logLines.Add($header)

    if ($r.Status -eq 'OK') {
        foreach ($text in $outputLines) {
            if ($OutputFormat -eq 'Text') { Write-Host "  $text" }
            $logLines.Add("  $text")
        }
    } else {
        $errText = if ($r.Error) { $r.Error.ToString() } else { "Unknown error" }
        if ($OutputFormat -eq 'Text') { Write-Host "  $errText" -ForegroundColor Red }
        $logLines.Add("  $errText")

        if ($r.Status -eq 'UNREACHABLE') {
            $hint = "  Hint: this machine may not have PS Remoting enabled - see .\pgate.ps1 -GenerateBootstrap"
            if ($OutputFormat -eq 'Text') { Write-Host $hint -ForegroundColor DarkGray }
            $logLines.Add($hint)
        }
    }
    if ($OutputFormat -eq 'Text') { Write-Host "" }
    $logLines.Add("")
}

# For Json/Csv, emit the structured per-host results to the success stream (so they can be
# piped/captured/redirected cleanly) - the colored summary below still goes to the console
# host either way, since Write-Host doesn't touch the success stream.
switch ($OutputFormat) {
    'Json' { $resultObjects.ToArray() | ConvertTo-Json -Depth 4 }
    'Csv'  { $resultObjects.ToArray() | ConvertTo-Csv -NoTypeInformation }
}

# Summary
Write-Host "---" -ForegroundColor Cyan
Write-Host "Summary: $successCount OK, $failCount failed of $(@($targetList).Count) total" -ForegroundColor $(if ($failCount -eq 0) { 'Green' } else { 'Yellow' })
$logLines.Add("---")
$logLines.Add("Summary: $successCount OK, $failCount failed of $(@($targetList).Count) total")

# Write log
if ($config.LogResults) {
    try {
        if (-not (Test-Path $LogDir)) { 
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null 
        }
        $logFile = Join-Path $LogDir ("pgate_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        $logLines | Set-Content -Path $logFile -Encoding UTF8 -Force
        Write-Host "Log written to $logFile" -ForegroundColor DarkGray
    } catch {
        Write-Warning "Failed to write log file: $_"
    }
}

# Exit with non-zero if any failures (for CI/CD integration)
if ($failCount -gt 0) {
    exit [Math]::Min($failCount, 255)
}
