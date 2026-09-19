"""Regression tests for v2 review findings (aware dates, None titles, CLI)."""

from datetime import date, datetime


def test_parse_date_normalizes_offset_to_naive_utc(mod):
    dt = mod._parse_date('2024-05-01T12:00:00+02:00')
    assert dt is not None
    assert dt.tzinfo is None
    assert dt == datetime(2024, 5, 1, 10, 0, 0)


def test_entry_datetime_never_aware(mod):
    entry = {'published': 'Wed, 02 Oct 2002 13:00:00 +0200'}
    dt = mod._entry_datetime(entry)
    assert dt is not None
    assert dt.tzinfo is None


def test_select_candidates_mixed_tz_no_crash(mod):
    from rss_downcast.feed import select_candidates

    e1 = {'title': 'a', 'published': '2024-05-01T12:00:00+02:00', 'links': []}
    e2 = {'title': 'b', 'published_parsed': (2024, 4, 1, 0, 0, 0, 0, 0, -1), 'links': []}
    link = type('L', (), {'href': 'http://x/1', 'type': 'audio/mpeg'})()
    out = select_candidates([(e1, link), (e2, link)], last_downloaded=datetime(2024, 1, 1))
    assert len(out) == 2


def test_sanitize_none_title(mod):
    assert mod.sanitize_filename_from_entry({'title': None}) == 'untitled'


def test_parse_since_accepts_date_objects():
    from rss_downcast.cli import _parse_since

    assert _parse_since(date(2024, 1, 2)) == datetime(2024, 1, 2)
    assert _parse_since(datetime(2024, 1, 2, 3, 4)) == datetime(2024, 1, 2, 3, 4)
    assert _parse_since('2024-01-02') == datetime(2024, 1, 2)


def test_prune_invalid_flags_are_bad_parameter(tmp_path):
    from typer.testing import CliRunner

    from rss_downcast.cli import app

    db = str(tmp_path / 't.db')
    r = CliRunner().invoke(app, ['--db', db, 'prune', str(tmp_path), '--max-age', 'garbage'])
    assert r.exit_code != 0
    assert 'max-age' in r.output.lower() or 'invalid' in r.output.lower()


def test_config_verbose_applies(tmp_path):
    import logging

    from typer.testing import CliRunner

    from rss_downcast.cli import app

    cfg = tmp_path / 'c.toml'
    cfg.write_text('[defaults]\nverbose = true\n', encoding='utf-8')
    db = str(tmp_path / 't.db')
    r = CliRunner().invoke(app, ['--db', db, '--config', str(cfg), 'feeds', 'list'])
    assert r.exit_code == 0
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    logging.getLogger().setLevel(logging.INFO)


def test_db_row_factory_and_created_at(mod, tmp_path):
    conn = mod.setup_database(str(tmp_path / 't.db'))
    fid = mod.get_or_create_feed(conn, 'http://a/f', 'A')
    row = conn.execute('SELECT * FROM feeds WHERE feed_id = ?', (fid,)).fetchone()
    assert row['feed_url'] == 'http://a/f'  # key access via Row
    assert row['created_at']
    conn.close()


def test_prune_to_keep_last_returns_counts(mod, tmp_path):
    conn = mod.setup_database(str(tmp_path / 't.db'))
    d = tmp_path / 's'
    d.mkdir()
    fid = mod.get_or_create_feed(conn, 'http://a/f', 'A', save_dir=str(d))
    conn.execute(
        'INSERT INTO episodes (feed_id, guid, title, published, filepath, downloaded_at)'
        " VALUES (?, 'g1', 't', '2024-01-01T00:00:00', '', 'now')",
        (fid,),
    )
    conn.commit()
    assert mod.prune_to_keep_last(conn, fid, str(d)) == (1, 0)
    conn.close()
