"""Typer CLI for rss-downcast.

Author: Audel Diaz <https://github.com/AudelDiaz/rss-downcast>
License: GPLv3 — see LICENSE.
"""

import logging
import os
from datetime import datetime
from pathlib import Path

import typer

from rss_downcast import __version__
from rss_downcast import audit as audit_mod
from rss_downcast import db as db_mod
from rss_downcast import sync as sync_mod
from rss_downcast.config import find_config_path, load_config
from rss_downcast.opml import export_opml, import_opml
from rss_downcast.retention import parse_max_age, parse_size, prune_feed

app = typer.Typer(
    name='rss-downcast',
    help='Download, manage and archive podcast episodes from RSS feeds.',
    no_args_is_help=False,
)
feeds_app = typer.Typer(help='Manage tracked feeds.')
episodes_app = typer.Typer(help='Inspect tracked episodes.')
opml_app = typer.Typer(help='OPML backup / migration.')
app.add_typer(feeds_app, name='feeds')
app.add_typer(episodes_app, name='episodes')
app.add_typer(opml_app, name='opml')


def _version_callback(value: bool):
    if value:
        typer.echo(f'rss-downcast {__version__}')
        raise typer.Exit()


@app.callback()
def _global(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, '--verbose', help='Verbose logging (DEBUG).'),
    quiet: bool = typer.Option(False, '--quiet', help='Quiet logging (WARNING only).'),
    config: str | None = typer.Option(None, '--config', metavar='FILE', help='Config file (TOML).'),
    no_config: bool = typer.Option(False, '--no-config', help='Disable config file loading.'),
    db: str | None = typer.Option(None, '--db', help='SQLite database path.'),
    version: bool = typer.Option(
        False, '--version', callback=_version_callback, is_eager=True, help='Show version.'
    ),
):
    if verbose and quiet:
        raise typer.BadParameter('--verbose and --quiet are mutually exclusive')
    if config and no_config:
        raise typer.BadParameter('--config and --no-config are mutually exclusive')
    if config and not Path(config).exists():
        raise typer.BadParameter(f'Config file not found: {config}')

    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    logging.getLogger().setLevel(level)

    cfg_path = find_config_path(config, no_config=no_config)
    cfg = load_config(cfg_path)
    if cfg_path and cfg:
        logging.debug('Loaded config %s: %s', cfg_path, cfg)

    ctx.obj = {'config': cfg, 'db': db, 'verbose': verbose, 'quiet': quiet}

    if not verbose and not quiet:
        if cfg.get('verbose'):
            logging.getLogger().setLevel(logging.DEBUG)
        elif cfg.get('quiet'):
            logging.getLogger().setLevel(logging.WARNING)


def _cfg(ctx: typer.Context) -> dict:
    return (ctx.obj or {}).get('config', {}) if ctx.obj else {}


def _db_path(ctx: typer.Context) -> str | None:
    return (ctx.obj or {}).get('db') if ctx.obj else None


def _from_cli(ctx: typer.Context, name: str) -> bool:
    """True when ``name`` was supplied on the command line (not a default)."""
    try:
        source = ctx.get_parameter_source(name)
    except Exception:  # pragma: no cover - defensive, provenance API missing
        return False
    return getattr(source, 'name', '') == 'COMMANDLINE'


def _eff(ctx: typer.Context, name: str, cli_value, default=None):
    """CLI flag wins when explicitly passed; then TOML config; then default.

    Provenance comes from ``Context.get_parameter_source`` so a ``false``
    boolean default never masks a config value, and vice versa. A config
    ``true`` still cannot be negated per-run (no ``--no-...`` flags).
    """
    if _from_cli(ctx, name):
        return cli_value
    cfg = _cfg(ctx)
    if name in cfg:
        return cfg[name]
    return cli_value if cli_value is not None else default


def _coerce_keep(keep) -> int | None:
    if keep is None:
        return None
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        raise typer.BadParameter(f'--keep must be a positive integer (got {keep!r})') from None
    if keep < 1:
        raise typer.BadParameter(f'--keep must be a positive integer (got {keep})')
    return keep


def _human_size(num) -> str:
    size = float(num)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f'{size:.0f}{unit}' if unit == 'B' else f'{size:.1f}{unit}'
        size /= 1024
    return f'{size:.1f}TB'


