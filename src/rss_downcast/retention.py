"""Retention parsing and pruning (keep / max-age / max-size)."""

import logging
import os
import re
from datetime import datetime, timedelta


def parse_size(value):
    """Parse human size string to bytes. Accepts 500, 500K, 500M, 2G (1024-base)."""
    s = str(value).strip().lower()
    if not s:
        raise ValueError('empty size')
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([kmg]?b?)?$', s)
    if not m:
        raise ValueError(f'Invalid size: {value!r}')
    num = float(m.group(1))
    unit = (m.group(2) or '').strip()
    mult = 1
    if unit.startswith('k'):
        mult = 1024
    elif unit.startswith('m'):
        mult = 1024**2
    elif unit.startswith('g'):
        mult = 1024**3
    return int(num * mult)


def parse_max_age(value):
    """Parse age string to timedelta. Accepts '30', '30d', '30days' (days)."""
    s = str(value).strip().lower()
    m = re.match(r'^(\d+)\s*(d|day|days)?$', s)
    if not m:
        raise ValueError(f'Invalid max-age: {value!r}')
    days = int(m.group(1))
    if days < 1:
        raise ValueError('max-age must be >=1 day')
    return timedelta(days=days)


def prune_feed(conn, feed_id, save_dir, keep=None, max_age=None, max_size=None, dry_run=False):
    """Flexible retention: keep N newest, drop older than max_age, cap total size.

    Returns (kept_count, removed_count).
    """
    cursor = conn.cursor()
    cursor.execute(
        'SELECT episode_id, filepath, published FROM episodes WHERE feed_id = ? '
        'ORDER BY published DESC, episode_id DESC',
        (feed_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return (0, 0)

    cutoff = None
    if max_age is not None:
        if isinstance(max_age, timedelta):
            cutoff = datetime.utcnow() - max_age
        elif isinstance(max_age, datetime):
            cutoff = max_age
        else:
            raise TypeError('max_age must be timedelta or datetime')

    if keep is not None:
        if keep < 1:
            raise ValueError('--keep must be >=1')
        kept_rows = rows[:keep]
        removed_rows = rows[keep:]
    else:
        kept_rows = list(rows)
        removed_rows = []

    if cutoff is not None:
        still_kept = []
        for eid, fp, pub in kept_rows:
            if not pub:
                still_kept.append((eid, fp, pub))
                continue
            try:
                dt = datetime.fromisoformat(pub)
            except (ValueError, TypeError):
                still_kept.append((eid, fp, pub))
                continue
            if dt < cutoff:
                removed_rows.append((eid, fp, pub))
            else:
                still_kept.append((eid, fp, pub))
        kept_rows = still_kept

    if max_size is not None:
        acc = 0
        sized_kept = []
        sized_removed = []
        for eid, fp, pub in kept_rows:
            sz = 0
            if fp and os.path.exists(fp):
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    sz = 0
            if acc + sz <= max_size or not sized_kept:
                sized_kept.append((eid, fp, pub))
                acc += sz
            else:
                sized_removed.append((eid, fp, pub))
        removed_rows = sized_removed + removed_rows
        kept_rows = sized_kept

    if not removed_rows:
        return (len(kept_rows), 0)

    kept_paths = {os.path.abspath(fp) for _, fp, _ in kept_rows if fp}
    if dry_run:
        logging.info(
            'DRY-RUN prune: would keep %s, remove %s (keep=%s max_age=%s max_size=%s)',
            len(kept_rows),
            len(removed_rows),
            keep,
            max_age,
            max_size,
        )
        for eid, fp, pub in removed_rows:
            logging.info('  would remove episode_id=%s filepath=%s published=%s', eid, fp, pub)
        return (len(kept_rows), len(removed_rows))

    removed = 0
    abs_save = os.path.abspath(save_dir)
    for eid, fp, _pub in removed_rows:
        cursor.execute('DELETE FROM episodes WHERE episode_id = ?', (eid,))
        removed += 1
        if fp and os.path.abspath(fp) not in kept_paths:
            try:
                same_root = os.path.commonpath([abs_save, os.path.abspath(fp)]) == abs_save
                if same_root and os.path.exists(fp):
                    os.remove(fp)
                    logging.info('Removed pruned file: %s', fp)
            except (OSError, ValueError):
                pass
    conn.commit()
    if removed:
        logging.info('Pruned %s old episode(s); keeping %s newest.', removed, len(kept_rows))
    return (len(kept_rows), removed)


def prune_to_keep_last(conn, feed_id, save_dir):
    """Keep only the newest downloaded episode row (and file) for a feed."""
    return prune_feed(conn, feed_id, save_dir, keep=1)
