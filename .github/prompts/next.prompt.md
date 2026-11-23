---
mode: agent
description: Run the next build chunk of the NIFTY platform
---
Read `AGENTS.md` and `docs/STATE.md`. Then open only `prompts/<next_chunk>-*.md` (the chunk named by `next_chunk` in STATE.md) and the files it lists, nothing else. Execute it, run its acceptance commands until green, update `docs/STATE.md`, reply in ≤8 lines (done / deviations / blockers / next_chunk), and STOP. Ask me (question tool) only for missing preconditions, spec conflicts, or steps marked ASK; otherwise decide, log it under Deviations, and continue.
