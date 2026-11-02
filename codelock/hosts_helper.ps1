<#
CodeLock hosts helper.

This script is installed once into a protected location
(Program Files\CodeLock) by an administrator. The GUI never copies it from the
project folder at run time and never executes project-folder code elevated.

Fixed interface:
    -Operation block | unblock | status | recover | repair

``repair`` removes damaged CodeLock entries and then writes a fresh verified
block in the same elevated run; ``recover`` removes the entries and leaves the
hosts file unblocked (used by --restore and by shutdown).

The blocked websites, redirect address and markers are compiled into this file.
The helper never accepts a hosts path, hostname, command or hosts content from
the caller. The only test hook is -TestMode, which is refused inside an
elevated process and requires CODELOCK_HELPER_TEST_HOSTS_PATH; it exists so the
offline self-test can exercise the script against temporary files.

Exit codes:
    0  operation completed and verified
    2  invalid invocation / refused test mode
    3  permission, encoding or write failure
    4  post-write verification failure
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('block', 'unblock', 'status', 'recover', 'repair')]
    [string]$Operation,

    [switch]$TestMode
)

$ErrorActionPreference = 'Stop'

$script:BeginMarker = '# >>> CodeLock block (managed automatically) >>>'
$script:EndMarker = '# <<< CodeLock block (managed automatically) <<<'
$script:RedirectIp = '0.0.0.0'
$script:Websites = @(
    'instagram.com',
    'www.instagram.com',
    'facebook.com',
    'www.facebook.com',
    'x.com',
    'www.x.com',
    'twitter.com',
    'www.twitter.com',
    'reddit.com',
    'www.reddit.com',
    'tiktok.com',
    'www.tiktok.com',
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'netflix.com',
    'www.netflix.com',
    'twitch.tv',
    'www.twitch.tv',
    'primevideo.com',
    'www.primevideo.com'
)

function Test-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Payload {
    param([hashtable]$Payload)
    $Payload['operation'] = $Operation
    Write-Output (ConvertTo-Json -InputObject $Payload -Compress)
}

