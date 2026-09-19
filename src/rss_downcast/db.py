"""SQLite persistence for rss-downcast (v2 schema, no legacy migration)."""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from rss_downcast import DEFAULT_APP_DIR_NAME, DEFAULT_DB_NAME

SCHEMA_FEEDS = """
CREATE TABLE IF NOT EXISTS feeds (
    feed_id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_url TEXT UNIQUE NOT NULL,
    feed_title TEXT,
    save_dir TEXT,
    created_at TEXT NOT NULL DEFAULT ''
)
"""

SCHEMA_EPISODES = """
CREATE TABLE IF NOT EXISTS episodes (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL REFERENCES feeds (feed_id) ON DELETE CASCADE,
    guid TEXT NOT NULL,
    title TEXT,
    published TEXT,
    filepath TEXT,
    downloaded_at TEXT,
    UNIQUE (feed_id, guid)
)
"""


def default_db_path():
    """Default v2 database location under the user's data dir."""
    xdg = os.environ.get('XDG_DATA_HOME')
    base = Path(xdg) if xdg else Path.home() / '.local' / 'share'
    return base / DEFAULT_APP_DIR_NAME / DEFAULT_DB_NAME


def init_schema(conn):
    cursor = conn.cursor()
    cursor.execute(SCHEMA_FEEDS)
    cursor.execute(SCHEMA_EPISODES)
    conn.commit()
    return conn


def connect(db_path=None):
    """Open a connection and ensure the v2 schema exists. Caller owns close()."""
    path = Path(db_path) if db_path else default_db_path()
    if str(path) != ':memory:':
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    logging.info('Database setup complete at %s', path)
    return conn


@contextmanager
def get_conn(db_path=None):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_or_create_feed(conn, feed_url, feed_title, save_dir=None):
    """Get the ``feed_id`` for a ``feed_url``, creating the feed if needed."""
    cursor = conn.cursor()
    cursor.execute('SELECT feed_id FROM feeds WHERE feed_url = ?', (feed_url,))
    result = cursor.fetchone()
    save_dir = os.path.abspath(save_dir) if save_dir else None
    if result:
        feed_id = result[0]
        if save_dir is not None:
            set_feed_save_dir(conn, feed_id, save_dir)
        return feed_id
    cursor.execute(
        'INSERT INTO feeds (feed_url, feed_title, save_dir, created_at) VALUES (?, ?, ?, ?)',
        (feed_url, feed_title, save_dir, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    logging.info('Added new feed to database: %s', feed_title)
    return cursor.lastrowid


def get_feed_save_dir(conn, feed_id):
    cursor = conn.cursor()
    cursor.execute('SELECT save_dir FROM feeds WHERE feed_id = ?', (feed_id,))
    result = cursor.fetchone()
    value = result[0] if result else None
    return value or None


def set_feed_save_dir(conn, feed_id, save_dir):
    if not save_dir:
        return
    abs_dir = os.path.abspath(save_dir)
    cursor = conn.cursor()
    cursor.execute('UPDATE feeds SET save_dir = ? WHERE feed_id = ?', (abs_dir, feed_id))
    conn.commit()


def list_feeds(conn):
    """Return all feeds as (feed_id, feed_url, feed_title, save_dir) rows."""
    return conn.execute(
        'SELECT feed_id, feed_url, feed_title, save_dir FROM feeds ORDER BY feed_id'
    ).fetchall()


def get_feed_url_by_id(conn, feed_id):
    cursor = conn.cursor()
    cursor.execute('SELECT feed_url FROM feeds WHERE feed_id = ?', (feed_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def remove_feed(conn, feed_id, delete_files=False):
    """Remove a feed and its episodes. Returns True if the feed existed."""
    cursor = conn.cursor()
    cursor.execute('SELECT save_dir FROM feeds WHERE feed_id = ?', (feed_id,))
    row = cursor.fetchone()
    if not row:
        return False
    save_dir = row[0]

    filepaths = []
    if delete_files and save_dir:
        filepaths = [
            r[0]
            for r in cursor.execute(
                'SELECT filepath FROM episodes WHERE feed_id = ?', (feed_id,)
            ).fetchall()
            if r[0]
        ]

    cursor.execute('DELETE FROM episodes WHERE feed_id = ?', (feed_id,))
    cursor.execute('DELETE FROM feeds WHERE feed_id = ?', (feed_id,))

    if delete_files and save_dir and filepaths:
        abs_save = os.path.abspath(save_dir)
        for fp in filepaths:
            try:
                abs_fp = os.path.abspath(fp)
                if os.path.commonpath([abs_save, abs_fp]) == abs_save and os.path.exists(fp):
                    os.remove(fp)
                    logging.info('Removed file for deleted feed %s: %s', feed_id, fp)
            except (OSError, ValueError):
                pass

    conn.commit()
    logging.info(
        'Removed feed %s (%s episode(s))', feed_id, len(filepaths) if delete_files else 'unknown'
    )
    return True
