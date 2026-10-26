"""Every reference link in the infra/lab notebooks answers HTTP 200 (opt-in: LABS_LINKS=1).

The links are read the same way the audit reads the notebooks (the committed
`.ipynb` through FileNotebookSource, the targets through rules.markdown_links),
so a link added to any section is checked without listing it here. A 429
(rate limit, which GitHub returns to bursts of requests) is retried after the
server's Retry-After or a fixed wait; any other status fails.
"""

from __future__ import annotations

import os
import time

import pytest
import requests

from labs_audit.adapters.outbound.filesystem import FileNotebookSource
from labs_audit.domain import rules

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("LABS_LINKS") != "1", reason="set LABS_LINKS=1 to check the links"),
]

HEADERS = {"User-Agent": "labs-setup-link-check/1.0 (+https://github.com/mavasbel-itam)"}
RETRIES = 4
WAIT_SECONDS = 30


def _links(root):
    source = FileNotebookSource(root)
    found: dict[str, list[str]] = {}
    for stem in source.pairs():
        for target in rules.markdown_links(source.committed(stem)):
            found.setdefault(target, []).append(stem)
    return found


def _status(url: str) -> int:
    for attempt in range(RETRIES):
        response = requests.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
        if response.status_code != 429 or attempt == RETRIES - 1:
            return response.status_code
        time.sleep(int(response.headers.get("Retry-After", WAIT_SECONDS)))
    raise AssertionError("unreachable")  # pragma: no cover


def test_every_notebook_link_answers_200(labs_root):
    links = _links(labs_root)
    assert len(links) > 100, len(links)
    failures = {}
    for url, stems in sorted(links.items()):
        status = _status(url)
        if status != 200:
            failures[url] = (status, sorted(set(stems)))
    assert failures == {}, "\n".join(f"{status} {url} ({', '.join(stems)})" for url, (status, stems) in failures.items())
