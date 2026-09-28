"""Unit tests for read-only library inspection (audit module)."""

import pytest

from rss_downcast import audit
from rss_downcast import db as db_mod


@pytest.fixture
def conn(tmp_path):
    connection = db_mod.connect(str(tmp_path / 'test.db'))
    yield connection
    connection.close()


@pytest.fixture
def feed(conn, tmp_path):
    save_dir = tmp_path / 'save'
    save_dir.mkdir()
    feed_id = db_mod.get_or_create_feed(conn, 'http://x/feed', 'Show', save_dir=str(save_dir))
    return feed_id, save_dir


def _add_episode(conn, feed_id, guid, title, published, path):
    conn.execute(
        'INSERT INTO episodes (feed_id, guid, title, published, filepath, downloaded_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (feed_id, guid, title, published, str(path), 'now'),
    )
    conn.commit()


def test_feed_summary_counts_and_sizes(conn, feed):
    feed_id, save_dir = feed
    (save_dir / 'a.mp3').write_bytes(b'x' * 1000)
    (save_dir / 'b.m4a').write_bytes(b'y' * 2000)
    _add_episode(conn, feed_id, 'g1', 'Ep 1', '2026-01-01T00:00:00', save_dir / 'a.mp3')
    _add_episode(conn, feed_id, 'g2', 'Ep 2', '2026-02-01T00:00:00', save_dir / 'b.m4a')

    summary = audit.feed_summary(conn, feed_id)

    assert summary is not None
    assert (summary.episodes, summary.files) == (2, 2)
    assert summary.size_bytes == 3000
    assert summary.missing == 0
    assert summary.orphans == 0
    assert summary.newest == '2026-02-01T00:00:00'


def test_missing_file_is_counted(conn, feed):
    feed_id, save_dir = feed
    _add_episode(conn, feed_id, 'g1', 'Gone', '2026-01-01T00:00:00', save_dir / 'missing.mp3')

    summary = audit.feed_summary(conn, feed_id)

    assert summary.episodes == 1
    assert summary.missing == 1
    assert summary.files == 0


def test_txt_sidecar_is_not_an_orphan(conn, feed):
    feed_id, save_dir = feed
    (save_dir / 'a.mp3').write_bytes(b'x')
    (save_dir / 'a.txt').write_text('sidecar')
    _add_episode(conn, feed_id, 'g1', 'Ep', '2026-01-01T00:00:00', save_dir / 'a.mp3')

    summary = audit.feed_summary(conn, feed_id)

    assert summary.orphans == 0
    assert summary.files == 1  # only the .mp3 is inventoried


def test_untracked_media_is_an_orphan(conn, feed):
    feed_id, save_dir = feed
    (save_dir / 'a.mp3').write_bytes(b'x')
    (save_dir / 'orphan.mp3').write_bytes(b'z')
    _add_episode(conn, feed_id, 'g1', 'Ep', '2026-01-01T00:00:00', save_dir / 'a.mp3')

    summary = audit.feed_summary(conn, feed_id)

    assert summary.orphans == 1


def test_find_orphans_is_scoped_per_feed(conn, tmp_path):
    dir_a = tmp_path / 'a'
    dir_b = tmp_path / 'b'
    dir_a.mkdir()
    dir_b.mkdir()
    feed_a = db_mod.get_or_create_feed(conn, 'http://x/a', 'A', save_dir=str(dir_a))
    feed_b = db_mod.get_or_create_feed(conn, 'http://x/b', 'B', save_dir=str(dir_b))
    (dir_a / 'orphan.mp3').write_bytes(b'a')
    (dir_b / 'other.mp3').write_bytes(b'b')

    orphans_a = audit.find_orphans(conn, feed_a)
    orphans_b = audit.find_orphans(conn, feed_b)

    assert orphans_a == [str(dir_a / 'orphan.mp3')]
    assert orphans_b == [str(dir_b / 'other.mp3')]


def test_list_episodes_limit_and_missing_filter(conn, feed):
    feed_id, save_dir = feed
    (save_dir / 'a.mp3').write_bytes(b'x')
    _add_episode(conn, feed_id, 'g1', 'Present', '2026-01-01T00:00:00', save_dir / 'a.mp3')
    _add_episode(conn, feed_id, 'g2', 'Gone', '2026-02-01T00:00:00', save_dir / 'gone.mp3')
    _add_episode(conn, feed_id, 'g3', 'Newest', '2026-03-01T00:00:00', save_dir / 'gone2.mp3')

    limited = audit.list_episodes(conn, feed_id, limit=2)
    assert [e.title for e in limited] == ['Newest', 'Gone']

    missing = audit.list_episodes(conn, feed_id, missing_only=True)
    assert [e.title for e in missing] == ['Newest', 'Gone']
    assert all(e.exists is False for e in missing)


def test_summaries_all_and_single(conn, tmp_path):
    dir_a = tmp_path / 'a'
    dir_a.mkdir()
    feed_a = db_mod.get_or_create_feed(conn, 'http://x/a', 'A', save_dir=str(dir_a))
    db_mod.get_or_create_feed(conn, 'http://x/b', 'B')

    assert [s.feed_id for s in audit.summaries(conn)] == [feed_a, feed_a + 1]
    assert [s.feed_id for s in audit.summaries(conn, feed_a)] == [feed_a]
    assert audit.summaries(conn, 999) == []


def test_feed_summary_unknown_returns_none(conn):
    assert audit.feed_summary(conn, 123) is None
