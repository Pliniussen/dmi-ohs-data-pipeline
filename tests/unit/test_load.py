import pytest

from dmi_ohs.load import _code_set_parameters

PARAMETERS = {"precip_past1h": {}, "precip_past24h": {}, "wind_dir": {}}


def test_single_parameter_key():
    assert _code_set_parameters("wind_dir", PARAMETERS) == ["wind_dir"]


def test_shared_key_expands_to_each_parameter():
    key = "precip_past1h_precip_past24h"
    assert _code_set_parameters(key, PARAMETERS) == ["precip_past1h", "precip_past24h"]


def test_unknown_key_is_rejected():
    with pytest.raises(ValueError, match="nope"):
        _code_set_parameters("nope", PARAMETERS)
