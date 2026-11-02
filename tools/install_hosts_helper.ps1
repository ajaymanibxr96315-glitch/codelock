<#
CodeLock hosts-helper installer.

Run this ONCE from an elevated PowerShell. It is the only supported way to
create the trusted installation that CodeLock verifies before every elevated
launch:

    powershell -NoProfile -ExecutionPolicy Bypass `
        -File .\tools\install_hosts_helper.ps1

The installer:
  * copies codelock\hosts_helper.ps1 into %ProgramFiles%\CodeLock;
  * writes hosts_helper.manifest.json with the SHA-256 of the copied file;
  * sets the owner to Administrators and replaces inherited permissions with
    SYSTEM/Administrators full control and Users read+execute;
  * does NOT run the helper and does NOT touch the hosts file.

CodeLock never installs or refreshes this helper by itself. To update the
helper, run this installer again from an elevated terminal.
#>
[CmdletBinding()]
param(
    [string]$Source,
    [string]$InstallDirectory
)

$ErrorActionPreference = 'Stop'

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Icacls {
    param([string[]]$Arguments)
    & "$env:SystemRoot\System32\icacls.exe" @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "icacls failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

if (-not (Test-Elevated)) {
    Write-Error 'Run this installer from an elevated PowerShell window.'
    exit 1
}

if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    $InstallDirectory = Join-Path $programFiles 'CodeLock'
}
$InstallDirectory = [IO.Path]::GetFullPath($InstallDirectory)

if ([string]::IsNullOrWhiteSpace($Source)) {
    $Source = Join-Path $PSScriptRoot '..\codelock\hosts_helper.ps1'
}
$Source = [IO.Path]::GetFullPath($Source)
if (-not [IO.File]::Exists($Source)) {
    Write-Error "Helper source not found: $Source"
    exit 1
}

$helperName = 'hosts_helper.ps1'
$manifestName = 'hosts_helper.manifest.json'
$helperTarget = Join-Path $InstallDirectory $helperName
$manifestTarget = Join-Path $InstallDirectory $manifestName

if (-not [IO.Directory]::Exists($InstallDirectory)) {
    New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
}

# Replace inherited permissions on the directory itself first.
Invoke-Icacls @(
    $InstallDirectory,
    '/inheritance:r',
    '/grant:r', '*S-1-5-18:(OI)(CI)F',
    '/grant:r', '*S-1-5-32-544:(OI)(CI)F',
    '/grant:r', '*S-1-5-32-545:(OI)(CI)RX'
)
Invoke-Icacls @($InstallDirectory, '/setowner', '*S-1-5-32-544')

# Remove an old pair so the new files inherit the protected directory ACL.
foreach ($path in @($helperTarget, $manifestTarget)) {
    if ([IO.File]::Exists($path)) {
        try { [IO.File]::Delete($path) } catch { throw "Could not replace $path" }
    }
}

[IO.File]::Copy($Source, $helperTarget, $false)
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash.ToLowerInvariant()
$copiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $helperTarget).Hash.ToLowerInvariant()
if ($sourceHash -ne $copiedHash) {
    Write-Error 'The copied helper does not match the source. Installation aborted.'
    exit 1
}

$manifest = [ordered]@{
    product      = 'CodeLock'
    format       = 1
    helper       = $helperName
    algorithm    = 'sha256'
    sha256       = $copiedHash
    size         = (Get-Item -LiteralPath $helperTarget).Length
    installed_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    installer    = 'tools/install_hosts_helper.ps1'
}
$manifestText = ConvertTo-Json -InputObject $manifest
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($manifestTarget, $manifestText, $utf8)

foreach ($path in @($helperTarget, $manifestTarget)) {
    Invoke-Icacls @($path, '/inheritance:r')
    Invoke-Icacls @(
        $path,
        '/grant:r', '*S-1-5-18:F',
        '/grant:r', '*S-1-5-32-544:F',
        '/grant:r', '*S-1-5-32-545:RX'
    )
    Invoke-Icacls @($path, '/setowner', '*S-1-5-32-544')
}

Write-Output "Installed $helperTarget"
Write-Output "Manifest  $manifestTarget"
Write-Output "SHA-256   $copiedHash"
Write-Output 'The hosts file was not changed. Start CodeLock to verify the installation.'