def _sync_one(
    conn,
    url,
    save_dir,
    *,
    save_text,
    num_episodes,
    since,
    full_history,
    dry_run,
    keep_n,
    max_age_delta,
    max_size_bytes,
    any_retention,
):
    """Fetch + download one feed, then optionally prune it in the same run."""
    _, _, feed_id = sync_mod.sync_url(
        url,
        save_dir,
        conn=conn,
        save_text=save_text,
        num_episodes=num_episodes,
        since=since,
        full_history=full_history,
        dry_run=dry_run,
    )
    if any_retention:
        prune_feed(
            conn,
            feed_id,
            save_dir,
            keep=keep_n,
            max_age=max_age_delta,
            max_size=max_size_bytes,
            dry_run=dry_run,
        )
    return feed_id


def _sync_all_feeds(conn, **kwargs):
    """Run :func:`_sync_one` for every feed; isolate per-feed failures."""
    feeds = db_mod.list_feeds(conn)
    if not feeds:
        typer.echo('No feeds found in database.')
        raise typer.Exit()
    failures = 0
    for feed_id, feed_url, feed_title, feed_dir in feeds:
        if not feed_dir:
            logging.error('Skipping feed %s (%s): no stored save directory.', feed_id, feed_title)
            failures += 1
            continue
        logging.info('Syncing feed %s: %s', feed_id, feed_title)
        try:
            _sync_one(conn, feed_url, feed_dir, **kwargs)
        except SystemExit:
            failures += 1
            logging.error('Feed %s (%s) failed; continuing.', feed_id, feed_title)
        except Exception as e:  # noqa: BLE001 - keep the batch going per feed
            failures += 1
            logging.error('Feed %s (%s) failed: %s', feed_id, feed_title, e)
    if failures:
        typer.echo(f'Sync finished with {failures} failing feed(s).')
        raise typer.Exit(code=1)
    typer.echo(f'Synced {len(feeds)} feed(s).')


def _remove_orphans(save_dir, orphans):
    """Delete orphan files, refusing any path outside ``save_dir``."""
    if not save_dir:
        return 0
    abs_save = os.path.abspath(save_dir)
    removed = 0
    for path in orphans:
        try:
            if os.path.commonpath([abs_save, os.path.abspath(path)]) != abs_save:
                logging.warning('Refusing to delete outside save dir: %s', path)
                continue
            os.remove(path)
            removed += 1
        except (OSError, ValueError) as e:
            logging.warning('Could not remove orphan %s: %s', path, e)
    return removed


