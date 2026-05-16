import asyncio
import os
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RequireWise BRD Agent API")
logger = logging.getLogger(__name__)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
LOCAL_BRD_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_brds.json")

def get_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _load_local_brd_cache() -> list[dict]:
    try:
        if not os.path.exists(LOCAL_BRD_CACHE_PATH):
            return []
        with open(LOCAL_BRD_CACHE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_local_brd_cache(items: list[dict]) -> None:
    with open(LOCAL_BRD_CACHE_PATH, "w", encoding="utf-8") as file:
        json.dump(items, file, ensure_ascii=False, indent=2)


def _brd_slug_from_item(item) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("filename") or item.get("name") or item.get("id") or "").strip()
    return ""


def _persist_local_brd(filename: str, content: str, source: str) -> None:
    slug = _brd_slug_from_item({"filename": filename})
    if not slug or not str(content or "").strip():
        return

    now = _current_timestamp()
    existing = _load_local_brd_cache()
    record = {
        "id": slug,
        "filename": slug,
        "name": slug,
        "content": content,
        "source": source,
        "preview": "",
        "updated_at": now,
    }

    merged = []
    replaced = False
    for item in existing:
        if _brd_slug_from_item(item) == slug:
            merged.append({**item, **record})
            replaced = True
        else:
            merged.append(item)
    if not replaced:
        merged.insert(0, record)

    _save_local_brd_cache(merged)


def _merge_brd_inventories(remote_items: list, local_items: list) -> list[dict | str]:
    merged: dict[str, dict | str] = {}

    for item in remote_items:
        slug = _brd_slug_from_item(item)
        if not slug:
            continue
        merged[slug] = item

    for item in local_items:
        slug = _brd_slug_from_item(item)
        if not slug:
            continue
        if slug not in merged:
            merged[slug] = item
            continue

        remote_item = merged[slug]
        if isinstance(remote_item, dict) and isinstance(item, dict):
            merged[slug] = {**item, **remote_item, "content": remote_item.get("content") or item.get("content") or ""}
        elif isinstance(item, dict):
            merged[slug] = item

    return list(merged.values())


def _filter_brd_inventory(items: list, filename: str) -> list:
    target = str(filename or "").strip().lower()
    if not target:
        return items
    return [item for item in items if _brd_slug_from_item(item).lower() == target]


BRD_AGENT_LLM_API_KEY = os.getenv("BRD_AGENT_LLM_API_KEY", "").strip()
BRD_AGENT_LLM_BASE_URL = os.getenv("BRD_AGENT_LLM_BASE_URL", "https://imllm.intermesh.net/").strip()
BRD_AGENT_LLM_MODEL = os.getenv("BRD_AGENT_LLM_MODEL", "anthropic/claude-opus-4-6").strip()
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_BATCH_MODEL = os.getenv("SARVAM_BATCH_MODEL", "saaras:v3").strip()
SARVAM_BATCH_MODE = os.getenv("SARVAM_BATCH_MODE", "transcribe").strip()
SARVAM_BATCH_LANGUAGE = os.getenv("SARVAM_BATCH_LANGUAGE", "unknown").strip()
SARVAM_BATCH_INITIAL_WAIT_SECONDS = max(1, int(os.getenv("SARVAM_BATCH_INITIAL_WAIT_SECONDS", "15")))
SARVAM_BATCH_POLL_INTERVAL_SECONDS = max(2, int(os.getenv("SARVAM_BATCH_POLL_INTERVAL_SECONDS", "10")))
SARVAM_BATCH_MAX_WAIT_SECONDS = max(60, int(os.getenv("SARVAM_BATCH_MAX_WAIT_SECONDS", "3600")))
SARVAM_BATCH_HTTP_ATTEMPTS = max(1, int(os.getenv("SARVAM_BATCH_HTTP_ATTEMPTS", "4")))
WEBHOOK_HTTP_ATTEMPTS = max(1, int(os.getenv("WEBHOOK_HTTP_ATTEMPTS", "3")))
SARVAM_BATCH_INIT_URL = "https://api.sarvam.ai/speech-to-text/job/v1"
SARVAM_BATCH_UPLOAD_URL = "https://api.sarvam.ai/speech-to-text/job/v1/upload-files"
SARVAM_BATCH_START_URL = "https://api.sarvam.ai/speech-to-text/job/v1/{job_id}/start"
SARVAM_BATCH_STATUS_URL = "https://api.sarvam.ai/speech-to-text/job/v1/{job_id}/status"
SARVAM_BATCH_DOWNLOAD_URL = "https://api.sarvam.ai/speech-to-text/job/v1/download-files"
SARVAM_BATCH_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
FILE_SEARCH_API_BASE = os.getenv("FILE_SEARCH_API_BASE", "").strip().rstrip("/")
FILE_SEARCH_REQUEST_JSON = os.getenv("FILE_SEARCH_REQUEST_JSON", "").strip()
FILE_SEARCH_TIMEOUT_SECONDS = max(5.0, float(os.getenv("FILE_SEARCH_TIMEOUT_SECONDS", "45")))
FILE_SEARCH_MAX_CONTEXT_CHARS = max(500, int(os.getenv("FILE_SEARCH_MAX_CONTEXT_CHARS", "6000")))
FILE_SEARCH_MAX_ITEMS = max(1, int(os.getenv("FILE_SEARCH_MAX_ITEMS", "8")))


