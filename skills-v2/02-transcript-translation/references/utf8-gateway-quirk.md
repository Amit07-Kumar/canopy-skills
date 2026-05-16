# UTF-8 gateway quirk — why translation was hallucinating

## Symptom

Sending a Hindi transcript to `/api/translate` returned an English translation
that was semantically unrelated to the input. Example reproduction:

Input:
```
[Speaker 2]: जी सर। हाँ अभी कर लेते हैं सर, क्योंकि ज्यादा बेहतर रहेगा इसको।
[Speaker 3]: हाँ जी। तो अगर अभी कनेक्ट करना है, अभी कर लेते हैं।
```

Bogus output:
```
[Speaker 2]: In the matter of the petition filed by the petitioner before this court, the respondent's lawyer has presented arguments before the court...
[Speaker 3]: The court has heard the arguments of both sides, and the decision is as follows.
```

## Root cause

Python's `json.dumps()` defaults to `ensure_ascii=True`, which converts Hindi
codepoints to escape sequences:

```
"जी सर"  →  "जी सर"
```

When httpx serializes our payload via the convenience `json=payload`
parameter, it uses this default. The `imllm.intermesh.net` gateway then
mis-parses the escape sequences (likely passes them through as literal
backslash sequences to the upstream Claude model). Claude sees garbled
placeholder characters and falls back to producing a "best-effort"
hallucinated translation matching the prompt structure.

## Fix

Serialize the body with `ensure_ascii=False` and post raw UTF-8 bytes:

```python
body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
headers["Content-Type"] = "application/json; charset=utf-8"
async with httpx.AsyncClient(timeout=180.0) as client:
    response = await client.post(endpoint, content=body, headers=headers)
```

Same payload now arrives at the gateway as actual Devanagari codepoints.
Claude reads them correctly and produces a faithful, literal translation.

## Verification

```python
import json, urllib.request

payload = {
    "text": "[Speaker 2]: जी सर। हाँ अभी कर लेते हैं सर।",
    "target_language": "English",
}
body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:8025/api/translate",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode("utf-8"))
```

Expected: `{"success": true, "translated": "[Speaker 2]: Yes sir. Yes, let's do it now sir...", ...}`
