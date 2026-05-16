$ErrorActionPreference = 'Stop'

$meetingBase = 'http://127.0.0.1:5098'
$brdBase = 'http://127.0.0.1:8025'
$pass = 0
$fail = 0

function Check($Name, [scriptblock]$Block) {
    try {
        $result = & $Block
        Write-Host "PASS [$Name]" -ForegroundColor Green
        $script:pass++
        return $result
    } catch {
        $message = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $message = $_.ErrorDetails.Message
        }
        Write-Host "FAIL [$Name] $message" -ForegroundColor Red
        $script:fail++
        return $null
    }
}

$meetingHealth = Check 'Meeting health' { Invoke-RestMethod "$meetingBase/health" }
$brdHealth = Check 'BRD health' { Invoke-RestMethod "$brdBase/health" }
$dashboardBefore = Check 'RequireWise dashboard data' {
    Invoke-RestMethod "$brdBase/api/dashboard-data" -Method POST -ContentType 'application/json' -Body (@{ project = 'Execution Command Center' } | ConvertTo-Json)
}
$businessOverview = Check 'Meeting Master business overview' { Invoke-RestMethod "$meetingBase/api/v1/kpis/business-overview" }

$guest = Check 'Guest auth' {
    Invoke-RestMethod "$meetingBase/api/v1/auth/guest" -Method POST -ContentType 'application/json' -Body (@{ device_id = 'portable-e2e-device'; device_name = 'Portable E2E' } | ConvertTo-Json)
}

if ($guest) {
    $headers = @{ Authorization = "Bearer $($guest.access_token)" }
    $processBody = @{
        title = 'E2E Validation - Execution Command Center Sync'
        transcript = 'The product lead will share the premium seller pitch deck by Friday. The customer success owner should schedule a buyer callback tomorrow at 11 AM. Engineering will update the BRD with pricing objections, escalation paths and next-step owners by end of day Thursday. Schedule a review meeting tomorrow at 3 PM with the steering committee to ratify the metric definitions and lock the rollout date.'
        attendee_emails = @('amit.kumar5@indiamart.com')
        participants = @('Product Lead', 'Customer Success Owner', 'Engineering Lead')
    } | ConvertTo-Json

    $meeting = Check 'Process transcript' {
        Invoke-RestMethod "$meetingBase/api/v1/meetings/process-text" -Method POST -ContentType 'application/json' -Body $processBody -Headers $headers
    }

    if ($meeting) {
        $meetingId = $meeting.meeting_id
        $stored = Check 'Get meeting' { Invoke-RestMethod "$meetingBase/api/v1/meetings/$meetingId" -Headers $headers }
        $kpis = Check 'Meeting KPIs' { Invoke-RestMethod "$meetingBase/api/v1/meetings/$meetingId/kpis" -Headers $headers }
        $overview = Check 'User KPI overview' { Invoke-RestMethod "$meetingBase/api/v1/kpis/overview" -Headers $headers }
        $workspaceOverview = Check 'Workspace KPI overview' { Invoke-RestMethod "$meetingBase/api/v1/kpis/business-overview" }
        $bridge = Check 'Generate BRD from meeting' {
            Invoke-RestMethod "$meetingBase/api/v1/meetings/$meetingId/generate-brd" -Method POST -ContentType 'application/json' -Body '{"filename":"e2e-execution-command-center-sync"}' -Headers $headers
        }
        $emailPayload = @{ subject = $stored.mail.subject; to = 'amit.kumar5@indiamart.com'; body = $stored.mail.body; cc = @() } | ConvertTo-Json
        $send = Check 'Manual send email' {
            Invoke-RestMethod "$meetingBase/api/v1/meetings/$meetingId/send-email" -Method POST -ContentType 'application/json' -Body $emailPayload -Headers $headers
        }
        $dashboardAfter = Check 'RequireWise dashboard refresh' {
            Invoke-RestMethod "$brdBase/api/dashboard-data" -Method POST -ContentType 'application/json' -Body (@{ project = 'Execution Command Center' } | ConvertTo-Json)
        }

        if ($kpis) {
            Write-Host "      EHI: $($kpis.execution_health_index) | Completeness: $($kpis.context_completeness_score) | Leakage: $($kpis.action_leakage_rate)" -ForegroundColor Cyan
        }
        if ($stored) {
            Write-Host "      Auto dispatch: $($stored.automation.dispatch_success) | Auto mail: $($stored.automation.auto_sent_email) | Recipients: $($stored.automation.recipients -join ',')" -ForegroundColor Cyan
        }
        if ($bridge) {
            Write-Host "      BRD filename: $($bridge.data.filename)" -ForegroundColor Cyan
        }
        if ($dashboardAfter) {
            $metrics = $dashboardAfter.data.metrics
            Write-Host "      Dashboard EHI: $($metrics.execution_health) | Context: $($metrics.context_completeness) | Automation: $($metrics.automation_coverage)" -ForegroundColor Cyan
        }
        if ($workspaceOverview) {
            Write-Host "      Workspace processed meetings: $($workspaceOverview.total)" -ForegroundColor Cyan
        }
    }
}

Write-Host "RESULTS pass=$pass fail=$fail" -ForegroundColor Yellow
if ($fail -gt 0) {
    exit 1
}