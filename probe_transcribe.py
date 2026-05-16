"""Probe the transcribe-speakers webhook directly to see exact error."""
import sys, urllib.request, urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://imworkflow.intermesh.net/webhook/transcribe-speakers"
AUDIO = r"D:\10xHackathon\audio.mp3"

with open(AUDIO, "rb") as fh:
    audio_bytes = fh.read()

boundary = "----PROBE-BOUNDARY-1234567"
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="audio"; filename="audio.mp3"\r\n'
    f"Content-Type: audio/mpeg\r\n\r\n"
).encode() + audio_bytes + f"\r\n--{boundary}--\r\n".encode()

req = urllib.request.Request(
    URL,
    data=body,
    headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-Language": "unknown",
        "X-Model": "saaras:v3",
        "X-Timestamps": "true",
    },
    method="POST",
)

print(f"POST {URL}")
print(f"audio size: {len(audio_bytes)} bytes")

try:
    with urllib.request.urlopen(req, timeout=180) as r:
        text = r.read().decode("utf-8", errors="replace")
        print(f"\nHTTP {r.status}")
        print(f"len: {len(text)}")
        print(text[:1500])
except urllib.error.HTTPError as e:
    text = e.read().decode("utf-8", errors="replace")
    print(f"\nHTTPError {e.code}")
    print(text[:1500])
except Exception as e:
    print(f"\nerr {type(e).__name__}: {e}")
