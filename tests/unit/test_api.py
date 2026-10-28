from datetime import datetime, timedelta, timezone

import pytest
import requests

from dmi_ohs import api
from dmi_ohs.api import FetchError, fetch_observations, make_session

START = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)
# A non-UTC end time checks that times are converted to UTC before sending.
END = datetime(2026, 10, 7, 11, 0, tzinfo=timezone(timedelta(hours=2)))


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeSession:
    """Returns the given responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, params, timeout):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def page(count, start=0):
    # The real API includes a "next" link even on the last page.
    return FakeResponse({
        "type": "FeatureCollection",
        "features": [{"id": str(start + i)} for i in range(count)],
        "links": [{"rel": "next", "href": "https://example.invalid/next"}],
    })


def test_single_short_page():
    session = FakeSession(page(3))
    result = fetch_observations("06120", START, END, session)

    assert result == {"type": "FeatureCollection", "features": [{"id": "0"}, {"id": "1"}, {"id": "2"}]}
    assert len(session.requests) == 1
    request = session.requests[0]
    assert request["url"] == api.OBSERVATIONS_URL
    assert request["params"] == {
        "stationId": "06120",
        "datetime": "2026-10-07T08:00:00Z/2026-10-07T09:00:00Z",
        "limit": api.PAGE_LIMIT,
        "offset": 0,
    }
    assert request["timeout"] == api.TIMEOUT


def test_pages_are_merged_until_a_short_page(monkeypatch):
    monkeypatch.setattr(api, "PAGE_LIMIT", 2)
    session = FakeSession(page(2), page(2, start=2), page(1, start=4))
    result = fetch_observations("06120", START, END, session)

    assert [f["id"] for f in result["features"]] == ["0", "1", "2", "3", "4"]
    assert [r["params"]["offset"] for r in session.requests] == [0, 2, 4]


def test_stops_on_empty_page(monkeypatch):
    monkeypatch.setattr(api, "PAGE_LIMIT", 2)
    session = FakeSession(page(2), page(0))
    result = fetch_observations("06120", START, END, session)

    assert len(result["features"]) == 2
    assert len(session.requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        requests.ConnectionError("no route"),
        FakeResponse({}, status=503),
        FakeResponse(ValueError("not JSON")),
    ],
)
def test_request_failures_raise_fetch_error(response):
    with pytest.raises(FetchError, match="DMI API request failed"):
        fetch_observations("06120", START, END, FakeSession(response))


@pytest.mark.parametrize("body", [{"type": "FeatureCollection"}, {"features": "x"}, []])
def test_response_without_feature_list(body):
    with pytest.raises(FetchError, match="no feature list"):
        fetch_observations("06120", START, END, FakeSession(FakeResponse(body)))


def test_session_retries_transient_errors():
    retry = make_session().get_adapter("https://opendataapi.dmi.dk").max_retries
    assert retry.total == 5
    assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
