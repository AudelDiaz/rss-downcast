"""Sync orchestration: select → download → tag → record."""

import logging
import os
import time
from datetime import datetime

from rss_downcast import db as db_mod
from rss_downcast.download import download_file
from rss_downcast.feed import (
    entry_datetime,
    feed_has_episodes,
    fetch_feed,
    get_last_downloaded_date,
    is_audio_enclosure,
    parse_feed,
    select_candidates,
)
from rss_downcast.media import (
    extension_for_link,
    sanitize_filename_from_entry,
    save_text_file,
    set_mp3_tags,
    truncate_basename,
    unique_filepath,
)


def collect_episodes(feed):
    return [
        (entry, link)
        for entry in feed.entries
        for link in entry.get('links', [])
        if is_audio_enclosure(link)
    ]


def preview_episodes(episodes, save_dir):
    for entry, link in episodes:
        fn = truncate_basename(sanitize_filename_from_entry(entry))
        ext = extension_for_link(link)
        preview = (
            unique_filepath(save_dir, fn, ext)
            if os.path.exists(os.path.join(save_dir, fn + ext))
            else os.path.join(save_dir, fn + ext)
        )
        logging.info('  - %s  [%s] -> %s', fn, link.href, preview)


def run_sync(
    conn,
    feed_id,
    feed,
    save_dir,
    save_text=False,
    num_episodes=None,
    since=None,
    full_history=False,
    dry_run=False,
    client=None,
):
    """Sync one feed. Returns (considered, downloaded)."""
    if num_episodes is not None and num_episodes < 1:
        logging.error(
            '--num-episodes must be a positive integer (got %s). Nothing to download.',
            num_episodes,
        )
        return (0, 0)

    all_episodes = collect_episodes(feed)
    last_downloaded = get_last_downloaded_date(conn, feed_id)
    if last_downloaded is not None:
        logging.info(
            'Newest already-downloaded episode for this feed: %s',
            last_downloaded.isoformat(),
        )
    else:
        logging.info('No prior downloads for this feed.')

    has_any = feed_has_episodes(conn, feed_id)
    if not has_any and not full_history and num_episodes is None and since is None:
        logging.info(
            'This feed has no downloads yet. Nothing downloaded: pass --num-episodes N, '
            '--since YYYY-MM-DD, or --all to seed it (otherwise no episodes are fetched).'
        )
        return (0, 0)

    episodes_to_consider = select_candidates(
        all_episodes, last_downloaded, num_episodes, since=since
    )

    cursor = conn.cursor()
    episodes_to_download = []
    for entry, link in episodes_to_consider:
        guid = entry.get('id', link.href)
        cursor.execute('SELECT guid FROM episodes WHERE feed_id = ? AND guid = ?', (feed_id, guid))
        if not cursor.fetchone():
            episodes_to_download.append((entry, link))

    logging.info(
        'Found %s total episodes. Considering %s. Found %s new episodes to download.',
        len(all_episodes),
        len(episodes_to_consider),
        len(episodes_to_download),
    )

    if dry_run:
        if not episodes_to_download:
            logging.info('DRY-RUN: nothing would be downloaded.')
        else:
            logging.info('DRY-RUN: would download %s episode(s):', len(episodes_to_download))
            preview_episodes(episodes_to_download, save_dir)
        return (len(episodes_to_consider), 0)

    successful = 0
    total = len(episodes_to_download)
    for i, (entry, link) in enumerate(episodes_to_download):
        filename = truncate_basename(sanitize_filename_from_entry(entry))
        ext = extension_for_link(link)
        full_path = unique_filepath(save_dir, filename, ext)
        logging.info('Downloading audio file %s of %s: %s', i + 1, total, filename)
        if download_file(link.href, full_path, client=client):
            guid = entry.get('id', link.href)
            pub_date = entry_datetime(entry)
            published_iso = pub_date.strftime('%Y-%m-%dT%H:%M:%S') if pub_date else ''
            title = entry.get('title', 'untitled')
            try:
                cursor.execute(
                    'INSERT INTO episodes '
                    '(feed_id, guid, title, published, filepath, downloaded_at) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        feed_id,
                        guid,
                        title,
                        published_iso,
                        full_path,
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
                successful += 1
            except Exception:  # sqlite3.IntegrityError (duck-typed for test doubles)
                logging.warning(
                    'Episode with GUID %s already in database for this feed. Skipping.',
                    guid,
                )
                continue
            if full_path.lower().endswith('.mp3'):
                set_mp3_tags(full_path, entry, feed)
            if save_text:
                save_text_file(entry, full_path)
        if i < total - 1:
            logging.info('Sleeping for 1 second...')
            time.sleep(1)

    logging.info('Completed! Successfully downloaded %s / %s audio files', successful, total)
    return (len(episodes_to_consider), successful)


def sync_url(
    rss_url,
    save_dir,
    conn=None,
    save_text=False,
    num_episodes=None,
    since=None,
    full_history=False,
    dry_run=False,
    client=None,
):
    """Fetch URL, ensure feed row, run sync. Returns (considered, downloaded, feed_id)."""
    os.makedirs(save_dir, exist_ok=True)
    content = fetch_feed(rss_url, client=client)
    feed = parse_feed(content)
    close_conn = conn is None
    if close_conn:
        conn = db_mod.connect()
    try:
        feed_id = db_mod.get_or_create_feed(
            conn, rss_url, feed.feed.get('title', 'N/A'), save_dir=save_dir
        )
        considered, downloaded = run_sync(
            conn,
            feed_id,
            feed,
            save_dir,
            save_text=save_text,
            num_episodes=num_episodes,
            since=since,
            full_history=full_history,
            dry_run=dry_run,
            client=client,
        )
        return (considered, downloaded, feed_id)
    finally:
        if close_conn:
            conn.close()
