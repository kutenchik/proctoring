param([Parameter(Mandatory=$true)][ValidatePattern('^\d{4}\.\d{1,2}\.\d+$')][string]$Version)
$ErrorActionPreference='Stop'
function File-Sha256([string]$Path) {
    $stream=[IO.File]::OpenRead($Path);$sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
    finally {$stream.Dispose();$sha.Dispose()}
}
# Download only. Never install a service or create a tunnel. Version and digest
# are pinned from the official Cloudflare release, with normal certificate checks.
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dest=Join-Path $repo ('build\stage4b-tools\'+$Version)
if(Test-Path -LiteralPath $dest) {throw 'Version directory exists; inspect and preserve it'}
$release=Invoke-RestMethod -Uri ('https://api.github.com/repos/cloudflare/cloudflared/releases/tags/'+$Version)
if($release.tag_name -ne $Version -or $release.draft -or $release.prerelease) {throw 'Expected stable official release'}
$asset=@($release.assets|Where-Object {$_.name -ceq 'cloudflared-windows-amd64.exe'})
if($asset.Count -ne 1 -or $asset[0].digest -notmatch '^sha256:[a-f0-9]{64}$') {throw 'Official asset digest unavailable; do not guess or bypass verification'}
$url='https://github.com/cloudflare/cloudflared/releases/download/'+$Version+'/cloudflared-windows-amd64.exe'
if($asset[0].browser_download_url -cne $url) {throw 'Unexpected asset URL'}
New-Item -ItemType Directory -Path $dest|Out-Null
$binary=Join-Path $dest 'cloudflared.exe'
Invoke-WebRequest -Uri $url -OutFile $binary -UseBasicParsing
$expected=$asset[0].digest.Substring(7)
if((File-Sha256 $binary) -ne $expected) {throw 'Downloaded binary hash mismatch; do not execute it'}
$metadata=@{version=$Version;url=$url;sha256=$expected;bytes=(Get-Item -LiteralPath $binary).Length}
[IO.File]::WriteAllText((Join-Path $dest 'verified-release.json'),($metadata|ConvertTo-Json),(New-Object Text.UTF8Encoding $false))
Write-Output ('Verified official binary: '+$binary)
Write-Output ('SHA256: '+$expected)
