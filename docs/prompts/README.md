# Prompts used during the hackathon (Nov 14–15, 2026)

This folder is the public record of **how Super Intelligence (SI) tools were used to build V.I.T.A.L.I.S.**: the relevant prompts sent to each AI harness, in chronological order, and the part of the project each one created. It supports the "Use of Super Intelligence" disclosure required by NASA Space Apps ([`../AI_USE.md`](../AI_USE.md)).

| Harness | Role in the project | File | Prompts |
|---|---|---|---|
| **Antigravity** (Google Antigravity CLI agent) | Product build: design, backend, assistant L.I.S., native desktop port, backend integration, alarms, Wellbeing module, releases v1.0.0 → v1.2.0 | [`antigravity.md`](antigravity.md) | 32 entries |
| **Claude Code** (Anthropic) | 3D anatomy viewer, removal of the web prototype, touch-first UI and alerts, tablet version | [`claude-code.md`](claude-code.md) | 8 entries |

The other harnesses available to the team (Codex, OpenCode, Cursor, GitHub Copilot, Orca) have **no sessions during the hackathon dates** and are therefore not documented here.

## How the prompts were selected

* **Source:** the harnesses' own session transcripts on the developer's machine, dated Nov 14–15, 2026 (local time, UTC−6). Nothing was reconstructed from memory.
* **Kept:** prompts that created or reshaped a part of the project — architecture decisions, features, stack changes, behaviour rules, releases.
* **Omitted:** one-word continuations ("sigue", "listo", "como va"), requests for archives, screenshots, desktop shortcuts, status pings and similar operational messages, plus the final repository-delivery request.
* **Language:** prompts are in **Spanish**, the team's working language, and are reproduced verbatim (typos kept) with an English translation. Long prompts are abridged with `…`.
* **Redaction:** API keys, e-mail addresses and private product names were replaced by `[REDACTED_…]` markers. **No secret is stored in this repository.**
* **Ideas were human.** The challenge selection, the product concept (self-assessment, personal baseline, 3D body, emergency mode, on-board assistant), the scope and every clinical-indicator decision came from the team; the prompts show the team directing the tools, not asking them for the idea.

## Timeline (local time) with the resulting milestones

| Date · time | Harness | Prompt | Milestone |
|---|---|---|---|
| Nov 14 · 12:33 | Antigravity | AG-01 | Figma mock-up of the 6 views |
| Nov 14 · 14:03–14:50 | Antigravity | AG-03, AG-04 | First prototype, OSD-575 pipeline, backend brief |
| Nov 14 · 15:21–17:12 | Antigravity | AG-05 … AG-10 | Assistant concept AURA → **L.I.S.**, project renamed **V.I.T.A.L.I.S.** |
| Nov 14 · 17:55–18:12 | Antigravity | AG-11, AG-12 | Decision: Python backend + **native** desktop app |
| Nov 14 · 18:49–20:12 | Claude Code | CC-01 … CC-04 | 3D viewer (172 meshes); web prototype archived (`80a311b`) |
| Nov 14 · 20:25–21:16 | Claude Code | CC-05 … CC-07 | Declutter, touch UI, alerts and organ highlighting |
| Nov 14 · 18:59–23:46 | Antigravity | AG-13 … AG-19 | Agent behaviour, themes, bilingual voice |
| Nov 15 · 00:29–01:09 | Antigravity | AG-20, AG-21 | Backend integration, Mission Control, **v1.0.0** (`4b196ed`) |
| Nov 15 · 01:12–03:54 | Antigravity | AG-22 … AG-29 | Yellow-state help, red alarm, live waveforms, **v1.1.0** |
| Nov 15 · 04:03–04:43 | Antigravity | AG-30 … AG-32 | Wellbeing (NASA BHP), persistence, **v1.2.0** (`ba860cb`) |
| Nov 15 · 05:09 | Claude Code | CC-08 | Android tablet version, layout audit |

Time order is exact within each harness; the two harnesses ran partly in parallel, so the timeline above interleaves them.
