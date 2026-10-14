param(
 [Parameter(Mandatory=$true)][string]$RunDirectory,
 [Parameter(Mandatory=$true)][string]$Cloudflared,
 [Parameter(Mandatory=$true)][string]$CloudflaredSha256,
 [switch]$OperatorApprovedPublicExposure
)
$ErrorActionPreference='Stop'
if(-not $OperatorApprovedPublicExposure){throw 'Separate explicit operator approval required'}
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$run=[IO.Path]::GetFullPath($RunDirectory)
if([IO.Path]::GetDirectoryName($run) -ne (Join-Path $repo 'build/stage4b')){throw 'Direct isolated run child required'}
if(-not (Test-Path -LiteralPath (Join-Path $run 'synthetic.json'))){throw 'Prepare disposable data first'}
foreach($name in @('deadline.json','tunnel-owner.json','closed.json')){if(Test-Path -LiteralPath (Join-Path $run $name)){throw 'One exposure only; do not reuse this run'}}
$manifest=Get-Content -LiteralPath (Join-Path $run 'prepared-hashes.json') -Raw|ConvertFrom-Json
foreach($entry in $manifest){
 $file=[IO.Path]::GetFullPath((Join-Path $repo $entry.path))
 if(-not $file.StartsWith($repo+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Invalid build manifest path'}
 if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256){throw 'Prepared source/build identity changed; reverify before exposure'}
}
$python=Join-Path $repo '.venv-server/Scripts/python.exe'
$guardScript=Join-Path $repo 'scripts/stage4b-exposure-deadline.py'
$deadline=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+900
$guard=Start-Process -FilePath $python -ArgumentList @('"'+$guardScript+'"','--operator-approved','--run','"'+$run+'"','--deadline',[string]$deadline) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'guard.stdout.log') -RedirectStandardError (Join-Path $run 'guard.stderr.log')
$readyLimit=[DateTime]::UtcNow.AddSeconds(10)
while(-not(Test-Path (Join-Path $run 'deadline.json')) -and [DateTime]::UtcNow -lt $readyLimit -and -not $guard.HasExited){Start-Sleep -Milliseconds 100;$guard.Refresh()}
if($guard.HasExited -or -not(Test-Path (Join-Path $run 'deadline.json'))){throw 'Independent deadline guard did not start; tunnel forbidden'}
. (Join-Path $repo 'scripts/stage4b-process-identity.ps1')
$identity=Get-Stage4BIdentity $guard.Id
if(-not $identity -or $identity.exe -cne $python){throw 'Cannot verify guard ownership'}
$identity.deadline=$deadline
$identity|ConvertTo-Json|Set-Content (Join-Path $run 'guard-owner.json')
# Independent guard exists BEFORE the only operation that starts public exposure.
& (Join-Path $repo 'scripts/stage4b-demo.ps1') -Action Tunnel -RunDirectory $run -Cloudflared $Cloudflared -CloudflaredSha256 $CloudflaredSha256 -OperatorApprovedPublicExposure
if($LASTEXITCODE){throw 'Tunnel launch failed; preserve this run, no retry'}
Write-Output 'Maximum 15 minutes began before tunnel launch. Pin the exact generated origin and Start the isolated gateway separately. Stop immediately on critical failure.'
