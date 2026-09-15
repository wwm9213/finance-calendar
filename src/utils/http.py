from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "finance-calendar/1.0 (open-source calendar generator)",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def get_text(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    accept: str = "text/html,application/xhtml+xml",
) -> str:
    response = session.get(url, timeout=timeout, headers={"Accept": accept})
    response.raise_for_status()
    return response.text
