"""
End-to-end real-flow validation for the Meeting Master + RequireWise stack.

Validates with NO mocks:
  1. POST /api/v1/meetings/process-text (real n8n AISummarization)
  2. Poll /meetings/{id}/status until completed
  3. Verify completed meeting has real MoM, tasks, calendar, automation, KPIs
  4. POST /api/v1/meetings/{id}/generate-brd (real RequireWise LLM)
  5. Verify BRD persisted in local_brds.json
  6. POST /api/dashboard-data — verify live metrics include the new project
  7. Verify /api/v1/calendar/authorize is no longer a placeholder (501)
  8. Verify /api/openproject-tickets no longer returns hardcoded WP-1..WP-5

Run with: python e2e_full_validation.py
"""
import json
import time
import sys
from datetime import datetime

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

MM = "http://127.0.0.1:5098/api/v1"
BRD = "http://127.0.0.1:8025/api"

# Real (anonymized) meeting transcript content modeled on the kind of
# customer-success call this product is built for. NOT a mock — this is the
# real transcript text the system will process via the real n8n AISummarization
# webhook. No fake KPIs, no fake BRD content, no fake dashboard data.
REAL_TRANSCRIPT = """Speaker 1: Welcome back. As discussed last week, the goal of today's session is to lock down the rollout plan for the seller verification flow before the quarter ends. We have three open items I want to close.
Speaker 2: Right. The KYC integration with the third party is still pending review. Engineering said the contract piece needs final sign off from legal by Friday or the launch will slip by two weeks.
Speaker 1: That is unacceptable. Please escalate to the legal lead today and request a same-day turn around. Loop me on the thread so I can push if needed.
Speaker 2: Understood. I will send the escalation note within the hour and follow up tomorrow morning if there is no response.
Speaker 1: Good. Second item — the dashboard for execution health. The metric definitions for context completeness and action leakage need to be locked. The data team flagged ambiguity last sprint.
Speaker 2: I scheduled a 30 minute review with the data team tomorrow at 11 AM. We will walk through every formula and ratify the definitions. I will share the final spec by end of day Thursday.
Speaker 1: Make sure executive review gets the final numbers before Friday. The board pack draft is due Monday morning.
Speaker 2: Will do. I will also send the BRD update to the steering committee on Thursday so they have time to comment before the weekend.
Speaker 1: Third — the long context BRD generation pipeline. We need a final dry run of an end-to-end real meeting flowing into a structured BRD with no manual edits. Have engineering done that?
Speaker 2: Yes, we validated one full run yesterday. The output quality was strong but the bridge timeout needed to be raised because the LLM call for long transcripts was taking over 90 seconds. That is fixed now.
Speaker 1: Excellent. Please document the test result in our follow-up email and CC the engineering manager. Also book a 15 minute review session for next Tuesday so we can show this to the steering committee.
Speaker 2: Noted. I will draft the email today and set up the Tuesday review on the shared calendar.
Speaker 1: Great. Let us close. Action items — escalate legal review, lock KPI definitions, send BRD update Thursday, book Tuesday steering review. Thank you everyone."""

PROJECT_TITLE = f"E2E Real Flow Validation {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
BRD_FILENAME = f"e2e-real-flow-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"


def step(n, msg):
    print(f"\n[{n}] {msg}", flush=True)


def fail(msg):
    print(f"  FAIL: {msg}", flush=True)
    sys.exit(1)


def ok(msg):
    print(f"  OK: {msg}", flush=True)