def _parse_max_age_delta(value):
    if not value:
        return None
    try:
        return parse_max_age(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def _parse_size_bytes(value):
    if not value:
        return None
    try:
        size = parse_size(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if size < 1:
        raise typer.BadParameter('--max-size must be >=1 byte')
    return size


def _resolve_retention(ctx: typer.Context, keep, keep_last, max_age, max_size):
    """Merge retention flags with TOML defaults and enforce keep/keep-last.

    CLI flags win over config, so ``--keep-last`` still works when the config
    defines ``keep`` (and vice versa). Returns
    ``(keep_n, max_age_delta, max_size_bytes, any_set)``.
    """
    keep_from_cli = keep is not None
    keep_last_from_cli = _from_cli(ctx, 'keep_last')
    if keep_from_cli and keep_last_from_cli:
        raise typer.BadParameter('--keep and --keep-last are mutually exclusive')

    if keep_from_cli:
        keep_value, keep_last_value = keep, False
    elif keep_last_from_cli:
        keep_value, keep_last_value = None, True
    else:
        cfg = _cfg(ctx)
        keep_value = cfg.get('keep')
        keep_last_value = bool(cfg.get('keep_last', False))
        if keep_value is not None and keep_last_value:
            raise typer.BadParameter('Config sets both keep and keep_last; define only one')

    keep_value = _coerce_keep(keep_value)
    max_age_delta = _parse_max_age_delta(_eff(ctx, 'max_age', max_age))
    max_size_bytes = _parse_size_bytes(_eff(ctx, 'max_size', max_size))
    keep_n = keep_value if keep_value is not None else (1 if keep_last_value else None)
    any_set = keep_n is not None or max_age_delta is not None or max_size_bytes is not None
    return keep_n, max_age_delta, max_size_bytes, any_set


def _parse_since(value) -> datetime | None:
    from datetime import date

    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except (ValueError, TypeError):
        raise typer.BadParameter('--since must be a date in YYYY-MM-DD format') from None


@app.command()
def sync(
    ctx: typer.Context,
    url: str | None = typer.Argument(None, help='RSS feed URL (omit with --feed-id).'),
    save_dir: str | None = typer.Argument(
        None, help='Directory for downloaded files (defaults to stored dir with --feed-id).'
    ),
    feed_id: int | None = typer.Option(None, '--feed-id', help='Sync a tracked feed by ID.'),
    all_feeds: bool = typer.Option(False, '--all-feeds', help='Sync every tracked feed.'),
    num_episodes: int | None = typer.Option(None, '--num-episodes', '--num', metavar='N'),
    since: str | None = typer.Option(None, '--since', metavar='YYYY-MM-DD'),
    all: bool = typer.Option(False, '--all', help='Download full archive on new feeds.'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Preview without downloading.'),
    save_text: bool = typer.Option(False, '--save-text', '--save_text', help='Save .txt sidecar.'),
    keep: int | None = typer.Option(None, '--keep', metavar='N'),
    keep_last: bool = typer.Option(False, '--keep-last', help='Keep only newest episode.'),
    max_age: str | None = typer.Option(None, '--max-age', metavar='DAYS'),
    max_size: str | None = typer.Option(None, '--max-size', metavar='SIZE'),
):
    """Sync a feed: download new episodes, then optionally prune."""
    num_episodes = _eff(ctx, 'num_episodes', num_episodes)
    since_s = _eff(ctx, 'since', since)
    full_history = _eff(ctx, 'all', all, False)
    dry_run = _eff(ctx, 'dry_run', dry_run, False)
    save_text = _eff(ctx, 'save_text', save_text, False)

    if num_episodes is not None and num_episodes < 1:
        raise typer.BadParameter('--num-episodes must be a positive integer')
    keep_n, max_age_delta, max_size_bytes, any_retention = _resolve_retention(
        ctx, keep, keep_last, max_age, max_size
    )
    since_date = _parse_since(since_s)

    if all_feeds and (url or save_dir or feed_id is not None):
        raise typer.BadParameter('--all-feeds cannot be combined with URL, SAVE_DIR or --feed-id')

    db_path = _db_path(ctx)
    with db_mod.get_conn(db_path) as conn:
        if all_feeds:
            _sync_all_feeds(
                conn,
                save_text=save_text,
                num_episodes=num_episodes,
                since=since_date,
                full_history=full_history,
                dry_run=dry_run,
                keep_n=keep_n,
                max_age_delta=max_age_delta,
                max_size_bytes=max_size_bytes,
                any_retention=any_retention,
            )
            return
        if feed_id is not None:
            stored_url = db_mod.get_feed_url_by_id(conn, feed_id)
            if not stored_url:
                raise typer.BadParameter(f'No feed found with --feed-id {feed_id}')
            url = stored_url
            if save_dir is None:
                save_dir = db_mod.get_feed_save_dir(conn, feed_id)
                if save_dir:
                    logging.info('Using stored save directory for feed %s: %s', feed_id, save_dir)
        if not url:
            raise typer.BadParameter('URL is required unless --feed-id is used')
        if not save_dir:
            raise typer.BadParameter('SAVE_DIR is required (or store one via `feeds add URL DIR`)')
        _sync_one(
            conn,
            url,
            save_dir,
            save_text=save_text,
            num_episodes=num_episodes,
            since=since_date,
            full_history=full_history,
            dry_run=dry_run,
            keep_n=keep_n,
            max_age_delta=max_age_delta,
            max_size_bytes=max_size_bytes,
            any_retention=any_retention,
        )


@feeds_app.command('list')
def feeds_list(ctx: typer.Context):
    """List all tracked feeds."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        rows = db_mod.list_feeds(conn)
    if not rows:
        typer.echo('No feeds found in database.')
        return
    for feed_id, feed_url, feed_title, save_dir in rows:
        typer.echo(f'{feed_id} | {feed_url} | {feed_title} | {save_dir or ""}')


@feeds_app.command('add')
def feeds_add(
    ctx: typer.Context,
    url: str = typer.Argument(..., help='RSS feed URL.'),
    save_dir: str | None = typer.Argument(None, help='Save directory (optional).'),
):
    """Track a new feed without downloading."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        feed_id = db_mod.get_or_create_feed(conn, url, url, save_dir=save_dir)
    typer.echo(f'Added feed {feed_id}')


@feeds_app.command('remove')
def feeds_remove(
    ctx: typer.Context,
    feed_id: int = typer.Argument(..., help='Feed ID to remove.'),
    delete_files: bool = typer.Option(False, '--delete-files', help='Delete episode files.'),
):
    """Remove a feed and its episode rows."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        ok = db_mod.remove_feed(conn, feed_id, delete_files=delete_files)
    if not ok:
        raise typer.BadParameter(f'No feed found with id {feed_id}')
    typer.echo(f'Removed feed {feed_id}')


@app.command()
def status(
    ctx: typer.Context,
    feed_id: int | None = typer.Option(None, '--feed-id', help='Limit to one feed.'),
):
    """Show per-feed library status and integrity totals."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        rows = audit_mod.summaries(conn, feed_id)
    if not rows:
        typer.echo('No feeds found in database.')
        return
    typer.echo(
        f'{"ID":>3}  {"EPS":>4}  {"FILES":>5}  {"SIZE":>9}  {"MISS":>4}  {"ORPH":>4}  '
        f'{"NEWEST":<19}  TITLE'
    )
    for s in rows:
        typer.echo(
            f'{s.feed_id:>3}  {s.episodes:>4}  {s.files:>5}  {_human_size(s.size_bytes):>9}  '
            f'{s.missing:>4}  {s.orphans:>4}  {(s.newest or "-"):<19}  {s.title}'
        )
    typer.echo(
        f'TOTAL: {len(rows)} feed(s), {sum(s.episodes for s in rows)} episode(s), '
        f'{_human_size(sum(s.size_bytes for s in rows))}, '
        f'missing={sum(s.missing for s in rows)}, orphans={sum(s.orphans for s in rows)}'
    )


@episodes_app.command('list')
def episodes_list(
    ctx: typer.Context,
    feed_id: int | None = typer.Option(None, '--feed-id', help='Limit to one feed.'),
    limit: int = typer.Option(50, '--limit', metavar='N', help='Max rows (0 = no limit).'),
    missing: bool = typer.Option(False, '--missing', help='Only rows whose file is absent.'),
):
    """List tracked episodes, newest first."""
    if limit < 0:
        raise typer.BadParameter('--limit must be >= 0 (0 = no limit)')
    with db_mod.get_conn(_db_path(ctx)) as conn:
        rows = audit_mod.list_episodes(conn, feed_id, limit=limit, missing_only=missing)
    if not rows:
        typer.echo('No episodes found.')
        return
    typer.echo(f'{"FEED":>4}  {"PUBLISHED":<19}  {"SIZE":>9}  {"STATE":<7}  TITLE')
    for e in rows:
        state = 'OK' if e.exists else 'MISSING'
        typer.echo(
            f'{e.feed_id:>4}  {(e.published or "-"):<19}  {_human_size(e.size):>9}  '
            f'{state:<7}  {e.title}'
        )


@app.command()
def verify(
    ctx: typer.Context,
    feed_id: int | None = typer.Option(None, '--feed-id', help='Limit to one feed.'),
    fix: bool = typer.Option(False, '--fix', help='Delete rows whose file is missing.'),
    remove_orphans: bool = typer.Option(
        False, '--remove-orphans', help='Delete untracked media files.'
    ),
):
    """Report missing files and orphaned downloads; optionally repair."""
    findings = 0
    fixed = 0
    with db_mod.get_conn(_db_path(ctx)) as conn:
        rows = audit_mod.summaries(conn, feed_id)
        if not rows:
            typer.echo('No feeds found in database.')
            return
        for s in rows:
            missing_rows = audit_mod.find_missing(conn, s.feed_id)
            orphans = audit_mod.find_orphans(conn, s.feed_id)
            if not missing_rows and not orphans:
                continue
            typer.echo(f'[{s.feed_id}] {s.title}')
            for r in missing_rows:
                findings += 1
                typer.echo(f'  missing  {r["published"] or "-"}  {r["filepath"] or "(no path)"}')
            for path in orphans:
                findings += 1
                typer.echo(f'  orphan   {path}')
            if fix and missing_rows:
                for r in missing_rows:
                    conn.execute('DELETE FROM episodes WHERE episode_id = ?', (r['episode_id'],))
                conn.commit()
                fixed += len(missing_rows)
                typer.echo(f'  fixed    removed {len(missing_rows)} dead row(s)')
            if remove_orphans and orphans:
                removed = _remove_orphans(s.save_dir, orphans)
                fixed += removed
                typer.echo(f'  fixed    removed {removed} orphan file(s)')
    if findings == 0:
        typer.echo('OK: no missing files or orphans.')
        return
    if fixed >= findings:
        typer.echo(f'Fixed {fixed} finding(s).')
        return
    typer.echo(f'{findings - fixed} finding(s) remain.')
    raise typer.Exit(code=1)


@app.command()
def prune(
    ctx: typer.Context,
    save_dir: str | None = typer.Argument(None, help='Feed save directory.'),
    feed_id: int | None = typer.Option(None, '--feed-id', help='Feed ID (else match by dir).'),
    all_feeds: bool = typer.Option(False, '--all-feeds', help='Prune every tracked feed.'),
    keep: int | None = typer.Option(None, '--keep', metavar='N'),
    keep_last: bool = typer.Option(False, '--keep-last'),
    max_age: str | None = typer.Option(None, '--max-age', metavar='DAYS'),
    max_size: str | None = typer.Option(None, '--max-size', metavar='SIZE'),
    dry_run: bool = typer.Option(False, '--dry-run'),
):
    """Prune episode files/rows for a feed directory (or every feed)."""
    dry_run = _eff(ctx, 'dry_run', dry_run, False)
    if all_feeds and (save_dir or feed_id is not None):
        raise typer.BadParameter('--all-feeds cannot be combined with SAVE_DIR or --feed-id')
    keep_n, max_age_delta, max_size_bytes, any_retention = _resolve_retention(
        ctx, keep, keep_last, max_age, max_size
    )
    if not any_retention:
        raise typer.BadParameter('Nothing to do: pass --keep, --keep-last, --max-age or --max-size')

    with db_mod.get_conn(_db_path(ctx)) as conn:
        if all_feeds:
            feeds = db_mod.list_feeds(conn)
            if not feeds:
                typer.echo('No feeds found in database.')
                raise typer.Exit()
            total_kept = total_removed = 0
            for fid, _url, title, feed_dir in feeds:
                if not feed_dir:
                    logging.error('Skipping feed %s (%s): no stored save directory.', fid, title)
                    continue
                kept, removed = prune_feed(
                    conn,
                    fid,
                    feed_dir,
                    keep=keep_n,
                    max_age=max_age_delta,
                    max_size=max_size_bytes,
                    dry_run=dry_run,
                )
                total_kept += kept
                total_removed += removed
                typer.echo(f'[{fid}] {title}: kept {kept}, removed {removed}')
            typer.echo(f'Pruned: kept {total_kept}, removed {total_removed}')
            return
        if not save_dir:
            raise typer.BadParameter('SAVE_DIR is required unless --all-feeds is used')
        if feed_id is None:
            rows = conn.execute('SELECT feed_id, save_dir FROM feeds').fetchall()
            abs_target = os.path.abspath(save_dir)
            matches = [r[0] for r in rows if r[1] and os.path.abspath(r[1]) == abs_target]
            if not matches:
                raise typer.BadParameter(f'No feed found with save_dir {save_dir}')
            feed_id = matches[0]
        kept, removed = prune_feed(
            conn,
            feed_id,
            save_dir,
            keep=keep_n,
            max_age=max_age_delta,
            max_size=max_size_bytes,
            dry_run=dry_run,
        )
    typer.echo(f'Pruned: kept {kept}, removed {removed}')


@opml_app.command('export')
def opml_export(
    ctx: typer.Context,
    output: str = typer.Argument(..., help='Output OPML file.'),
):
    """Export feeds to OPML."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        count = export_opml(conn, output)
    typer.echo(f'Exported {count} feed(s) to {output}')


@opml_app.command('import')
def opml_import(
    ctx: typer.Context,
    input: str = typer.Argument(..., help='Input OPML file.'),
):
    """Import feeds from OPML."""
    with db_mod.get_conn(_db_path(ctx)) as conn:
        imported, skipped = import_opml(conn, input)
    typer.echo(f'Imported {imported} feed(s), skipped {skipped} existing')


def main():
    app()


if __name__ == '__main__':
    main()
