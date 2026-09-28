"""Read-only library inspection: per-feed summaries and integrity checks.

Combines DB rows with a filesystem scan of each feed's (flat) save directory.
The CLI is responsible for all rendering; this module returns plain data.
"""

import logging
import os
from dataclasses import dataclass

from rss_downcast import db as db_mod

# Only media files are considered for the on-disk inventory; `.txt` sidecars
# from `--save-text` and other artifacts are deliberately ignored.
AUDIO_EXTS = frozenset({'.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.flac', '.wav', '.aac'})


@dataclass(frozen=True)
class FeedSummary:
    feed_id: int
    title: str
    save_dir: str | None
    episodes: int
    files: int
    size_bytes: int
    newest: str | None
    missing: int
    orphans: int


@dataclass(frozen=True)
class EpisodeInfo:
    feed_id: int
    title: str
    published: str
    size: int
    exists: bool
    filepath: str


def _scan_audio(save_dir):
    """Map absolute path -> size for media files directly under ``save_dir``."""
    found = {}
    if not save_dir or not os.path.isdir(save_dir):
        return found
    try:
        with os.scandir(save_dir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                if os.path.splitext(entry.name)[1].lower() not in AUDIO_EXTS:
                    continue
                path = os.path.abspath(entry.path)
                try:
                    found[path] = entry.stat().st_size
                except OSError:
                    found[path] = 0
    except OSError as e:  # pragma: no cover - unreadable dir
        logging.warning('Could not scan %s: %s', save_dir, e)
    return found


def _episode_rows(conn, feed_id=None):
    return db_mod.list_episodes(conn, feed_id)


def _missing(rows):
    return [r for r in rows if not r['filepath'] or not os.path.exists(r['filepath'])]


def feed_summary(conn, feed_id):
    """Build a :class:`FeedSummary` for one feed, or ``None`` if unknown."""
    feed = conn.execute(
        'SELECT feed_id, feed_title, save_dir FROM feeds WHERE feed_id = ?', (feed_id,)
    ).fetchone()
    if feed is None:
        return None

    rows = _episode_rows(conn, feed_id)
    on_disk = _scan_audio(feed['save_dir'])
    tracked = {os.path.abspath(r['filepath']) for r in rows if r['filepath']}
    orphan_count = sum(1 for path in on_disk if path not in tracked)
    newest = next((r['published'] for r in rows if r['published']), None)

    return FeedSummary(
        feed_id=feed['feed_id'],
        title=feed['feed_title'] or '',
        save_dir=feed['save_dir'],
        episodes=len(rows),
        files=len(on_disk),
        size_bytes=sum(on_disk.values()),
        newest=newest,
        missing=len(_missing(rows)),
        orphans=orphan_count,
    )


def summaries(conn, feed_id=None):
    """Summaries for one feed or all feeds (id order)."""
    if feed_id is not None:
        summary = feed_summary(conn, feed_id)
        return [] if summary is None else [summary]
    ids = [r[0] for r in conn.execute('SELECT feed_id FROM feeds ORDER BY feed_id')]
    return [feed_summary(conn, i) for i in ids]


def list_episodes(conn, feed_id=None, limit=50, missing_only=False):
    """Episode rows as :class:`EpisodeInfo`, newest-first.

    ``limit=0`` means no limit. ``missing_only`` keeps rows whose file is absent.
    """
    result = []
    for row in _episode_rows(conn, feed_id):
        filepath = row['filepath'] or ''
        size = 0
        exists = False
        if filepath:
            try:
                size = os.path.getsize(filepath)
                exists = True
            except OSError:
                exists = False
        if missing_only and exists:
            continue
        result.append(
            EpisodeInfo(
                feed_id=row['feed_id'],
                title=row['title'] or '',
                published=row['published'] or '',
                size=size,
                exists=exists,
                filepath=filepath,
            )
        )
        if limit and len(result) >= limit:
            break
    return result


def find_missing(conn, feed_id=None):
    """Episode rows whose ``filepath`` is empty or no longer exists."""
    return _missing(_episode_rows(conn, feed_id))


def find_orphans(conn, feed_id):
    """Absolute paths of media files under a feed's save_dir not tracked in DB."""
    feed = conn.execute('SELECT save_dir FROM feeds WHERE feed_id = ?', (feed_id,)).fetchone()
    if feed is None or not feed['save_dir']:
        return []
    on_disk = _scan_audio(feed['save_dir'])
    tracked = {
        os.path.abspath(r['filepath']) for r in _episode_rows(conn, feed_id) if r['filepath']
    }
    return sorted(path for path in on_disk if path not in tracked)
