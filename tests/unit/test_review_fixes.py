"""Regression tests for the v2.0.1 review fixes.

Covers retention flag precedence (CLI beats TOML, mutual exclusion on the
command line only) and duplicate-GUID orphan cleanup.
"""

import time

import feedparser
import httpx
from typer.testing import CliRunner

from rss_downcast import db as db_mod
from rss_downcast import sync as sync_mod
from rss_downcast.cli import app

runner = CliRunner()


def _seed_feed(db_path, save_dir):
    conn = db_mod.connect(db_path)
    try:
        return db_mod.get_or_create_feed(conn, 'http://x/feed', 'Show', save_dir=str(save_dir))
    finally:
        conn.close()


def _write_config(tmp_path, body):
    cfg = tmp_path / 'rss-downcast.toml'
    cfg.write_text(body, encoding='utf-8')
    return str(cfg)


def _empty_feed_dir(tmp_path):
    save_dir = tmp_path / 'podcasts'
    save_dir.mkdir()
    db_path = str(tmp_path / 't.db')
    _seed_feed(db_path, save_dir)
    return db_path, save_dir


def test_keep_last_overrides_config_keep(tmp_path):
    """Config `keep` must not make `--keep-last` fail as mutually exclusive."""
    db_path, save_dir = _empty_feed_dir(tmp_path)
    cfg = _write_config(tmp_path, '[defaults]\nkeep = 5\n')

    result = runner.invoke(
        app, ['--config', cfg, '--db', db_path, 'prune', str(save_dir), '--keep-last']
    )

    assert result.exit_code == 0, result.output
    assert 'kept' in result.output.lower()


def test_cli_keep_overrides_config_keep_last(tmp_path):
    """Config `keep_last` must not make `--keep 3` fail as mutually exclusive."""
    db_path, save_dir = _empty_feed_dir(tmp_path)
    cfg = _write_config(tmp_path, '[defaults]\nkeep_last = true\n')

    result = runner.invoke(
        app, ['--config', cfg, '--db', db_path, 'prune', str(save_dir), '--keep', '3']
    )

    assert result.exit_code == 0, result.output


def test_both_keep_flags_on_cli_conflict(tmp_path):
    db_path, save_dir = _empty_feed_dir(tmp_path)

    result = runner.invoke(
        app, ['--db', db_path, 'prune', str(save_dir), '--keep', '3', '--keep-last']
    )

    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output


def test_config_both_keys_conflict(tmp_path):
    """A config that sets keep and keep_last is a clear error, not a silent pick."""
    db_path, save_dir = _empty_feed_dir(tmp_path)
    cfg = _write_config(tmp_path, '[defaults]\nkeep = 5\nkeep_last = true\n')

    result = runner.invoke(app, ['--config', cfg, '--db', db_path, 'prune', str(save_dir)])

    assert result.exit_code != 0
    assert 'keep_last' in result.output


def test_max_size_zero_rejected_by_prune(tmp_path):
    db_path, save_dir = _empty_feed_dir(tmp_path)

    result = runner.invoke(app, ['--db', db_path, 'prune', str(save_dir), '--max-size', '0'])

    assert result.exit_code != 0
    assert 'max-size' in result.output.lower()


def test_max_size_zero_rejected_by_sync_before_fetch(tmp_path):
    """Validation runs before any network/database work in `sync`."""
    result = runner.invoke(
        app,
        [
            '--db',
            str(tmp_path / 't.db'),
            'sync',
            'http://127.0.0.1:9/feed.xml',
            str(tmp_path / 'out'),
            '--max-size',
            '0',
        ],
    )

    assert result.exit_code != 0
    assert 'max-size' in result.output.lower()


class _Link:
    def __init__(self, href, ctype='audio/mpeg'):
        self.href = href
        self.type = ctype


def _mock_client():
    def handler(request):
        return httpx.Response(200, headers={'Content-Type': 'audio/mpeg'}, content=b'ID3' * 16)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_duplicate_guid_leaves_no_orphan_file(tmp_path, monkeypatch):
    """A duplicate GUID must not leave the just-downloaded file on disk."""
    monkeypatch.setattr(sync_mod.time, 'sleep', lambda *_: None)
    save_dir = tmp_path / 'podcasts'
    save_dir.mkdir()
    db_path = str(tmp_path / 't.db')
    feed = feedparser.FeedParserDict(
        {
            'feed': {'title': 'Show'},
            'entries': [
                feedparser.FeedParserDict(
                    {
                        'title': 'Dup Episode',
                        'id': 'dup-guid',
                        'published_parsed': time.struct_time((2022, 10, 2, 0, 0, 0, 0, 0, -1)),
                        'links': [_Link('http://x/a.mp3'), _Link('http://x/b.mp3')],
                    }
                )
            ],
        }
    )
    conn = db_mod.connect(db_path)
    feed_id = db_mod.get_or_create_feed(conn, 'http://x/feed', 'Show', save_dir=str(save_dir))
    with _mock_client() as client:
        considered, downloaded = sync_mod.run_sync(
            conn, feed_id, feed, str(save_dir), full_history=True, client=client
        )
    conn.close()

    assert downloaded == 1
    assert sorted(p.name for p in save_dir.iterdir()) == ['2022-10-02_dup_episode.mp3']

    check = db_mod.connect(db_path)
    try:
        count = check.execute('SELECT COUNT(*) FROM episodes').fetchone()[0]
    finally:
        check.close()
    assert count == 1
