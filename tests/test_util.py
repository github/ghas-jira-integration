import json
import pytest
import util


def test_state_from_json_returns_states_when_version_present():
    payload = json.dumps({"version": 2, "states": {"octo/repo": True}})
    assert util.state_from_json(payload) == {"octo/repo": True}


def test_state_from_json_returns_empty_dict_when_version_missing():
    payload = json.dumps({"states": {"octo/repo": True}})
    assert util.state_from_json(payload) == {}


def test_state_from_json_raises_on_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        util.state_from_json("not valid json")


def test_state_from_json_raises_when_states_missing_but_version_present():
    payload = json.dumps({"version": 2})
    with pytest.raises(KeyError):
        util.state_from_json(payload)


def test_state_to_json_round_trips_through_state_from_json():
    state = {"octo/repo": True, "octo/other": False}
    assert util.state_from_json(util.state_to_json(state)) == state


def test_state_to_json_includes_current_version():
    assert json.loads(util.state_to_json({}))["version"] == 2


def test_state_from_file_returns_empty_dict_when_file_missing(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    assert util.state_from_file(str(missing)) == {}


def test_state_from_file_returns_empty_dict_when_path_is_a_directory(tmp_path):
    assert util.state_from_file(str(tmp_path)) == {}


def test_state_to_file_round_trips_through_state_from_file(tmp_path):
    fpath = tmp_path / "state.json"
    state = {"octo/repo": True}
    util.state_to_file(str(fpath), state)
    assert util.state_from_file(str(fpath)) == state


def test_make_key_differs_for_different_input():
    assert util.make_key("octo/repo") != util.make_key("octo/other")