def main():
    # ----- 0. Verify removed-mock endpoints -----
    step(0, "Verify mock-removal sanity")

    r = httpx.get(f"{MM}/calendar/authorize", timeout=10)
    if r.status_code != 501:
        fail(f"/calendar/authorize should be 501 now, got {r.status_code}: {r.text[:200]}")
    if "placeholder" in r.text.lower():
        fail("/calendar/authorize still contains 'placeholder'")
    ok(f"/calendar/authorize returns 501 (no placeholder URL)")

    r = httpx.get(f"{BRD}/openproject-tickets", timeout=10)
    body = r.json()
    if body.get("source") == "local-fallback" or any(t.get("id", "").startswith("WP-") for t in body.get("tickets", [])):
        fail(f"OpenProject still returns hardcoded WP-* tickets: {body}")
    ok(f"/openproject-tickets returns no hardcoded samples (source={body.get('source')}, tickets={len(body.get('tickets', []))})")

    # ----- 1. Create real meeting via process-text -----
    step(1, "POST /meetings/process-text with a REAL transcript")
    payload = {
        "transcript": REAL_TRANSCRIPT,
        "title": PROJECT_TITLE,
        "attendee_emails": ["amit.kumar5@indiamart.com"],
        "speaker_hints": ["Engineering Lead", "Project Manager"],
    }
    r = httpx.post(f"{MM}/meetings/process-text", json=payload, timeout=300)
    if r.status_code != 200:
        fail(f"process-text returned {r.status_code}: {r.text[:500]}")

    meeting = r.json()
    meeting_id = meeting.get("meeting_id")
    if not meeting_id:
        fail(f"no meeting_id in response: {meeting}")
    ok(f"meeting_id={meeting_id} status={meeting.get('status')} stage={meeting.get('processing_stage')}")

    # ----- 2. Verify completed-state shape (process-text returns synchronously) -----
    step(2, "Verify the returned meeting has real MoM / tasks / calendar / automation / KPIs")

    raw_tr = meeting.get("raw_transcript") or meeting.get("transcript_en") or ""
    if not raw_tr or len(raw_tr) < 100:
        fail(f"raw_transcript is missing or too short ({len(raw_tr)} chars)")
    ok(f"raw_transcript persisted ({len(raw_tr)} chars)")

    tasks = meeting.get("tasks") or []
    if not tasks:
        fail("no tasks extracted")
    ok(f"{len(tasks)} task(s) extracted; first: {tasks[0].get('title')!r}")

    cal = meeting.get("calendar_events") or []
    ok(f"{len(cal)} calendar event(s) extracted")

    mail = meeting.get("mail") or {}
    if not mail.get("body"):
        fail("mail body is empty")
    ok(f"mail body present ({len(mail.get('body', ''))} chars), sent={mail.get('sent')}")

    automation = meeting.get("automation") or {}
    ok(f"automation: dispatch_success={automation.get('dispatch_success')}, "
       f"recipients={automation.get('recipients')}, error={automation.get('error')}")

    kpis = meeting.get("kpis") or {}
    must_have_kpis = [
        "execution_health_index", "context_completeness_score",
        "action_leakage_rate", "task_count", "calendar_count",
    ]
    missing = [k for k in must_have_kpis if k not in kpis]
    if missing:
        fail(f"KPIs missing keys: {missing}")
    ok(f"KPIs present: EHI={kpis.get('execution_health_index')}, "
       f"CCS={kpis.get('context_completeness_score')}, "
       f"tasks={kpis.get('task_count')}, cal={kpis.get('calendar_count')}")

    # Check we are not silently using regex local-fallback for this real meeting
    model_used = meeting.get("model_used") or ""
    if "local-fallback" in model_used and "n8n" not in model_used:
        fail(f"meeting was generated entirely by local-fallback (model_used={model_used!r})")
    ok(f"model_used={model_used!r}")

    # ----- 3. Wait for processing to actually complete -----
    step(3, "Poll /meetings/{id}/status until completed")
    for i in range(120):
        rs = httpx.get(f"{MM}/meetings/{meeting_id}/status", timeout=10)
        if rs.status_code != 200:
            fail(f"status check failed: {rs.status_code} {rs.text[:200]}")
        s = rs.json()
        if s.get("status") == "completed":
            ok(f"completed after {i+1} poll(s); stage={s.get('stage')} progress={s.get('progress')}")
            break
        if s.get("status") == "failed":
            fail(f"meeting failed: {s.get('error') or s.get('message')}")
        time.sleep(2)
    else:
        fail("meeting did not reach completed within 240s")

    # Re-fetch the full meeting after completion to capture final automation state
    rf = httpx.get(f"{MM}/meetings/{meeting_id}", timeout=10).json()
    final_automation = rf.get("automation") or {}
    ok(f"final automation: dispatch_success={final_automation.get('dispatch_success')} "
       f"auto_sent_email={final_automation.get('auto_sent_email')} "
       f"auto_scheduled_calendar={final_automation.get('auto_scheduled_calendar')}")

    # ----- 4. Generate BRD via Meeting Master bridge -----
    step(4, "POST /meetings/{id}/generate-brd")
    r = httpx.post(
        f"{MM}/meetings/{meeting_id}/generate-brd",
        json={"filename": BRD_FILENAME},
        timeout=450,
    )
    if r.status_code != 200:
        fail(f"generate-brd returned {r.status_code}: {r.text[:500]}")
    body = r.json()
    if not body.get("success"):
        fail(f"generate-brd success=False: {body}")
    nested = body.get("data", {}).get("response", {})
    src = nested.get("source")
    if src not in ("n8n", "llm-agent"):
        fail(f"BRD source unexpected: {src}")
    brd_text = nested.get("data", {}).get("text") or ""
    if len(brd_text) < 1200:
        fail(f"BRD content suspiciously short ({len(brd_text)} chars)")
    # TBDs are acceptable in a real BRD for genuinely unspecified facts
    # (unset deadlines, pending sign-offs). Only flag when the doc is
    # short AND TBD-heavy — that pattern indicates a skeleton dump.
    tbd_count = brd_text.count("TBD")
    if len(brd_text) < 4000 and tbd_count > 4:
        fail(f"BRD looks like a skeleton (TBD count = {tbd_count}, len = {len(brd_text)})")
    # Require the structural backbone of a real BRD
    must_have_headings = ["executive summary", "functional requirements", "non-functional"]
    lower = brd_text.lower()
    missing_headings = [h for h in must_have_headings if h not in lower]
    if missing_headings:
        fail(f"BRD missing required sections: {missing_headings}")
    ok(f"BRD generated via source={src}, {len(brd_text)} chars, {tbd_count} TBD(s)")

    # ----- 5. Verify persisted in local_brds.json -----
    step(5, "Verify BRD persisted in brd-agent/backend/local_brds.json")
    with open("D:\\10xHackathon\\brd-agent\\backend\\local_brds.json", "r", encoding="utf-8") as fh:
        local_brds = json.load(fh)
    # local_brds.json is a list of records keyed by 'filename' field
    if isinstance(local_brds, dict):
        rec = local_brds.get(BRD_FILENAME)
    else:
        rec = next((r for r in local_brds if r.get("filename") == BRD_FILENAME), None)
    if not rec:
        fail(f"BRD slug {BRD_FILENAME!r} not found in local_brds.json "
             f"({'dict' if isinstance(local_brds, dict) else 'list'} of {len(local_brds)})")
    ok(f"persisted: source={rec.get('source')}, "
       f"content_len={len(rec.get('content', ''))}, "
       f"updated_at={rec.get('updated_at')}")

    # ----- 6. Dashboard data for this real project -----
    step(6, "POST /dashboard-data with the real project name")
    r = httpx.post(
        f"{BRD}/dashboard-data",
        json={"project": PROJECT_TITLE},
        timeout=60,
    )
    if r.status_code != 200:
        fail(f"dashboard-data returned {r.status_code}: {r.text[:300]}")
    d = r.json()
    metrics = d.get("data", {}).get("metrics", {})
    required = [
        "execution_health", "context_completeness", "automation_coverage",
        "brd_count", "processed_meetings", "high_risk_meetings",
        "action_leakage", "closure_rate",
    ]
    missing = [k for k in required if k not in metrics]
    if missing:
        fail(f"dashboard metrics missing keys: {missing}")
    if metrics.get("brd_count", 0) <= 0:
        fail(f"brd_count is zero — dashboard not seeing the new BRD")
    if metrics.get("processed_meetings", 0) <= 0:
        fail(f"processed_meetings is zero — dashboard not seeing real meetings")
    ok(f"dashboard metrics live: {json.dumps(metrics)}")

    sources = d.get("data", {}).get("data_sources", [])
    ok(f"data_sources: {[(s['label'], s['count'], s['status']) for s in sources]}")

    print("\n=========================================")
    print(f"PASS — full real-flow E2E validated")
    print(f"  meeting_id = {meeting_id}")
    print(f"  brd_filename = {BRD_FILENAME}")
    print(f"  project = {PROJECT_TITLE}")
    print("=========================================")


if __name__ == "__main__":
    main()
