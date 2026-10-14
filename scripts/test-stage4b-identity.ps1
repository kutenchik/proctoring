param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $repo 'scripts/stage4b-process-identity.ps1')
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$checks=New-Object 'Collections.Generic.List[string]'
function Check([string]$Name,[scriptblock]$Test) { & $Test; $checks.Add($Name) }
function Reject([scriptblock]$Test) { $failed=$false;try { & $Test } catch {$failed=$true};if(-not $failed){throw 'Expected closed rejection'} }
function Clone($Record) { return ($Record|ConvertTo-Json|ConvertFrom-Json) }
$fixture=$null;$unrelated=$null
try {
 $fixture=Start-Process powershell.exe -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 120') -WindowStyle Hidden -PassThru
 $unrelated=Start-Process powershell.exe -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 120') -WindowStyle Hidden -PassThru
 $saved=Get-Stage4BIdentity $fixture.Id
 $record=Join-Path $OutputDirectory 'owned.json';$saved|ConvertTo-Json|Set-Content $record
 Check 'same live process after JSON roundtrip' {if(-not(Test-Stage4BIdentity (Read-Stage4BIdentity $record))){throw 'Not found'}}
 Check 'fractional precision 100ns' {
  foreach($stamp in @('2026-10-14T12:28:15.6224190Z','2026-10-14T12:28:15.1234567Z','2026-10-14T12:28:15.1Z')) {
   $decoded=('{"created":"'+$stamp+'"}'|ConvertFrom-Json).created
   if((ConvertTo-Stage4BUtcTicks $stamp) -ne (ConvertTo-Stage4BUtcTicks $decoded)){throw 'Precision loss'}
  }
 }
 Check 'equivalent UTC offsets and culture independence' {
  $before=[Threading.Thread]::CurrentThread.CurrentCulture
  try {
   foreach($culture in @('en-US','ru-RU','kk-KZ')) {
    [Threading.Thread]::CurrentThread.CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($culture)
    if((ConvertTo-Stage4BUtcTicks '2026-10-14T17:28:15.1234567+05:00') -ne (ConvertTo-Stage4BUtcTicks '2026-10-14T12:28:15.1234567Z')){throw 'Instant differs'}
   }
  } finally {[Threading.Thread]::CurrentThread.CurrentCulture=$before}
 }
 Check 'one tick difference rejected' {$bad=Clone $saved;$bad.created=([DateTimeOffset]::Parse($saved.created,[Globalization.CultureInfo]::InvariantCulture)).AddTicks(1);Reject {Assert-Stage4BIdentityMatch $saved $bad}}
 Check 'simulated PID reuse rejected without termination' {$bad=Get-Stage4BIdentity $unrelated.Id;$bad.pid=$saved.pid;Reject {Assert-Stage4BIdentityMatch $saved $bad}}
 Check 'executable owner command and PID exact' {foreach($field in @('exe','owner','command','pid')) {$bad=Clone $saved;if($field -eq 'pid'){$bad.pid++}else{$bad.$field+='changed'};Reject {Assert-Stage4BIdentityMatch $saved $bad}}}
 Check 'malformed missing ambiguous timestamps rejected' {
  foreach($stamp in @($null,'','10/14/2026 12:28:15','2026-10-14T12:28:15','2026-10-14T12:28:15-00:00','2026-10-14T12:28:15.12345678Z',[DateTime]::SpecifyKind([DateTime]::Now,[DateTimeKind]::Unspecified))) {Reject {ConvertTo-Stage4BUtcTicks $stamp}}
  foreach($field in @('pid','exe','command','owner','created')) {$bad=Clone $saved;$bad.$field=$null;Reject {Test-Stage4BIdentity $bad}}
 }
 Check 'duplicate JSON property and duplicate PID rejected' {
  $text=$saved|ConvertTo-Json
  ($text -replace '^\{','{"pid":123,')|Set-Content (Join-Path $OutputDirectory 'bad.json')
  Reject {Read-Stage4BIdentity (Join-Path $OutputDirectory 'bad.json')}
  @($saved,$saved)|ConvertTo-Json|Set-Content (Join-Path $OutputDirectory 'bad.json')
  Reject {Read-Stage4BIdentity (Join-Path $OutputDirectory 'bad.json')}
 }
 Check 'mismatched stop leaves both processes running' {
  $bad=Clone $saved;$bad.command+='changed';Reject {Stop-Stage4BOwnedProcess $bad}
  if($fixture.HasExited -or $unrelated.HasExited){throw 'Unexpected process termination'}
 }
 Check 'same fixture validated in other shell' {
  $otherShell=if($PSVersionTable.PSVersion.Major -eq 5){(Get-Command pwsh.exe).Source}else{(Get-Command powershell.exe).Source}
  $script=Join-Path $OutputDirectory 'cross.ps1'
  ". '$repo/scripts/stage4b-process-identity.ps1'; if(-not(Test-Stage4BIdentity (Read-Stage4BIdentity '$record'))){throw 'Not matched'}"|Set-Content $script
  & $otherShell -NoProfile -File $script
  if($LASTEXITCODE){throw 'Other shell failed'}
 }
 Check 'Stop terminates exact owned fixture only' {Stop-Stage4BOwnedProcess (Read-Stage4BIdentity $record);$fixture.Refresh();$unrelated.Refresh();if(-not $fixture.HasExited -or $unrelated.HasExited){throw 'Wrong process terminated'}}
 Check 'preserved record read-only reproduction' {
  $history=Join-Path $repo 'build/stage4b/snapshots-01/tunnel-owner.json'
  $hash=(Get-FileHash $history).Hash
  $old=Read-Stage4BIdentity $history
  $instant=ConvertTo-Stage4BUtcTicks $old.created
  if($instant -ne (ConvertTo-Stage4BUtcTicks '2026-10-14T12:28:15.6224190Z')){throw 'Historical instant differs'}
  if((Get-FileHash $history).Hash -ne $hash){throw 'History changed'}
  @{shell=$PSVersionTable.PSVersion.ToString();type=$old.created.GetType().FullName;old_string_comparison=('2026-10-14T12:28:15.6224190Z' -ceq $old.created);utc_ticks=$instant}|ConvertTo-Json|Set-Content (Join-Path $OutputDirectory 'historical-reproduction.json')
 }
 @{shell=$PSVersionTable.PSVersion.ToString();passed=$checks.Count;checks=@($checks)}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $OutputDirectory 'results.json')
 Write-Output ($PSVersionTable.PSVersion.ToString()+': '+$checks.Count+' checks passed')
} finally {
 foreach($process in @($fixture,$unrelated)) {if($process){try{if(-not $process.HasExited){$process.Kill();$process.WaitForExit()}}finally{$process.Dispose()}}}
}
