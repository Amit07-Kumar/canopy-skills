"""Ingest all extracted LaunchMail PDFs into Gemini File Search via our proxy."""
import sys, os, glob, json, urllib.request, urllib.error, mimetypes, time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MM_INGEST = "http://127.0.0.1:5098/api/v1/filesearch/ingest-file"
MM_STATUS = "http://127.0.0.1:5098/api/v1/filesearch/status"
MM_SEARCH = "http://127.0.0.1:5098/api/v1/filesearch/search"

ROOT = r"D:\10xHackathon\LaunchMail"

pdfs = sorted(glob.glob(os.path.join(ROOT, '**', '*.pdf'), recursive=True))
print(f"\nFound {len(pdfs)} PDF(s) under {ROOT}")
for p in pdfs:
    print(f"  - {os.path.basename(p)} ({os.path.getsize(p)} bytes)")


def post_multipart_file(url, field, filepath):
    """Send a multipart/form-data POST with a single file field. No deps."""
    boundary = f"----CanopyIngest{int(time.time()*1000)}"
    filename = os.path.basename(filepath)
    content_type = mimetypes.guess_type(filepath)[0] or "application/pdf"
    with open(filepath, "rb") as fh:
        file_bytes = fh.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


print("\n=== Pre-ingest filesearch status ===")
with urllib.request.urlopen(MM_STATUS, timeout=30) as r:
    pre = json.loads(r.read().decode("utf-8"))
    print(f"connected: {pre.get('configured')}, documents_count: {pre.get('documents_count')}")
pre_count = int(pre.get('documents_count') or 0)

print("\n=== Ingesting each PDF ===")
ingested = []
for path in pdfs:
    name = os.path.basename(path)
    print(f"\n  -> {name}")
    status, text = post_multipart_file(MM_INGEST, "file", path)
    try:
        payload = json.loads(text)
    except Exception:
        payload = {"raw": text[:400]}
    if status == 200 and payload.get("success"):
        upstream = payload.get("upstream") or {}
        op_name = (upstream.get("result") or {}).get("name", "")[-60:]
        print(f"     OK   filename={payload.get('filename')} upstream_op=...{op_name}")
        ingested.append(name)
    else:
        print(f"     FAIL HTTP {status}: {json.dumps(payload)[:300]}")
    # small delay between uploads to be gentle on Gemini quota
    time.sleep(2)

print(f"\n=== Ingested {len(ingested)} / {len(pdfs)} PDFs ===")

# Allow Gemini to finish embedding before we query
print("\nWaiting 20s for Gemini to finish embedding all docs...")
time.sleep(20)

print("\n=== Post-ingest filesearch status ===")
with urllib.request.urlopen(MM_STATUS, timeout=30) as r:
    post = json.loads(r.read().decode("utf-8"))
    print(f"documents_count: {post.get('documents_count')}  (was {pre_count})")

# Try a real RAG search against the ingested mails
print("\n=== RAG query: 'What is the XMPP real-time push for buyleads?' ===")
req = urllib.request.Request(
    MM_SEARCH,
    data=json.dumps({"query": "What is the XMPP real-time push feature for seller buyleads and how does it work?"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
        ans = (data.get("answer") or data.get("response") or data.get("summary") or data.get("text") or "")
        if ans:
            print("\nANSWER:")
            print(ans[:1200])
        else:
            print("\nResponse keys:", list(data.keys())[:8])
            print(json.dumps(data, indent=2)[:800])
except urllib.error.HTTPError as e:
    print(f"\nHTTPError {e.code}: {e.read().decode('utf-8', errors='replace')[:400]}")
