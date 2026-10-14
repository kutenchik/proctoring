param(
    [Parameter(Mandatory=$true)][ValidateSet('Prepare','Tunnel','Pin','Start','Restart','Invite','Reset','Stop')][string]$Action,
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [string]$PublicOrigin,
    [string]$Cloudflared,
    [string]$CloudflaredSha256,
    [string]$Email,
    [ValidateRange(1024,65535)][int]$Port=8034,
    [switch]$OperatorApprovedPublicExposure
)
$ErrorActionPreference='Stop'
function File-Sha256([string]$Path) {
    $stream=[IO.File]::OpenRead($Path);$sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
    finally {$stream.Dispose();$sha.Dispose()}
}
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$run=[IO.Path]::GetFullPath($RunDirectory)
$allowed=[IO.Path]::GetFullPath((Join-Path $repo 'build\stage4b'))+[IO.Path]::DirectorySeparatorChar
if (-not $run.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)) {throw 'Run directory must be a new child of build/stage4b'}
$python=Join-Path $repo '.venv-server\Scripts\python.exe'
function Write-Json($Path,$Value) { [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 12),(New-Object Text.UTF8Encoding $false)) }
. (Join-Path $PSScriptRoot 'stage4b-process-identity.ps1')
function Assert-Free {
    if(Get-NetTCPConnection -State Listen -LocalPort $config.port -ErrorAction SilentlyContinue) {throw 'Port occupied; inspect owner separately. No process will be replaced.'}
}
function Set-Environment {
    $env:PYTHONPATH=Join-Path $repo 'src'
    $env:PROCTOR_SERVER_DATABASE=Join-Path $run 'teacher.sqlite3'
    $env:PROCTOR_EVIDENCE_ROOT=Join-Path $run 'evidence'
    $env:PROCTOR_SERVER_URL=$config.origin
    $env:PROCTOR_TEACHER_ORIGIN=$config.origin
    $env:PROCTOR_ALLOW_LOOPBACK_HTTP='0'
    $env:PROCTOR_DEMO_FRONTEND=Join-Path $repo 'teacher-web\dist'
}
if($Action -eq 'Prepare') {
    if(Test-Path -LiteralPath $run) {throw 'Refusing to reuse an existing run directory'}
    New-Item -ItemType Directory -Path $run | Out-Null
    Write-Json (Join-Path $run 'config.json') @{version=1;port=$Port;origin=$null;repository=$repo}
    Write-Output 'Prepared isolated empty run. No listener, tunnel, account or capture started.'
    exit
}
$config=Get-Content -LiteralPath (Join-Path $run 'config.json') -Raw | ConvertFrom-Json
if($config.repository -ne $repo) {throw 'Repository identity mismatch'}
if($Action -eq 'Tunnel') {
    if(-not $OperatorApprovedPublicExposure) {throw 'Explicit operator approval required before creating any public tunnel'}
    Assert-Free
    if(Test-Path (Join-Path $run 'tunnel-owner.json')) {throw 'One tunnel per run directory; preserve old run and use a new prepared directory after shutdown'}
    if(-not $CloudflaredSha256 -or $CloudflaredSha256 -notmatch '^[a-fA-F0-9]{64}$') {throw 'Official release SHA256 required'}
    $binary=(Resolve-Path -LiteralPath $Cloudflared).Path
    if((File-Sha256 $binary) -ne $CloudflaredSha256) {throw 'cloudflared SHA256 mismatch'}
    foreach($file in @('config.yml','config.yaml')) {
        if(Test-Path (Join-Path $env:USERPROFILE ('.cloudflared\'+$file))) {throw 'Existing cloudflared configuration found; do not override or delete it'}
    }
    $p=Start-Process -FilePath $binary -ArgumentList @('tunnel','--no-autoupdate','--url',('http://127.0.0.1:'+$config.port),'--metrics','127.0.0.1:0','--loglevel','info') -WorkingDirectory $run -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'tunnel.stdout.log') -RedirectStandardError (Join-Path $run 'tunnel.stderr.log')
    $identity=Get-Stage4BIdentity $p.Id
    if(-not $identity) {throw 'Tunnel exited; inspect local logs'}
    Write-Json (Join-Path $run 'tunnel-owner.json') $identity
    Write-Output 'Tunnel launched toward closed loopback port. Read its assigned HTTPS URL in the local logs, then Pin it explicitly. No application is listening yet.'
    exit
}
if($Action -eq 'Pin') {
    Assert-Free
    if($PublicOrigin -cnotmatch '^https://[a-z0-9]+(-[a-z0-9]+)*\.trycloudflare\.com$') {throw 'Exact generated HTTPS origin required; no wildcards, paths or ports'}
    $owner=Read-Stage4BIdentity (Join-Path $run 'tunnel-owner.json')
    if(-not (Test-Stage4BIdentity $owner)) {throw 'Recorded tunnel no longer running'}
    $logs=(Get-Content (Join-Path $run 'tunnel.stdout.log') -Raw -ErrorAction SilentlyContinue)+(Get-Content (Join-Path $run 'tunnel.stderr.log') -Raw -ErrorAction SilentlyContinue)
    $urls=@([regex]::Matches($logs,'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com')|ForEach-Object {$_.Value}|Select-Object -Unique)
    if($urls.Count -ne 1 -or $urls[0] -cne $PublicOrigin) {throw 'Origin does not uniquely match the recorded tunnel output'}
    $config.origin=$PublicOrigin;Write-Json (Join-Path $run 'config.json') $config
    Write-Output 'Exact origin pinned. Starting the application is a separate explicit action.'
    exit
}
if($Action -eq 'Restart') {
    if(-not $OperatorApprovedPublicExposure) {throw 'Explicit approval required for an owned server restart'}
    $tunnel=Read-Stage4BIdentity (Join-Path $run 'tunnel-owner.json')
    if(-not (Test-Stage4BIdentity $tunnel)) {throw 'Recorded tunnel is no longer running; do not migrate pending attempts to a new origin'}
    $record=Join-Path $run 'server-owner.json'
    $identities=Read-Stage4BIdentity $record
    $identities=@($identities)
    foreach($saved in $identities) {[void](Test-Stage4BIdentity $saved)}
    $listeners=@(Get-NetTCPConnection -State Listen -LocalPort $config.port -ErrorAction SilentlyContinue)
    foreach($listener in $listeners) {if($listener.OwningProcess -notin @($identities.pid)) {throw 'Port owner differs; refusing restart'}}
    [array]::Reverse($identities)
    foreach($saved in $identities) {Stop-Stage4BOwnedProcess $saved}
    # Both fixed paths are inside the checked run root; preserve the ownership record.
    Move-Item -LiteralPath $record -Destination (Join-Path $run ('server-owner-'+[guid]::NewGuid().ToString('N')+'.json'))
    $Action='Start'
}
if($Action -in @('Start','Invite','Reset')) {
    if(-not $config.origin) {throw 'Pin the generated origin first'}
    Set-Environment
    if($Action -in @('Invite','Reset')) {
        if(-not $Email) {throw 'Disposable teacher email required'}
        & $python -m proctoring_server ($Action.ToLowerInvariant()) --email $Email
        exit $LASTEXITCODE
    }
    if(-not $OperatorApprovedPublicExposure) {throw 'Explicit approval required to expose the application through the running tunnel'}
    Assert-Free
    $tunnel=Read-Stage4BIdentity (Join-Path $run 'tunnel-owner.json')
    if(-not (Test-Stage4BIdentity $tunnel)) {throw 'Recorded tunnel not running'}
    if(Test-Path (Join-Path $run 'server-owner.json')) {throw 'Server already launched for this run; no silent restart'}
    if(-not(Test-Path (Join-Path $env:PROCTOR_DEMO_FRONTEND 'index.html'))) {throw 'Build the teacher frontend first'}
    $buildFiles=@('src\proctoring_server\demo.py','src\proctoring_server\app.py','src\proctoring_server\settings.py','teacher-web\dist\index.html')
    $hashes=@{}
    foreach($file in $buildFiles) {$hashes[$file]=(File-Sha256 (Join-Path $repo $file))}
    foreach($asset in Get-ChildItem -LiteralPath (Join-Path $env:PROCTOR_DEMO_FRONTEND 'assets') -File) {$hashes[$asset.Name]=(File-Sha256 $asset.FullName)}
    Write-Json (Join-Path $run ('build-identity-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')+'.json')) $hashes
    $arguments=@('-m','uvicorn','proctoring_server.demo:create_demo_app','--factory','--host','127.0.0.1','--port',$config.port,'--workers','1','--no-access-log','--no-proxy-headers','--no-server-header','--ws','websockets-sansio','--ws-max-size','393216','--ws-max-queue','8','--ws-per-message-deflate','false','--limit-concurrency','64','--backlog','64','--timeout-keep-alive','5','--timeout-graceful-shutdown','5')
    $p=Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $run 'server.stdout.log') -RedirectStandardError (Join-Path $run 'server.stderr.log')
    $identities=@(Get-Stage4BIdentity $p.Id)
    # Python's Windows venv launcher may own a second actual interpreter.
    for($i=0;$i -lt 30;$i++) {
        Start-Sleep -Milliseconds 200
        foreach($child in @(Get-CimInstance Win32_Process|Where-Object {$_.ParentProcessId -in @($identities.pid)})) {
            if($child.ProcessId -notin @($identities.pid)) {$identities+=Get-Stage4BIdentity $child.ProcessId}
        }
        Write-Json (Join-Path $run 'server-owner.json') @($identities|Where-Object {$_})
        $listener=Get-NetTCPConnection -State Listen -LocalPort $config.port -ErrorAction SilentlyContinue
        if($listener) {
            if($listener.OwningProcess -notin @($identities.pid) -or $listener.LocalAddress -ne '127.0.0.1') {throw 'Unexpected listener ownership; no automatic termination'}
            Write-Output 'One owned loopback server is listening. Share the pinned HTTPS URL only with authorized demo participants.';exit
        }
    }
    throw 'Server did not become ready; preserve logs and use Stop after identity inspection'
}
if($Action -eq 'Stop') {
    # Tunnel first: remove public ingress before closing the authoritative server.
    foreach($record in @('tunnel-owner.json','server-owner.json')) {
        $file=Join-Path $run $record
        if(-not(Test-Path $file)) {continue}
        $identities=Read-Stage4BIdentity $file
        $identities=@($identities)
        foreach($saved in $identities) {[void](Test-Stage4BIdentity $saved)}
        [array]::Reverse($identities)
        foreach($saved in $identities) {Stop-Stage4BOwnedProcess $saved}
    }
    Write-Output 'Recorded owned processes stopped; database, evidence, logs and other services preserved.'
}
