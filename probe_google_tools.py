"""
Direct probe of the google_tool_event webhook so we can see EXACTLY which
node in the workflow is failing. Sends the same payload meeting-master
sends, captures the response, and surfaces the error string.
"""
import json
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://n8n.backend.lehana.in/webhook/google_tool_event"

# Same shape meeting-master sends after our latest fixes. Two calendar
# events, both with proper titles, both with full datetimes.
payload = {
    "recipients": ["amit.kumar5@indiamart.com"],
    "calender": [
        {
            "event_title": "Video Call Setup",
            "title": "Video Call Setup",
            "event_date": "2026-05-17",
            "event_time": "11:00",
            "start_datetime": "2026-05-17T11:00:00",
            "end_datetime": "2026-05-17T12:00:00",
            "description": "Connect with senior team via video call to walk through the platform.",
            "notes": "Connect with senior team via video call to walk through the platform.",
            "participants": ["amit.kumar5@indiamart.com"],
            "attendees": ["amit.kumar5@indiamart.com"],
            "event_type": "MEETING",
            "time": "11:00",
        },
        {
            "event_title": "Aluminum Coil Processing Review",
            "title": "Aluminum Coil Processing Review",
            "event_date": "2026-05-18",
            "event_time": "15:00",
            "start_datetime": "2026-05-18T15:00:00",
            "end_datetime": "2026-05-18T16:00:00",
            "description": "Review the aluminum coil lead processing flow with the operations lead.",
            "notes": "Review the aluminum coil lead processing flow with the operations lead.",
            "participants": ["amit.kumar5@indiamart.com"],
            "attendees": ["amit.kumar5@indiamart.com"],
            "event_type": "MEETING",
            "time": "15:00",
        },
    ],
    "Task": [
        {
            "task_title": "Process Aluminum Coil Leads",
            "description": "Handle aluminum coil operations per lead instructions.",
            "category": "Ops",
            "priority": "Medium",
            "start_date": "2026-05-16",
            "edd": "2026-05-18",
            "calendar_block": True,
        },
        {
            "task_title": "Transfer Calls to Seniors",
            "description": "Transfer calls to seniors when needed during discussions.",
            "category": "Ops",
            "priority": "Low",
            "start_date": "2026-05-16",
            "edd": "2026-05-17",
            "calendar_block": True,
        },
    ],
    "MOM": [
        {
            "topic": "Video Call Setup",
            "discussion_summary": "Speakers discussed connecting via video call to walk a senior through the platform; agreed to fall back to audio call if video fails.",
            "decisions": "Proceed with video call setup",
            "owner": "Speaker 2",
        },
        {
            "topic": "Aluminum Coil Lead Processing",
            "discussion_summary": "Walked through entering aluminum coil keywords in the Buy Lead interface and reviewed valid present-time leads.",
            "decisions": "Continue processing aluminum coil leads per the current flow",
            "owner": "Speaker 3",
        },
    ],
}

body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
print(f"POST {URL}")
print(f"payload bytes: {len(body)}")
print(f"calender items: {len(payload['calender'])}, Task items: {len(payload['Task'])}, MOM items: {len(payload['MOM'])}")

req = urllib.request.Request(
    URL,
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8", errors="replace")
        print(f"\nHTTP {r.status}")
        print(text[:2000])
except urllib.error.HTTPError as e:
    text = e.read().decode("utf-8", errors="replace")
    print(f"\nHTTPError {e.code}")
    print(text[:2000])
except Exception as e:
    print(f"\nerr {type(e).__name__}: {e}")
