import sys
from datetime import timedelta

import psycopg
import pytest

from dmi_ohs import main
from dmi_ohs.main import PipelineError, lookback_from_env, run_every, run_file, station_ids_from_env


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


@pytest.mark.parametrize("args", [["--every", "0"], ["--every", "abc"], ["--every", "10", "--file", "x.json"]])
def test_main_rejects_bad_every(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["dmi_ohs.main", *args])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    # argparse exits with code 2 on invalid arguments.
    assert exit_info.value.code == 2


INTERVAL = timedelta(minutes=10)


class FakeLoop:
    """A clock, sleep and run for run_every that never really wait.

    Each run advances the clock by its duration and raises its error, if any.
    """

    def __init__(self, durations, errors=None):
        self.now = 0.0
        self.durations = durations
        self.errors = errors or {}
        self.starts = []
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def run(self):
        index = len(self.starts)
        self.starts.append(self.now)
        self.now += self.durations[index]
        if index in self.errors:
            raise self.errors[index]

    def __call__(self, runs):
        run_every(INTERVAL, run=self.run, sleep=self.sleep, clock=self.clock, runs=runs)


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    monkeypatch.delenv("DMI_STATION_IDS", raising=False)
    monkeypatch.delenv("DMI_INITIAL_LOOKBACK_HOURS", raising=False)


def test_run_every_keeps_a_fixed_rhythm():
    loop = FakeLoop([30, 45, 5])
    loop(runs=3)
    assert loop.starts == [0, 600, 1200]
    # Each wait is the interval minus how long the run took.
    assert loop.sleeps == [570, 555]


def test_run_every_skips_slots_a_slow_run_overran():
    loop = FakeLoop([1500, 10])
    loop(runs=2)
    # The run ended at 1500 s, past the 600 and 1200 s slots, so the next run starts at 1800 s.
    assert loop.starts == [0, 1800]


def test_run_every_continues_after_failed_runs(capsys):
    loop = FakeLoop(
        [1, 1, 1],
        errors={0: PipelineError("failed stations: 06180"), 1: psycopg.OperationalError("db is down")},
    )
    loop(runs=3)
    assert loop.starts == [0, 600, 1200]
    err = capsys.readouterr().err
    assert "run failed: failed stations: 06180" in err
    assert "run failed: db is down" in err


def test_run_every_stops_on_unexpected_errors():
    loop = FakeLoop([1, 1], errors={0: RuntimeError("bug")})
    with pytest.raises(RuntimeError, match="bug"):
        loop(runs=2)
    assert loop.starts == [0]


@pytest.mark.parametrize(
    ("name", "value"), [("DMI_STATION_IDS", " , "), ("DMI_INITIAL_LOOKBACK_HOURS", "abc")]
)
def test_run_every_checks_settings_before_the_first_run(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    loop = FakeLoop([1])
    with pytest.raises(PipelineError, match=name):
        loop(runs=1)
    assert loop.starts == []
