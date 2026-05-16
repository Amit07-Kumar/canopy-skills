"""Test translate endpoint and meeting-master proxy with full UTF-8."""
import json, sys, urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TEXT = """[Speaker 2]: जी सर। हाँ अभी कर लेते हैं सर, क्योंकि ज्यादा बेहतर रहेगा इसको। अभी सीनियर ही बैठे हुए थे, उनको भी ले लेता हूँ वीडियो कॉल पे। मेल आईडी बताऊँ सर जो यहाँ पर रजिस्टर है।
[Speaker 3]: हाँ जी। तो अगर अभी कनेक्ट करना है, अभी कर लेते हैं।"""

body = json.dumps({"text": TEXT, "target_language": "English"}, ensure_ascii=False).encode("utf-8")

for label, url in [
    ("brd-agent direct", "http://127.0.0.1:8025/api/translate"),
]:
    print(f"\n=== {label}: {url} ===")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
            print("success:", data.get("success"))
            print("model:", data.get("model"))
            print("len:", len(data.get("translated", "")))
            print("translated:")
            print(data.get("translated", ""))
            print("error:", data.get("error"))
    except Exception as e:
        print("err", type(e).__name__, e)
