# Public local-development example. Run from the repository root.
# HTTP is accepted only because BOTH configured origins are literal loopback.
$env:PYTHONPATH = (Join-Path $PWD 'src')
$env:PROCTOR_SERVER_DATABASE = (Join-Path $PWD 'server/data/teacher.sqlite3')
$env:PROCTOR_EVIDENCE_ROOT = (Join-Path $PWD 'server/data/evidence')
$env:PROCTOR_SERVER_URL = 'http://127.0.0.1:8000'
$env:PROCTOR_TEACHER_ORIGIN = 'http://127.0.0.1:5174'
$env:PROCTOR_ALLOW_LOOPBACK_HTTP = '1'
# Deployment defaults require HTTPS. Do not point this example at a LAN/public
# host or use it as an Internet deployment recipe.
