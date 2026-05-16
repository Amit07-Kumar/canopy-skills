"""Batch-ingest every PDF under a folder into Gemini File Search via the
meeting-master proxy. Verifies the document count increment and runs a
post-ingest smoke search.

Usage:
    python ingest_launch_mails.py [/path/to/folder]

If no folder is given, defaults to D:\\10xHackathon\\LaunchMail (the
unzipped LaunchMail archive used in the hackathon demo).

Output: per-file status, pre/post document counts, and one sample search
answer (or the upstream quota error, surfaced honestly).
"""
import sys, os, glob, json, urllib.request, urllib.error, mimetypes, time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MM_INGEST = "http://127.0.0.1:5098/api/v1/filesearch/ingest-file"
MM_STATUS = "http://127.0.0.1:5098/api/v1/filesearch/status"
MM_SEARCH = "http://127.0.0.1:5098/api/v1/filesearch/search"

ROOT = sys.argv[1] if len(sys.argv) > 1 else r"D:\10xHackathon\LaunchMail"

pdfs = sorted(glob.glob(os.path.join(ROOT, '**', '*.pdf'), recursive=True))
print(f"\nFound {len(pdfs)} PDF(s) under {ROOT}")


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


print("\n=== Pre-ingest status ===")
with urllib.request.urlopen(MM_STATUS, timeout=30) as r:
    pre = json.loads(r.read().decode("utf-8"))
    pre_count = int(pre.get("documents_count") or 0)
print(f"documents_count: {pre_count}")

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
        op = (upstream.get("result") or {}).get("name", "")[-50:]
        print(f"     OK  upstream_op=...{op}")
        ingested.append(name)
    else:
        print(f"     FAIL HTTP {status}: {json.dumps(payload)[:300]}")
    time.sleep(2)

print(f"\n=== Ingested {len(ingested)} / {len(pdfs)} PDFs ===")
print("Waiting 20s for Gemini to finish embedding...")
time.sleep(20)

print("\n=== Post-ingest status ===")
with urllib.request.urlopen(MM_STATUS, timeout=30) as r:
    post = json.loads(r.read().decode("utf-8"))
    post_count = int(post.get("documents_count") or 0)
print(f"documents_count: {post_count}  (was {pre_count}, +{post_count - pre_count})")

# Sample RAG search — quota may throttle; surface honestly
print("\n=== Sample RAG search ===")
req = urllib.request.Request(
    MM_SEARCH,
    data=json.dumps({"query": "What are the main XMPP launch deliverables and rollout plan?"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
        ans = (data.get("answer") or data.get("response") or data.get("summary") or data.get("text") or "")
        if ans:
            print("ANSWER:")
            print(ans[:1200])
        else:
            print("Response keys:", list(data.keys())[:8])
except urllib.error.HTTPError as e:
    msg = e.read().decode("utf-8", errors="replace")[:500]
    print(f"HTTPError {e.code} (quota or transient): {msg}")
