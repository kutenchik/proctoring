param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'stage4b-process-identity.ps1')
New-Item -ItemType Directory -Force -Path $OutputDirectory|Out-Null
$hostExe=Join-Path $PSHOME $(if($PSVersionTable.PSVersion.Major -eq 5){'powershell.exe'}else{'pwsh.exe'})
$demo=Join-Path $PSScriptRoot 'stage4b-demo.ps1'
$run=Join-Path $repo ('build/stage4b/identity-fixture-'+[guid]::NewGuid().ToString('N'))
$children=New-Object 'Collections.Generic.List[object]'
$checks=New-Object 'Collections.Generic.List[string]'
function Fixture {
 $p=Start-Process powershell.exe -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 120') -WindowStyle Hidden -PassThru
 $children.Add($p);return $p
}
function Save($Name,$Record) {$Record|ConvertTo-Json -Depth 5|Set-Content -Encoding utf8 (Join-Path $run $Name)}
function Invoke-Action($Action,$Expected) {
 $wrapper=Join-Path $OutputDirectory ($Action+'.ps1')
 # Production Start/Restart validation runs, but process creation is blocked at the boundary.
 $stub=if($Action -in @('Start','Restart')){"function Start-Process { throw 'TEST_LAUNCH_BOUNDARY' }"}else{''}
 @"
`$ErrorActionPreference='Stop'
$stub
try { & '$demo' -Action $Action -RunDirectory '$run' -PublicOrigin 'https://ownership-fixture.trycloudflare.com' -OperatorApprovedPublicExposure } catch { Write-Output `$_.Exception.Message; exit 1 }
"@|Set-Content $wrapper
 $out=(& $hostExe -NoProfile -File $wrapper 2>&1|Out-String)
 $code=$LASTEXITCODE
 $out|Set-Content (Join-Path $OutputDirectory ($Action+'.log'))
 if($Expected -eq 'ok'){if($code){throw ('Action failed: '+$Action+' '+$out)}}elseif(-not $out.Contains($Expected)){throw ('Wrong failure: '+$Action+' '+$out)}
}
try {
 & $hostExe -NoProfile -File $demo -Action Prepare -RunDirectory $run -Port 58036
 if($LASTEXITCODE){throw 'Prepare failed'};$checks.Add('Prepare offline')
 $tunnel=Fixture;$unrelated=Fixture;$server=Fixture
 $owned=Get-Stage4BIdentity $tunnel.Id
 Save 'tunnel-owner.json' $owned
 'https://ownership-fixture.trycloudflare.com'|Set-Content (Join-Path $run 'tunnel.stdout.log')
 ''|Set-Content (Join-Path $run 'tunnel.stderr.log')
 Invoke-Action 'Pin' 'ok';$checks.Add('Pin accepts exact fixture identity')
 Invoke-Action 'Start' 'TEST_LAUNCH_BOUNDARY';$checks.Add('Start validates then reaches blocked launch boundary')
 $bad=@{};foreach($k in $owned.Keys){$bad[$k]=$owned[$k]};$bad.command+='wrong';Save 'tunnel-owner.json' $bad
 Invoke-Action 'Start' 'Process identity changed';$checks.Add('Start rejects mismatched command before launch')
 Invoke-Action 'Pin' 'Process identity changed';$checks.Add('Pin rejects mismatched identity')
 Invoke-Action 'Stop' 'Process identity changed';$tunnel.Refresh();if($tunnel.HasExited){throw 'Mismatched stop killed fixture'};$checks.Add('Stop fails closed')
 Save 'tunnel-owner.json' $owned
 Save 'server-owner.json' @(Get-Stage4BIdentity $server.Id)
 Invoke-Action 'Restart' 'TEST_LAUNCH_BOUNDARY';$server.Refresh();$tunnel.Refresh();if(-not $server.HasExited -or $tunnel.HasExited){throw 'Restart killed wrong process'};$checks.Add('Restart stops exact server fixture then reaches blocked boundary')
 Invoke-Action 'Stop' 'ok';$tunnel.Refresh();$unrelated.Refresh();if(-not $tunnel.HasExited -or $unrelated.HasExited){throw 'Wrong termination'};$checks.Add('Stop terminates only recorded tunnel')
 # Guard executes the same production Stop entry point against a second harmless fixture.
 $guardTarget=Fixture;Save 'tunnel-owner.json' (Get-Stage4BIdentity $guardTarget.Id)
 $deadline=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+5
 & (Join-Path $repo '.venv-server/Scripts/python.exe') (Join-Path $repo 'scripts/stage4b-exposure-deadline.py') --operator-approved --run $run --deadline $deadline
 if($LASTEXITCODE){throw 'Guard cleanup failed'}
 $guardTarget.Refresh();$unrelated.Refresh();if(-not $guardTarget.HasExited -or $unrelated.HasExited){throw 'Guard killed wrong process'};$checks.Add('Independent deadline guard uses shared Stop validation')
 @{shell=$PSVersionTable.PSVersion.ToString();passed=$checks.Count;checks=@($checks);fixture_run=$run;public_exposure=$false}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $OutputDirectory 'results.json')
 Write-Output ($PSVersionTable.PSVersion.ToString()+': '+$checks.Count+' lifecycle checks passed')
} finally {
 foreach($p in $children){try{if(-not $p.HasExited){$p.Kill();$p.WaitForExit()}}finally{$p.Dispose()}}
}