async def _sarvam_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(1, SARVAM_BATCH_HTTP_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code in SARVAM_BATCH_RETRYABLE_STATUS_CODES and attempt < SARVAM_BATCH_HTTP_ATTEMPTS:
                logger.warning(
                    "Sarvam %s %s returned %s on attempt %s/%s; retrying",
                    method,
                    url,
                    response.status_code,
                    attempt,
                    SARVAM_BATCH_HTTP_ATTEMPTS,
                )
                await asyncio.sleep(min(2 ** (attempt - 1), 5))
                continue

            response.raise_for_status()
            return response
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= SARVAM_BATCH_HTTP_ATTEMPTS:
                raise
            logger.warning(
                "Sarvam %s %s transport error on attempt %s/%s: %s. Retrying.",
                method,
                url,
                attempt,
                SARVAM_BATCH_HTTP_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(min(2 ** (attempt - 1), 5))

    if last_error:
        raise last_error
    raise RuntimeError(f"Sarvam request failed unexpectedly for {method} {url}")


async def _post_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    timeout: float = 60.0,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(1, WEBHOOK_HTTP_ATTEMPTS + 1):
        try:
            response = await client.post(url, json=payload, timeout=timeout)
            if response.status_code in SARVAM_BATCH_RETRYABLE_STATUS_CODES and attempt < WEBHOOK_HTTP_ATTEMPTS:
                logger.warning(
                    "Webhook POST %s returned %s on attempt %s/%s; retrying",
                    url,
                    response.status_code,
                    attempt,
                    WEBHOOK_HTTP_ATTEMPTS,
                )
                await asyncio.sleep(min(2 ** (attempt - 1), 5))
                continue
            return response
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= WEBHOOK_HTTP_ATTEMPTS:
                raise
            logger.warning(
                "Webhook POST %s transport error on attempt %s/%s: %s. Retrying.",
                url,
                attempt,
                WEBHOOK_HTTP_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(min(2 ** (attempt - 1), 5))

    if last_error:
        raise last_error
    raise RuntimeError(f"Webhook request failed unexpectedly for {url}")


def _current_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _project_name_from_slug(filename: str) -> str:
    cleaned = re.sub(r"-brd$", "", str(filename or "").strip(), flags=re.IGNORECASE)
    cleaned = cleaned.replace("-", " ").strip()
    return cleaned.title() or "Project"


def _brd_id_from_slug(filename: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "", str(filename or "").lower())
    slug = slug.strip("-") or "project"
    return f"BRD-{slug.upper().replace('-', '-') }"


def _looks_like_low_quality_brd(text: str) -> bool:
    body = str(text or "").strip()
    if not body:
        return True

    # A long BRD that already contains the full required structure should not
    # be rejected just because a few fields remain marked TBD.
    if len(body) >= 4000 and not _missing_brd_markers(body):
        return False

    lowered = body.lower()
    required_markers = [
        "executive summary",
        "functional requirements",
        "non-functional requirements",
    ]
    missing_markers = sum(1 for marker in required_markers if marker not in lowered)
    tbd_count = len(re.findall(r"\btbd\b", lowered, re.IGNORECASE))

    if len(body) < 1200:
        return True
    if missing_markers >= 2:
        return True
    if tbd_count >= 4:
        return True
    return False


def _repair_mojibake(text: str) -> str:
    body = str(text or "")
    if not any(marker in body for marker in ["â", "ð", "€™", "œ"]):
        return body

    try:
        repaired = body.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        if repaired and repaired.count("## ") >= body.count("## "):
            return repaired
    except Exception:
        pass
    return body


def _missing_brd_markers(text: str) -> list[str]:
    body = str(text or "")
    required_markers = [
        "## 1. EXECUTIVE SUMMARY",
        "## 2. BUSINESS OBJECTIVES",
        "## 3. STAKEHOLDER ANALYSIS",
        "## 4. FUNCTIONAL REQUIREMENTS",
        "### 🔴 MUST-HAVE",
        "### 🟡 SHOULD-HAVE",
        "### 🟢 NICE-TO-HAVE",
        "## 5. NON-FUNCTIONAL REQUIREMENTS",
        "## 6. ASSUMPTIONS & CONSTRAINTS",
        "## 7. DATA SOURCES & INTEGRATIONS",
        "## 8. ARCHITECTURE OVERVIEW",
        "## 9. OPEN CONFLICTS",
        "## 10. CORRECTIONS & FALSE POSITIVES",
        "## 11. CHANGE LOG",
    ]
    return [marker for marker in required_markers if marker not in body]


def _is_complete_brd(text: str) -> bool:
    body = _repair_mojibake(text)
    if _looks_like_low_quality_brd(body):
        return False
    return len(_missing_brd_markers(body)) == 0


def _llm_chat_completions_url(base_url: str) -> str:
    trimmed = str(base_url or "").rstrip("/")
    if trimmed.endswith("/v1"):
        return f"{trimmed}/chat/completions"
    return f"{trimmed}/v1/chat/completions"


def _compact_text(value: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _merge_warning_messages(*messages: str) -> str:
    parts = [_compact_text(message, 300) for message in messages if str(message or "").strip()]
    return " | ".join(parts)


def _file_search_search_url() -> str:
    if not FILE_SEARCH_API_BASE:
        raise RuntimeError("FILE_SEARCH_API_BASE is not configured")
    if FILE_SEARCH_API_BASE.endswith("/search"):
        return FILE_SEARCH_API_BASE
    return f"{FILE_SEARCH_API_BASE}/search"


def _file_search_request_overrides() -> dict:
    if not FILE_SEARCH_REQUEST_JSON:
        return {}
    try:
        payload = json.loads(FILE_SEARCH_REQUEST_JSON)
    except Exception as exc:
        raise RuntimeError(f"FILE_SEARCH_REQUEST_JSON is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("FILE_SEARCH_REQUEST_JSON must decode to a JSON object")
    return payload


def _build_file_search_query(filename: str, text: str, search_query: str = "") -> str:
    explicit = _compact_text(search_query, 400)
    if explicit:
        return explicit

    title = _compact_text(str(filename or "").replace("-", " "), 120)
    text_lines = [
        _compact_text(line, 220)
        for line in str(text or "").splitlines()
        if _compact_text(line, 220)
    ]
    summary = next((line for line in text_lines if len(line) >= 32), "")
    query = " | ".join(part for part in [title, summary] if part)
    return _compact_text(query, 400)


def _extract_file_search_hits(payload) -> list[str]:
    snippets: list[str] = []

    def append_item(item) -> None:
        if isinstance(item, str):
            text = _compact_text(item, 500)
            if text:
                snippets.append(text)
            return

        if not isinstance(item, dict):
            return

        title = _compact_text(
            item.get("title")
            or item.get("displayName")
            or item.get("name")
            or item.get("source")
            or item.get("id")
            or "",
            160,
        )
        excerpt = _compact_text(
            item.get("snippet")
            or item.get("text")
            or item.get("content")
            or item.get("excerpt")
            or item.get("pageContent")
            or item.get("chunkText")
            or item.get("summary")
            or item.get("answer")
            or item.get("response")
            or "",
            500,
        )

        if not excerpt:
            metadata = item.get("metadata")
            if isinstance(metadata, list):
                metadata_bits = []
                for meta in metadata[:4]:
                    if not isinstance(meta, dict):
                        continue
                    key = _compact_text(meta.get("key") or "", 60)
                    value = _compact_text(meta.get("stringValue") or meta.get("value") or "", 120)
                    if key and value:
                        metadata_bits.append(f"{key}={value}")
                excerpt = "; ".join(metadata_bits)

        formatted = f"{title}: {excerpt}" if title and excerpt else (title or excerpt)
        formatted = _compact_text(formatted, 650)
        if formatted:
            snippets.append(formatted)

    if isinstance(payload, dict):
        answer = _compact_text(payload.get("answer") or payload.get("response") or "", 500)
        if answer:
            snippets.append(answer)

        for key in ("results", "matches", "items", "chunks", "citations", "documents"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    append_item(item)

    unique: list[str] = []
    seen = set()
    for snippet in snippets:
        normalized = snippet.lower()
        if not snippet or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(snippet)

    return unique[:FILE_SEARCH_MAX_ITEMS]


async def _augment_brd_text_with_file_search(filename: str, text: str, search_query: str = "") -> tuple[str, dict | None]:
    if not FILE_SEARCH_API_BASE:
        return text, None

    query = _build_file_search_query(filename, text, search_query)
    if not query:
        return text, None

    payload = {"query": query}
    payload.update(_file_search_request_overrides())

    async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
        response = await client.post(_file_search_search_url(), json=payload)

    if response.status_code != 200:
        raise RuntimeError(f"File search returned {response.status_code}: {response.text[:200]}")

    try:
        search_payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"File search did not return valid JSON: {exc}") from exc

    hits = _extract_file_search_hits(search_payload)
    if not hits:
        return text, {"query": query, "hits": 0}

    context_lines = []
    remaining_chars = FILE_SEARCH_MAX_CONTEXT_CHARS
    for hit in hits:
        line = f"- {hit}"
        if len(line) > remaining_chars:
            break
        context_lines.append(line)
        remaining_chars -= len(line) + 1

    context_block = "\n".join(context_lines).strip()
    if not context_block:
        return text, {"query": query, "hits": 0}

    enriched_text = (
        f"{str(text or '').rstrip()}\n\n"
        f"Retrieved file-search context for BRD grounding\n"
        f"Query: {query}\n"
        f"{context_block}\n"
    )
    return enriched_text, {"query": query, "hits": len(context_lines)}


def _build_brd_generation_prompt(filename: str, text: str) -> str:
    project_name = _project_name_from_slug(filename)
    brd_id = _brd_id_from_slug(filename)
    current_date = _current_date()
    timestamp = _current_timestamp()

    return f"""You are RequireWise, an expert Business Requirements Document generator.

Your job is to convert unstructured business context into a polished, professional BRD using the exact template below and no other structure.

Input context will be provided below.

Current date:
{current_date}

Current timestamp:
{timestamp}

Follow these rules exactly:
1. ALWAYS output a complete BRD in valid Markdown.
2. ALWAYS use the exact section numbering and headings from 1 to 11.
3. NEVER add extra sections, prefaces, notes, explanations, or commentary outside the BRD.
4. Replace all placeholders with extracted business content from the provided context.
5. If a value is missing, use a realistic placeholder like TBD, To be confirmed, or a clearly safe business dummy.
6. Use professional business language throughout.
7. Keep the Executive Summary under 50 words.
8. Quantify business impact and success metrics wherever the source supports it.
9. Do not invent hard facts that are not supported by the input. If uncertain, write TBD.
10. Preserve the exact Markdown structure below.

Output exactly in this format:

# {project_name} - Business Requirements Document
**BRD ID**: {brd_id} | **Version**: v1.0 | **Status**: Draft | **Date**: {current_date}
**Source**: Multi-channel (Gmail/Slack/Meetings/Drive) | **Last Updated**: {timestamp}

---

## 1. EXECUTIVE SUMMARY (50 words max)
<1-2 sentence business problem + solution overview + key differentiator + ROI/value proposition>

**Business Impact**: <quantified metrics - time saved/cost reduced/revenue generated>

---

## 2. BUSINESS OBJECTIVES
**Primary Goal**: <main business outcome>
**Target Market**: <customer segments, geography, size>
**Success Metrics**: 
  - <KPI1>: <target>
  - <KPI2>: <target>
**Timeline**: <key milestones/deadlines>
**Budget**: <cost constraints/revenue targets>

---

## 3. STAKEHOLDER ANALYSIS
| Stakeholder | Role | Key Requirements | Concerns/Priorities | Sentiment |
|-------------|------|------------------|-------------------|-----------|
| <Name/Role> | <PM/CTO/etc> | <specific asks> | <risks/blockers> | <Positive/Neutral/Negative> |

---

## 4. FUNCTIONAL REQUIREMENTS

### 🔴 MUST-HAVE (Core MVP - Demo Critical)
<Bullet list of 3-5 essential features>

### 🟡 SHOULD-HAVE (Polish/Depth)
<Bullet list of 4-6 important features>

### 🟢 NICE-TO-HAVE (Future Vision)  
<Bullet list of visionary features>

---

## 5. NON-FUNCTIONAL REQUIREMENTS
**Performance**: <response times, throughput>
**Scalability**: <expected load/users>
**Security**: <auth, data protection>
**Usability**: <user experience targets>
**Reliability**: <uptime, error rates>
**Compatibility**: <browsers/devices/OS>

---

## 6. ASSUMPTIONS & CONSTRAINTS
**Assumptions**: ...
**Constraints**: ...
**Risks**: | Risk | Impact | Mitigation |

---

## 7. DATA SOURCES & INTEGRATIONS
Gmail API → <X> emails | Slack → <X> messages | Meetings → <X> transcripts | Drive Docs → <X> files

---

## 8. ARCHITECTURE OVERVIEW
<Tech stack table: Component | Technology | Justification>

---

## 9. OPEN CONFLICTS ({current_date})
| Topic | Debate | Type | Status | Last Discussion |

---

## 10. CORRECTIONS & FALSE POSITIVES ({current_date})
<item>: [FALSE POSITIVE / CORRECTED - <date>]

---

## 11. CHANGE LOG
v1.0 ({current_date}): Initial BRD generated from submitted business context.

---

**APPROVALS**:
Product Owner: ______ Date: ______
Engineering Lead: ______ Date: ______
**Auto-generated by RequireWise Agent** [{timestamp}]

Business context:
{text}
"""


def _build_brd_repair_prompt(filename: str, text: str, draft: str, missing_markers: list[str]) -> str:
        project_name = _project_name_from_slug(filename)
        current_date = _current_date()
        timestamp = _current_timestamp()
        missing = "\n".join(f"- {marker}" for marker in missing_markers) or "- None"

        return f"""The draft BRD below is not acceptable yet. Rewrite it into a complete, polished BRD.

Project name: {project_name}
Current date: {current_date}
Current timestamp: {timestamp}

Requirements:
- Preserve all valid business and technical details from the draft.
- Use the original business context to fill gaps.
- Output only Markdown.
- Use the exact required sections 1 through 11.
- Keep all section headings exactly as required.
- Ensure the three functional requirement subsections appear exactly:
    - ### 🔴 MUST-HAVE (Core MVP - Demo Critical)
    - ### 🟡 SHOULD-HAVE (Polish/Depth)
    - ### 🟢 NICE-TO-HAVE (Future Vision)
- Ensure sections 5 and 6 are present with substantial content.
- Remove encoding noise and output clean UTF-8 text.

Missing or malformed markers detected:
{missing}

Original business context:
{text}

Invalid draft BRD:
{draft}
"""


def _build_brd_markdown_prompt(filename: str, text: str) -> str:
        project_name = _project_name_from_slug(filename)
        current_date = _current_date()
        timestamp = _current_timestamp()

        return f"""Write a complete, polished Business Requirements Document in Markdown.

Project name: {project_name}
Current date: {current_date}
Current timestamp: {timestamp}

Requirements:
- Output only Markdown.
- Use the exact required sections 1 through 11.
- Keep all section headings exactly as required.
- Ensure the three functional requirement subsections appear exactly:
    - ### 🔴 MUST-HAVE (Core MVP - Demo Critical)
    - ### 🟡 SHOULD-HAVE (Polish/Depth)
    - ### 🟢 NICE-TO-HAVE (Future Vision)
- Use rich business detail and technical detail suitable for a hackathon demo and leadership review.
- If a detail is unknown, write TBD instead of omitting it.
- Remove encoding noise and output clean UTF-8 text.

Required headings:
- ## 1. EXECUTIVE SUMMARY
- ## 2. BUSINESS OBJECTIVES
- ## 3. STAKEHOLDER ANALYSIS
- ## 4. FUNCTIONAL REQUIREMENTS
- ## 5. NON-FUNCTIONAL REQUIREMENTS
- ## 6. ASSUMPTIONS & CONSTRAINTS
- ## 7. DATA SOURCES & INTEGRATIONS
- ## 8. ARCHITECTURE OVERVIEW
- ## 9. OPEN CONFLICTS
- ## 10. CORRECTIONS & FALSE POSITIVES
- ## 11. CHANGE LOG

Business context:
{text}
"""


def _build_brd_json_prompt(filename: str, text: str) -> str:
    project_name = _project_name_from_slug(filename)
    current_date = _current_date()

    return f"""Return ONLY valid JSON. Do not return Markdown.

You are generating the content for a world-class Business Requirements Document for {project_name}.
Use rich business detail and technical detail, suitable for a hackathon demo and leadership review.
If a field is unknown, use \"TBD\". Do not omit keys.

Required JSON schema:
{{
  "project_name": "string",
  "status": "string",
  "executive_summary": "string, max 50 words",
  "business_impact": "string",
  "primary_goal": "string",
  "target_market": "string",
  "success_metrics": [{{"name": "string", "target": "string"}}],
  "timeline": "string",
  "budget": "string",
  "stakeholders": [{{"stakeholder": "string", "role": "string", "key_requirements": "string", "concerns": "string", "sentiment": "Positive|Neutral|Negative|TBD"}}],
  "must_have": ["string"],
  "should_have": ["string"],
  "nice_to_have": ["string"],
  "non_functional": {{
    "performance": "string",
    "scalability": "string",
    "security": "string",
    "usability": "string",
    "reliability": "string",
    "compatibility": "string"
  }},
  "assumptions": ["string"],
  "constraints": ["string"],
  "risks": [{{"risk": "string", "impact": "string", "mitigation": "string"}}],
  "data_sources": {{
    "gmail": "string",
    "slack": "string",
    "meetings": "string",
    "drive_docs": "string"
  }},
  "architecture": [{{"component": "string", "technology": "string", "justification": "string"}}],
  "open_conflicts": [{{"topic": "string", "debate": "string", "type": "string", "status": "string", "last_discussion": "string"}}],
  "corrections": ["string"],
  "change_log": "string"
}}

Guidance:
- Make the BRD strong enough to showcase LLM-powered BRD generation in a hackathon demo.
- Include both business-level and technical-level depth.
- Use quantified impact and KPIs where the context supports it.
- Keep the executive summary under 50 words.
- Infer a credible architecture stack when context is product-level but not implementation-specific.
- Assume this is version v1.0 generated on {current_date}.

Business context:
{text}
"""


def _extract_json_object(raw_text: str) -> dict:
    body = _repair_mojibake(str(raw_text or "").strip())
    if not body:
        raise RuntimeError("LLM returned an empty JSON response")

    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", body, re.DOTALL)
    if not match:
        raise RuntimeError("LLM response did not contain a JSON object")

    try:
        parsed = json.loads(match.group(0))
    except Exception as exc:
        raise RuntimeError(f"Could not parse LLM JSON response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM JSON payload was not an object")
    return parsed


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _sanitize_text(text: str) -> str:
    cleaned = _repair_mojibake(str(text or "").strip())
    replacements = {
        "â€”": " - ",
        "â€“": " - ",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€¢": "-",
        "â†’": "->",
        "â‰¥": ">=",
        "â‰¤": "<=",
        "â¥": ">=",
        "â¤": "<=",
        "â¹": "INR ",
        "Â": "",
        "Ã©": "e",
        "Ã¨": "e",
        "Ã": "",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = cleaned.replace("â€", "")
    cleaned = cleaned.replace("â", "-")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _text_or_tbd(value, default: str = "TBD") -> str:
    text = _sanitize_text(str(value or ""))
    return text or default


def _normalize_status(value) -> str:
    text = _text_or_tbd(value, "Draft")
    canonical = {
        "draft": "Draft",
        "in review": "In Review",
        "approved": "Approved",
        "proposed": "Proposed",
        "final": "Final",
    }
    lowered = text.lower()
    return canonical.get(lowered, "Draft")


def _render_bullet_lines(items: list, fallback: str = "TBD") -> str:
    normalized = [_sanitize_text(str(item)) for item in _as_list(items) if _sanitize_text(str(item))]
    if not normalized:
        normalized = [fallback]
    return "\n".join(f"- {item}" for item in normalized)


def _render_metric_lines(items: list) -> str:
    rows = []
    for item in _as_list(items):
        if isinstance(item, dict):
            rows.append(f"  - {_text_or_tbd(item.get('name'))}: {_text_or_tbd(item.get('target'))}")
        else:
            rows.append(f"  - {_text_or_tbd(item)}: TBD")
    if not rows:
        rows = ["  - KPI 1: TBD", "  - KPI 2: TBD"]
    return "\n".join(rows)


def _render_stakeholder_rows(items: list) -> str:
    rows = []
    for item in _as_list(items):
        if isinstance(item, dict):
            rows.append(
                f"| {_text_or_tbd(item.get('stakeholder'))} | {_text_or_tbd(item.get('role'))} | {_text_or_tbd(item.get('key_requirements'))} | {_text_or_tbd(item.get('concerns'))} | {_text_or_tbd(item.get('sentiment'))} |"
            )
    if not rows:
        rows = ["| TBD | TBD | TBD | TBD | TBD |"]
    return "\n".join(rows)


def _render_risk_rows(items: list) -> str:
    rows = []
    for item in _as_list(items):
        if isinstance(item, dict):
            rows.append(f"| {_text_or_tbd(item.get('risk'))} | {_text_or_tbd(item.get('impact'))} | {_text_or_tbd(item.get('mitigation'))} |")
    if not rows:
        rows = ["| TBD | TBD | TBD |"]
    return "\n".join(rows)


def _render_architecture_rows(items: list) -> str:
    rows = []
    for item in _as_list(items):
        if isinstance(item, dict):
            rows.append(
                f"| {_text_or_tbd(item.get('component'))} | {_text_or_tbd(item.get('technology'))} | {_text_or_tbd(item.get('justification'))} |"
            )
    if not rows:
        rows = ["| TBD | TBD | TBD |"]
    return "\n".join(rows)


def _render_conflict_rows(items: list) -> str:
    rows = []
    for item in _as_list(items):
        if isinstance(item, dict):
            rows.append(
                f"| {_text_or_tbd(item.get('topic'))} | {_text_or_tbd(item.get('debate'))} | {_text_or_tbd(item.get('type'))} | {_text_or_tbd(item.get('status'))} | {_text_or_tbd(item.get('last_discussion'))} |"
            )
    if not rows:
        rows = [f"| None identified | No unresolved debate captured yet | TBD | Open | {_current_date()} |"]
    return "\n".join(rows)


def _render_correction_lines(items: list) -> str:
    normalized = [_sanitize_text(str(item)) for item in _as_list(items) if _sanitize_text(str(item))]
    if not normalized:
        normalized = [f"No corrections identified: [CORRECTED - {_current_date()}]"]
    return "\n".join(f"{item}" for item in normalized)


def _render_brd_from_payload(filename: str, payload: dict) -> str:
    project_name = _text_or_tbd(payload.get("project_name"), _project_name_from_slug(filename))
    brd_id = _brd_id_from_slug(filename)
    version = "v1.0"
    status = _normalize_status(payload.get("status"))
    current_date = _current_date()
    timestamp = _current_timestamp()
    non_functional = payload.get("non_functional") if isinstance(payload.get("non_functional"), dict) else {}
    data_sources = payload.get("data_sources") if isinstance(payload.get("data_sources"), dict) else {}

    return f"""# {project_name} - Business Requirements Document
**BRD ID**: {brd_id} | **Version**: {version} | **Status**: {status} | **Date**: {current_date}
**Source**: Multi-channel (Gmail/Slack/Meetings/Drive) | **Last Updated**: {timestamp}

---

## 1. EXECUTIVE SUMMARY (50 words max)
{_text_or_tbd(payload.get('executive_summary'))}

**Business Impact**: {_text_or_tbd(payload.get('business_impact'))}

---

## 2. BUSINESS OBJECTIVES
**Primary Goal**: {_text_or_tbd(payload.get('primary_goal'))}
**Target Market**: {_text_or_tbd(payload.get('target_market'))}
**Success Metrics**: 
{_render_metric_lines(payload.get('success_metrics'))}
**Timeline**: {_text_or_tbd(payload.get('timeline'))}
**Budget**: {_text_or_tbd(payload.get('budget'))}

---

## 3. STAKEHOLDER ANALYSIS
| Stakeholder | Role | Key Requirements | Concerns/Priorities | Sentiment |
|-------------|------|------------------|-------------------|-----------|
{_render_stakeholder_rows(payload.get('stakeholders'))}

---

## 4. FUNCTIONAL REQUIREMENTS

### 🔴 MUST-HAVE (Core MVP - Demo Critical)
{_render_bullet_lines(payload.get('must_have'))}

### 🟡 SHOULD-HAVE (Polish/Depth)
{_render_bullet_lines(payload.get('should_have'))}

### 🟢 NICE-TO-HAVE (Future Vision)  
{_render_bullet_lines(payload.get('nice_to_have'))}

---

## 5. NON-FUNCTIONAL REQUIREMENTS
**Performance**: {_text_or_tbd(non_functional.get('performance'))}
**Scalability**: {_text_or_tbd(non_functional.get('scalability'))}
**Security**: {_text_or_tbd(non_functional.get('security'))}
**Usability**: {_text_or_tbd(non_functional.get('usability'))}
**Reliability**: {_text_or_tbd(non_functional.get('reliability'))}
**Compatibility**: {_text_or_tbd(non_functional.get('compatibility'))}

---

## 6. ASSUMPTIONS & CONSTRAINTS
**Assumptions**: {_render_bullet_lines(payload.get('assumptions'))}
**Constraints**: {_render_bullet_lines(payload.get('constraints'))}
**Risks**: | Risk | Impact | Mitigation |
|------|--------|------------|
{_render_risk_rows(payload.get('risks'))}

---

## 7. DATA SOURCES & INTEGRATIONS
Gmail API → {_text_or_tbd(data_sources.get('gmail'))} | Slack → {_text_or_tbd(data_sources.get('slack'))} | Meetings → {_text_or_tbd(data_sources.get('meetings'))} | Drive Docs → {_text_or_tbd(data_sources.get('drive_docs'))}

---

## 8. ARCHITECTURE OVERVIEW
| Component | Technology | Justification |
|-----------|------------|---------------|
{_render_architecture_rows(payload.get('architecture'))}

---

## 9. OPEN CONFLICTS ({current_date})
| Topic | Debate | Type | Status | Last Discussion |
|-------|--------|------|--------|-----------------|
{_render_conflict_rows(payload.get('open_conflicts'))}

---

## 10. CORRECTIONS & FALSE POSITIVES ({current_date})
{_render_correction_lines(payload.get('corrections'))}

---

## 11. CHANGE LOG
{version} ({current_date}): {_text_or_tbd(payload.get('change_log'), 'Initial BRD generated from submitted business context.')}

---

**APPROVALS**:
Product Owner: ______ Date: ______
Engineering Lead: ______ Date: ______
**Auto-generated by RequireWise Agent** [{timestamp}]
"""


def _extract_message_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    return ""


async def _request_llm_content(endpoint: str, headers: dict, system_prompt: str, user_prompt: str, timeout: float = 180.0) -> str:
    payload = {
        "model": BRD_AGENT_LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 8000,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
    return _repair_mojibake(_extract_message_content(result)).strip()


async def _generate_brd_with_llm(filename: str, text: str) -> str:
    if not BRD_AGENT_LLM_API_KEY:
        raise RuntimeError("BRD_AGENT_LLM_API_KEY is not configured")

    prompt = _build_brd_json_prompt(filename, text)
    endpoint = _llm_chat_completions_url(BRD_AGENT_LLM_BASE_URL)
    payload = {
        "model": BRD_AGENT_LLM_MODEL,
        "temperature": 0.3,
        "max_tokens": 8000,
        "messages": [
            {
                "role": "system",
                "content": "You are RequireWise, a senior product strategist and enterprise solutions architect. Return only valid JSON matching the requested schema.",
            },
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    headers = {
        "Authorization": f"Bearer {BRD_AGENT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    # Long meeting-derived prompts are more reliable when generated directly as
    # Markdown instead of going through the stricter JSON-render-repair chain.
    if len(text or "") >= 2500:
        direct_markdown = await _request_llm_content(
            endpoint,
            headers,
            "You write complete enterprise BRDs in Markdown. Return only Markdown with the exact required heading structure.",
            _build_brd_markdown_prompt(filename, text),
        )
        if _is_complete_brd(direct_markdown):
            return direct_markdown

        repaired_long_markdown = await _request_llm_content(
            endpoint,
            headers,
            "You repair incomplete BRDs. Return only polished Markdown with the exact required section structure.",
            _build_brd_repair_prompt(filename, text, direct_markdown, _missing_brd_markers(direct_markdown)),
        )
        if _is_complete_brd(repaired_long_markdown):
            return repaired_long_markdown

        # Final pass: synthesize ONLY the missing sections and append. The
        # model is much more reliable when asked to generate a small slice
        # than to redo the whole 25k-char BRD. This recovers the occasional
        # case where both prior passes truncated the same back-half sections.
        partial = repaired_long_markdown or direct_markdown
        missing_list = _missing_brd_markers(partial)
        if partial and missing_list:
            try:
                tail = await _request_llm_content(
                    endpoint,
                    headers,
                    "You are completing a BRD. Output ONLY the missing Markdown sections, in their canonical order, with their `## N. HEADING` headers exactly as listed. No preamble. No closing remark.",
                    (
                        "Source context:\n"
                        f"{text[:4000]}\n\n"
                        "Existing partial BRD (do not repeat):\n"
                        f"{partial}\n\n"
                        "Generate ONLY these missing sections, in order, "
                        "each with its full body content (lists, tables, owners, dates as appropriate). "
                        "Use TBD where the source does not state a value. "
                        "Output Markdown only.\n\n"
                        "Missing sections:\n- " + "\n- ".join(missing_list)
                    ),
                )
                if tail:
                    stitched = partial.rstrip() + "\n\n" + tail.strip() + "\n"
                    if _is_complete_brd(stitched):
                        return stitched
            except Exception as exc:
                logger.warning("Final BRD section-append pass failed: %s", exc)

        missing = ", ".join(_missing_brd_markers(repaired_long_markdown or direct_markdown)) or "unknown structure issue"
        raise RuntimeError(f"Rendered BRD is incomplete after markdown generation: {missing}")

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    content = _repair_mojibake(_extract_message_content(result))
    payload_json = None
    if content.strip():
        try:
            payload_json = _extract_json_object(content)
        except Exception:
            payload_json = None

    repair_prompt = f"""Return ONLY valid JSON matching the required schema from the previous request.

If the prior output was cut off or malformed, finish and correct it.

Business context:
{text}

Previous invalid output:
{content}
"""
    repair_payload = {
        "model": BRD_AGENT_LLM_MODEL,
        "temperature": 0.2,
        "max_tokens": 8000,
        "messages": [
            {
                "role": "system",
                "content": "You repair malformed JSON for BRD generation. Return only valid JSON with all required keys populated.",
            },
            {
                "role": "user",
                "content": repair_prompt,
            }
        ],
    }

    if payload_json is None:
        repaired = await _request_llm_content(
            endpoint,
            headers,
            "You repair malformed JSON for BRD generation. Return only valid JSON with all required keys populated.",
            repair_prompt,
        )
        payload_json = _extract_json_object(repaired)

    markdown = _render_brd_from_payload(filename, payload_json)
    if _is_complete_brd(markdown):
        return markdown

    missing_markers = _missing_brd_markers(markdown)
    repaired_markdown = await _request_llm_content(
        endpoint,
        headers,
        "You repair incomplete BRDs. Return only polished Markdown with the exact required section structure.",
        _build_brd_repair_prompt(filename, text, markdown, missing_markers),
    )
    if _is_complete_brd(repaired_markdown):
        return repaired_markdown

    direct_markdown = await _request_llm_content(
        endpoint,
        headers,
        "You write complete enterprise BRDs in Markdown. Return only Markdown with the exact required heading structure.",
        _build_brd_markdown_prompt(filename, text),
    )
    if _is_complete_brd(direct_markdown):
        return direct_markdown

    candidate = direct_markdown or repaired_markdown or markdown
    missing = ", ".join(_missing_brd_markers(candidate)) or "unknown structure issue"
    raise RuntimeError(f"Rendered BRD is incomplete after JSON generation: {missing}")


def _mom_item_to_str(item) -> str:
    """Convert a MOM item (str or dict) to a human-readable string."""
    if isinstance(item, str):
        # Guard: if it looks like a Python repr dict, parse it
        stripped = item.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                import ast as _ast
                parsed = _ast.literal_eval(stripped)
                if isinstance(parsed, dict):
                    return _mom_item_to_str(parsed)
            except Exception:
                pass
        return item
    if isinstance(item, dict):
        topic = item.get("topic", "")
        summary = item.get("discussion_summary", "") or item.get("decisions", "")
        owner = item.get("owner", "")
        parts = [p for p in [topic, summary] if p]
        text = ": ".join(parts) if len(parts) > 1 else (parts[0] if parts else str(item))
        if owner:
            text += f" (Owner: {owner})"
        return text
    return str(item)


def _build_text_speaker_map(transcript: str) -> dict[str, str]:
    speaker_map: dict[str, str] = {}
    current_speaker = None
    current_lines: list[str] = []
    label_pattern = re.compile(r'^\[?([A-Z][a-z]+(?: [A-Z][a-z]+)?)\]?\s*:\s*(.*)$')

    def _flush() -> None:
        nonlocal current_speaker, current_lines
        if current_speaker and current_lines:
            text = " ".join(part for part in current_lines if part).strip()
            if text:
                speaker_map[current_speaker] = (
                    f"{speaker_map[current_speaker]} {text}".strip()
                    if current_speaker in speaker_map
                    else text
                )
        current_speaker = None
        current_lines = []

    for raw_line in str(transcript or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = label_pattern.match(line)
        if match:
            _flush()
            current_speaker = match.group(1).strip()
            body = match.group(2).strip()
            current_lines = [body] if body else []
            continue
        if current_speaker:
            current_lines.append(line)
        else:
            current_speaker = "Speaker 1"
            current_lines = [line]

    _flush()
    return speaker_map or {"Speaker 1": str(transcript or "").strip()}


def _normalize_speaker_map(raw_payload) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    metadata_keys = {"error", "code", "language_code", "request_id"}

    def _ingest(entry):
        if not isinstance(entry, dict):
            return
        for key, value in entry.items():
            if str(key or "").strip().lower() in metadata_keys:
                continue
            text = str(value or "").strip()
            if not text:
                continue
            speaker = str(key).strip()
            cleaned[speaker] = (f"{cleaned[speaker]} {text}".strip()
                                if speaker in cleaned else text)

    if isinstance(raw_payload, list):
        for entry in raw_payload:
            _ingest(entry)
    else:
        _ingest(raw_payload)
    return cleaned


def _normalize_sarvam_speaker_label(label: str) -> str:
    raw = str(label or "").strip().replace("_", " ")
    match = re.fullmatch(r"(?i)speaker\s*([0-9]+)", raw)
    if match:
        return f"Speaker {match.group(1)}"
    if raw.isdigit():
        return f"Speaker {int(raw) + 1}"
    return raw or "Speaker 1"


def _speaker_map_from_sarvam_payload(payload) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}

    diarized = payload.get("diarized_transcript")
    entries = diarized.get("entries") if isinstance(diarized, dict) else None
    speaker_map: dict[str, str] = {}

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            speaker = _normalize_sarvam_speaker_label(
                entry.get("speaker_id") or entry.get("speaker") or entry.get("speaker_label")
            )
            text = str(entry.get("transcript") or entry.get("text") or "").strip()
            if not text:
                continue
            speaker_map[speaker] = f"{speaker_map.get(speaker, '')} {text}".strip()

    segments = payload.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            speaker = _normalize_sarvam_speaker_label(
                segment.get("speaker") or segment.get("speaker_id") or segment.get("speaker_label")
            )
            text = str(segment.get("text") or segment.get("transcript") or "").strip()
            if not text:
                continue
            speaker_map[speaker] = f"{speaker_map.get(speaker, '')} {text}".strip()

    if speaker_map:
        return speaker_map

    transcript = str(payload.get("transcript") or "").strip()
    return _build_text_speaker_map(transcript) if transcript else {}


def _extract_sarvam_output_files(status_payload: dict) -> list[str]:
    file_names: list[str] = []
    for detail in status_payload.get("job_details") or []:
        if not isinstance(detail, dict):
            continue
        for output in detail.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            file_name = str(output.get("file_name") or "").strip()
            if file_name:
                file_names.append(file_name)
    return file_names


async def _download_sarvam_output_payloads(
    client: httpx.AsyncClient,
    headers: dict,
    job_id: str,
    file_names: list[str],
) -> list[dict]:
    if not file_names:
        return []

    download_response = await _sarvam_request_with_retry(
        client,
        "POST",
        SARVAM_BATCH_DOWNLOAD_URL,
        headers={**headers, "Content-Type": "application/json"},
        json={"job_id": job_id, "files": file_names},
        timeout=30.0,
    )
    download_payload = download_response.json()
    download_urls = download_payload.get("download_urls") or {}
    if not isinstance(download_urls, dict):
        return []

    payloads: list[dict] = []
    for file_name in file_names:
        details = download_urls.get(file_name) or {}
        if not isinstance(details, dict):
            continue
        file_url = details.get("file_url")
        if not file_url:
            continue
        try:
            payload = await asyncio.to_thread(_read_json_from_signed_url, file_url)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)

    return payloads


def _upload_bytes_to_signed_url(url: str, content: bytes, content_type: str) -> None:
    request = Request(
        url,
        data=content,
        method="PUT",
        headers={
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type or "application/octet-stream",
        },
    )
    with urlopen(request, timeout=600) as response:
        status = getattr(response, "status", None) or response.getcode()
        if status not in {200, 201}:
            raise RuntimeError(f"Signed upload failed with HTTP {status}")


def _read_json_from_signed_url(url: str) -> dict:
    request = Request(url, method="GET")
    with urlopen(request, timeout=60) as response:
        return httpx.Response(200, content=response.read()).json()


async def _transcribe_audio_with_sarvam_batch(filename: str, content: bytes, content_type: str) -> dict[str, str]:
    if not SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY is not configured")

    headers = {"api-subscription-key": SARVAM_API_KEY}
    job_filename = os.path.basename(filename or f"audio-{int(time.time())}.mp3")

    async with httpx.AsyncClient(follow_redirects=True) as client:
        init_response = await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_INIT_URL,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "job_parameters": {
                    "model": SARVAM_BATCH_MODEL,
                    "mode": SARVAM_BATCH_MODE,
                    "language_code": SARVAM_BATCH_LANGUAGE,
                    "with_diarization": True,
                    "with_timestamps": True,
                }
            },
            timeout=30.0,
        )
        init_payload = init_response.json()

        job_id = str(init_payload.get("job_id") or "").strip()
        if not job_id:
            raise RuntimeError("Sarvam batch init response is missing job_id")

        upload_links_response = await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_UPLOAD_URL,
            headers={**headers, "Content-Type": "application/json"},
            json={"job_id": job_id, "files": [job_filename]},
            timeout=30.0,
        )
        upload_links_payload = upload_links_response.json()
        upload_urls = upload_links_payload.get("upload_urls") or {}
        upload_details = upload_urls.get(job_filename) if isinstance(upload_urls, dict) else None
        upload_url = upload_details.get("file_url") if isinstance(upload_details, dict) else None
        if not upload_url:
            raise RuntimeError("Sarvam batch upload URL was not returned for the audio file")

        await asyncio.to_thread(_upload_bytes_to_signed_url, upload_url, content, content_type)

        await _sarvam_request_with_retry(
            client,
            "POST",
            SARVAM_BATCH_START_URL.format(job_id=job_id),
            headers={**headers, "Content-Type": "application/json"},
            json={},
            timeout=30.0,
        )

        await asyncio.sleep(SARVAM_BATCH_INITIAL_WAIT_SECONDS)
        deadline = time.monotonic() + SARVAM_BATCH_MAX_WAIT_SECONDS

        while True:
            status_response = await _sarvam_request_with_retry(
                client,
                "GET",
                SARVAM_BATCH_STATUS_URL.format(job_id=job_id),
                headers=headers,
                timeout=30.0,
            )
            status_payload = status_response.json()

            state = str(status_payload.get("job_state") or status_payload.get("status") or "").strip().lower()
            if state == "completed":
                speaker_map = _speaker_map_from_sarvam_payload(status_payload)
                if speaker_map:
                    return speaker_map

                output_payloads = await _download_sarvam_output_payloads(
                    client,
                    headers,
                    job_id,
                    _extract_sarvam_output_files(status_payload),
                )
                for output_payload in output_payloads:
                    speaker_map = _speaker_map_from_sarvam_payload(output_payload)
                    if speaker_map:
                        return speaker_map

                raise RuntimeError("Sarvam batch completed but returned no speaker transcript")

            if state in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(str(status_payload.get("error") or status_payload))

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Sarvam batch transcription timed out after {SARVAM_BATCH_MAX_WAIT_SECONDS} seconds")

            await asyncio.sleep(SARVAM_BATCH_POLL_INTERVAL_SECONDS)


def _speaker_map_to_transcript(speaker_map: dict[str, str]) -> str:
    return "\n".join(f"{speaker}: {text}" for speaker, text in speaker_map.items() if str(text or "").strip())


def _guess_owner(sentence: str) -> str | None:
    speaker_match = re.match(r'^\[?([A-Z][a-z]+(?: [A-Z][a-z]+)?)\]?\s*:\s*(.*)$', sentence)
    if speaker_match:
        speaker = speaker_match.group(1).strip()
        body = speaker_match.group(2).strip()
        direct_target = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,', body)
        if direct_target:
            return direct_target.group(1).strip()
        if re.search(r"\b(i|i'll|i will|main|mai)\b", body, re.IGNORECASE):
            return speaker
        return speaker

    direct_target = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,', sentence)
    if direct_target:
        return direct_target.group(1).strip()

    said_subject = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+said\b', sentence, re.IGNORECASE)
    if said_subject:
        return said_subject.group(1).strip()

    leading_name = re.match(r'^([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b', sentence)
    return leading_name.group(1).strip() if leading_name else None


def _extract_deadline_hint(sentence: str) -> str | None:
    match = re.search(
        r'\b(kal tak|kal|aaj|aaj tak|shaam tak|subah tak|today|tomorrow|this evening|tonight|next week|'
        r'by friday|by thursday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
        r'\d{1,2}\s*(?:baje|am|pm)|\d{4}-\d{2}-\d{2})\b',
        sentence,
        re.IGNORECASE,
    )
    return match.group(0).strip() if match else None


def _topic_from_sentence(sentence: str) -> str:
    body = re.sub(r'^\[?[A-Z][a-z]+(?: [A-Z][a-z]+)?\]?\s*:\s*', '', sentence).strip()
    words = re.findall(r'[A-Za-z0-9]+', body)[:6]
    return " ".join(words).title() if words else "Meeting Action"


def _build_summary_text(mom_items: list) -> str:
    return "\n".join(f"- {_mom_item_to_str(item)}" for item in mom_items) if mom_items else "No summary extracted."


def _error_text(exc: Exception, fallback: str) -> str:
    message = str(exc or "").strip()
    if message:
        return message
    return f"{fallback} ({exc.__class__.__name__})"


_YYYY_MM_DD_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _fix_past_year_date(value: str, reference_date: datetime | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    reference = reference_date or datetime.now()
    match = _YYYY_MM_DD_RE.search(text)
    if not match:
        return text

    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year >= reference.year:
        return text

    try:
        candidate = datetime(reference.year, month, day)
        if candidate.date() < reference.date():
            candidate = datetime(reference.year + 1, month, day)
    except ValueError:
        return text

    normalized = candidate.strftime("%Y-%m-%d")
    return text[:match.start()] + normalized + text[match.end():]


def _normalize_structured_dates(result: dict) -> dict:
    normalized = dict(result or {})
    tasks = []
    for item in normalized.get("Task", []) if isinstance(normalized.get("Task"), list) else []:
        if not isinstance(item, dict):
            tasks.append(item)
            continue
        updated = dict(item)
        for key in ("edd", "due_date", "deadline", "start_date"):
            if updated.get(key):
                updated[key] = _fix_past_year_date(updated[key])
        tasks.append(updated)
    if tasks:
        normalized["Task"] = tasks

    calendar = []
    for item in normalized.get("calender", []) if isinstance(normalized.get("calender"), list) else []:
        if not isinstance(item, dict):
            calendar.append(item)
            continue
        updated = dict(item)
        for key in ("event_date", "date", "time", "start_time"):
            if updated.get(key):
                updated[key] = _fix_past_year_date(updated[key])
        calendar.append(updated)
    if calendar:
        normalized["calender"] = calendar

    return normalized


def _fallback_structured_result(transcript: str) -> dict:
    sentences = [segment.strip() for segment in re.split(r'(?<=[.!?])\s+|\n+', str(transcript or '')) if segment.strip()]
    action_pattern = re.compile(
        r'\b(will|needs? to|should|must|going to|has to|agreed to|committed to|please|review|share|send|update|schedule|set|call|approve|kar do|karna hai|bhej|set kar|review kar|chahiye)\b',
        re.IGNORECASE,
    )

    actionable = []
    seen = set()
    for sentence in sentences:
        key = re.sub(r'\s+', ' ', sentence).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        if action_pattern.search(sentence):
            actionable.append(sentence)

    source_sentences = actionable or sentences[:4]
    mom_items = []
    tasks = []
    calendar = []

    for index, sentence in enumerate(source_sentences[:6], start=1):
        owner = _guess_owner(sentence)
        deadline = _extract_deadline_hint(sentence)
        topic = _topic_from_sentence(sentence)
        clean_sentence = re.sub(r'^\[?[A-Z][a-z]+(?: [A-Z][a-z]+)?\]?\s*:\s*', '', sentence).strip()
        mom_items.append({
            "topic": topic,
            "discussion_summary": clean_sentence,
            "decisions": "",
            "owner": owner or "",
        })
        tasks.append({
            "task_title": topic,
            "description": clean_sentence,
            "category": "OTHER",
            "priority": "High" if deadline else "Medium",
            "edd": deadline,
            "owner": owner,
        })
        if re.search(r'\b(schedule|set|call|callback|meeting|review)\b', sentence, re.IGNORECASE):
            calendar.append({
                "event_title": topic,
                "event_type": "Meeting",
                "event_date": deadline or "Follow-up required",
                "participants": [owner] if owner else [],
                "notes": clean_sentence,
            })

    return {
        "success": True,
        "summary": _build_summary_text(mom_items),
        "tasks": tasks,
        "calendar": calendar,
        "MOM": mom_items,
        "raw": {"fallback": True},
    }


def _normalize_summary_payload(result: dict, transcript: str) -> dict:
    if not isinstance(result, dict):
        raise ValueError("AISummarization returned an invalid payload")

    result = _normalize_structured_dates(result)

    mom = result.get("MOM", []) if isinstance(result.get("MOM", []), list) else []
    tasks = result.get("Task", []) if isinstance(result.get("Task", []), list) else []
    calendar = result.get("calender", []) if isinstance(result.get("calender", []), list) else []
    if not mom and not tasks and not calendar:
        raise ValueError("AISummarization returned no MOM, tasks, or calendar events")

    return {
        "success": True,
        "summary": _build_summary_text(mom),
        "tasks": tasks,
        "calendar": calendar,
        "MOM": mom,
        "raw": result,
    }


def _summarization_result_or_fallback(response: httpx.Response, transcript: str) -> dict:
    if response.status_code == 200:
        data = response.json()
        result = data[0] if isinstance(data, list) and len(data) > 0 else data
        try:
            return _normalize_summary_payload(result, transcript)
        except Exception as exc:
            logger.warning("AISummarization payload invalid; using transcript fallback: %s", exc)
    else:
        logger.warning("AISummarization returned status %s; using transcript fallback", response.status_code)

    fallback = _fallback_structured_result(transcript)
    fallback["warning"] = f"AISummarization unavailable; used transcript-derived extraction instead."
    return fallback

# N8N Webhooks — Core Features
# UPDATE_BRD: Updates an existing BRD via GET with ?filename=<slug>&summary=<text>
N8N_WEBHOOK_UPDATE_BRD = os.getenv("N8N_WEBHOOK_UPDATE_BRD", "https://n8n.backend.lehana.in/webhook/update-brd")
# NEW_BRD: Creates a new BRD via POST with {filename, text}
N8N_WEBHOOK_NEW_BRD = os.getenv("N8N_WEBHOOK_NEW_BRD", "https://n8n.backend.lehana.in/webhook/new-brd")
# LIST_BRDS: Lists BRDs via GET, optional ?filename=<slug> to check specific file
# Response includes {id, name, preview} for each BRD — preview is a Google Docs URL
N8N_WEBHOOK_LIST_BRDS = os.getenv("N8N_WEBHOOK_LIST_BRDS", "https://n8n.backend.lehana.in/webhook/list-brds")
# TRANSCRIBE_AUDIO: Audio file → speaker-separated transcript text
N8N_WEBHOOK_TRANSCRIBE_AUDIO = os.getenv("N8N_WEBHOOK_TRANSCRIBE_AUDIO", "https://imworkflow.intermesh.net/webhook/transcribe-speakers")
# AI_SUMMARIZATION: Speaker transcript → MOM + Tasks + Calendar events
N8N_WEBHOOK_AI_SUMMARIZATION = os.getenv("N8N_WEBHOOK_AI_SUMMARIZATION", "https://imworkflow.intermesh.net/webhook/AISummarization")
# GOOGLE_TOOLS: Trigger Google Calendar events, email MOM to recipients
N8N_WEBHOOK_GOOGLE_TOOLS = os.getenv("N8N_WEBHOOK_GOOGLE_TOOLS", "https://n8n.backend.lehana.in/webhook/google_tool_event")

# Phase 2 Webhooks
N8N_WEBHOOK_DASHBOARD_DATA = os.getenv("N8N_WEBHOOK_DASHBOARD_DATA", "https://n8n.backend.lehana.in/webhook/dashboard-data")
N8N_WEBHOOK_CONFLICT_DETECTION = os.getenv("N8N_WEBHOOK_CONFLICT_DETECTION", "https://n8n.backend.lehana.in/webhook/conflict-detection")
N8N_WEBHOOK_KNOWLEDGE_GRAPH = os.getenv("N8N_WEBHOOK_KNOWLEDGE_GRAPH", "https://n8n.backend.lehana.in/webhook/knowledge-graph")
N8N_WEBHOOK_SLACK_INTEGRATION = os.getenv("N8N_WEBHOOK_SLACK_INTEGRATION", "https://n8n.backend.lehana.in/webhook/slack-integration")
N8N_WEBHOOK_GMAIL_INTEGRATION = os.getenv("N8N_WEBHOOK_GMAIL_INTEGRATION", "https://n8n.backend.lehana.in/webhook/gmail-integration")
N8N_WEBHOOK_GENERATE_BRD = os.getenv("N8N_WEBHOOK_GENERATE_BRD_FROM_EMAIL", "https://n8n.backend.lehana.in/webhook/generate-brd-from-email")
MEETING_MASTER_API_BASE = os.getenv("MEETING_MASTER_API_BASE", "http://127.0.0.1:5098/api/v1")
MEETING_MASTER_DASHBOARD_DEVICE_ID = os.getenv("MEETING_MASTER_DASHBOARD_DEVICE_ID", "requirewise-dashboard")

# OpenProject Configuration — Fetches work packages from a connected OpenProject instance
# OPENPROJECT_API_URL: Base URL of the OpenProject instance (e.g., https://project.example.com)
# OPENPROJECT_API_KEY: API token for authentication (Basic auth with 'apikey' as username)
# OPENPROJECT_PROJECT: Project identifier/slug in OpenProject
# OPENPROJECT_TICKET_TYPE: (Optional) Work package type ID to filter by
OPENPROJECT_API_URL = os.getenv("OPENPROJECT_API_URL", "")
OPENPROJECT_API_KEY = os.getenv("OPENPROJECT_API_KEY", "")
OPENPROJECT_PROJECT = os.getenv("OPENPROJECT_PROJECT", "")
OPENPROJECT_TICKET_TYPE = os.getenv("OPENPROJECT_TICKET_TYPE", "")

class UpdateBRDRequest(BaseModel):
    filename: str = ""  # lowercase-hyphen slug of BRD name; empty = detect automatically
    summary: str = ""

class NewBRDRequest(BaseModel):
    filename: str  # lowercase-hyphen slug (e.g., "my-project-brd")
    text: str      # prompt/content for BRD generation
    search_query: str = ""

class TranscriptRequest(BaseModel):
    transcript: str

class TaskAssignRequest(BaseModel):
    summary: str

class GoogleToolsRequest(BaseModel):
    """Trigger Google Calendar events and email MOM to recipients."""
    recipients: list[str] = []
    calender: list[dict] = []    # [{title, time}] — field name matches real n8n API (their typo)
    Task: list[dict | str] = []
    MOM: list[dict | str] = []

class DashboardRequest(BaseModel):
    project: str

class IntegrationRequest(BaseModel):
    project: str
    source: str # 'slack' or 'gmail'

class GenerateBRDRequest(BaseModel):
    email_id: str
    transcript: str
    title: str = ""
    search_query: str = ""


async def _fetch_brds_snapshot() -> list[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.get(N8N_WEBHOOK_LIST_BRDS, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("brds"), list):
            return data["brds"]
        return [data] if data else []


async def _get_meeting_master_headers(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        f"{MEETING_MASTER_API_BASE}/auth/guest",
        json={"device_id": MEETING_MASTER_DASHBOARD_DEVICE_ID, "device_name": "RequireWise Dashboard"},
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Meeting Master guest auth did not return an access token")
    return {"Authorization": f"Bearer {token}"}


def _severity_from_meeting(meeting: dict) -> str:
    kpis = meeting.get("kpis") or {}
    ehi = float(kpis.get("execution_health_index") or 0)
    leakage = float(kpis.get("action_leakage_rate") or 0)
    missing_count = len(kpis.get("missing_fields") or [])
    if ehi < 40 or leakage >= 75 or missing_count >= 3:
        return "Critical"
    if ehi < 60 or leakage >= 50 or missing_count >= 2:
        return "High"
    if ehi < 75 or leakage >= 30 or missing_count >= 1:
        return "Medium"
    return "Low"


def _meeting_activity_items(meetings: list[dict]) -> list[dict]:
    items = []
    for meeting in meetings[:6]:
        kpis = meeting.get("kpis") or {}
        automation = meeting.get("automation") or {}
        items.append({
            "icon": "📈",
            "text": f"{meeting.get('title') or 'Meeting'} processed with EHI {round(float(kpis.get('execution_health_index') or 0))}",
            "time": str(meeting.get("processed_at") or meeting.get("date") or "recently"),
            "color": "blue",
        })
        if automation.get("dispatch_success"):
            items.append({
                "icon": "✉️",
                "text": f"Auto follow-up sent to {len(automation.get('recipients') or [])} recipients",
                "time": str(automation.get("dispatched_at") or meeting.get("processed_at") or "recently"),
                "color": "green",
            })
    return items[:8]


def _business_signals(overview: dict) -> list[dict]:
    return [
        {"name": "Execution Discipline", "role": "Operations", "sentiment": round(float(overview.get("execution_health_index") or 0)), "color": "#60a5fa"},
        {"name": "Context Quality", "role": "Business Analysis", "sentiment": round(float(overview.get("context_completeness_score") or 0)), "color": "#34d399"},
        {"name": "Automation Readiness", "role": "Productivity", "sentiment": round(float(overview.get("automation_coverage") or 0)), "color": "#f59e0b"},
        {"name": "Closure Momentum", "role": "Execution", "sentiment": round(float(overview.get("closure_rate") or 0)), "color": "#a78bfa"},
    ]


async def _fetch_execution_dashboard(project: str) -> dict:
    brds = []
    try:
        brds = await _fetch_brds_snapshot()
    except Exception:
        brds = []

    async with httpx.AsyncClient() as client:
        try:
            overview_response = await client.get(f"{MEETING_MASTER_API_BASE}/kpis/business-overview", timeout=30.0)
            overview_response.raise_for_status()
            overview_payload = overview_response.json()
            overview = overview_payload.get("overview", {})
            meetings = overview_payload.get("meetings", [])[:6]
        except Exception as exc:
            return {
                "project_name": project,
                "metrics": {
                    "execution_health": 0,
                    "context_completeness": 0,
                    "automation_coverage": 0,
                    "brd_count": len(brds),
                },
                "recent_activity": [{"icon": "⚠️", "text": f"Meeting Master unavailable: {exc}", "time": "just now", "color": "red"}],
                "data_sources": [
                    {"label": "Processed Meetings", "count": 0, "icon": "🎙️", "status": "unavailable"},
                    {"label": "Auto Emails", "count": 0, "icon": "✉️", "status": "unavailable"},
                    {"label": "Tasks Extracted", "count": 0, "icon": "✅", "status": "unavailable"},
                    {"label": "BRDs Available", "count": len(brds), "icon": "📄", "status": "live"},
                ],
                "business_signals": [],
                "conflicts": [],
                "meetings": [],
            }

    task_total = sum(len(meeting.get("tasks") or []) for meeting in meetings)
    auto_emails = sum(1 for meeting in meetings if (meeting.get("automation") or {}).get("dispatch_success"))
    conflicts = []
    for meeting in meetings:
        kpis = meeting.get("kpis") or {}
        missing_fields = kpis.get("missing_fields") or []
        leakage = round(float(kpis.get("action_leakage_rate") or 0), 1)
        ehi = round(float(kpis.get("execution_health_index") or 0), 1)
        automation = meeting.get("automation") or {}
        if ehi >= 75 and leakage < 30 and not missing_fields and automation.get("dispatch_success"):
            continue
        conflicts.append({
            "type": "Execution",
            "severity": _severity_from_meeting(meeting),
            "status": "Open" if missing_fields or not automation.get("dispatch_success") else "In Review",
            "title": meeting.get("title") or "Untitled meeting",
            "description": f"Execution Health Index {ehi}, action leakage {leakage}%, missing fields: {', '.join(missing_fields) or 'none'}.",
            "createdAt": str(meeting.get("processed_at") or meeting.get("date") or datetime.utcnow().isoformat()),
            "sources": [
                {"type": "Meeting", "from": meeting.get("title") or "Meeting", "date": str(meeting.get("date") or ""), "excerpt": meeting.get("summary") or "No summary available"},
                {"type": "KPI", "from": "Execution dashboard", "date": str(kpis.get("generated_at") or ""), "excerpt": f"EHI {ehi}, context {kpis.get('context_completeness_score', 0)}%, automation {automation.get('dispatch_success', False)}"},
            ],
            "suggestions": [
                "Assign owners to all tasks before sharing the BRD" if "task_owner" in missing_fields else "Validate action items and owners with the meeting host",
                "Capture recipient emails to keep auto follow-up enabled" if "recipient_email" in missing_fields else "Use the MoM email as the approved follow-up baseline",
                "Map key discussion points into BRD requirements to reduce leakage" if leakage >= 40 else "Link this meeting to a BRD update while context is still fresh",
            ],
        })

    return {
        "project_name": project,
        "metrics": {
            "execution_health": round(float(overview.get("execution_health_index") or 0)),
            "context_completeness": round(float(overview.get("context_completeness_score") or 0)),
            "automation_coverage": round(float(overview.get("automation_coverage") or 0)),
            "brd_count": len(brds),
            "processed_meetings": int(overview.get("processed_meetings") or 0),
            "high_risk_meetings": int(overview.get("high_risk_meetings") or 0),
            "action_leakage": round(float(overview.get("action_leakage_rate") or 0)),
            "closure_rate": round(float(overview.get("closure_rate") or 0)),
        },
        "recent_activity": _meeting_activity_items(meetings),
        "data_sources": [
            {"label": "Processed Meetings", "count": int(overview.get("processed_meetings") or 0), "icon": "🎙️", "status": "live"},
            {"label": "Auto Emails", "count": auto_emails, "icon": "✉️", "status": "live"},
            {"label": "Tasks Extracted", "count": task_total, "icon": "✅", "status": "live"},
            {"label": "BRDs Available", "count": len(brds), "icon": "📄", "status": "live"},
        ],
        "business_signals": _business_signals(overview),
        "conflicts": conflicts,
        "meetings": meetings,
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "brd-agent"}


# ---------------------------------------------------------------------------
# Translation — exposes the imllm LLM gateway as a small translation API so
# Meeting Master (and the frontend) can fill `transcript_en` from a raw
# non-English transcript without each app re-implementing the gateway call.
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    text: str
    target_language: str = "English"
    source_language: Optional[str] = None
    preserve_speaker_tags: bool = True


@app.post("/api/translate")
async def translate_text(request: TranslateRequest):
    """LLM-translate `text` to `target_language` with no embellishment.

    Returns: { success, translated, model, source_language?, warning? }.
    On failure returns success=False with the upstream error message so
    callers can surface a real reason instead of silently filling fake text.
    """
    text = (request.text or "").strip()
    if not text:
        return {"success": False, "error": "empty text", "translated": ""}

    if not BRD_AGENT_LLM_API_KEY:
        return {
            "success": False,
            "error": "BRD_AGENT_LLM_API_KEY is not configured",
            "translated": "",
        }

    speaker_rule = (
        "Keep any speaker label prefixes verbatim — including [Speaker N]:, "
        "Speaker N:, names followed by a colon, or square-bracket tags. "
        "Translate ONLY the spoken content after each tag."
        if request.preserve_speaker_tags
        else "Do not invent speaker labels."
    )

    user_instruction = (
        f"Translate the following transcript into {request.target_language}.\n"
        "Rules:\n"
        "- Translate the actual content of the transcript below — do NOT invent, "
        "summarize, paraphrase, or add new dialogue.\n"
        "- Keep the meaning faithful and the sentence order the same.\n"
        f"- {speaker_rule}\n"
        "- If a portion is already in the target language, leave it unchanged.\n"
        "- Return ONLY the translated transcript text. No preamble, no "
        "commentary, no markdown fences, no explanations.\n\n"
        f"=== TRANSCRIPT TO TRANSLATE ===\n{text}\n=== END TRANSCRIPT ==="
    )

    endpoint = _llm_chat_completions_url(BRD_AGENT_LLM_BASE_URL)
    headers = {
        "Authorization": f"Bearer {BRD_AGENT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": BRD_AGENT_LLM_MODEL,
        "temperature": 0.0,
        "max_tokens": min(8000, max(1000, int(len(text) * 2.5))),
        "messages": [
            {
                "role": "system",
                "content": "You are a faithful, literal translator. You translate the user-provided text exactly as written, preserving structure and speaker labels. You never invent new content.",
            },
            {"role": "user", "content": user_instruction},
        ],
    }

    try:
        # IMPORTANT: send the body with ensure_ascii=False so Devanagari /
        # Tamil / Telugu / etc characters arrive at the gateway as real UTF-8
        # codepoints, not \uXXXX escapes. The Intermesh gateway has been
        # observed to misread the escaped form as garbled placeholder chars
        # which causes the model to hallucinate a "best-effort" translation.
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers_utf8 = dict(headers)
        headers_utf8["Content-Type"] = "application/json; charset=utf-8"
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(endpoint, content=body, headers=headers_utf8)
            response.raise_for_status()
            result = response.json()
        translated = _repair_mojibake(_extract_message_content(result)).strip()
        return {
            "success": True,
            "translated": translated,
            "model": BRD_AGENT_LLM_MODEL,
            "target_language": request.target_language,
            "source_language": request.source_language,
        }
    except Exception as exc:
        logger.exception("translate endpoint failed")
        return {"success": False, "error": str(exc), "translated": ""}


# ---------------------------------------------------------------------------
# File search proxy — surfaces the Gemini File Search service so the meeting
# UI and the BRD UI can ingest documents/text and run RAG queries through
# this backend without exposing the upstream URL to every browser.
# ---------------------------------------------------------------------------

def _ensure_filesearch_configured() -> str:
    base = FILE_SEARCH_API_BASE
    if not base:
        raise HTTPException(
            status_code=503,
            detail="FILE_SEARCH_API_BASE is not configured on the server.",
        )
    return base


@app.get("/api/filesearch/status")
async def filesearch_status():
    base = FILE_SEARCH_API_BASE
    if not base:
        return {
            "success": False,
            "configured": False,
            "base_url": "",
            "error": "FILE_SEARCH_API_BASE is not configured",
        }
    try:
        async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
            info = await client.get(f"{base}/store-info")
            info.raise_for_status()
            store_info = info.json()
            docs = await client.get(f"{base}/documents")
            docs.raise_for_status()
            docs_payload = docs.json()
        return {
            "success": True,
            "configured": True,
            "base_url": base,
            "store": store_info,
            "documents_count": docs_payload.get("total", len(docs_payload.get("documents", []))),
        }
    except Exception as exc:
        logger.warning("filesearch status check failed: %s", exc)
        return {
            "success": False,
            "configured": True,
            "base_url": base,
            "error": str(exc),
        }


@app.get("/api/filesearch/documents")
async def filesearch_documents():
    base = _ensure_filesearch_configured()
    async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
        r = await client.get(f"{base}/documents")
        r.raise_for_status()
        return r.json()


class FileSearchQuery(BaseModel):
    query: str
    sessionId: Optional[str] = None


@app.post("/api/filesearch/search")
async def filesearch_search(req: FileSearchQuery):
    base = _ensure_filesearch_configured()
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    payload: Dict[str, Any] = {"query": req.query}
    if req.sessionId:
        payload["sessionId"] = req.sessionId
    try:
        async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{base}/search", json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"filesearch upstream returned {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class IngestTextRequest(BaseModel):
    title: str
    content: str
    topic: Optional[str] = None
    source: Optional[str] = "meeting-master-ingest"


@app.post("/api/filesearch/ingest-text")
async def filesearch_ingest_text(req: IngestTextRequest):
    """Wrap plain text (e.g. an email subject+body) as a virtual .txt file
    and POST it to Gemini File Search /index for indexing.
    """
    base = _ensure_filesearch_configured()
    content = (req.content or "").strip()
    title = (req.title or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "-", title).strip("-")[:80] or "ingested"
    filename = f"{safe_title}.txt"
    body_bytes = content.encode("utf-8")

    files = {"file": (filename, body_bytes, "text/plain; charset=utf-8")}
    data = {}
    if req.topic:
        data["topic"] = req.topic
    if req.source:
        data["source"] = req.source

    try:
        async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{base}/index", files=files, data=data)
            r.raise_for_status()
            try:
                return {"success": True, "filename": filename, "upstream": r.json()}
            except Exception:
                return {"success": True, "filename": filename, "upstream_text": r.text[:500]}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"filesearch /index returned {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/filesearch/ingest-file")
async def filesearch_ingest_file(file: UploadFile = File(...)):
    """Forward a multipart file upload to Gemini File Search /index."""
    base = _ensure_filesearch_configured()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    files = {"file": (file.filename or "upload.bin", content, file.content_type or "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=FILE_SEARCH_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{base}/index", files=files)
            r.raise_for_status()
            try:
                return {"success": True, "filename": file.filename, "upstream": r.json()}
            except Exception:
                return {"success": True, "filename": file.filename, "upstream_text": r.text[:500]}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"filesearch /index returned {exc.response.status_code}: {exc.response.text[:300]}",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/config")
async def get_frontend_config():
    return get_config()

@app.post("/api/update-brd")
async def update_brd(request: UpdateBRDRequest):
    """
    Calls the n8n update-brd webhook (GET method) with filename and summary as query params.
    If filename is empty, it is omitted so n8n can auto-detect.
    Example: GET /webhook/update-brd?filename=remote-automator&summary=buffalo
    """
    try:
        params = {}
        if request.filename:
            params["filename"] = request.filename
        if request.summary:
            params["summary"] = request.summary
        async with httpx.AsyncClient() as client:
            response = await client.get(
                N8N_WEBHOOK_UPDATE_BRD,
                params=params,
                timeout=60.0
            )
            if response.status_code != 200:
                print(f"Warning: update-brd returned {response.status_code}. Response: {response.text[:200]}")
                return {"success": False, "error": f"update-brd returned {response.status_code}"}
            # Webhook may return JSON or plain text (markdown) — handle both
            try:
                data = response.json()
            except Exception:
                # Plain text response — wrap as text field for the frontend
                data = {"text": response.text}
            return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/new-brd")
async def create_new_brd(request: NewBRDRequest):
    """Create a new BRD. Prefer the n8n workflow, but if it fails or returns
    a low-quality stub, generate the BRD through the configured LLM gateway.
    Do not silently downgrade to the old skeletal local template."""
    source_text = request.text or ""
    search_metadata = None
    search_warning = None
    try:
        source_text, search_metadata = await _augment_brd_text_with_file_search(
            request.filename,
            source_text,
            request.search_query,
        )
    except Exception as exc:
        search_warning = _error_text(exc, "File search context retrieval failed")

    webhook_text = ""
    webhook_error = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                N8N_WEBHOOK_NEW_BRD,
                json={"filename": request.filename, "text": source_text},
                timeout=120.0,
            )
        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, dict):
                    webhook_text = data.get("text") or ""
                elif isinstance(data, str):
                    webhook_text = data
            except Exception:
                webhook_text = response.text or ""
        else:
            webhook_error = f"n8n returned {response.status_code}"
    except Exception as exc:
        webhook_error = _error_text(exc, "n8n unreachable")

    if webhook_text.strip() and not _looks_like_low_quality_brd(webhook_text):
        _persist_local_brd(request.filename, webhook_text, "n8n")
        warning = _merge_warning_messages(search_warning)
        return {
            "success": True,
            "source": "n8n",
            "warning": warning or None,
            "context": search_metadata,
            "data": {"text": webhook_text, "filename": request.filename},
        }

    llm_warning = webhook_error
    if webhook_text.strip() and _looks_like_low_quality_brd(webhook_text):
        llm_warning = "n8n returned a low-quality BRD stub; upgraded via LLM."

    try:
        llm_markdown = await _generate_brd_with_llm(request.filename, source_text)
        _persist_local_brd(request.filename, llm_markdown, "llm-agent")
        return {
            "success": True,
            "source": "llm-agent",
            "warning": _merge_warning_messages(llm_warning, search_warning) or None,
            "context": search_metadata,
            "data": {"text": llm_markdown, "filename": request.filename},
        }
    except Exception as exc:
        return {
            "success": False,
            "source": "generation-failed",
            "error": _error_text(exc, "LLM BRD generation failed"),
            "warning": _merge_warning_messages(llm_warning, search_warning) or None,
            "context": search_metadata,
        }

@app.get("/api/list-brds")
async def list_brds(filename: str = ""):
    """
    Lists available BRDs by calling GET /webhook/list-brds.
    If filename is provided, checks for that specific BRD.
    Returns the raw response from n8n.
    """
    local_items = _filter_brd_inventory(_load_local_brd_cache(), filename)
    try:
        params = {}
        if filename:
            params["filename"] = filename
        async with httpx.AsyncClient() as client:
            response = await client.get(
                N8N_WEBHOOK_LIST_BRDS,
                params=params,
                timeout=30.0
            )
            if response.status_code != 200:
                print(f"Warning: list-brds returned {response.status_code}. Response: {response.text[:200]}")
                return {"success": True, "warning": f"list-brds returned {response.status_code}", "brds": local_items}
            data = response.json()
            # Normalize: ensure we always return a brds array
            if isinstance(data, list):
                remote_items = data
            elif isinstance(data, dict) and "brds" in data:
                remote_items = data["brds"]
            else:
                remote_items = [data] if data else []

            merged_items = _merge_brd_inventories(_filter_brd_inventory(remote_items, filename), local_items)
            return {"success": True, "brds": merged_items}
    except Exception as e:
        return {"success": True, "warning": str(e), "brds": local_items}

@app.post("/api/transcript-summary")
async def transcript_summary(request: TranscriptRequest):
    """
    Sends pasted transcript text to the AISummarization n8n workflow.
    The workflow returns MOM (minutes of meeting), Tasks, and Calendar events.
    We extract a human-readable summary from the MOM, tasks from Task, and calendar from calender.
    """
    try:
        payload = _build_text_speaker_map(request.transcript)
        transcript = _speaker_map_to_transcript(payload)
        async with httpx.AsyncClient() as client:
            response = await _post_json_with_retry(client, N8N_WEBHOOK_AI_SUMMARIZATION, payload, timeout=60.0)
            return _summarization_result_or_fallback(response, transcript)
    except Exception as e:
        return {"success": False, "error": _error_text(e, "Transcript summary failed")}

@app.post("/api/audio-summary")
async def audio_summary(audio: UploadFile = File(...)):
    """
    Two-step audio processing pipeline:
      Step 1: Send audio to transcribe-audio → get speaker-separated transcript
      Step 2: Send transcript to AISummarization → get MOM + Tasks + Calendar
    Returns both the raw transcript and the structured summary.
    """
    try:
        content = await audio.read()
        content_type = str(audio.content_type or "").strip().lower()

        if content_type and not content_type.startswith("audio/"):
            return {"success": False, "error": f"Unsupported upload type '{content_type}'. Please upload an audio recording."}

        if not content or len(content) < 256:
            return {"success": False, "error": "The uploaded recording is too small or invalid. Please retry with a real audio clip or paste the transcript manually."}

        async with httpx.AsyncClient() as client:
            # ── Step 1: Audio → Speaker Transcript ──
            speaker_map = await _transcribe_audio_with_sarvam_batch(
                audio.filename or "meeting-audio.mp3",
                content,
                audio.content_type or "audio/mpeg",
            )

            if not speaker_map:
                return {"success": False, "error": "No speaker data detected from the audio. Try clearer audio or paste the transcript manually."}

            # ── Step 2: Speaker Transcript → AI Summarization ──
            summarize_res = await _post_json_with_retry(client, N8N_WEBHOOK_AI_SUMMARIZATION, speaker_map, timeout=60.0)
            normalized = _summarization_result_or_fallback(summarize_res, _speaker_map_to_transcript(speaker_map))

            normalized["transcript"] = speaker_map
            return normalized
    except httpx.TimeoutException:
        return {"success": False, "error": "Audio transcription timed out. Please retry with a shorter or clearer recording."}
    except httpx.RequestError as e:
        return {"success": False, "error": _error_text(e, "Could not reach the audio transcription service")}
    except Exception as e:
        return {"success": False, "error": _error_text(e, "Audio processing failed")}

@app.post("/api/assign-tasks")
async def assign_tasks(request: TaskAssignRequest):
    """
    Sends the meeting summary to AISummarization to extract structured tasks and calendar events.
    Returns tasks, calendar events, and MOM items.
    """
    try:
        payload = _build_text_speaker_map(request.summary)
        transcript = _speaker_map_to_transcript(payload)
        async with httpx.AsyncClient() as client:
            response = await _post_json_with_retry(client, N8N_WEBHOOK_AI_SUMMARIZATION, payload, timeout=60.0)
            normalized = _summarization_result_or_fallback(response, transcript)
            return {
                "success": True,
                "tasks": normalized.get("tasks", []),
                "calendar": normalized.get("calendar", []),
                "MOM": normalized.get("MOM", []),
                "raw": normalized.get("raw", {}),
            }
    except Exception as e:
        return {"success": False, "error": _error_text(e, "Task extraction failed")}

@app.post("/api/google-tools")
async def trigger_google_tools(request: GoogleToolsRequest):
    """
    Triggers Google Workspace integrations: schedule Calendar events,
    log tasks, and email MOM to all recipients.
    Uses the google_tool_event n8n workflow.
    """
    try:
        payload = {
            "recipients": request.recipients,
            "calender": request.calender,
            "Task": request.Task,
            "MOM": request.MOM
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                N8N_WEBHOOK_GOOGLE_TOOLS,
                json=payload,
                timeout=60.0
            )
            if response.status_code != 200:
                return {"success": False, "error": f"Google Tools returned {response.status_code}: {response.text[:500]}"}
            data = response.json()
            return {"success": True, "message": data.get("message", "Events logged and emails sent successfully.")}
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- Phase 2 Endpoints ---

@app.post("/api/dashboard-data")
async def get_dashboard_data(request: DashboardRequest):
    data = await _fetch_execution_dashboard(request.project)
    return {"success": True, "data": data}

@app.post("/api/conflict-detection")
async def detect_conflicts(request: DashboardRequest):
    data = await _fetch_execution_dashboard(request.project)
    return {"success": True, "conflicts": data.get("conflicts", [])}

def _build_local_knowledge_graph(project: str) -> dict:
    """Build a knowledge graph from live Meeting Master data.

    Pulls the workspace KPI overview, extracts entities (people, projects,
    tasks, meetings, recipients) and relationships from the stored meetings.
    Deterministic — no LLM call, no n8n dependency.
    """
    import re as _re
    nodes_index = {}
    edges = []

    def _add_node(node_id, label, group):
        if node_id and node_id not in nodes_index:
            nodes_index[node_id] = {"id": node_id, "label": label, "group": group}

    def _add_edge(src, dst, rel):
        if src and dst and src != dst:
            edges.append({"source": src, "target": dst, "label": rel})

    project_node = f"project:{project or 'Workspace'}"
    _add_node(project_node, project or "Workspace", "project")

    try:
        meeting_api = os.getenv("MEETING_MASTER_API_BASE", "http://127.0.0.1:5098/api/v1")
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{meeting_api}/kpis/business-overview?limit=25")
            workspace = r.json() if r.status_code == 200 else {"meetings": []}
    except Exception:
        workspace = {"meetings": []}

    for meeting in workspace.get("meetings", []) or []:
        if not isinstance(meeting, dict):
            continue
        m_id = f"meeting:{meeting.get('meeting_id', '?')}"
        m_label = meeting.get("title") or "Untitled meeting"
        _add_node(m_id, m_label, "meeting")
        _add_edge(project_node, m_id, "includes")

        for attendee in (meeting.get("attendees") or []):
            if not isinstance(attendee, dict):
                continue
            email = attendee.get("email") or ""
            name = attendee.get("name") or email or ""
            if not name:
                continue
            p_id = f"person:{email or name}"
            _add_node(p_id, name, "person")
            _add_edge(m_id, p_id, "attended_by")

        for task in (meeting.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            t_title = task.get("title") or "Task"
            t_id = f"task:{m_id}:{t_title[:30]}"
            _add_node(t_id, t_title, "task")
            _add_edge(m_id, t_id, "produces")
            assignee = task.get("assignee")
            if assignee:
                p_id = f"person:{assignee}"
                _add_node(p_id, assignee, "person")
                _add_edge(t_id, p_id, "owned_by")

        for event in (meeting.get("calendar_events") or []):
            if not isinstance(event, dict):
                continue
            e_title = event.get("title") or "Event"
            e_id = f"event:{m_id}:{e_title[:30]}"
            _add_node(e_id, e_title, "event")
            _add_edge(m_id, e_id, "schedules")

    return {"nodes": list(nodes_index.values()), "edges": edges}


@app.post("/api/knowledge-graph")
async def get_knowledge_graph(request: DashboardRequest):
    """Try the n8n workflow first; fall back to a deterministic local graph
    derived from stored meetings."""
    webhook_error = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                N8N_WEBHOOK_KNOWLEDGE_GRAPH,
                json={"project": request.project},
                timeout=30.0,
            )
        if response.status_code == 200:
            try:
                payload = response.json()
                graph = payload.get("graph", {}) if isinstance(payload, dict) else {}
                if (graph.get("nodes") or graph.get("edges")):
                    return {"success": True, "source": "n8n", "graph": graph}
            except Exception:
                pass
        else:
            webhook_error = f"n8n returned {response.status_code}"
    except Exception as exc:
        webhook_error = _error_text(exc, "n8n unreachable")

    graph = _build_local_knowledge_graph(request.project)
    return {
        "success": True,
        "source": "local-fallback",
        "warning": webhook_error or "n8n knowledge-graph workflow unavailable; built locally from meeting data.",
        "graph": graph,
    }

@app.post("/api/trigger-integration")
async def trigger_integration(request: IntegrationRequest):
    """Try the n8n integration workflow first; on 404/error fall back to a
    deterministic local digest summary built from Meeting Master data so the
    UI gets a meaningful response instead of an error toast."""
    webhook_url = N8N_WEBHOOK_SLACK_INTEGRATION if request.source == 'slack' else N8N_WEBHOOK_GMAIL_INTEGRATION
    webhook_error = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json={"project": request.project},
                timeout=30.0,
            )
        if response.status_code == 200:
            try:
                payload = response.json() if response.content else {}
            except Exception:
                payload = {}
            return {"success": True, "source": "n8n",
                    "message": payload.get("message", f"{request.source.title()} integration triggered.")}
        webhook_error = f"n8n returned {response.status_code}"
    except Exception as exc:
        webhook_error = _error_text(exc, "n8n unreachable")

    # Local fallback — build a digest of recent meetings to "send" via this channel.
    digest_items = []
    try:
        meeting_api = os.getenv("MEETING_MASTER_API_BASE", "http://127.0.0.1:5098/api/v1")
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{meeting_api}/kpis/business-overview?limit=5")
            if r.status_code == 200:
                for m in (r.json().get("meetings") or [])[:5]:
                    digest_items.append({
                        "title": m.get("title"),
                        "summary": (m.get("summary") or "")[:120],
                        "ehi": (m.get("kpis") or {}).get("execution_health_index"),
                    })
    except Exception:
        pass

    channel = "#requirewise-digest" if request.source == "slack" else f"digest-{request.project}@indiamart.com"
    return {
        "success": True,
        "source": "local-fallback",
        "warning": webhook_error or "n8n integration workflow unavailable; generated local digest preview.",
        "message": f"{request.source.title()} digest prepared for {request.project} ({len(digest_items)} recent meetings)",
        "preview": {
            "channel": channel,
            "items": digest_items or [{"note": "No recent meetings in workspace"}],
        },
    }

def _build_brd_from_email_text(title: str, email_text: str) -> dict:
    """Parse a plain-email body into a structured BRD locally."""
    import re as _re
    lines = [l.strip() for l in (email_text or "").splitlines() if l.strip()]
    text = "\n".join(lines)
    title = title or "BRD from email"

    def _extract_block(*keywords):
        for kw in keywords:
            m = _re.search(rf"(?im)^\s*(?:{kw})[:\s]*$", text)
            if m:
                start = m.end()
                tail = text[start:start+1200]
                stop = _re.search(r"\n\s*[A-Z][A-Za-z ]{2,40}:\s*\n", tail)
                return tail[:stop.start()].strip() if stop else tail.strip()
        return ""

    problem = _extract_block("problem statement", "problem", "background")
    scope = _extract_block("what we want to build", "scope", "objectives", "goals")
    users = _extract_block("users", "stakeholders", "personas")
    constraints = _extract_block("constraints", "non functional", "non-functional")
    questions = _extract_block("open questions", "questions", "risks")

    summary_first = next((l for l in lines if len(l) > 30 and not l.endswith(":")), title)

    return {
        "title": f"Business Requirements Document — {title}",
        "summary": summary_first,
        "sections": [
            {"title": "1. Executive Summary", "content": summary_first},
            {"title": "2. Problem Statement", "content": problem or "TBD — captured from source email"},
            {"title": "3. Scope and Functional Requirements", "content": scope or "TBD"},
            {"title": "4. Users and Stakeholders", "content": users or "TBD"},
            {"title": "5. Non-Functional Requirements", "content": constraints or "TBD"},
            {"title": "6. Open Questions and Risks", "content": questions or "TBD"},
            {"title": "7. Source", "content": (email_text or "")[:1500]},
        ],
    }


@app.post("/api/generate-brd-from-email")
async def generate_brd_from_email(request: GenerateBRDRequest):
    """Try the n8n workflow first; if unavailable, generate the BRD through
    the configured LLM using the provided email text and any available
    file-search context."""
    email_text = request.transcript or ""
    search_metadata = None
    search_warning = None
    try:
        email_text, search_metadata = await _augment_brd_text_with_file_search(
            request.title or request.email_id or "email-brd",
            email_text,
            request.search_query,
        )
    except Exception as exc:
        search_warning = _error_text(exc, "File search context retrieval failed")

    webhook_error = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                N8N_WEBHOOK_GENERATE_BRD,
                json={"email_id": request.email_id, "transcript": email_text, "title": request.title},
                timeout=120.0,
            )
        if response.status_code == 200:
            try:
                payload = response.json()
                if isinstance(payload, dict) and payload.get("sections"):
                    return {
                        "success": True,
                        "source": "n8n",
                        "warning": _merge_warning_messages(search_warning) or None,
                        "context": search_metadata,
                        "brd": payload,
                    }
                if isinstance(payload, dict) and payload.get("title"):
                    return {
                        "success": True,
                        "source": "n8n",
                        "warning": _merge_warning_messages(search_warning) or None,
                        "context": search_metadata,
                        "brd": payload,
                    }
            except Exception:
                pass
        else:
            webhook_error = f"n8n returned {response.status_code}"
    except Exception as exc:
        webhook_error = _error_text(exc, "n8n unreachable")

    try:
        llm_markdown = await _generate_brd_with_llm(
            _brd_slug_from_item(request.title or request.email_id or "email-brd") or "email-brd",
            email_text,
        )
        return {
            "success": True,
            "source": "llm-agent",
            "warning": _merge_warning_messages(webhook_error, search_warning) or None,
            "context": search_metadata,
            "brd": {
                "title": request.title or "Generated BRD",
                "markdown": llm_markdown,
            },
        }
    except Exception as exc:
        return {
            "success": False,
            "source": "generation-failed",
            "error": _error_text(exc, "Email BRD generation failed"),
            "warning": _merge_warning_messages(webhook_error, search_warning) or None,
            "context": search_metadata,
        }

@app.get("/api/openproject-tickets")
async def get_openproject_tickets():
    """
    Fetches work packages from the configured OpenProject instance.
    Uses Basic auth with 'apikey' as username and OPENPROJECT_API_KEY as password.
    Optionally filters by work package type if OPENPROJECT_TICKET_TYPE is set.
    Returns a list of tickets with id, subject, status, type, assignee, priority, description.
    """
    if not OPENPROJECT_API_URL or not OPENPROJECT_API_KEY:
        return {
            "success": False,
            "source": "not-configured",
            "warning": "OPENPROJECT_API_URL / OPENPROJECT_API_KEY not configured. Set both env vars to enable the integration.",
            "tickets": [],
        }

    try:
        import base64
        auth_string = base64.b64encode(f"apikey:{OPENPROJECT_API_KEY}".encode()).decode()
        headers = {"Authorization": f"Basic {auth_string}"}

        url = f"{OPENPROJECT_API_URL}/api/v3/projects/{OPENPROJECT_PROJECT}/work_packages"
        params = {"pageSize": 100}
        if OPENPROJECT_TICKET_TYPE:
            params["filters"] = json.dumps([{"type": {"operator": "=", "values": [OPENPROJECT_TICKET_TYPE]}}])

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            if response.status_code != 200:
                return {"success": False, "error": f"OpenProject returned {response.status_code}: {response.text[:300]}", "tickets": []}
            data = response.json()
            elements = data.get("_embedded", {}).get("elements", [])
            tickets = []
            for wp in elements:
                # Skip test/noise tickets with "Trying" in the title (case-insensitive)
                subject = wp.get("subject", "")
                if "trying" in subject.lower():
                    continue
                links = wp.get("_links", {})
                desc = wp.get("description", {})
                tickets.append({
                    "id": wp.get("id"),
                    "subject": wp.get("subject", ""),
                    "status": links.get("status", {}).get("title", ""),
                    "type": links.get("type", {}).get("title", ""),
                    "assignee": links.get("assignee", {}).get("title", "Unassigned"),
                    "priority": links.get("priority", {}).get("title", ""),
                    "description": desc.get("raw", "") if isinstance(desc, dict) else str(desc or ""),
                    "createdAt": wp.get("createdAt", ""),
                    "updatedAt": wp.get("updatedAt", ""),
                })
            return {"success": True, "tickets": tickets, "total": len(tickets)}
    except Exception as e:
        return {"success": False, "error": str(e), "tickets": []}

# Mount frontend static files (use absolute path so server works from any cwd)
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
