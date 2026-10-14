# Shared Stage 4B identity validation, compatible with Windows PowerShell 5.1 / PS 7.
# Timestamp identity is exact UTC .NET ticks (100 ns), never formatted culture text.
function ConvertTo-Stage4BUtcTicks($Value) {
    if ($Value -is [DateTimeOffset]) { return $Value.UtcDateTime.Ticks }
    if ($Value -is [DateTime]) {
        if ($Value.Kind -eq [DateTimeKind]::Unspecified) { throw 'Ambiguous process creation timestamp' }
        if ($Value.Kind -eq [DateTimeKind]::Local -and ([TimeZoneInfo]::Local.IsAmbiguousTime($Value) -or [TimeZoneInfo]::Local.IsInvalidTime($Value))) { throw 'Ambiguous local process creation timestamp' }
        return $Value.ToUniversalTime().Ticks
    }
    if ($Value -isnot [string] -or $Value -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})$' -or $Value.EndsWith('-00:00')) {
        throw 'Invalid or ambiguous process creation timestamp'
    }
    $stamp=[DateTimeOffset]::MinValue
    $formats=[string[]]@("yyyy-MM-dd'T'HH:mm:sszzz", "yyyy-MM-dd'T'HH:mm:ss.FFFFFFFzzz")
    $text=$Value
    if($text.EndsWith('Z')) { $text=$text.Substring(0,$text.Length-1)+'+00:00' }
    if(-not [DateTimeOffset]::TryParseExact($text,$formats,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$stamp)) {
        throw 'Invalid process creation timestamp'
    }
    return $stamp.UtcDateTime.Ticks
}
function Assert-Stage4BIdentity($Record) {
    if($null -eq $Record) { throw 'Missing process identity' }
    if(($Record.pid -isnot [int] -and $Record.pid -isnot [long]) -or $Record.pid -le 0 -or $Record.pid -gt [int]::MaxValue) { throw 'Invalid process PID' }
    foreach($field in @('exe','command','owner')) {
        if($Record.$field -isnot [string] -or [string]::IsNullOrWhiteSpace($Record.$field)) { throw 'Missing process identity field' }
    }
    [void](ConvertTo-Stage4BUtcTicks $Record.created)
}
function Read-Stage4BIdentity([string]$Path) {
    $raw=Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
    $records=@($raw | ConvertFrom-Json -ErrorAction Stop)
    if($records.Count -lt 1 -or $records.Count -gt 32) { throw 'Invalid ownership record count' }
    # Ownership documents contain scalar fields only. Reject unknown/duplicate JSON
    # keys instead of silently accepting ConvertFrom-Json's last-value behavior.
    $counts=@{}
    foreach($match in [regex]::Matches($raw,'("(?:[^"\\]|\\.)*")\s*:')) {
        $name=(('{"key":'+$match.Groups[1].Value+'}') | ConvertFrom-Json -ErrorAction Stop).key
        if($name -cnotin @('pid','created','exe','command','owner','deadline')) { throw 'Unknown ownership field' }
        $counts[$name]++
    }
    foreach($field in @('pid','created','exe','command','owner')) {
        if($counts[$field] -ne $records.Count) { throw 'Duplicate or missing ownership field' }
    }
    if($counts['deadline'] -gt $records.Count) { throw 'Duplicate ownership field' }
    $seen=@{}
    foreach($record in $records) {
        Assert-Stage4BIdentity $record
        if($seen.ContainsKey([string]$record.pid)) { throw 'Duplicate process identity' }
        $seen[[string]$record.pid]=$true
    }
    return $records
}
function Get-Stage4BIdentity([int]$ProcessId) {
    $p=Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    if(-not $p) { return $null }
    $owner=Invoke-CimMethod -InputObject $p -MethodName GetOwner -ErrorAction Stop
    if($owner.ReturnValue -ne 0) { throw 'Cannot verify process owner' }
    $ticks=ConvertTo-Stage4BUtcTicks $p.CreationDate
    $utc=New-Object DateTime -ArgumentList @([long]$ticks,[DateTimeKind]::Utc)
    $record=@{pid=$ProcessId;created=$utc.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",[Globalization.CultureInfo]::InvariantCulture);exe=$p.ExecutablePath;command=$p.CommandLine;owner=($owner.Domain+'\'+$owner.User)}
    Assert-Stage4BIdentity $record
    return $record
}
function Assert-Stage4BIdentityMatch($Saved,$Actual) {
    Assert-Stage4BIdentity $Saved
    Assert-Stage4BIdentity $Actual
    if($Saved.pid -ne $Actual.pid -or (ConvertTo-Stage4BUtcTicks $Saved.created) -ne (ConvertTo-Stage4BUtcTicks $Actual.created)) { throw 'Process identity changed; stopping without termination' }
    foreach($field in @('exe','command','owner')) {
        if(-not [string]::Equals($Saved.$field,$Actual.$field,[StringComparison]::Ordinal)) { throw 'Process identity changed; stopping without termination' }
    }
}
function Test-Stage4BIdentity($Saved) {
    Assert-Stage4BIdentity $Saved
    $actual=Get-Stage4BIdentity $Saved.pid
    if(-not $actual) { return $false }
    Assert-Stage4BIdentityMatch $Saved $actual
    return $true
}
function Stop-Stage4BOwnedProcess($Saved) {
    Assert-Stage4BIdentity $Saved
    if(-not (Test-Stage4BIdentity $Saved)) { return }
    $process=[Diagnostics.Process]::GetProcessById($Saved.pid)
    try {
        # Hold the process handle before final CIM validation; termination targets
        # this process object, not a later occupant of the same numeric PID.
        $null=$process.Handle
        if(-not (Test-Stage4BIdentity $Saved)) { return }
        $process.Kill()
        if(-not $process.WaitForExit(10000)) { throw 'Owned process did not exit' }
    } finally { $process.Dispose() }
}