function Read-HostsDocument {
    param([string]$Path)

    if (-not [IO.File]::Exists($Path)) {
        return [pscustomobject]@{
            Exists      = $false
            Bytes       = [byte[]]@()
            Text        = ''
            EncodingName = 'utf8'
            Newline     = "`n"
        }
    }

    $bytes = [IO.File]::ReadAllBytes($Path)
    $encodingName = 'utf8'
    $text = ''

    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $encodingName = 'utf8-bom'
        $text = [Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $encodingName = 'utf16-le'
        $text = [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $encodingName = 'utf16-be'
        $text = [Text.Encoding]::BigEndianUnicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    else {
        try {
            $strict = New-Object Text.UTF8Encoding($false, $true)
            $text = $strict.GetString($bytes)
        }
        catch {
            $encodingName = 'ansi'
            $text = [Text.Encoding]::Default.GetString($bytes)
        }
    }

    $newline = "`n"
    if ($text.Contains("`r`n")) { $newline = "`r`n" }

    return [pscustomobject]@{
        Exists       = $true
        Bytes        = $bytes
        Text         = $text
        EncodingName = $encodingName
        Newline      = $newline
    }
}

function Get-ManagedState {
    param([string]$Text)

    $inside = $false
    $begins = 0
    $ends = 0
    $bad = $false

    foreach ($line in [regex]::Split($Text, "\r\n|\n|\r")) {
        $trimmed = $line.Trim()
        if ($trimmed -ceq $script:BeginMarker) {
            if ($inside) { $bad = $true }
            else { $inside = $true; $begins++ }
        }
        elseif ($trimmed -ceq $script:EndMarker) {
            if (-not $inside) { $bad = $true }
            else { $inside = $false; $ends++ }
        }
    }
    if ($inside) { $bad = $true }

    $wellFormed = (-not $bad) -and ($begins -eq $ends) -and ($begins -le 1)
    $blocked = $wellFormed -and ($begins -eq 1)

    return [pscustomobject]@{
        Blocked    = [bool]$blocked
        WellFormed = [bool]$wellFormed
        Begins     = $begins
        Ends       = $ends
    }
}

function Test-CompleteBlock {
    param([string]$Text)

    $state = Get-ManagedState $Text
    if (-not $state.Blocked) { return $false }

    $inside = $false
    $found = @{}
    foreach ($line in [regex]::Split($Text, "\r\n|\n|\r")) {
        $trimmed = $line.Trim()
        if ($trimmed -ceq $script:BeginMarker) { $inside = $true; continue }
        if ($trimmed -ceq $script:EndMarker) { $inside = $false; continue }
        if ($inside) {
            foreach ($site in $script:Websites) {
                if ($trimmed -ceq ("$script:RedirectIp $site")) { $found[$site] = $true }
            }
        }
    }

    foreach ($site in $script:Websites) {
        if (-not $found.ContainsKey($site)) { return $false }
    }
    return $true
}

function Get-ManagedOutsideCount {
    param([string]$Text)

    $inside = $false
    $count = 0
    foreach ($line in [regex]::Split($Text, "\r\n|\n|\r")) {
        $trimmed = $line.Trim()
        if ($trimmed -ceq $script:BeginMarker) { $inside = $true; continue }
        if ($trimmed -ceq $script:EndMarker) { $inside = $false; continue }
        if ($inside) { continue }
        foreach ($site in $script:Websites) {
            if ($trimmed -ceq ("$script:RedirectIp $site")) { $count++; break }
        }
    }
    return $count
}

function Get-UpdatedText {
    param(
        [string]$CurrentText,
        [string]$Newline,
        [bool]$WantBlock
    )

    $state = Get-ManagedState $CurrentText
    if (-not $state.WellFormed) {
        throw 'CodeLock hosts markers are incomplete or mismatched; refusing to rewrite the file.'
    }
    if ((Get-ManagedOutsideCount $CurrentText) -gt 0) {
        throw 'CodeLock managed entries exist outside the block; run recovery before blocking.'
    }

    $kept = New-Object System.Collections.Generic.List[string]
    $inside = $false
    foreach ($line in [regex]::Split($CurrentText, "\r\n|\n|\r")) {
        $trimmed = $line.Trim()
        if ($trimmed -ceq $script:BeginMarker) { $inside = $true; continue }
        if ($trimmed -ceq $script:EndMarker) { $inside = $false; continue }
        if (-not $inside) { [void]$kept.Add($line) }
    }

    $base = ($kept.ToArray() -join $Newline).TrimEnd([char[]]@("`r", "`n"))
    if ($base.Length -gt 0) { $base += $Newline }
    if (-not $WantBlock) { return $base }

    if ($base.Length -gt 0 -and -not $base.EndsWith($Newline + $Newline)) {
        $base += $Newline
    }

    $block = New-Object System.Collections.Generic.List[string]
    [void]$block.Add($script:BeginMarker)
    foreach ($site in $script:Websites) {
        [void]$block.Add("$script:RedirectIp $site")
    }
    [void]$block.Add($script:EndMarker)
    return $base + ($block.ToArray() -join $Newline) + $Newline
}

function Get-RecoveredText {
    param(
        [string]$CurrentText,
        [string]$Newline
    )

    $kept = New-Object System.Collections.Generic.List[string]
    $removed = 0
    foreach ($line in [regex]::Split($CurrentText, "\r\n|\n|\r")) {
        $trimmed = $line.Trim()
        if ($trimmed -ceq $script:BeginMarker -or $trimmed -ceq $script:EndMarker) {
            $removed++
            continue
        }
        $managed = $false
        foreach ($site in $script:Websites) {
            if ($trimmed -ceq ("$script:RedirectIp $site")) { $managed = $true; break }
        }
        if ($managed) {
            $removed++
            continue
        }
        [void]$kept.Add($line)
    }

    $base = ($kept.ToArray() -join $Newline).TrimEnd([char[]]@("`r", "`n"))
    if ($base.Length -gt 0) { $base += $Newline }
    return [pscustomobject]@{
        Text    = $base
        Removed = $removed
    }
}

function Convert-TextToBytes {
    param(
        [string]$Text,
        [string]$EncodingName
    )

    switch ($EncodingName) {
        'utf8-bom' { $encoding = New-Object System.Text.UTF8Encoding($true) }
        'utf16-le' { $encoding = [System.Text.Encoding]::Unicode }
        'utf16-be' { $encoding = [System.Text.Encoding]::BigEndianUnicode }
        'ansi' { $encoding = [System.Text.Encoding]::Default }
        default { $encoding = New-Object System.Text.UTF8Encoding($false) }
    }

    $preamble = $encoding.GetPreamble()
    $body = $encoding.GetBytes($Text)
    if ($preamble.Length -eq 0) { return ,$body }

    $buffer = New-Object byte[] ($preamble.Length + $body.Length)
    [Array]::Copy($preamble, 0, $buffer, 0, $preamble.Length)
    [Array]::Copy($body, 0, $buffer, $preamble.Length, $body.Length)
    return ,$buffer
}

function Test-BytesEqual {
    param([byte[]]$Left, [byte[]]$Right)
    if ($Left.Length -ne $Right.Length) { return $false }
    for ($i = 0; $i -lt $Left.Length; $i++) {
        if ($Left[$i] -ne $Right[$i]) { return $false }
    }
    return $true
}

function Remove-StaleTemps {
    param([string]$Directory)

    try {
        $cutoff = (Get-Date).AddHours(-1)
        $stale = Get-ChildItem -LiteralPath $Directory -Filter 'hosts.codelock-*.tmp' -File -ErrorAction SilentlyContinue
        foreach ($item in $stale) {
            if ($item.LastWriteTime -lt $cutoff) {
                try { Remove-Item -LiteralPath $item.FullName -Force -ErrorAction Stop } catch { }
            }
        }
    }
    catch { }
}

function Write-HostsDocument {
    param(
        [string]$Path,
        [byte[]]$Bytes
    )

    $directory = [IO.Path]::GetDirectoryName($Path)
    Remove-StaleTemps -Directory $directory

    $temp = [IO.Path]::Combine($directory, 'hosts.codelock-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $backup = [IO.Path]::Combine($directory, 'hosts.codelock-backup-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $stream = $null
    try {
        $stream = New-Object IO.FileStream(
            $temp,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
        $stream.Close()
        $stream = $null

        $written = [IO.File]::ReadAllBytes($temp)
        if (-not (Test-BytesEqual -Left $written -Right $Bytes)) {
            throw 'The temporary hosts file did not match the intended content.'
        }

        if ([IO.File]::Exists($Path)) {
            # Atomic replace only. If this fails the original file is untouched;
            # there is deliberately no copy-over-destination fallback. .NET
            # Framework rejects a null backup path, so a temporary backup is
            # passed and deleted below (stale copies are also cleaned up).
            [IO.File]::Replace($temp, $Path, $backup, $true)
        }
        else {
            [IO.File]::Move($temp, $Path)
        }
    }
    finally {
        if ($null -ne $stream) {
            try { $stream.Close() } catch { }
        }
        foreach ($leftover in @($temp, $backup)) {
            if ([IO.File]::Exists($leftover)) {
                try { [IO.File]::Delete($leftover) } catch { }
            }
        }
    }

    $final = [IO.File]::ReadAllBytes($Path)
    if (-not (Test-BytesEqual -Left $final -Right $Bytes)) {
        throw 'The hosts file did not match the intended content after replacement.'
    }
}

function Backup-Original {
    param(
        [string]$Path,
        $Document
    )

    if (-not $Document.Exists) { return }
    if ($Document.Text.Contains($script:BeginMarker)) { return }

    $backup = $Path + '.codelock.bak'
    if ([IO.File]::Exists($backup)) { return }
    [IO.File]::WriteAllBytes($backup, $Document.Bytes)
}

function Save-DamagedCopy {
    param(
        [string]$Path,
        $Document
    )

    if (-not $Document.Exists) { return '' }
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $target = $Path + '.codelock-damaged-' + $stamp + '.bak'
    try {
        [IO.File]::WriteAllBytes($target, $Document.Bytes)
        return $target
    }
    catch {
        return ''
    }
}

function Invoke-DnsFlush {
    $result = [ordered]@{
        attempted = $true
        ok        = $false
        message   = ''
    }
    if ($TestMode) {
        $result.attempted = $false
        $result.message = 'DNS cache flush skipped in test mode.'
        return $result
    }
    try {
        $ipconfig = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'ipconfig.exe'
        if (-not [IO.File]::Exists($ipconfig)) {
            $result.message = 'ipconfig.exe was not found; DNS cache was not flushed.'
            return $result
        }
        $output = & $ipconfig /flushdns 2>&1 | Out-String
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            $result.ok = $true
            $result.message = 'DNS resolver cache flushed.'
        }
        else {
            $result.message = "ipconfig /flushdns exited with code $code."
        }
    }
    catch {
        $result.message = $_.Exception.Message
    }
    return $result
}

$elevated = Test-Elevated
$forcedError = ''

if ($TestMode) {
    if ($elevated) {
        Write-Payload @{
            ok = $false
            blocked = $false
            message = 'Test mode is refused inside an elevated process.'
        }
        exit 2
    }

    $testPath = [string]$env:CODELOCK_HELPER_TEST_HOSTS_PATH
    if ([string]::IsNullOrWhiteSpace($testPath)) {
        Write-Payload @{
            ok = $false
            blocked = $false
            message = 'Test mode requires CODELOCK_HELPER_TEST_HOSTS_PATH.'
        }
        exit 2
    }

    $resolvedTest = [IO.Path]::GetFullPath($testPath)
    $windowsFolder = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $realHosts = [IO.Path]::GetFullPath((Join-Path $windowsFolder 'System32\drivers\etc\hosts'))
    if ($resolvedTest.Equals($realHosts, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Payload @{
            ok = $false
            blocked = $false
            message = 'Test mode refuses the real system hosts file.'
        }
        exit 2
    }

    $hostsPath = $resolvedTest
    $forcedError = [string]$env:CODELOCK_HELPER_TEST_FORCE_ERROR
}
else {
    $windowsFolder = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $hostsPath = Join-Path $windowsFolder 'System32\drivers\etc\hosts'
    if (-not $elevated -and $Operation -ne 'status') {
        Write-Payload @{
            ok = $false
            blocked = $false
            message = 'Administrator rights are required to change the hosts file.'
        }
        exit 3
    }
}

try {
    $document = Read-HostsDocument $hostsPath
    $state = Get-ManagedState $document.Text

    if ($Operation -eq 'status') {
        Write-Payload @{
            ok = $true
            blocked = [bool]$state.Blocked
            wellFormed = [bool]$state.WellFormed
            complete = [bool](Test-CompleteBlock $document.Text)
            managedOutside = [int](Get-ManagedOutsideCount $document.Text)
            message = ''
        }
        exit 0
    }

    if ($Operation -eq 'recover' -or $Operation -eq 'repair') {
        $wantBlock = ($Operation -eq 'repair')
        if ($forcedError -eq 'write' -or $forcedError -eq $Operation) {
            throw "Simulated $Operation failure before writing."
        }
        $recovered = Get-RecoveredText -CurrentText $document.Text -Newline $document.Newline
        $forensic = ''
        if ($recovered.Removed -gt 0) {
            $forensic = Save-DamagedCopy -Path $hostsPath -Document $document
        }
        $finalText = $recovered.Text
        if ($wantBlock) {
            $finalText = Get-UpdatedText -CurrentText $recovered.Text -Newline $document.Newline -WantBlock $true
        }
        if ($document.Exists -and $finalText -cne $document.Text) {
            $bytes = Convert-TextToBytes -Text $finalText -EncodingName $document.EncodingName
            Write-HostsDocument -Path $hostsPath -Bytes $bytes
        }
        if ($forcedError -eq 'verify') {
            throw 'Simulated post-write verification failure.'
        }
        $verifiedDocument = Read-HostsDocument $hostsPath
        $verifiedState = Get-ManagedState $verifiedDocument.Text
        $outside = Get-ManagedOutsideCount $verifiedDocument.Text
        $stillPresent = $verifiedDocument.Text.Contains($script:BeginMarker) -or
            $verifiedDocument.Text.Contains($script:EndMarker) -or
            $outside -gt 0
        if (-not $wantBlock) {
            if ($stillPresent -or -not $verifiedState.WellFormed -or $verifiedState.Blocked) {
                Write-Payload @{
                    ok = $false
                    blocked = [bool]$verifiedState.Blocked
                    wellFormed = [bool]$verifiedState.WellFormed
                    managedOutside = [int]$outside
                    forensicBackup = $forensic
                    message = 'CodeLock entries are still present after recovery.'
                }
                exit 4
            }
            $dns = Invoke-DnsFlush
            Write-Payload @{
                ok = $true
                blocked = $false
                wellFormed = $true
                complete = $false
                managedOutside = 0
                removedLines = [int]$recovered.Removed
                forensicBackup = $forensic
                dns = $dns
                message = 'CodeLock entries were removed and the hosts file was verified.'
            }
            exit 0
        }
        if (-not (Test-CompleteBlock $verifiedDocument.Text) -or $outside -gt 0) {
            Write-Payload @{
                ok = $false
                blocked = [bool]$verifiedState.Blocked
                wellFormed = [bool]$verifiedState.WellFormed
                managedOutside = [int]$outside
                forensicBackup = $forensic
                message = 'The repaired block could not be verified.'
            }
            exit 4
        }
        $dns = Invoke-DnsFlush
        Write-Payload @{
            ok = $true
            blocked = $true
            wellFormed = $true
            complete = $true
            managedOutside = 0
            removedLines = [int]$recovered.Removed
            forensicBackup = $forensic
            dns = $dns
            message = 'Damaged CodeLock entries were removed and a fresh block was verified.'
        }
        exit 0
    }

    if (-not $state.WellFormed) {
        Write-Payload @{
            ok = $false
            blocked = [bool]$state.Blocked
            wellFormed = $false
            message = 'CodeLock hosts markers are incomplete or mismatched.'
        }
        exit 3
    }

    $outsideCount = Get-ManagedOutsideCount $document.Text
    if ($outsideCount -gt 0) {
        Write-Payload @{
            ok = $false
            blocked = [bool]$state.Blocked
            wellFormed = $true
            managedOutside = [int]$outsideCount
            message = 'CodeLock managed entries exist outside the block; recovery is required.'
        }
        exit 3
    }

    if ($Operation -eq 'unblock' -and -not $state.Blocked) {
        $dns = Invoke-DnsFlush
        Write-Payload @{
            ok = $true
            blocked = $false
            wellFormed = $true
            dns = $dns
            message = 'No CodeLock block is present.'
        }
        exit 0
    }

    $wantBlock = ($Operation -eq 'block')
    $updated = Get-UpdatedText -CurrentText $document.Text -Newline $document.Newline -WantBlock $wantBlock

    if ($forcedError -eq 'write' -or $forcedError -eq $Operation) {
        throw "Simulated $Operation failure before writing."
    }

    if ($updated -cne $document.Text) {
        if ($wantBlock) {
            Backup-Original -Path $hostsPath -Document $document
        }
        $bytes = Convert-TextToBytes -Text $updated -EncodingName $document.EncodingName
        Write-HostsDocument -Path $hostsPath -Bytes $bytes
    }

    if ($forcedError -eq 'verify') {
        throw 'Simulated post-write verification failure.'
    }

    $verifiedDocument = Read-HostsDocument $hostsPath
    $verifiedState = Get-ManagedState $verifiedDocument.Text
    $dns = Invoke-DnsFlush

    if ($wantBlock) {
        if (-not (Test-CompleteBlock $verifiedDocument.Text)) {
            Write-Payload @{
                ok = $false
                blocked = [bool]$verifiedState.Blocked
                wellFormed = [bool]$verifiedState.WellFormed
                dns = $dns
                message = 'The block was written but could not be verified.'
            }
            exit 4
        }
        Write-Payload @{
            ok = $true
            blocked = $true
            wellFormed = $true
            complete = $true
            dns = $dns
            message = 'Website blocking is installed and verified.'
        }
        exit 0
    }

    if (-not $verifiedState.WellFormed -or $verifiedState.Blocked) {
        Write-Payload @{
            ok = $false
            blocked = [bool]$verifiedState.Blocked
            wellFormed = [bool]$verifiedState.WellFormed
            dns = $dns
            message = 'The CodeLock block is still present after removal.'
        }
        exit 4
    }

    Write-Payload @{
        ok = $true
        blocked = $false
        wellFormed = $true
        dns = $dns
        message = 'Website blocking is removed and verified.'
    }
    exit 0
}
catch {
    Write-Payload @{
        ok = $false
        blocked = $false
        message = $_.Exception.Message
    }
    exit 3
}
