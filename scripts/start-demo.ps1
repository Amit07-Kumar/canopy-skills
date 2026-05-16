$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$meetingRoot = Join-Path $root 'meeting-master'
$brdBackendRoot = Join-Path $root 'brd-agent\backend'
$dotEnvPath = Join-Path $root '.env'

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) {
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            return
        }

        $parts = $line.Split('=', 2)
        if ($parts.Count -ne 2) {
            return
        }

        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if (-not $name) {
            return
        }

        Set-Item -Path ("Env:" + $name) -Value $value
    }
}

function Stop-PortProcess([int]$Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        return
    }

    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped process $processId on port $Port" -ForegroundColor Yellow
        } catch {
            Write-Warning ("Could not stop process {0} on port {1}: {2}" -f $processId, $Port, $_.Exception.Message)
        }
    }
}

function Wait-HttpReady([string]$Name, [string]$Url, [int]$TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Name is ready at $Url" -ForegroundColor Green
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    throw "Timed out waiting for $Name at $Url"
}

Stop-PortProcess -Port 5098
Stop-PortProcess -Port 8025

Import-DotEnv -Path $dotEnvPath

$meetingCommand = @"
`$env:AUTH_DISABLED='true'
`$env:DEBUG_MODE='true'
`$env:JWT_SECRET='local-dev-testing-key-1234'
`$env:UPLOAD_DIR='$($meetingRoot.Replace('\', '\'))\data\uploads'
`$env:STORAGE_FILE='$($meetingRoot.Replace('\', '\'))\data\store.json'
python -m uvicorn backend.api:app --host 127.0.0.1 --port 5098 --app-dir '$($meetingRoot.Replace('\', '\'))'
"@

$brdCommand = @"
`$env:MEETING_MASTER_API_BASE='http://127.0.0.1:5098/api/v1'
python -m uvicorn server:app --host 127.0.0.1 --port 8025 --app-dir '$($brdBackendRoot.Replace('\', '\'))'
"@

Start-Process powershell -WorkingDirectory $root -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $meetingCommand) | Out-Null
Start-Process powershell -WorkingDirectory $root -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $brdCommand) | Out-Null

Wait-HttpReady -Name 'Meeting Master' -Url 'http://127.0.0.1:5098/health'
Wait-HttpReady -Name 'RequireWise' -Url 'http://127.0.0.1:8025/health'

Write-Host 'Meeting Master starting on http://127.0.0.1:5098' -ForegroundColor Green
Write-Host 'RequireWise starting on http://127.0.0.1:8025' -ForegroundColor Green
Write-Host 'Run .\scripts\test-e2e.ps1 after both servers are up.' -ForegroundColor Cyan