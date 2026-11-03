"""Requests DazedTL's tools make to gitgud.io, where Forge and WolfDawn live.

Since 2026-11-02 GitGud answers a request without one of the headers its
Cloudflare rule looks for with a challenge page (HTTP 403), and its admin
asks apps to send one: X-Gitlab-Token passes whatever its value and GitLab
itself ignores it, so requests stay anonymous; a real token would ship to
every install. Players' GameUpdate (gameupdate/) and DazedTL's updater
(scripts/update.mjs) send the same header.
"""

import urllib.request

API = "https://gitgud.io/api/v4"
HEADERS = {"User-Agent": "DazedTL", "X-Gitlab-Token": "dazedtl"}


def request(url):
    """A request for *url* on gitgud.io with the headers GitGud lets through."""
    return urllib.request.Request(url, headers=HEADERS)
