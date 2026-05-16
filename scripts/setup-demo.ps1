$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$meetingRequirements = Join-Path $root 'meeting-master\docker\requirements.txt'
$brdRequirements = Join-Path $root 'brd-agent\backend\requirements.txt'

Write-Host 'Installing Meeting Master dependencies...' -ForegroundColor Cyan
python -m pip install -r $meetingRequirements

Write-Host 'Installing RequireWise dependencies...' -ForegroundColor Cyan
python -m pip install -r $brdRequirements

Write-Host 'Dependency setup complete.' -ForegroundColor Green