"""Streaming downloads with retry/backoff (httpx)."""

import logging
import os
import time

import httpx

from rss_downcast import USER_AGENT

try:  # optional: also tolerate requests-style sessions/failures in tests
    import requests as _requests

    _NETWORK_ERRORS = (httpx.HTTPError, _requests.RequestException, OSError)
except ImportError:  # pragma: no cover - requests not a runtime dep
    _NETWORK_ERRORS = (httpx.HTTPError, OSError)


def _iter_chunks(response):
    if hasattr(response, 'iter_bytes'):
        yield from response.iter_bytes(chunk_size=8192)
    else:  # requests-style fakes / sessions
        yield from response.iter_content(chunk_size=8192)


def download_file(url, filename, session=None, client=None, retries=3, sleep_fn=None):
    """Stream ``url`` to ``filename``. Returns True on success.

    A partial file is removed before each retry so a truncated download is
    never mistaken for a complete one.
    """
    _sleep = sleep_fn if sleep_fn is not None else time.sleep
    headers = {'User-Agent': USER_AGENT}
    transport = client if client is not None else session
    close = False
    if transport is None:
        transport = httpx.Client(headers=headers, timeout=60, follow_redirects=True)
        close = True
    try:
        for attempt in range(1, retries + 1):
            try:
                if hasattr(transport, 'stream'):
                    ctx = transport.stream('GET', url, headers=headers, timeout=60)
                else:  # requests-style session (session.get returns a context manager)
                    ctx = transport.get(url, headers=headers, stream=True, timeout=60)
                with ctx as response:
                    response.raise_for_status()
                    # Length check is only meaningful for identity bodies: with
                    # Content-Encoding (e.g. gzip) the declared length is the
                    # compressed size while iteration yields decoded bytes.
                    encoded = response.headers.get('Content-Encoding')
                    expected = response.headers.get('Content-Length')
                    try:
                        expected = (
                            int(expected)
                            if expected is not None and not encoded
                            else None
                        )
                    except (TypeError, ValueError):
                        expected = None
                    written = 0
                    with open(filename, 'wb') as file:
                        for chunk in _iter_chunks(response):
                            if chunk:
                                written += file.write(chunk)
                    if expected is not None and written != expected:
                        raise httpx.HTTPError(
                            f'Expected {expected} bytes, received {written}.'
                        )
                if attempt > 1:
                    logging.info(
                        'Download succeeded after %s retries: %s', attempt - 1, filename
                    )
                else:
                    logging.info('Downloaded: %s', filename)
                return True
            except OSError as e:
                # Local filesystem failure (permission, ENOSPC, missing dir):
                # retrying won't help — clean up and surface immediately.
                logging.error('Filesystem error downloading %s: %s', url, e)
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except OSError:
                        logging.warning('Could not remove partial file: %s', filename)
                return False
            except _NETWORK_ERRORS as e:
                logging.warning(
                    'Error downloading file (attempt %s/%s): %s', attempt, retries, e
                )
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except OSError:
                        logging.warning('Could not remove partial file: %s', filename)
                if attempt < retries:
                    sleep_time = 2**attempt
                    logging.info('Retrying in %s seconds...', sleep_time)
                    _sleep(sleep_time)
                else:
                    logging.error('Failed to download %s after %s attempts.', url, retries)
        return False
    finally:
        if close:
            transport.close()
