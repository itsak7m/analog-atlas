"""emit_http: stdlib HTTP Range reads for NASA Earthdata / LP DAAC (EMIT L2B MIN).

Token handling (Analog Atlas rule): the Earthdata user token is read from a local file at run
time and is sent ONLY as an 'Authorization: Bearer' header to NASA Earthdata hosts
(*.earthdata.nasa.gov, *.earthdatacloud.nasa.gov). It is never printed, logged, put in a URL or
written to any output file. Redirects (LP DAAC -> signed S3/CloudFront URL) are followed by hand
WITHOUT the header.
"""
import os
import time
import urllib.error
import urllib.request

ALLOWED_SUFFIXES = ('.earthdata.nasa.gov', '.earthdatacloud.nasa.gov')

_TOKEN = None
STATS = {'requests': 0, 'bytes': 0, 'retries': 0}


def load_token(path):
    """Read the token from a file (stripped). Returns True/False; the value stays in this module."""
    global _TOKEN
    try:
        with open(path, encoding='utf-8') as f:
            t = f.read().strip()
    except OSError:
        return False
    # tolerate a file holding 'EARTHDATA_TOKEN=...' or 'Bearer ...'
    first = t.splitlines()[0].strip() if t else ''
    if '=' in first and first.split('=', 1)[0].strip().isidentifier():
        first = first.split('=', 1)[1].strip().strip('"\'')
    t = first
    if t.lower().startswith('bearer '):
        t = t[7:].strip()
    _TOKEN = t or None
    return _TOKEN is not None


def _host_ok(url):
    host = url.split('/')[2].split(':')[0].lower()
    return url.startswith('https://') and any(host.endswith(s) for s in ALLOWED_SUFFIXES)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def get(url, off=None, n=None, timeout=120, tries=4):
    """Return (status, bytes). Range request when off/n are given. Follows redirects by hand."""
    last = None
    for attempt in range(tries):
        u = url
        try:
            for _ in range(8):
                req = urllib.request.Request(u)
                if off is not None:
                    req.add_header('Range', 'bytes=%d-%d' % (off, off + n - 1))
                if _TOKEN and _host_ok(u):
                    req.add_header('Authorization', 'Bearer ' + _TOKEN)
                try:
                    with _OPENER.open(req, timeout=timeout) as r:
                        data = r.read()
                        STATS['requests'] += 1
                        STATS['bytes'] += len(data)
                        return r.status, data
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308):
                        u = urllib.parse.urljoin(u, e.headers['Location'])
                        continue
                    if e.code in (401, 403, 404):
                        return e.code, b''
                    raise
            raise IOError('too many redirects')
        except (urllib.error.URLError, OSError, IOError) as e:  # transient network trouble
            last = e
            STATS['retries'] += 1
            time.sleep(2 + 4 * attempt)
    raise IOError('request failed after %d tries: %s' % (tries, type(last).__name__))


import urllib.parse  # noqa: E402  (used in get)
