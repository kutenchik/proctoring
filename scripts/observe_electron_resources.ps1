# Read-only numerical process snapshot. Caller filters to its exact owned tree.
$ErrorActionPreference = 'Stop'
$rows = @(Get-CimInstance Win32_Process | ForEach-Object {
    if ($null -ne $_.CreationDate) {
        [pscustomobject]@{
            pid = [int]$_.ProcessId
            parent = [int]$_.ParentProcessId
            created = ([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds()
            working_set_bytes = [double]$_.WorkingSetSize
            private_bytes = [double]$_.PrivatePageCount
            cpu_100ns = [double]$_.KernelModeTime + [double]$_.UserModeTime
        }
    }
})
ConvertTo-Json -InputObject $rows -Compress
