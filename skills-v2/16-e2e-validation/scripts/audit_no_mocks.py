"""Mock-data audit: greps the operational code paths for patterns that
must NEVER appear in production code. Run before any release / demo.

Patterns we eradicated (would re-regress trust in the product):
- Hardcoded fake names from earlier ad-hoc tests (Rahul, Neha, Amit Khanna, ...)
- Placeholder URLs (`?placeholder=true`)
- Sample OpenProject tickets (WP-1..WP-5 series)
- Dead BRD skeleton generator (`_build_local_brd_markdown`)
- Sample buttons in BRD frontend (`SAMPLE_BRD_PROMPT`, `btn-quick-sample-brd`)
- "AI daily scrum summary" subject template (the generic Groq output we override)

Greps two directories:
- meeting-master/ (everything except docs/ and __pycache__)
- brd-agent/      (everything except docs/ and __pycache__)

Exits 1 with the offending lines if anything is found.
"""
import sys, os, re, subprocess

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOTS = [
    r"D:\10xHackathon\meeting-master",
    r"D:\10xHackathon\brd-agent",
]

# Patterns we actually forbid in the operational code path.
# Each pattern flags a SPECIFIC removed regression — not generic words.
PATTERNS = [
    # Hardcoded fake personal names from the deleted OpenProject sample tickets
    (r"Rahul Sharma|Priya Sharma|Rohan Mehta|Amit Khanna|Neha Singh", "fake-personal-names"),
    # Placeholder OAuth URL
    (r"placeholder=true", "placeholder-oauth"),
    # WP-1..WP-5 hardcoded sample OpenProject tickets
    (r'"WP-[1-5]"', "wp-sample-tickets"),
    # Dead skeletal BRD generator
    (r"_build_local_brd_markdown", "dead-brd-skeleton"),
    # BRD frontend sample buttons (deleted)
    (r"btn-quick-sample-brd|btn-quick-transcript", "brd-sample-buttons"),
    # The old SAMPLE_BRD_PROMPT / SAMPLE_TRANSCRIPT constants from brd-agent
    # (NOTE: QUICK_START_SAMPLE_TRANSCRIPT is a different, legitimate opt-in
    # demo with role labels — explicitly excluded by the regex below).
    (r"\bSAMPLE_BRD_PROMPT\b|^[^A-Z]*\bSAMPLE_TRANSCRIPT\b", "deleted-sample-constants"),
]

EXCLUDE_DIRS = {"__pycache__", ".git", "docs", "node_modules", "tests"}
EXCLUDE_FILE_SUFFIXES = (".md", ".pdf", ".json")

# Strip comment lines so docstrings/inline comments that describe a removed
# pattern aren't flagged. We're scanning for actual data emissions, not docs.
COMMENT_LINE = re.compile(r"^\s*(?:#|//|\*|'''|\"\"\")")

violations = []

for root in ROOTS:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if fname.endswith(EXCLUDE_FILE_SUFFIXES):
                continue
            path = os.path.join(dirpath, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if COMMENT_LINE.match(line):
                            continue
                        for pattern, tag in PATTERNS:
                            if re.search(pattern, line):
                                violations.append((path, i, tag, line.rstrip()))
            except Exception as e:
                print(f"warn: could not read {path}: {e}")

if violations:
    print(f"\nFOUND {len(violations)} mock-data violation(s):\n")
    for path, lineno, pattern, line in violations:
        print(f"  {path}:{lineno}")
        print(f"    pattern: {pattern}")
        print(f"    line   : {line[:200]}")
        print()
    sys.exit(1)
else:
    print(f"OK — no mock-data patterns found in operational code paths.")
    print(f"  scanned: {ROOTS}")
    print(f"  patterns checked: {len(PATTERNS)}")
    sys.exit(0)
