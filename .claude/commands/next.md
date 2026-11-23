---
description: Run the next build chunk of the NIFTY platform (optional arg = chunk id, e.g. C03)
---
Read `AGENTS.md` and `docs/STATE.md`. Chunk to run: `$ARGUMENTS` if given, else `next_chunk` from STATE.md. Open only `prompts/<chunk>-*.md` and the files it lists, nothing else. Execute it, run its acceptance commands until green, update `docs/STATE.md`, reply in ≤8 lines (done / deviations / blockers / next_chunk), and STOP. Ask me (question tool) only for missing preconditions, spec conflicts, or steps marked ASK; otherwise decide, log it under Deviations, and continue.
