"""comp_pc: STAC search and anonymous blob signing (stdlib only, no account, no login).

Helper for scripts/fetch_composition.py.
  * Microsoft Planetary Computer STAC: https://planetarycomputer.microsoft.com/api/stac/v1
    Blob URLs are signed with a short-lived SAS token from the public endpoint
    /api/sas/v1/token/<storage account>/<container>. The token must be requested for the
    account/container that appears in the blob URL (for MOD21A2 that is
    modiseuwest/modis-061-cogs), not for the collection id.
  * Element 84 Earth Search (AWS Open Data, Sentinel-2 L2A COGs, no token):
    https://earth-search.aws.element84.com/v1
"""
import json
import threading
import time
import urllib.parse

import comp_cog as cc

PC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/"
ES_STAC = "https://earth-search.aws.element84.com/v1"

_tok_lock = threading.Lock()
_tokens = {}
TOKEN_CALLS = [0]


def get_json(url, body=None, tries=8, timeout=90):
    for k in range(tries):
        try:
            data = cc.http_get(url, {"Content-Type": "application/json", "Accept": "application/json"}
                               if body is not None else {"Accept": "application/json"},
                               timeout=timeout, body=json.dumps(body).encode() if body is not None else None)
            return json.loads(data)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(3 + 5 * k)


def search(stac, collection, max_items=5000, **kw):
    """POST /search with paging. kw: bbox, intersects, datetime, query, sortby, limit."""
    body = {"collections": [collection], "limit": min(kw.pop("limit", 1000), 1000)}
    body.update({k: v for k, v in kw.items() if v is not None})
    out = []
    url = stac + "/search"
    while True:
        d = get_json(url, body)
        out.extend(d.get("features", []))
        nxt = [l for l in d.get("links", []) if l.get("rel") == "next"]
        if not nxt or len(out) >= max_items:
            break
        if nxt[0].get("method", "GET").upper() == "POST" or nxt[0].get("body"):
            body = nxt[0].get("body", body)
            url = nxt[0]["href"]
        else:                                   # GET paging link (token in the URL)
            url = nxt[0]["href"]
            body = None
            d = get_json(url)
            out.extend(d.get("features", []))
            break
    return out


def blob_key(href):
    u = urllib.parse.urlparse(href)
    return u.netloc.split(".")[0] + "/" + u.path.lstrip("/").split("/")[0]


def token(key):
    with _tok_lock:
        t = _tokens.get(key)
        if t and t[1] > time.time() + 120:
            return t[0]
    d = get_json(PC_SAS + key)
    TOKEN_CALLS[0] += 1
    with _tok_lock:
        _tokens[key] = (d["token"], time.time() + 40 * 60)
    return d["token"]


def drop_token(href):
    with _tok_lock:
        _tokens.pop(blob_key(href), None)


def sign(href):
    return href + ("&" if "?" in href else "?") + token(blob_key(href))


def pc_source(href, tries=8):
    """comp_cog.Source for a Planetary Computer blob (re-signed on every read, token cached)."""
    return cc.Source(url_fn=lambda: sign(href), on_error=lambda: drop_token(href), tries=tries)


def public_source(href, tries=8):
    return cc.Source(url_fn=lambda: href, tries=tries)
