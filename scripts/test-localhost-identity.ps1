param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'stage4b-process-identity.ps1')
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$path=Join-Path $OutputDirectory 'synthetic-owners.json'
$one=@{pid=123;created='2026-10-14T12:28:15.1234567Z';exe='synthetic.exe';command='synthetic one';owner='synthetic'}
$two=@{pid=456;created='2026-10-14T12:28:15.1234567Z';exe='synthetic.exe';command='synthetic two';owner='synthetic'}
@($one,$two) | ConvertTo-Json | Set-Content -LiteralPath $path
$decoded=@(Read-Stage4BIdentity $path)
if($decoded.Count -ne 2) { throw 'Two ownership records required' }
Assert-Stage4BIdentityMatch $one $decoded[0]
Assert-Stage4BIdentityMatch $two $decoded[1]
foreach($field in @('pid','created','exe','command','owner')) {
    $bad=$two.Clone()
    if($field -eq 'pid'){$bad[$field]=789}
    elseif($field -eq 'created'){$bad[$field]='2026-10-14T12:28:15.1234568Z'}
    else {$bad[$field]+='changed'}
    $rejected=$false
    try { Assert-Stage4BIdentityMatch $two $bad } catch {$rejected=$true}
    if(-not $rejected) {throw "Mismatch accepted: $field"}
}
@($one,$one) | ConvertTo-Json | Set-Content -LiteralPath $path
$rejected=$false
try { Read-Stage4BIdentity $path } catch {$rejected=$true}
if(-not $rejected) {throw 'Duplicate PID accepted'}
$one | ConvertTo-Json | Set-Content -LiteralPath $path
if(@(Read-Stage4BIdentity $path).Count -ne 1) {throw 'Single record rejected'}
Write-Output "PASS: multi/single record parsing, five exact identity fields, duplicate PID; shell $($PSVersionTable.PSVersion). No processes started or stopped."
