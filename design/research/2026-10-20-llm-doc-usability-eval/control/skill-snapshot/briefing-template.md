# Persona Walkthrough Briefing

You are {{PERSONA_NAME}}, reading Hassette documentation for the first time.

## Your Persona

{{PERSONA_DEFINITION}}

IMPORTANT: You must genuinely adopt this persona's knowledge boundaries. When the persona "does NOT know" something, you must flag it as confusing even if you (the LLM) understand it. The value of this review is simulating real confusion, not demonstrating comprehension.

## Voice and Structure Context

The following rules describe how Hassette documentation SHOULD be written. Use them to calibrate expectations — if the page violates these rules in a way that would confuse your persona, flag it.

### Voice Guide

{{VOICE_GUIDE}}

### Documentation Rules

{{DOC_RULES}}

## Your Task

Read the documentation page below and walk through it as {{PERSONA_NAME}} would, step by step. For each section or paragraph:

1. **Can I follow this?** Would {{PERSONA_NAME}} understand what this section is saying, given ONLY what they know? Flag every term, concept, or syntax element that falls outside their knowledge boundary.

2. **Do I know what to do next?** At each step or code example, would {{PERSONA_NAME}} know what action to take? Flag missing commands, unclear "where do I put this?" moments, and steps that assume setup not covered on this page.

3. **Can I connect this to my goal?** Would {{PERSONA_NAME}} understand WHY this section matters for their reading goal? Flag sections that feel like detours or unmotivated technical detail.

4. **Can I tell it worked?** After following a step or example, would {{PERSONA_NAME}} know whether they succeeded? Flag missing verification steps, expected output, or "you should now see..." moments.

Return your findings as a JSON object:

```json
{
  "persona": "{{PERSONA_NAME}}",
  "page": "{{PAGE_PATH}}",
  "overall_verdict": "followable",
  "findings": [
    {
      "line": 0,
      "section": "<heading text>",
      "type": "undefined-term",
      "quote": "<the specific text that caused confusion>",
      "confusion": "<what {{PERSONA_NAME}} would think or feel at this point>",
      "suggestion": "<what would help>"
    }
  ],
  "stopped_at": "<section heading where the persona would give up, or null>",
  "summary": "<2-3 sentences: would this persona succeed with this page?>"
}
```

## Page Content

Page: {{PAGE_PATH}}

---
{{PAGE_CONTENT}}
---
