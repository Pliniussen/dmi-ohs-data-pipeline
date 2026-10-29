import sys
from datetime import timedelta

import pytest

from dmi_ohs import main
from dmi_ohs.main import PipelineError, lookback_from_env, run_file, station_ids_from_env


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("06120", ["06120"]),
        ("06120,06180", ["06120", "06180"]),
        (" 06120 , 06180 ,", ["06120", "06180"]),
        ("06180,06120,06180", ["06180", "06120"]),
    ],
)
def test_station_ids_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("DMI_STATION_IDS", raw)
    assert station_ids_from_env() == expected


def test_station_ids_default_to_odense(monkeypatch):
    monkeypatch.delenv("DMI_STATION_IDS", raising=False)
    assert station_ids_from_env() == ["06120"]


@pytest.mark.parametrize("raw", ["", " , "])
def test_station_ids_must_not_be_empty(monkeypatch, raw):
    monkeypatch.setenv("DMI_STATION_IDS", raw)
    with pytest.raises(PipelineError, match="no station IDs"):
        station_ids_from_env()


@pytest.mark.parametrize(("raw", "expected"), [("24", 24), ("0.5", 0.5), ("720", 720)])
def test_lookback_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("DMI_INITIAL_LOOKBACK_HOURS", raw)
    assert lookback_from_env() == timedelta(hours=expected)


def test_lookback_defaults_to_24_hours(monkeypatch):
    monkeypatch.delenv("DMI_INITIAL_LOOKBACK_HOURS", raising=False)
    assert lookback_from_env() == timedelta(hours=24)


@pytest.mark.parametrize("raw", ["abc", "", "0", "-1", "nan", "inf"])
def test_lookback_must_be_positive(monkeypatch, raw):
    monkeypatch.setenv("DMI_INITIAL_LOOKBACK_HOURS", raw)
    with pytest.raises(PipelineError, match="DMI_INITIAL_LOOKBACK_HOURS"):
        lookback_from_env()


class FakeConnection:
    def close(self):
        pass


@pytest.mark.parametrize(
    ("content", "match"),
    [
        (None, "No such file"),
        ("not json", "Expecting value"),
        ('{"features": []}', "no observation features"),
    ],
)
def test_run_file_reports_bad_input(tmp_path, monkeypatch, content, match):
    # Bad content fails while parsing, before the connection is used.
    monkeypatch.setattr(main, "get_connection", FakeConnection)
    path = tmp_path / "observations.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(PipelineError, match=match):
        run_file(path)


def test_main_exits_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dmi_ohs.main", "--file", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit, match="Error: .*missing.json"):
        main.main()
