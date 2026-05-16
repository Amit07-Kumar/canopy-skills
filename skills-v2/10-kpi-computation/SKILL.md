---
name: kpi-computation
description: Compute per-meeting and portfolio Key Performance Indicators — Execution Health Index, Context Completeness, Action Leakage, Ownership Coverage, Due Date Coverage, Calendar Coverage, Time-to-Action. All formulas pure-functional, no hidden defaults, derived strictly from the stored meeting record.
---

# KPI Computation

## When to use this skill

- You need to understand or extend the EHI / context completeness /
  leakage formulas.
- The dashboard or per-meeting card shows surprising KPI values and you
  need to trace which signal drove it.
- A new business signal needs to be added — find the right insertion point.

## How to apply

### Module

`meeting-master/backend/services/kpi.py`. Pure-functional — no I/O, no
LLM calls. Takes a meeting dict (or list for portfolio) and returns a dict.

### Per-meeting KPIs

`compute_meeting_kpis(meeting) → dict`. Fields:

```
execution_health_index       0–100, weighted blend of the others
context_completeness_score   0–100, completeness of attendee/topic/decision fields
action_leakage_rate          0–100, % of detected commitments not converted to tasks
closure_rate                 0–100, % of tasks marked DONE
time_to_action_seconds       seconds from meeting end → first auto-dispatch (or 0 when pending)
ownership_coverage           0–100, % of tasks with an assignee set
due_date_coverage            0–100, % of tasks with a due_date set
priority_clarity_rate        0–100, % of tasks with a Priority value
calendar_coverage            0–100, % of action items that also created a calendar hold
task_context_coverage        0–100, % of tasks with a non-empty description/context
detected_commitments         int, regex-matched commitment verbs in transcript
task_count                   int
calendar_count               int
recipient_count              int
email_ready                  bool, mail body non-empty + at least one recipient
auto_dispatch_success        bool, mirrors automation.dispatch_success
missing_fields               List[str], names of unfilled critical fields
generated_at                 ISO timestamp
```

### Portfolio KPIs

`compute_portfolio_kpis(meetings) → dict`. Averages the per-meeting KPIs
across all completed meetings. Adds:

```
processed_meetings          int
high_risk_meetings          int, count where EHI < 60
execution_health_index_avg  float
context_completeness_avg    float
automation_coverage         0–100, % of meetings with dispatch_success
action_leakage_rate_avg     float
closure_rate_avg            float
```

These feed [[08-dashboard-metrics]].

### Key formulas

```
execution_health_index = round(
    0.30 * context_completeness_score
  + 0.25 * (100 - action_leakage_rate)
  + 0.20 * ownership_coverage
  + 0.15 * due_date_coverage
  + 0.10 * action_speed_score
)

context_completeness_score = round(
    0.40 * (has_attendees) * 100
  + 0.30 * (has_topic) * 100
  + 0.30 * (has_decision) * 100
)

action_leakage_rate = max(0, 1 - task_count / detected_commitments) * 100
  # where detected_commitments = max(_detect_commitments(transcript), task_count)
  # — guaranteed non-negative; commitments-without-tasks is the leakage.

action_speed_score:
  - 100 if time_to_action_seconds <= 30s
  -  85 if 30s < time_to_action <= 5 min
  -  70 if 5 min < time_to_action <= 30 min
  -  55 partial credit if email_ready but not yet dispatched
  -   0 otherwise
```

The `55.0` partial-credit floor for "ready but not dispatched" is an
intentional honesty signal — it doesn't inflate execution-health to a
real-dispatched 70 unless the email has actually been sent.

### Hidden vs honest defaults

The module never returns hardcoded "good" values. Every formula short-circuits
to 0 when its inputs are missing. The dashboard's "Closure Momentum: 0" is
literal — no tasks are DONE yet, so closure is 0%.

### Commitment detection

`_detect_commitments(transcript)` regex pattern (English + Hindi):

```
\b(will|needs? to|should|must|going to|has to|agreed to|committed to|please|
review|share|send|update|schedule|set|call|approve|approval|book|booking|
calendar|event|ticket|
kar do|kar dena|karna hai|karna hoga|bhej dungi|bhej dega|bhej do|
set kar do|review kar lo|dekh lo|chahiye|बुक|कैलेंडर|इवेंट|टिकट)\b
```

This is the same pattern the fallback transcript extractor uses
(see [[03-ai-summarization]]).

## Verification

```powershell
# Per-meeting
curl http://127.0.0.1:5098/api/v1/meetings/<id>/kpis
# Portfolio
curl http://127.0.0.1:5098/api/v1/kpis/business-overview
```

## Related skills

- [[04-mom-email-generation]] — KPI snapshot shows in MoM email body
- [[08-dashboard-metrics]] — consumes portfolio KPIs
- [[13-auto-dispatch-flow]] — time_to_action measured here
- [[16-e2e-validation]] — KPI shape assertions in every E2E run
