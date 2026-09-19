"""Shared pytest fixtures for the rss-downcast package.

The ``mod`` fixture exposes a compatibility namespace with the legacy
(single-file) attribute names so the v1 test-suite keeps exercising the same
behaviors against the new ``rss_downcast`` package layout.
"""

import sys
import types
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from rss_downcast import __version__  # noqa: E402
from rss_downcast import config as _config  # noqa: E402
from rss_downcast import db as _db  # noqa: E402
from rss_downcast import download as _download  # noqa: E402
from rss_downcast import feed as _feed  # noqa: E402
from rss_downcast import media as _media  # noqa: E402
from rss_downcast import opml as _opml  # noqa: E402
from rss_downcast import retention as _retention  # noqa: E402
from rss_downcast import sync as _sync  # noqa: E402


class _RequestsCompat(types.SimpleNamespace):
    """Duck-typed ``requests`` exposing RequestException as httpx-compatible."""

    RequestException = httpx.HTTPError


def _setup_database(db_path=None):
    return _db.connect(db_path)


def _list_feeds(db_path=None):
    conn = _db.connect(db_path)
    try:
        rows = _db.list_feeds(conn)
    finally:
        conn.close()
    if not rows:
        print('No feeds found in database.')
        return
    for feed_id, feed_url, feed_title, save_dir in rows:
        print(f'{feed_id} | {feed_url} | {feed_title} | {save_dir or ""}')


def _export_opml(db_path=None, output_path=None):
    if db_path is not None and not Path(db_path).exists():
        conn = _db.connect(':memory:')
    else:
        conn = _db.connect(db_path)
    try:
        return _opml.export_opml(conn, output_path)
    finally:
        conn.close()


def _import_opml(db_path=None, input_path=None):
    conn = _db.connect(db_path)
    try:
        return _opml.import_opml(conn, input_path)
    finally:
        conn.close()


def _parse_and_download(
    save_dir,
    save_text,
    num_episodes=None,
    conn=None,
    feed_id=None,
    feed=None,
    session=None,
    since=None,
    full_history=False,
    dry_run=False,
):
    return _sync.run_sync(
        conn,
        feed_id,
        feed,
        save_dir,
        save_text=save_text,
        num_episodes=num_episodes,
        since=since,
        full_history=full_history,
        dry_run=dry_run,
        client=session,
    )


@pytest.fixture(scope='session')
def mod():
    """Return the compat namespace, built once per session."""
    return types.SimpleNamespace(
        __version__=__version__,
        requests=_RequestsCompat(),
        # config
        find_config_path=_config.find_config_path,
        load_config=_config.load_config,
        # db
        setup_database=_setup_database,
        get_or_create_feed=_db.get_or_create_feed,
        get_feed_url_by_id=_db.get_feed_url_by_id,
        get_feed_save_dir=_db.get_feed_save_dir,
        set_feed_save_dir=_db.set_feed_save_dir,
        list_feeds=_list_feeds,
        remove_feed=_db.remove_feed,
        # opml
        export_opml=_export_opml,
        import_opml=_import_opml,
        # feed
        fetch_rss_feed=_feed.fetch_feed,
        _parse_date=_feed._parse_date,
        _published_parsed_as_date=_feed._published_parsed_as_date,
        _entry_datetime=_feed.entry_datetime,
        entry_date_prefix=_feed.entry_date_prefix,
        _is_audio_enclosure=_feed.is_audio_enclosure,
        _episode_sort_key=_feed.episode_sort_key,
        _get_last_downloaded_date=_feed.get_last_downloaded_date,
        _feed_has_episodes=_feed.feed_has_episodes,
        _select_candidates=_feed.select_candidates,
        # download
        download_file=_download.download_file,
        # media
        sanitize_title=_media.sanitize_title,
        sanitize_filename_from_entry=_media.sanitize_filename_from_entry,
        _unique_filepath=_media.unique_filepath,
        save_text_file=_media.save_text_file,
        set_mp3_tags=_media.set_mp3_tags,
        # retention
        parse_size=_retention.parse_size,
        parse_max_age=_retention.parse_max_age,
        prune_feed=_retention.prune_feed,
        prune_to_keep_last=_retention.prune_to_keep_last,
        # sync
        parse_and_download=_parse_and_download,
    )
