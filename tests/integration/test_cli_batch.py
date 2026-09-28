"""Integration tests for the batch flags (`sync/prune --all-feeds`)."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from typer.testing import CliRunner

from rss_downcast import db as db_mod
from rss_downcast.cli import app

runner = CliRunner()

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Batch Show</title>
    <item>
      <title>Ep 1</title>
      <guid>batch-1</guid>
      <pubDate>Wed, 02 Oct 2002 13:00:00 GMT</pubDate>
      <enclosure url="{base}/ep1.mp3" type="audio/mpeg" length="203"/>
    </item>
  </channel>
</rss>
"""

MP3_BYTES = b'ID3' + b'\x00' * 200


class _Handler(BaseHTTPRequestHandler):
    feed_xml = ''

    def do_GET(self):  # noqa: N802
        if self.path == '/feed.xml':
            body = self.feed_xml.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/rss+xml')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/ep1.mp3':
            self.send_response(200)
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(MP3_BYTES)))
            self.end_headers()
            self.wfile.write(MP3_BYTES)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence request logging
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    _Handler.feed_xml = FEED_XML.format(base=base)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield base
    finally:
        srv.shutdown()
        srv.server_close()


def _register(db_path, url, save_dir):
    conn = db_mod.connect(db_path)
    try:
        return db_mod.get_or_create_feed(conn, url, 'Batch', save_dir=str(save_dir))
    finally:
        conn.close()


def _invoke(*args):
    return runner.invoke(app, ['--quiet', *args])


def test_sync_all_feeds_continues_on_failure(server, tmp_path):
    db_path = str(tmp_path / 'batch.db')
    good_dir = tmp_path / 'good'
    bad_dir = tmp_path / 'bad'
    _register(db_path, f'{server}/feed.xml', good_dir)
    _register(db_path, f'{server}/missing.xml', bad_dir)

    result = _invoke('--db', db_path, 'sync', '--all-feeds', '--all')

    assert result.exit_code == 1, result.output
    assert 'failing' in result.output.lower()
    assert len(list(good_dir.glob('*.mp3'))) == 1
    assert not list(bad_dir.glob('*.mp3'))


def test_prune_all_feeds_keeps_newest(tmp_path):
    db_path = str(tmp_path / 'prune.db')
    conn = db_mod.connect(db_path)
    for i in (1, 2):
        feed_dir = tmp_path / f'f{i}'
        feed_dir.mkdir()
        feed_id = db_mod.get_or_create_feed(conn, f'http://x/{i}', f'F{i}', save_dir=str(feed_dir))
        for n in range(1, 4):
            path = feed_dir / f'ep{n}.mp3'
            path.write_bytes(b'x')
            conn.execute(
                'INSERT INTO episodes (feed_id, guid, title, published, filepath, downloaded_at) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (feed_id, f'g{i}-{n}', f'ep{n}', f'2026-01-0{n}T00:00:00', str(path), 'now'),
            )
        conn.commit()
    conn.close()

    result = _invoke('--db', db_path, 'prune', '--all-feeds', '--keep', '2')

    assert result.exit_code == 0, result.output
    assert 'Pruned' in result.output
    for i in (1, 2):
        assert len(list((tmp_path / f'f{i}').glob('*.mp3'))) == 2


def test_all_feeds_conflicts_with_explicit_target(tmp_path):
    db_path = str(tmp_path / 'conflict.db')
    save_dir = tmp_path / 'dir'
    save_dir.mkdir()

    sync_result = _invoke('--db', db_path, 'sync', 'http://x/feed', str(save_dir), '--all-feeds')
    prune_result = _invoke('--db', db_path, 'prune', str(save_dir), '--all-feeds', '--keep', '2')

    assert sync_result.exit_code != 0
    assert prune_result.exit_code != 0
    assert '--all-feeds' in sync_result.output
    assert '--all-feeds' in prune_result.output
