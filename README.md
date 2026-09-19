# rss-downcast — v2.0.0

Download, manage, and archive podcast episodes from RSS feeds. Typer CLI +
SQLite tracking: sync new episodes per feed, tag MP3s, prune retention,
OPML backup.

## Installation

```bash
uv pip install -e .   # or: pip install -e .
rss-downcast --help
rss-downcast --version  # 2.0.0
```

Requires Python ≥3.11. Runtime deps (audited, `pip-audit` clean):
`typer`, `feedparser`, `httpx`, `mutagen`.

## Usage

```bash
rss-downcast sync URL DIR [--num N --since YYYY-MM-DD --all --dry-run --save-text]
rss-downcast feeds list
rss-downcast feeds add URL [DIR]
rss-downcast feeds remove ID [--delete-files]
rss-downcast prune DIR [--keep N --keep-last --max-age 30d --max-size 2G] [--feed-id ID]
rss-downcast opml export FILE
rss-downcast opml import FILE
```

Global options: `--db FILE` (default `~/.local/share/rss-downcast/downloads.db`),
`--config FILE` / `--no-config`, `--verbose` / `--quiet`.

First sync of a feed downloads nothing unless you pass `--num N`, `--since DATE`
or `--all` (seed guard). Later runs fetch only episodes newer than the newest
download (incremental sync).

Filenames: `YYYY-MM-DD_ascii_title.mp3`, collision-safe (`_<n>` suffix).

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

Specs: [`docs/specs/`](docs/specs/) (`v2-rss-downcast.md` is the v2 north star).
Changelog: [`CHANGELOG.md`](CHANGELOG.md).

## License

GPL-3.0-only — see `LICENSE`. Author: Audel Diaz
(`https://github.com/AudelDiaz/rss-downcast`).
