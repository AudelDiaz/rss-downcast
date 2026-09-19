"""Filenames, MP3 tags and .txt sidecars."""

import logging
import os
import re
import unicodedata
import uuid
from urllib.parse import unquote, urlparse

from mutagen.id3 import COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2
from mutagen.mp3 import MP3

from rss_downcast.feed import _published_parsed_as_date, entry_date_prefix


def _sanitize_basename(title):
    if not title:
        return 'untitled'
    if not isinstance(title, str):
        title = str(title)
    try:
        normalized = unicodedata.normalize('NFKD', title)
        ascii_title = normalized.encode('ascii', 'ignore').decode('ascii')
    except Exception as e:  # pragma: no cover - defensive
        logging.warning("Could not normalize title '%s'. Using it as is. Error: %s", title, e)
        ascii_title = title
    sanitized = ascii_title.replace(' ', '_')
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '', sanitized)
    sanitized = re.sub(r'__+', '_', sanitized)
    sanitized = re.sub(r'--+', '-', sanitized)
    sanitized = sanitized.strip('_-')
    if not sanitized:
        sanitized = 'untitled'
    return sanitized.lower()


def sanitize_title(title, date_str=None):
    """Filesystem-friendly name with optional date prefix (raw or YYYY-MM-DD)."""
    from rss_downcast.feed import _parse_date

    sanitized = _sanitize_basename(title)
    if date_str:
        dt = _parse_date(date_str)
        if dt is not None:
            sanitized = f'{dt.strftime("%Y-%m-%d")}_{sanitized}'
        else:
            logging.warning(
                "Could not parse date: '%s'. Filename will not have a date prefix.", date_str
            )
    return sanitized


def sanitize_filename_from_entry(entry):
    prefix = entry_date_prefix(entry)
    return sanitize_title(entry.get('title', 'untitled'), prefix)


def truncate_basename(basename, limit=200):
    if len(basename) > limit:
        basename = basename[:limit].rstrip('_-')
    return basename or 'untitled'


def extension_for_link(link):
    parsed = urlparse(unquote(link.href))
    _, ext = os.path.splitext(parsed.path)
    if ext:
        return ext
    lt = (getattr(link, 'type', '') or '').lower()
    if lt.startswith('audio/'):
        return '.mp3'
    if lt.startswith('video/'):
        return '.mp4'
    return '.mp3'


def unique_filepath(save_dir, basename, ext):
    candidate = os.path.join(save_dir, basename + ext)
    if not os.path.exists(candidate):
        return candidate
    counter = 2
    while True:
        candidate = os.path.join(save_dir, f'{basename}_{counter}{ext}')
        if not os.path.exists(candidate):
            return candidate
        counter += 1
        if counter > 1000:
            candidate = os.path.join(save_dir, f'{basename}_{uuid.uuid4().hex[:8]}{ext}')
            if not os.path.exists(candidate):
                return candidate
            continue


def save_text_file(entry, filename):
    base, ext = os.path.splitext(filename)
    txt_path = f'{base}.txt' if ext else f'{filename}.txt'
    with open(txt_path, 'w', encoding='utf-8') as file:
        file.write(f'Title: {entry.get("title", "N/A")}\n')
        file.write(f'Subtitle: {entry.get("subtitle", "N/A")}\n')
        file.write(f'Published Date: {entry.get("published", "N/A")}\n')
        file.write(f'Content: {entry.get("summary", "N/A")}\n')


def set_mp3_tags(filename, entry, feed):
    """Best-effort ID3 tagging; failures are logged, never raised."""
    try:
        audio = MP3(filename, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        if 'title' in feed.feed:
            audio.tags.add(TALB(encoding=3, text=feed.feed.title))
        artist = entry.get('author') or feed.feed.get('author')
        if artist:
            audio.tags.add(TPE1(encoding=3, text=artist))
            audio.tags.add(TPE2(encoding=3, text=artist))
        if 'title' in entry:
            audio.tags.add(TIT2(encoding=3, text=entry.title))
        pub_date = _published_parsed_as_date(entry)
        if pub_date is not None:
            audio.tags.add(TDRC(encoding=3, text=pub_date.strftime('%Y-%m-%dT%H:%M:%S')))
        summary = entry.get('summary')
        if summary:
            audio.tags.add(COMM(encoding=3, lang='eng', text=summary))
        if hasattr(feed.feed, 'tags') and feed.feed.tags:
            audio.tags.add(TCON(encoding=3, text=feed.feed.tags[0].term))
        audio.save()
        logging.info('Successfully set MP3 tags for: %s', filename)
    except Exception as e:  # pragma: no cover - depends on file/mp3 internals
        logging.error('Could not tag file (continuing): %s - %s', filename, e)
