$ErrorActionPreference = 'Stop'

function Stop-PortProcess([int]$Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host "Nothing listening on port $Port" -ForegroundColor DarkGray
        return
    }

    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped process $processId on port $Port" -ForegroundColor Yellow
    }
}

Stop-PortProcess -Port 5098
Stop-PortProcess -Port 8025

Write-Host 'Demo services stopped.' -ForegroundColor Green