"""RSS fetching, date handling and candidate selection."""

import logging
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlparse

import feedparser
import httpx

from rss_downcast import USER_AGENT

try:
    import requests as _requests

    _FETCH_ERRORS = (httpx.HTTPError, _requests.RequestException)
except ImportError:  # pragma: no cover
    _FETCH_ERRORS = (httpx.HTTPError,)

DATE_FORMATS = [
    '%Y-%m-%d',
    '%a, %d %b %Y %H:%M:%S %Z',
    '%a, %d %b %Y %H:%M:%S %z',
    '%a, %d %b %Y %H:%M:%S',
]


def _naive_utc(dt):
    """Normalize to naive UTC so aware/naive datetimes never mix (no TypeError)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _parse_date(date_str):
    """Parse a date string to a naive-UTC datetime. Returns None if unparseable."""
    if not date_str:
        return None
    for fmt in DATE_FORMATS:
        try:
            return _naive_utc(datetime.strptime(date_str, fmt))
        except ValueError:
            continue
    try:
        return _naive_utc(datetime.fromisoformat(date_str.replace('Z', '+00:00')))
    except ValueError:
        pass
    try:
        return _naive_utc(parsedate_to_datetime(date_str))
    except (TypeError, ValueError):
        return None


def _published_parsed_as_date(entry):
    for key in ('published_parsed', 'updated_parsed'):
        ts = entry.get(key)
        if ts:
            try:
                return datetime(*ts[:6])
            except (TypeError, ValueError):
                continue
    return None


def entry_datetime(entry):
    """Resolve an entry's publication datetime (naive UTC; parsed field, then raw)."""
    return _published_parsed_as_date(entry) or _parse_date(
        entry.get('published') or entry.get('updated')
    )


def entry_date_prefix(entry):
    dt = entry_datetime(entry)
    return dt.strftime('%Y-%m-%d') if dt else None


def fetch_feed(url, client=None, session=None):
    """Fetch raw RSS bytes. Raises SystemExit(1) on network failure."""
    headers = {'User-Agent': USER_AGENT}
    transport = client if client is not None else session
    close = False
    if transport is None:
        transport = httpx.Client(headers=headers, timeout=30, follow_redirects=True)
        close = True
    try:
        response = transport.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.content
    except _FETCH_ERRORS as e:
        logging.error('Error fetching the RSS feed: %s', e)
        logging.error('Please check the URL and authentication token (if applicable)')
        logging.error('Exiting...')
        raise SystemExit(1) from None
    finally:
        if close:
            transport.close()


def parse_feed(content):
    return feedparser.parse(content)


def is_audio_enclosure(link):
    """True for audio/* plus video/mp4|mpeg; extension fallback when typeless."""
    t = getattr(link, 'type', None) or ''
    t = t.lower().strip()
    if t:
        return t.startswith('audio/') or t in ('video/mp4', 'video/mpeg')
    href = getattr(link, 'href', '') or ''
    _, ext = os.path.splitext(urlparse(unquote(href)).path)
    return ext.lower() in ('.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.flac', '.wav', '.aac')


def episode_sort_key(entry_link):
    entry, _link = entry_link
    dt = entry_datetime(entry)
    return dt.timestamp() if dt else 0.0


def get_last_downloaded_date(conn, feed_id):
    """Newest ``published`` datetime already downloaded, or None."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(published) FROM episodes WHERE feed_id = ? AND published != ''",
        (feed_id,),
    )
    value = cursor.fetchone()[0]
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def feed_has_episodes(conn, feed_id):
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM episodes WHERE feed_id = ? LIMIT 1', (feed_id,))
    return cursor.fetchone() is not None


def select_candidates(all_episodes, last_downloaded=None, num_episodes=None, since=None):
    """Pick (entry, link) pairs to consider, newest-first. See spec scenarios."""
    ordered = sorted(all_episodes, key=episode_sort_key, reverse=True)

    if last_downloaded is not None:
        base = [
            pair
            for pair in ordered
            if (dt := entry_datetime(pair[0])) is None or dt > last_downloaded
        ]
    else:
        base = ordered

    if since is not None:
        base = [
            pair for pair in base if (dt := entry_datetime(pair[0])) is not None and dt >= since
        ]

    if num_episodes is not None and num_episodes < 1:
        return []
    if num_episodes is not None:
        return base[:num_episodes]
    return base
