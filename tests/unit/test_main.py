import pytest

from dmi_ohs.main import PipelineError, station_ids_from_env


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
