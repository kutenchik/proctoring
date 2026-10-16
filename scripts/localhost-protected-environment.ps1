# Configuration only. Never starts devices, hooks, or an application.
$protectedRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../build/localhost-protected/manual-01'))
. (Join-Path $PSScriptRoot 'localhost-environment.ps1') -RunDirectory $protectedRoot
$env:PROCTOR_LOCAL_CONFIG = Join-Path $protectedRoot 'protected-student.toml'
if (-not (Test-Path -LiteralPath $env:PROCTOR_LOCAL_CONFIG)) {
    throw 'Protected configuration has not been prepared. Do not use the ordinary student.toml as a replacement.'
}
$env:PROCTOR_PROTECTED_RUN = $protectedRoot
# Pass this explicitly as --user-data-dir; APPDATA alone does not relocate Electron.
$env:PROCTOR_ELECTRON_PROFILE = Join-Path $protectedRoot 'electron-profile'
