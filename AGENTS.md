# AGENTS.md — RSS Podcast Downloader

Conventions for any agent (DSH / DeepSeek Harness, opencode, etc.) working in this repo.
This file bridges the author's personal opencode skillset into agent sessions.

## Reusable skill store (source of truth)

The author maintains skills + memory for opencode, stowed at:

- Skills: `~/.config/opencode/skills/<name>/SKILL.md`
  (resolves via `~/.dotfiles/stow/opencode/.config/opencode/skills/...`)
- Global workflow / sizing: `~/.config/opencode/AGENTS.md`
- Session memory: `~/.config/opencode/memory/*.md`

These are plain Markdown. When a task matches, READ the relevant file and treat
its contents as authoritative instructions for that task. Do not assume their
contents from the summary below.

## Skill → when to load (per task)

| Skill file | Load when working on... |
|------------|--------------------------|
| `sdd` | Any non-trivial / new feature — write a spec to `docs/specs/<name>.md` before coding |
| `testing` | Adding/structuring Python tests (uses `tests/unit` + `tests/integration`, pytest) |
| `automation` | CI/CD, Makefiles, script automation |
| `docs` | README / ARCHITECTURE.md / project documentation templates |
| `adversarial-review` | Before merging, or after any M/L change — run the hunt checklist |
| `docker` / `django` / `fastapi` / `nvim` / `zellij` | Matching technology work |

> Note: this agent's own session skill catalog is fixed at startup and does NOT
> include these files. Load them by reading the path above when relevant.

## Right-sizing workflow (from author's global AGENTS.md)

Classify each task FIRST, then run only the phases its size requires.

- **S (small)** — single file, no logic change (typo, comment, config value,
  one string). Implement only. No spec/review/tests unless the diff changes logic.
- **S-docs (docs-only)** — only `*.md`, `docs/**`, `config.example.toml`, `CHANGELOG.md`, `README.md`. No spec, no tests, no adversarial review — only `ruff format --check` if needed. If diff touches `*.py`, `pyproject.toml`, or `.github/**`, re-classify as M/L. Detection: `git diff --stat --name-only` all paths match `^(README|CHANGELOG|config\.example\.toml|docs/|.*\.md$)`.
- **M (medium)** — multiple files OR new logic / branching / thresholds.
  Phases: understand → implement → test → adversarial review. Write a spec
  (`sdd`, save to `docs/specs/`); dispatch an adversarial review on the diff.
- **L (large)** — architecture / data-model / security / cross-cutting refactor,
  or the user says "plan/spec first". Full pipeline: understand → implement →
  test → adversarial review → verify → deploy, with explicit user approval gates
  at plan and before deploy.

When unsure, round UP one size.

## Session memory

Read `~/.config/opencode/memory/` only when a task directly relates to the
author's infrastructure, configuration, or previously persisted work
(e.g. workstation, home lab, deployment targets). Do not load proactively on
every task.

## Project specifics (rss-downcast v2)

- Typer CLI package: `src/rss_downcast/` (`cli`, `config`, `db`, `feed`,
  `download`, `media`, `retention`, `opml`, `sync`). Entry `rss-downcast`.
- State: `~/.local/share/rss-downcast/downloads.db` (or `--db`).
  Tables `feeds`, `episodes` (FK CASCADE, `UNIQUE(feed_id, guid)`).
- Env: local `.venv` (Python 3.14). Deps: typer, feedparser, httpx, mutagen.
  Audit: `uvx pip-audit`. Spec: `docs/specs/v2-rss-downcast.md`.
- Tests: `tests/unit` + `tests/integration` via `tests/conftest.py `mod`` compat
  namespace; `pythonpath = ["src"]` in pyproject. Run `pytest tests/ -q`,
  `ruff check .`.
- License GPL-3.0-only, author Audel Diaz. No upstream references remain
  (one attribution line in CHANGELOG per GPL §5).
