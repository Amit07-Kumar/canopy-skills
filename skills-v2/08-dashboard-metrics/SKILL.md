---
name: dashboard-metrics
description: Compute and serve the live RequireWise dashboard — execution health, context completeness, automation coverage, BRD count, processed meetings, action leakage, closure rate — strictly from real stored meetings and BRDs. No mocked metrics anywhere.
---

# Dashboard Metrics (live, no mocks)

## When to use this skill

- The dashboard shows zeros / stale values and you need to trace where
  each number is computed.
- You need to add a new metric or business signal.
- A demo is approaching and you need to verify the dashboard reflects
  real activity.

## How to apply

### Endpoint

`POST http://127.0.0.1:8025/api/dashboard-data`

Request:
```json
{ "project": "Project Title or BRD slug" }
```

Note: the field name is **`project`**, NOT `project_name`. Earlier ad-hoc
test scripts had this wrong.

### Response (live shape)

```json
{
  "success": true,
  "data": {
    "project_name": "Project Title or BRD slug",
    "metrics": {
      "execution_health":      67,
      "context_completeness":  86,
      "automation_coverage":   91,
      "brd_count":             21,
      "processed_meetings":    11,
      "high_risk_meetings":    8,
      "action_leakage":        50,
      "closure_rate":          0
    },
    "recent_activity": [
      {"icon": "📈", "text": "...", "time": "<ISO>", "color": "blue"}
    ],
    "data_sources": [
      {"label": "Processed Meetings", "count": 11, "icon": "🎙️", "status": "live"},
      {"label": "Auto Emails",        "count": 5,  "icon": "✉️", "status": "live"},
      {"label": "Tasks Extracted",    "count": 19, "icon": "✅", "status": "live"},
      {"label": "BRDs Available",     "count": 21, "icon": "📄", "status": "live"}
    ],
    "business_signals": [
      {"name": "Execution Discipline",  "role": "Operations",       "sentiment": 67, "color": "#60a5fa"},
      {"name": "Context Quality",       "role": "Business Analysis","sentiment": 86, "color": "#34d399"},
      {"name": "Automation Readiness",  "role": "Productivity",     "sentiment": 91, "color": "#f59e0b"},
      {"name": "Closure Momentum",      "role": "Execution",        "sentiment": 0,  "color": "#a78bfa"}
    ],
    "conflicts": []
  }
}
```

All numeric fields are computed live, never hardcoded.

### Compute path

`brd-agent/backend/server.py:_fetch_execution_dashboard`:

1. Pulls `_fetch_brds_snapshot()` (real persisted BRDs from `local_brds.json`
   plus the n8n list-brds webhook).
2. Pulls Meeting Master's `/api/v1/kpis/business-overview` (real portfolio KPIs).
3. If Meeting Master is unreachable, returns metrics ALL ZEROED with a
   "Meeting Master unavailable" entry in `recent_activity`. Numbers stay
   zero — never fabricated.
4. On success, derives:
   - `execution_health = round(overview.execution_health_index_avg)`
   - `context_completeness = round(overview.context_completeness_avg)`
   - `automation_coverage = round(overview.automation_coverage)`
   - `brd_count = len(brds)`
   - `processed_meetings = overview.processed_meetings`
   - `high_risk_meetings = count where EHI < 60`
   - `action_leakage = round(overview.action_leakage_rate_avg)`
   - `closure_rate = round(overview.closure_rate_avg)`

### Meeting Master upstream

`meeting-master/backend/api.py` → `GET /api/v1/kpis/business-overview`:

- Reads the entire `store.json` meetings dict.
- Calls `services/kpi.compute_portfolio_kpis(meetings)`.
- Returns averaged KPIs over the portfolio, plus per-meeting flags
  for high-risk detection.

### What "no mocks" guarantees

Audited grep targets that should never appear in operational code:

- ❌ Hardcoded BRD count
- ❌ Hardcoded sample projects list
- ❌ "if not data, return placeholder metrics"
- ❌ Sample tickets (the old WP-1..WP-5 OpenProject fallback is removed)
- ❌ `local-fallback` source in business signals

Tests in [[16-e2e-validation]] grep for these patterns to prevent regressions.

## Frontend rendering

`brd-agent/frontend/dashboard.js`:

- `renderKPIBar(data)` — bars sized by `metrics.<key>`, no defaults.
- `renderActivityFeed(data)` — uses real `recent_activity` array.
- `renderStakeholderSentiment(data)` — uses real `business_signals`.
- Empty state explicitly shows "No recent activity" — does NOT fabricate
  sample activity to fill space.
- `loadDashboardData` error catch sets `REQUIREWISE_DASHBOARD_DATA` to a
  SINGLE real error-message activity entry, never fake metrics.

## Conflict detection

`POST /api/conflict-detection` returns the `conflicts` array from
`_fetch_execution_dashboard`. Each conflict is computed from real meetings
where decisions / owners / dates contradict across the portfolio.

## Verification

```powershell
curl -X POST http://127.0.0.1:8025/api/dashboard-data `
     -H "Content-Type: application/json" `
     -d '{"project": "Any Real BRD Title"}'
```

Inspect the JSON. Every `count` should match the real store. Run the
audio E2E and watch `brd_count` and `processed_meetings` increment.

## Related skills

- [[10-kpi-computation]] — formulas behind each metric
- [[07-brd-generation]] — feeds `brd_count`
- [[08-dashboard-metrics]] — this skill (self)
- [[16-e2e-validation]] — verifies live computation per run
