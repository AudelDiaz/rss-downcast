# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-09-27

### Fixed (review v2.0.1)
- Retention flags: CLI flags now win over TOML defaults by parameter provenance,
  so `--keep-last` works when the config sets `keep` (and vice versa); the
  mutual-exclusion error only fires when both flags are on the command line, and
  a config that sets both keys is a clear error. `--keep`/`--max-age`/
  `--max-size` validation is shared by `sync` and `prune` (`--max-size` must be
  `>= 1` byte everywhere).
- Duplicate GUID no longer leaves the just-downloaded file orphaned on disk when
  the episode INSERT fails.
- `retention.prune_feed()` uses timezone-aware `datetime.now(UTC)` (stored
  `published` values stay naive UTC).

### Added
- Library inspection commands: `status` (per-feed dashboard: episodes, on-disk
  size, newest, missing files, orphan files, totals), `episodes list`
  (`--feed-id`, `--limit`, `--missing`), and `verify` (`--fix` to drop rows whose
  file is missing, `--remove-orphans` to delete untracked media files; exits
  non-zero while findings remain). Backed by a new read-only `audit` module.
- Batch flags `sync --all-feeds` and `prune --all-feeds` (mutually exclusive with
  an explicit `URL`/`SAVE_DIR`/`--feed-id`); `sync` isolates per-feed failures and
  exits non-zero if any feed failed.
- CLI end-to-end integration tests (`sync` → fetch → download → prune) and
  regression tests for flag precedence and orphan cleanup.

## [2.0.0] - 2026-09-19

### Changed (breaking)
- **Rebrand `rss-downcast`**: author Audel Diaz, `github.com/AudelDiaz/rss-downcast`,
  license GPL-3.0-only (fixes `pyproject` claiming MIT), entry point `rss-downcast`,
  config `rss-downcast.toml`, DB default `~/.local/share/rss-downcast/downloads.db`.
  Originally forked from `johnsosoka/rss-podcast-downloader` (v1 lineage); no code
  or branding of the original remains.
- **Typer + `src/` layout**: `src/rss_downcast/` (`cli`, `config`, `db`, `feed`,
  `download`, `media`, `retention`, `opml`, `sync`). Legacy single-file
  `rss-podcast-downloader.py` + shim `rss_podcast_downloader.py` deleted.
- **Subcommand CLI**: `sync URL DIR`, `feeds list|add|remove`, `prune DIR`,
  `opml export|import`. No migration for v1 CLI flags or v1 `downloads.db`.
- **httpx** replaces `requests` (streaming + retry kept; skips length-check on
  encoded bodies; local OSError no longer retried as network).
- Minimal direct deps (`typer`, `feedparser`, `httpx`, `mutagen`;
  `requires-python >=3.11`); transitive deps kept out of `requirements.txt`.

### Fixed (review v2)
- Timezone-aware vs naive crash in selection/sort (all normalized to naive UTC).
- `None`/missing title no longer aborts sync (`untitled` fallback).
- `published` stored via full date resolution (the incremental anchor advances on
  string-only dates); `entry.title` attribute access hardened.
- `prune` parse errors are clean CLI errors; `--keep "5"` coercion;
  TOML-native dates accepted for `--since`; `verbose`/`quiet` honored from config;
  `prune_to_keep_last` returns counts; FK `ON DELETE CASCADE` + `row_factory=Row`
  + `created_at` column.

## [1.1.0] - 2026-09-04

### Added
- **Flexible retention**: flags `--keep N`, `--max-age DAYS` (e.g. `30d`),
  `--max-size SIZE` (e.g. `500M`, `2G`) via `prune_feed()`. Composable; protects
  shared files and respects `commonpath(save_dir)`. `prune_to_keep_last` is now a
  `keep=1` wrapper.
- **Feeds CRUD + OPML**: `remove_feed()`, `export_opml()`, `import_opml()` with CLI
  `--remove-feed ID [--delete-files]`, `--export-opml FILE`, `--import-opml FILE`.
- **Installable packaging**: `pyproject.toml` `[project]` + `[build-system] hatchling`
  + `[project.scripts] rss-podcast-downloader = rss_podcast_downloader:main`; the
  `rss_podcast_downloader.py` shim dynamically loads the hyphenated script.
- **TOML config file**: `find_config_path()` / `load_config()` with priority
  `--config` > `./rss-podcast-downloader.toml` > `XDG_CONFIG_HOME` >
  `~/.config/rss-podcast-downloader/config.toml`; `[defaults]` section; CLI
  overrides config. Flags `--config FILE`, `--no-config`. Example in
  `config.example.toml`.
- **Sync UX**: `--dry-run` (lists without downloading or writing to the DB),
  `audio/*` + `video/mp4` support (previously `audio/mpeg` only) via
  `_is_audio_enclosure()`, anti-collision `_unique_filepath()` `_2/_3` suffix,
  `--verbose`/`--quiet`, filename truncation >200 chars.
- **Versioning**: `__version__ = '1.1.0'` + `--version` flag + versioned
  `USER_AGENT`.

### Fixed
- **FP-1**: `download_file` treats a malformed `Content-Length` (`ValueError`) as
  `None` instead of aborting the batch.
- **FP-3**: `download_file` accepts an injectable `sleep_fn` for tests without
  `time.sleep`.
- **FP-4**: `save_text_file` produces `ep.txt`, not `ep.mp3.txt` (strips ext) +
  `encoding='utf-8'`.
- **FP-5**: Reproducible pins `mutagen==1.48.1`, `pytest==9.1.1`, `ruff==0.16.6`
  in `requirements.txt` and `ci.yml`; `pyproject.toml:target-version py310`.

### Changed
- `pyproject.toml` is now the source of truth for dependencies and build;
  `rss_podcast_downloader.py` is an importable module for `pipx`/`uv tool`.

### Specs
- New specs: `docs/specs/retention.md`, `docs/specs/feed-crud-opml.md`,
  `docs/specs/packaging-config.md`.

## [1.0.0] - 2026-02-02
- First installable version with stateful DB, multi-feed tracking and initial tests.
