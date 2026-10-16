# Dot-source from any directory. Configuration only: no services or devices start.
param([string]$RunDirectory)
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if(-not $RunDirectory) {$RunDirectory=Join-Path $repo 'build/localhost-acceptance/manual-01'}
$run=[IO.Path]::GetFullPath($RunDirectory)
New-Item -ItemType Directory -Force -Path $run | Out-Null
$env:PYTHONPATH=Join-Path $repo 'src'
$env:PROCTOR_SERVER_DATABASE=Join-Path $run 'teacher.sqlite3'
$env:PROCTOR_EVIDENCE_ROOT=Join-Path $run 'evidence'
$env:PROCTOR_SERVER_URL='http://127.0.0.1:8000'
$env:PROCTOR_TEACHER_ORIGIN='http://127.0.0.1:5174'
$env:PROCTOR_ALLOW_LOOPBACK_HTTP='1'
$env:TEACHER_API_PROXY=$env:PROCTOR_SERVER_URL
$env:PROCTORING_PYTHON=Join-Path $repo '.venv/Scripts/python.exe'
# Isolate Python DPAPI/outbox state. Electron may retain its OS roaming profile.
$env:LOCALAPPDATA=Join-Path $run 'local-app-data'
$env:APPDATA=Join-Path $run 'roaming-app-data'
$env:PROCTOR_LOCAL_CONFIG=Join-Path $run 'student.toml'
if(-not (Test-Path -LiteralPath $env:PROCTOR_LOCAL_CONFIG)) {
    $text=Get-Content -LiteralPath (Join-Path $repo 'config/connected.example.toml') -Raw
    $text=$text.Replace('clipboard_guard_enabled = true','clipboard_guard_enabled = false')
    $text=$text.Replace('vm_check_enabled = true','vm_check_enabled = false')
    $text=$text.Replace('../sessions',(($run -replace '\\','/')+'/sessions'))
    foreach($folder in @('assets','models','artifacts')) {
        $text=$text.Replace('../'+$folder,(($repo -replace '\\','/')+'/'+$folder))
    }
    [IO.File]::WriteAllText($env:PROCTOR_LOCAL_CONFIG,$text,(New-Object Text.UTF8Encoding($false)))
}
Write-Output "Local run: $run"
Write-Output 'API 127.0.0.1:8000; teacher 127.0.0.1:5174. No processes started.'
