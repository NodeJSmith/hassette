# Design: Visual Parity Round 2

**Date:** 2026-03-21
**Status:** archived
**Spec:** N/A — second pass of 012-visual-parity-verification

## Problem

Round 1 of visual parity verification (012) fixed 20 gaps but the user still sees differences. The old UI screenshots from round 1 are still valid — a fresh capture of the new UI + fresh comparison is needed to find remaining gaps.

## Architecture

Reuse the same 6-phase pipeline from 012, skipping Phase 1 (old screenshots already exist at `design/audits/visual-parity/old/`).

Old screenshots: `design/audits/visual-parity/old/` (27 files from 012-WP01)
New screenshots: `design/audits/visual-parity/round2/` (fresh captures)
Comparison output: `design/audits/visual-parity/round2-comparison.md`
Gap checklist: `design/audits/visual-parity/round2-gap-checklist.md`

## Non-Goals

Same as 012 — one-time verification, desktop only, no functional testing.
