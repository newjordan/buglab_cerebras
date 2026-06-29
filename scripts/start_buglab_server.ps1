$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:BUGLAB_HOST = "127.0.0.1"
$env:BUGLAB_PORT = "8765"

& "C:\Python313\python.exe" -u -m app.server *> (Join-Path $root "server.8765.log")
