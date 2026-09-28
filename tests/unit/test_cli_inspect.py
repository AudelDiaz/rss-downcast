"""CLI tests for `status`, `episodes list` and `verify`."""

from typer.testing import CliRunner

from rss_downcast import db as db_mod
from rss_downcast.cli import app

runner = CliRunner()


def _seed(tmp_path, *, missing=True, orphan=True):
    db_path = str(tmp_path / 't.db')
    save_dir = tmp_path / 'save'
    save_dir.mkdir()
    conn = db_mod.connect(db_path)
    feed_id = db_mod.get_or_create_feed(conn, 'http://x/feed', 'Show', save_dir=str(save_dir))
    (save_dir / 'a.mp3').write_bytes(b'x' * 1000)
    conn.execute(
        'INSERT INTO episodes (feed_id, guid, title, published, filepath, downloaded_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (feed_id, 'g1', 'Ep 1', '2026-01-01T00:00:00', str(save_dir / 'a.mp3'), 'now'),
    )
    if missing:
        conn.execute(
            'INSERT INTO episodes (feed_id, guid, title, published, filepath, downloaded_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (feed_id, 'g2', 'Ep 2 gone', '2026-02-01T00:00:00', str(save_dir / 'gone.mp3'), 'now'),
        )
    if orphan:
        (save_dir / 'orphan.mp3').write_bytes(b'z' * 10)
    conn.commit()
    conn.close()
    return db_path, save_dir, feed_id


def _invoke(*args):
    return runner.invoke(app, ['--quiet', *args])


def test_status_reports_totals(tmp_path):
    db_path, _save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'status')

    assert result.exit_code == 0
    assert 'TOTAL: 1 feed(s), 2 episode(s)' in result.output
    assert 'missing=1' in result.output
    assert 'orphans=1' in result.output
    assert 'Show' in result.output


def test_episodes_list_marks_missing(tmp_path):
    db_path, _save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'episodes', 'list')

    assert result.exit_code == 0
    assert 'Ep 1' in result.output
    assert 'MISSING' in result.output
    assert 'OK' in result.output


def test_episodes_list_missing_filter(tmp_path):
    db_path, _save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'episodes', 'list', '--missing')

    assert result.exit_code == 0
    assert 'Ep 2 gone' in result.output
    assert 'Ep 1' not in result.output


def test_episodes_list_rejects_negative_limit(tmp_path):
    db_path, _save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'episodes', 'list', '--limit', '-1')

    assert result.exit_code != 0


def test_verify_reports_and_exits_nonzero(tmp_path):
    db_path, save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'verify')

    assert result.exit_code == 1
    assert 'missing' in result.output
    assert 'orphan' in result.output
    # Report-only: nothing was changed.
    assert (save_dir / 'orphan.mp3').exists()


def test_verify_fix_removes_dead_rows_only(tmp_path):
    db_path, save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'verify', '--fix')

    assert result.exit_code == 1  # orphan still unfixed
    conn = db_mod.connect(db_path)
    try:
        titles = [r[0] for r in conn.execute('SELECT title FROM episodes')]
    finally:
        conn.close()
    assert titles == ['Ep 1']
    assert (save_dir / 'orphan.mp3').exists()


def test_verify_remove_orphans_deletes_files_only(tmp_path):
    db_path, save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'verify', '--remove-orphans')

    assert result.exit_code == 1  # missing row still unfixed
    assert not (save_dir / 'orphan.mp3').exists()
    conn = db_mod.connect(db_path)
    try:
        count = conn.execute('SELECT COUNT(*) FROM episodes').fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_verify_both_fixes_exit_zero(tmp_path):
    db_path, save_dir, _fid = _seed(tmp_path)

    result = _invoke('--db', db_path, 'verify', '--fix', '--remove-orphans')

    assert result.exit_code == 0, result.output
    assert 'Fixed' in result.output
    assert not (save_dir / 'orphan.mp3').exists()


def test_verify_clean_library(tmp_path):
    db_path, _save_dir, _fid = _seed(tmp_path, missing=False, orphan=False)

    result = _invoke('--db', db_path, 'verify')

    assert result.exit_code == 0
    assert 'OK' in result.output
