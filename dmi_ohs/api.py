from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

OBSERVATIONS_URL = "https://opendataapi.dmi.dk/v2/metObs/collections/observation/items"
# Rows per request. One hour for one station is about 110 rows, so this is
# normally a single page.
PAGE_LIMIT = 10000
# Seconds to wait for a connection and for the response.
TIMEOUT = (5, 30)


class FetchError(RuntimeError):
    """The DMI API could not be reached or returned an unusable response."""

    pass


def make_session() -> requests.Session:
    """Create a session that retries rate limits, server errors and dropped connections."""
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _format_time(moment: datetime) -> str:
    # The API expects RFC 3339 times; send them in UTC with a "Z" suffix.
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_observations(
    station_id: str, start: datetime, end: datetime, session: requests.Session | None = None
) -> dict:
    """Fetch every observation for a station between start and end (both inclusive).

    Pages are requested by offset until a page comes back short. The API
    includes a "next" link even on the last page, so that link cannot tell us
    when to stop. The pages are merged into one FeatureCollection, the same
    shape as a saved API response.
    """
    session = session or make_session()
    features: list = []
    while True:
        params = {
            "stationId": station_id,
            "datetime": f"{_format_time(start)}/{_format_time(end)}",
            "limit": PAGE_LIMIT,
            "offset": len(features),
        }
        try:
            response = session.get(OBSERVATIONS_URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            page = response.json()
        except (requests.RequestException, ValueError) as error:
            raise FetchError(f"DMI API request failed (offset {params['offset']}): {error}") from error

        page_features = page.get("features") if isinstance(page, dict) else None
        if not isinstance(page_features, list):
            raise FetchError(f"DMI API response has no feature list (offset {params['offset']})")
        features.extend(page_features)
        if len(page_features) < PAGE_LIMIT:
            return {"type": "FeatureCollection", "features": features}
