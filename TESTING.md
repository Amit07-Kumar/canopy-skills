# Testing

How to verify the workspace is healthy and how to extend the test surface as features are added. See [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) for orientation.

---

## 1. TL;DR — verify everything works

```powershell
# from d:\10xHackathon
powershell -ExecutionPolicy Bypass -File .\scripts\setup-demo.ps1   # once
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1   # spawns two PS windows on :5098 and :8025
powershell -ExecutionPolicy Bypass -File .\scripts\test-e2e.ps1     # 13 black-box checks
powershell -ExecutionPolicy Bypass -File .\scripts\stop-demo.ps1
```

`test-e2e.ps1` exits non-zero if any check fails.

## 2. What the e2e covers

[scripts/test-e2e.ps1](scripts/test-e2e.ps1) runs 13 checks against both running services:

| # | Check | What it proves |
|---|---|---|
| 1 | `GET :5098/health` | Meeting Master is up |
| 2 | `GET :8025/health` | RequireWise is up |
| 3 | `POST :8025/api/dashboard-data` (pre-meeting) | Cross-app dashboard fetch works |
| 4 | `GET :5098/api/v1/kpis/business-overview` | Workspace rollup endpoint serves |
| 5 | `POST :5098/api/v1/auth/guest` | Guest JWT minted |
| 6 | `POST :5098/api/v1/meetings/process-text` | Full text-processing pipeline + KPI compute + auto-dispatch |
| 7 | `GET :5098/api/v1/meetings/{id}` | Persisted record retrievable |
| 8 | `GET :5098/api/v1/meetings/{id}/kpis` | Per-meeting KPI compute returns EHI/completeness/leakage |
| 9 | `GET :5098/api/v1/kpis/overview` (auth) | User-scoped rollup |
| 10 | `GET :5098/api/v1/kpis/business-overview` (no auth) | Workspace rollup reflects new meeting |
| 11 | `POST :5098/api/v1/meetings/{id}/generate-brd` | Meeting → BRD bridge |
| 12 | `POST :5098/api/v1/meetings/{id}/send-email` | Manual MoM send |
| 13 | `POST :8025/api/dashboard-data` (post-meeting) | Dashboard now reflects the new meeting |

It also prints the live numbers (EHI / completeness / automation / recipients / dashboard EHI / workspace count) so you can eyeball the demo story.

## 3. Last run

Captured 2026-05-14:

```
PASS [Meeting health]
PASS [BRD health]
PASS [RequireWise dashboard data]
PASS [Meeting Master business overview]
PASS [Guest auth]
PASS [Process transcript]
PASS [Get meeting]
PASS [Meeting KPIs]
PASS [User KPI overview]
PASS [Workspace KPI overview]
PASS [Generate BRD from meeting]
PASS [Manual send email]
PASS [RequireWise dashboard refresh]
      EHI: 69.4 | Completeness: 98.3 | Leakage: 40.0
      Auto dispatch: True | Auto mail: True | Recipients: rahul@example.com,neha@example.com
      BRD filename: portable-demo-revenue-sync
      Dashboard EHI: 74 | Context: 93 | Automation: 100
      Workspace processed meetings: 45
RESULTS pass=13 fail=0
```

Additional smoke checks beyond the script (also green):

- `GET :5098/health` → `{status: ok, started: "May 14, 2026 at 02:09 PM IST", version: "1.0.0"}`
- `GET :8025/api/config` → 7 project options
- `GET :8025/api/list-brds` → 11 BRDs (Google Doc IDs)
- `GET :5098/api/v1/meetings` (anonymous, because `AUTH_DISABLED=true`) → meetings list

## 4. Coverage gaps — known and intentional

The e2e is black-box only. The following are **not** covered today:

- **Audio upload path** (`POST /api/v1/meetings/upload`) — needs a real audio fixture + transcription provider keys. [meeting-master/tests/test_audio.wav](meeting-master/tests/test_audio.wav) and `sample_add_listing.m4a` exist but aren't wired to the e2e.
- **n8n webhook path** — pipeline is exercised with `USE_N8N_WEBHOOKS=true`, but assertions don't check webhook URLs were called.
- **AI-provider failover** ([services/ai.py](meeting-master/backend/services/ai.py)) — system-prompt merge and JSON extraction fallbacks are exercised manually per [meeting-master/tests/TEST_GUIDE.md](meeting-master/tests/TEST_GUIDE.md), not automatically.
- **brd-agent endpoints other than `/api/dashboard-data` and `/health`** — `/api/new-brd`, `/api/transcript-summary`, `/api/audio-summary`, `/api/google-tools` are unverified by the e2e.
- **Frontend** — no UI tests. Visual sanity check is opening `http://127.0.0.1:5098/` and `http://127.0.0.1:8025/` in a browser.
- **No `pytest` suite.** `pytest` and `pytest-asyncio` are pinned in [meeting-master/docker/requirements.txt](meeting-master/docker/requirements.txt) but no `test_*.py` files exist.

## 5. Adding a new check to the e2e

Edit [scripts/test-e2e.ps1](scripts/test-e2e.ps1) and add a `Check 'name' { ... }` block. The helper:

```powershell
function Check($Name, [scriptblock]$Block) {
    try { & $Block; Write-Host "PASS [$Name]" -ForegroundColor Green; $script:pass++ }
    catch { Write-Host "FAIL [$Name] $($_.Exception.Message)" -ForegroundColor Red; $script:fail++ }
}
```

…increments pass/fail counters and the script `exit 1`s if anything fails. Inside the block, just `Invoke-RestMethod` and throw on bad shape if needed:

```powershell
$kpis = Check 'New metric: time-to-action' {
    $r = Invoke-RestMethod "$meetingBase/api/v1/meetings/$meetingId/kpis" -Headers $headers
    if (-not $r.time_to_action_seconds) { throw 'time_to_action_seconds missing' }
    $r
}
```

## 6. Adding a `pytest` suite (recommended path for new features)

Dependencies are already in [meeting-master/docker/requirements.txt](meeting-master/docker/requirements.txt). To bootstrap:

```powershell
# from d:\10xHackathon\meeting-master
$env:AUTH_DISABLED='true'; $env:STORAGE_FILE="$PWD\data\store.json"
python -m pytest -q
```

Conventional location: `meeting-master/backend/tests/test_kpi.py`, `…/test_storage.py`, etc. Use FastAPI's `TestClient`:

```python
from fastapi.testclient import TestClient
from backend.api import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

KPI helpers in [services/kpi.py](meeting-master/backend/services/kpi.py) are pure functions — good first unit-test targets (`_detect_commitments`, `_action_speed_score`, `compute_meeting_kpis`).

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Timed out waiting for Meeting Master at :5098/health` during `start-demo.ps1` | Port already taken by another process, or import error | Script auto-kills :5098/:8025; watch the spawned PS window for the uvicorn error |
| `FAIL [Process transcript] ... 422` | Body shape changed in `MeetingTextProcessRequest` model | Diff [meeting-master/backend/models.py](meeting-master/backend/models.py) against the JSON in `test-e2e.ps1` |
| `FAIL [Generate BRD from meeting]` | brd-agent process died or `MEETING_MASTER_API_BASE` mis-set | Re-run `start-demo.ps1`, check the brd-agent PS window |
| Litellm/openai version warnings on pip install | brd-agent overwrites Meeting Master pins | Cosmetic — both apps still boot |
| `403`/`401` on a route that was passing | `AUTH_DISABLED` env not propagated to the new server window | Re-run `start-demo.ps1` to re-export env vars |
