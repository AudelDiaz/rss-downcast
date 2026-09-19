"""Unit tests for versioning (Typer CLI)."""

import pathlib
import re


def test_version_exists_and_semver(mod):
    assert hasattr(mod, '__version__')
    assert re.match(r'^\d+\.\d+\.\d+', mod.__version__)


def test_version_matches_pyproject(mod):
    pyproject = pathlib.Path('pyproject.toml').read_text(encoding='utf-8')
    m = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
    assert m, 'version not found in pyproject.toml'
    assert m.group(1) == mod.__version__


def test_version_flag():
    from typer.testing import CliRunner

    from rss_downcast import __version__
    from rss_downcast.cli import app

    result = CliRunner().invoke(app, ['--version'])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_entry_point_callable():
    from rss_downcast.cli import main

    assert callable(main)
