# rss-downcast — v2.0.1

Download, manage, and archive podcast episodes from RSS feeds. A Typer CLI backed
by SQLite: sync new episodes per feed, tag MP3s, prune with retention rules,
inspect library health, and back up feeds with OPML.

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, module relationships,
the data model and key decisions.

## Features

- Incremental sync per feed (only episodes newer than the last download).
- Seed guard: a brand-new feed downloads nothing until you pass `--num`,
  `--since` or `--all`.
- Streaming downloads with retry/backoff; partial files are never kept.
- ID3 tagging (`TIT2`/`TPE1`/`TALB`/`TDRC`/`COMMENT`) and optional `.txt` sidecars.
- Retention: `--keep N`, `--keep-last`, `--max-age 30d`, `--max-size 2G`.
- Library inspection: `status`, `episodes list`, and `verify` (missing files /
  orphan files, with optional repair).
- Batch operations across every feed with `--all-feeds`.
- OPML import/export.

## Installation

```bash
uv pip install -e .   # or: pip install -e .
rss-downcast --help
rss-downcast --version  # 2.0.1
```

Requires Python ≥3.11. Runtime deps (audited, `pip-audit` clean):
`typer`, `feedparser`, `httpx`, `mutagen`.

## Usage

```bash
# Sync
rss-downcast sync URL DIR [--num N --since YYYY-MM-DD --all --dry-run --save-text]
rss-downcast sync --feed-id ID [DIR]        # tracked feed: reuses stored URL + save dir
rss-downcast sync --all-feeds [--all ...]   # every tracked feed

# Feeds
rss-downcast feeds list
rss-downcast feeds add URL [DIR]
rss-downcast feeds remove ID [--delete-files]

# Retention
rss-downcast prune DIR [--keep N --keep-last --max-age 30d --max-size 2G] [--feed-id ID]
rss-downcast prune --all-feeds [--keep N --dry-run]

# Inspection / maintenance
rss-downcast status [--feed-id ID]
rss-downcast episodes list [--feed-id ID] [--limit N] [--missing]
rss-downcast verify [--feed-id ID] [--fix] [--remove-orphans]

# Backup / migration
rss-downcast opml export FILE
rss-downcast opml import FILE
```

Global options: `--db FILE` (default `~/.local/share/rss-downcast/downloads.db`),
`--config FILE` / `--no-config`, `--verbose` / `--quiet`.

First sync of a feed downloads nothing unless you pass `--num N`, `--since DATE`
or `--all` (seed guard). Later runs fetch only episodes newer than the newest
download (incremental sync).

Filenames: `YYYY-MM-DD_ascii_title.mp3`, collision-safe (`_<n>` suffix).

### Inspecting a library

`status` prints one row per feed with the episode count, on-disk size, newest
publication date, and integrity counters:

```console
$ rss-downcast status
 ID   EPS  FILES       SIZE  MISS  ORPH  NEWEST               TITLE
  1     3      3    101.2MB     0     0  2026-09-20T18:17:00  Andrés Spyker Podcast
  2     3      3    314.6MB     0     0  2026-09-21T14:00:00  Dante Gebel Live
TOTAL: 2 feed(s), 6 episode(s), 415.8MB, missing=0, orphans=0
```

- `episodes list` shows rows newest-first (`--missing` filters to rows whose file
  is gone; `--limit 0` means no limit).
- `verify` reports dead rows and orphan files and exits non-zero while findings
  remain. `--fix` deletes rows whose file is missing; `--remove-orphans` deletes
  untracked media files under the feed's save dir. The two are independent —
  `--remove-orphans` is destructive, so back up the DB first.

## Config file

`./rss-downcast.toml`, `$XDG_CONFIG_HOME/rss-downcast/rss-downcast.toml`,
or `~/.config/rss-downcast/rss-downcast.toml` (also `config.toml` in the app
dirs). See `config.example.toml`. CLI flags always win; a `false` CLI default
cannot negate a `true` config value for one run.

## Development

```bash
uv venv .venv
uv pip install -e .
uv pip install pytest ruff
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run ruff check .
uvx pip-audit
```

Project layout and data flow: [ARCHITECTURE.md](ARCHITECTURE.md).
Specs: [`docs/specs/`](docs/specs/) (`v2-rss-downcast.md` is the v2 north star).
Changelog: [`CHANGELOG.md`](CHANGELOG.md).

## Tech stack

- Python ≥3.11 (stdlib `tomllib`, `sqlite3`, `argparse`-free Typer CLI)
- [Typer](https://typer.tiangolo.com/) for the CLI
- [httpx](https://www.python-httpx.org/) for feed + media downloads
- [feedparser](https://feedparser.readthedocs.io/) for RSS/Atom parsing
- [mutagen](https://mutagen.readthedocs.io/) for ID3 tags
- SQLite for state (single file, no server)

## License

GPL-3.0-only — see `LICENSE`. Author: Audel Diaz
(`https://github.com/AudelDiaz/rss-downcast`).
