---
name: caveman-stats
description: >
  Upstream caveman-stats describes a Claude Code hook feature for token usage
  receipts. This project-local install does not vendor JS hooks, shell hooks,
  statusline scripts, or plugin-level install scripts needed to run it.
---

Upstream caveman-stats is delivered by `hooks/caveman-stats.js`, read by `hooks/caveman-mode-tracker.js` on `/caveman-stats`.

This repo does **not** include those JS hooks, shell hooks, statusline scripts, or plugin-level install scripts. No local hook intercepts `/caveman-stats`.

Installed executable caveman code in this repo is limited to `caveman-compress` Python scripts. Treat this skill as upstream reference unless hooks are installed separately outside this repo.
