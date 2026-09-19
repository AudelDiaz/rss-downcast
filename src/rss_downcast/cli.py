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
opml_app = typer.Typer(help='OPML backup / migration.')
app.add_typer(feeds_app, name='feeds')
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


def _eff(ctx: typer.Context, name: str, cli_value, default=None):
    """CLI wins when set; otherwise TOML config; otherwise default.

    Note: a `false` CLI default cannot negate a `true` config value for a
    single run (Typer 0.27 has no parameter-source API); edit the config
    or pass the positive flag explicitly.
    """
    if cli_value is not None and cli_value is not False:
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
    keep = _eff(ctx, 'keep', keep)
    keep_last = _eff(ctx, 'keep_last', keep_last, False)
    max_age_s = _eff(ctx, 'max_age', max_age)
    max_size_s = _eff(ctx, 'max_size', max_size)

    if num_episodes is not None and num_episodes < 1:
        raise typer.BadParameter('--num-episodes must be a positive integer')
    if keep is not None and keep_last:
        raise typer.BadParameter('--keep and --keep-last are mutually exclusive')
    keep = _coerce_keep(keep)
    try:
        max_age_delta = parse_max_age(max_age_s) if max_age_s else None
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    try:
        max_size_bytes = parse_size(max_size_s) if max_size_s else None
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if max_size_bytes is not None and max_size_bytes < 1:
        raise typer.BadParameter('--max-size must be >=1 byte')
    since_date = _parse_since(since_s)

    db_path = _db_path(ctx)
    with db_mod.get_conn(db_path) as conn:
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
        _, _, feed_id = sync_mod.sync_url(
            url,
            save_dir,
            conn=conn,
            save_text=save_text,
            num_episodes=num_episodes,
            since=since_date,
            full_history=full_history,
            dry_run=dry_run,
        )
        if keep is not None or keep_last or max_age_delta is not None or max_size_bytes is not None:
            keep_n = keep if keep is not None else (1 if keep_last else None)
            prune_feed(
                conn,
                feed_id,
                save_dir,
                keep=keep_n,
                max_age=max_age_delta,
                max_size=max_size_bytes,
                dry_run=dry_run,
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
def prune(
    ctx: typer.Context,
    save_dir: str = typer.Argument(..., help='Feed save directory.'),
    feed_id: int | None = typer.Option(None, '--feed-id', help='Feed ID (else match by dir).'),
    keep: int | None = typer.Option(None, '--keep', metavar='N'),
    keep_last: bool = typer.Option(False, '--keep-last'),
    max_age: str | None = typer.Option(None, '--max-age', metavar='DAYS'),
    max_size: str | None = typer.Option(None, '--max-size', metavar='SIZE'),
    dry_run: bool = typer.Option(False, '--dry-run'),
):
    """Prune episode files/rows for a feed directory."""
    keep = _eff(ctx, 'keep', keep)
    keep_last = _eff(ctx, 'keep_last', keep_last, False)
    max_age_s = _eff(ctx, 'max_age', max_age)
    max_size_s = _eff(ctx, 'max_size', max_size)
    dry_run = _eff(ctx, 'dry_run', dry_run, False)

    if keep is not None and keep_last:
        raise typer.BadParameter('--keep and --keep-last are mutually exclusive')
    keep = _coerce_keep(keep)
    try:
        max_age_delta = parse_max_age(max_age_s) if max_age_s else None
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    try:
        max_size_bytes = parse_size(max_size_s) if max_size_s else None
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if keep is None and not keep_last and max_age_delta is None and max_size_bytes is None:
        raise typer.BadParameter('Nothing to do: pass --keep, --keep-last, --max-age or --max-size')

    with db_mod.get_conn(_db_path(ctx)) as conn:
        if feed_id is None:
            rows = conn.execute('SELECT feed_id, save_dir FROM feeds').fetchall()
            abs_target = os.path.abspath(save_dir)
            matches = [r[0] for r in rows if r[1] and os.path.abspath(r[1]) == abs_target]
            if not matches:
                raise typer.BadParameter(f'No feed found with save_dir {save_dir}')
            feed_id = matches[0]
        keep_n = keep if keep is not None else (1 if keep_last else None)
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
