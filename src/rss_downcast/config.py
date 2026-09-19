"""TOML config loading for rss-downcast (stdlib tomllib, Python >=3.11)."""

import logging
import os
import tomllib
from pathlib import Path

from rss_downcast import DEFAULT_CONFIG_NAME

KNOWN_KEYS = frozenset(
    {
        'keep',
        'max_age',
        'max_size',
        'verbose',
        'quiet',
        'save_text',
        'num_episodes',
        'since',
        'all',
        'keep_last',
        'dry_run',
    }
)


def find_config_path(explicit=None, no_config=False):
    """Resolve config file path by priority.

    Priority: explicit > ./rss-downcast.toml (cwd) > XDG > ~/.config/...
    Returns Path or None.
    """
    if no_config:
        return None
    if explicit:
        return Path(explicit).expanduser()
    candidates = [
        Path.cwd() / DEFAULT_CONFIG_NAME,
    ]
    xdg = os.environ.get('XDG_CONFIG_HOME')
    app_dirs = []
    if xdg:
        app_dirs.append(Path(xdg) / 'rss-downcast')
    app_dirs.append(Path.home() / '.config' / 'rss-downcast')
    for d in app_dirs:
        candidates.append(d / DEFAULT_CONFIG_NAME)
        candidates.append(d / 'config.toml')
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def load_config(path=None):
    """Load TOML config and return defaults dict.

    Supports [defaults] table or top-level scalar keys. Returns {} if missing.
    """
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, 'rb') as f:
            data = tomllib.load(f)
    except Exception as e:  # noqa: BLE001
        logging.warning('Failed to parse config %s: %s', p, e)
        return {}
    if 'defaults' in data and isinstance(data['defaults'], dict):
        return dict(data['defaults'])
    result = {}
    for k, v in data.items():
        if isinstance(v, dict):
            continue
        nk = k.replace('-', '_')
        if nk in KNOWN_KEYS:
            result[nk] = v
    return result
