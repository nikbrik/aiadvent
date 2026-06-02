# caveman-stats

Real session token receipts. No AI estimation.

## What it does

Upstream caveman-stats is a Claude Code hook feature. In this project-local install, JS hooks, shell hooks, statusline scripts, and plugin-level install scripts are not vendored. No local `caveman-mode-tracker` hook intercepts `/caveman-stats`.

Installed executable caveman code in this repo is limited to `caveman-compress` Python scripts. Treat `caveman-stats` here as upstream documentation/reference unless hook files are installed separately outside this repo.

## How to invoke

```
/caveman-stats
```

## Example output

```
Session: 47 turns
Input:   12,304 tokens
Output:   3,891 tokens (caveman)
Baseline: 11,247 tokens (estimated without caveman)
Saved:    7,356 tokens (~65%)
```

## See also

- [`SKILL.md`](./SKILL.md) — project-local availability note
