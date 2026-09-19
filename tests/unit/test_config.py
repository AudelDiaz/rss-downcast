"""Unit tests for config file loader and package layout."""


def test_find_config_path_explicit(mod, tmp_path):
    cfg = tmp_path / 'my.toml'
    cfg.write_text('[defaults]\nkeep=5\n', encoding='utf-8')
    # Should return explicit even if not exists? Actually returns Path anyway
    found = mod.find_config_path(str(cfg))
    assert found == cfg


def test_find_config_path_no_config_flag(mod):
    assert mod.find_config_path(explicit='/tmp/x.toml', no_config=True) is None


def test_load_config_defaults_table(mod, tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('[defaults]\nkeep=5\nverbose=true\n', encoding='utf-8')
    data = mod.load_config(str(cfg))
    assert data == {'keep': 5, 'verbose': True}


def test_load_config_top_level_fallback(mod, tmp_path):
    cfg = tmp_path / 'c2.toml'
    cfg.write_text('keep=3\nquiet=true\n', encoding='utf-8')
    data = mod.load_config(str(cfg))
    assert data['keep'] == 3
    assert data['quiet'] is True


def test_load_config_missing_returns_empty(mod, tmp_path):
    missing = tmp_path / 'no.toml'
    assert mod.load_config(str(missing)) == {}
    assert mod.load_config(None) == {}


def test_load_config_invalid_toml_returns_empty(mod, tmp_path, caplog):
    import logging

    cfg = tmp_path / 'bad.toml'
    cfg.write_text('invalid = [', encoding='utf-8')
    with caplog.at_level(logging.WARNING):
        data = mod.load_config(str(cfg))
    assert data == {}


def test_package_importable():
    # New src-layout package exposes the public surface directly
    import importlib

    m = importlib.import_module('rss_downcast.cli')
    assert callable(m.main)
    db = importlib.import_module('rss_downcast.db')
    assert callable(db.connect)
    assert callable(db.get_or_create_feed)
    cfg = importlib.import_module('rss_downcast.config')
    assert callable(cfg.find_config_path)


def test_config_via_cli_overrides(tmp_path, monkeypatch):
    # Config discovery: ./rss-downcast.toml with keep=5 is found from cwd

    cfg = tmp_path / 'rss-downcast.toml'
    cfg.write_text('[defaults]\nkeep=5\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    from rss_downcast import config as rpd_cfg

    found = rpd_cfg.find_config_path()
    assert found is not None
    assert found.name == 'rss-downcast.toml'
    data = rpd_cfg.load_config(str(cfg))
    assert data['keep'] == 5
