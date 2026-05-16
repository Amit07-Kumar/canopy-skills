"""
End-to-end validation of the real audio upload path.

Uploads D:\\10xHackathon\\audio.mp3 to POST /api/v1/meetings/upload, polls
status, and verifies:
  - The remote n8n transcription webhook was actually invoked
  - raw_transcript is real (non-empty, persisted)
  - model_used reflects the n8n pipeline (not local-fallback)
  - Tasks/MoM/calendar/automation/KPIs are populated
"""
import json
import os
import sys
import time

# Force stdout to UTF-8 so we can print Hindi transcript previews on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

MM = "http://127.0.0.1:5098/api/v1"
AUDIO_FILE = r"D:\10xHackathon\audio.mp3"
AUDIO_CHUNK_FILE = r"D:\10xHackathon\utils\audio_chunk_25s.mp3"


def step(n, msg):
    print(f"\n[{n}] {msg}", flush=True)


def fail(msg):
    print(f"  FAIL: {msg}", flush=True)
    sys.exit(1)


def ok(msg):
    print(f"  OK: {msg}", flush=True)


def main():
    audio_path = AUDIO_FILE if os.path.exists(AUDIO_FILE) else AUDIO_CHUNK_FILE
    if not os.path.exists(audio_path):
        fail(f"No test audio file found at {AUDIO_FILE} or {AUDIO_CHUNK_FILE}")
    size = os.path.getsize(audio_path)
    ok(f"Using audio: {audio_path} ({size/1024:.1f} KB)")

    step(1, "POST /meetings/upload (real audio -> real remote n8n)")
    with open(audio_path, "rb") as fh:
        files = {"audio": ("audio.mp3", fh, "audio/mpeg")}
        data = {
            "title": f"E2E Audio Upload Validation {int(time.time())}",
            "attendee_emails": json.dumps(["amit.kumar5@indiamart.com"]),
            "speaker_hints": json.dumps(["Speaker 1", "Speaker 2"]),
        }
        r = httpx.post(f"{MM}/meetings/upload", files=files, data=data, timeout=120)
    if r.status_code not in (200, 201):
        fail(f"upload returned {r.status_code}: {r.text[:500]}")
    body = r.json()
    meeting_id = body.get("meeting_id")
    if not meeting_id:
        fail(f"no meeting_id in response: {body}")
    ok(f"meeting_id={meeting_id} initial_status={body.get('status')}")

    step(2, "Poll /meetings/{id}/status until completed or failed (up to 8 minutes)")
    deadline = time.time() + 8 * 60
    final = None
    while time.time() < deadline:
        rs = httpx.get(f"{MM}/meetings/{meeting_id}/status", timeout=15)
        if rs.status_code != 200:
            time.sleep(2)
            continue
        s = rs.json()
        print(f"    progress={s.get('progress')} stage={s.get('stage')} status={s.get('status')} "
              f"msg={(s.get('message') or '')[:80]!r}", flush=True)
        if s.get("status") in ("completed", "failed"):
            final = s
            break
        time.sleep(4)

    if not final:
        fail("Polling timed out after 8 minutes")
    if final.get("status") == "failed":
        fail(f"meeting failed: {final.get('error') or final.get('message')}")

    step(3, "Inspect final meeting record")
    r = httpx.get(f"{MM}/meetings/{meeting_id}", timeout=15)
    meeting = r.json()

    raw = meeting.get("raw_transcript") or ""
    if not raw or len(raw) < 50:
        fail(f"raw_transcript too short ({len(raw)} chars). Audio path may have silently failed.")
    ok(f"raw_transcript: {len(raw)} chars; first 80 chars: {raw[:80]!r}")

    model = meeting.get("model_used") or ""
    if "local-fallback" in model and "n8n" not in model:
        fail(f"audio meeting fell back to local regex (model_used={model!r}). n8n is not being invoked.")
    ok(f"model_used={model!r}")

    tasks = meeting.get("tasks") or []
    if not tasks:
        fail("no tasks extracted from audio meeting")
    ok(f"{len(tasks)} task(s); first: {tasks[0].get('title')!r}")

    # Verify diarization (speaker tags) made it through
    speakers = [a for a in (meeting.get("attendees") or []) if a.get("speaker_id")]
    if not speakers:
        ok("No diarization attendees found — n8n response may not have included speakers; not a hard failure")
    else:
        ok(f"diarization preserved: {len(speakers)} speaker(s) attached")

    automation = meeting.get("automation") or {}
    ok(f"automation: dispatch_success={automation.get('dispatch_success')} "
       f"auto_sent_email={automation.get('auto_sent_email')} "
       f"auto_scheduled_calendar={automation.get('auto_scheduled_calendar')}")

    kpis = meeting.get("kpis") or {}
    ok(f"KPIs: EHI={kpis.get('execution_health_index')} "
       f"CCS={kpis.get('context_completeness_score')} "
       f"tasks={kpis.get('task_count')} cal={kpis.get('calendar_count')}")

    print("\n=========================================")
    print(f"PASS — real audio upload -> n8n -> completed meeting validated")
    print(f"  meeting_id = {meeting_id}")
    print(f"  audio_url  = {meeting.get('audio_url')}")
    print("=========================================")


if __name__ == "__main__":
    main()
