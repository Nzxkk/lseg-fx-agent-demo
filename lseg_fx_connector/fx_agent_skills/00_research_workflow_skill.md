---
name: research-workflow
description: Goal-driven FX research orchestration workflow. Converts a user objective into a traceable sequence of local skills, data checks, signal generation, risk review, and business-facing reporting.
category: flow
---

# FX Research Workflow

Use this skill when the user asks the FX Agent to run a complete workflow rather than a single calculation.

## When to Use

- The task combines data retrieval, signal generation, news interpretation, risk checks, and reporting.
- The user wants a Vibe-Trading style Agent instead of a one-off script.
- The output should be explainable to business users and reproducible from local artifacts.

## Execution Model

The Agent follows a research-only chain:

1. Interpret the user objective.
2. Load the local skill catalog.
3. Map each execution step to the skill responsible for that step.
4. Run the deterministic signal engine.
5. Read generated artifacts from `lseg_fx_connector/output`.
6. Classify each result into trade candidate, watchlist, no action, or blocked.
7. Produce a Chinese report with artifacts and caveats.

## Evidence Rules

- Every conclusion must trace back to a CSV, Markdown report, or JSON Agent run artifact.
- Do not treat a successful process exit as enough evidence; output rows must exist.
- Prefer explicit failure over silent fallback when data is missing.
- Do not present LLM-generated language as a source of truth; the LLM only explains computed results.

## Output Contract

The Agent run should contain:

- `steps`
- `skills`
- `skill_plan`
- `signals`
- `decisions`
- `risk_checks`
- `artifacts`
- `report`

## Boundary

This workflow does not place orders, manage positions, or send external trading instructions. It is a local research and reporting workflow.
