# Required BRD section markers

Every BRD persisted in `local_brds.json` must contain these 11 Markdown
section headings, in this order:

```markdown
# Business Requirements Document: <Project Title>

**Document Version:** 1.0
**Date:** <YYYY-MM-DD>
**Author:** <name or "BRD Auto-Generator">
**Status:** Draft — Pending Stakeholder Review

---

## 1. EXECUTIVE SUMMARY

Under 50 words. Quantify business impact. Reference the source meeting context.

## 2. BUSINESS OBJECTIVES

Numbered goals (O-1, O-2, ...). Each with a measurable success criterion.

## 3. STAKEHOLDER ANALYSIS

Table per stakeholder with interest level, influence, and required engagement.

## 4. FUNCTIONAL REQUIREMENTS

Numbered (FR-M01, FR-M02, ...). Each requirement phrased as
"The system must …". Include acceptance criteria.

## 5. NON-FUNCTIONAL REQUIREMENTS

Performance, security, compliance, accessibility. Use measurable targets.

## 6. ASSUMPTIONS & CONSTRAINTS

Numbered. Distinguish hard constraints from working assumptions.

## 7. DATA SOURCES & INTEGRATIONS

Inbound and outbound. List each system with the field-level contract.

## 8. ARCHITECTURE OVERVIEW

High-level diagram description. Components, data flow, scaling considerations.

## 9. OPEN CONFLICTS

Discrepancies between source-of-truth signals (transcripts vs prior BRDs vs
file search hits). Each conflict with proposed resolution.

## 10. CORRECTIONS & FALSE POSITIVES

Items the AI initially extracted but later corrected. Audit trail.

## 11. CHANGE LOG

Versioned table of doc revisions.
```

These markers are checked by `_is_complete_brd(text)` in `brd-agent/backend/server.py`.
Missing any → the third-pass section-append recovery is triggered.

Use `TBD` for genuinely unknown values. Heuristic accepts ≥ 4000 chars +
all sections present even with TBDs (real meetings legitimately leave some
fields pending).
