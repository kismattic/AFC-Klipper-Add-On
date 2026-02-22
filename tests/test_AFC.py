"""
Unit tests for extras/AFC.py

Covers:
  - State: string constants
  - AFC_VERSION: version string format
  - afc._remove_after_last: string helper
  - afc._get_message: message queue peek and pop
  - afc.get_status: returns required keys
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from extras.AFC import afc, State, AFC_VERSION


# ── State constants ───────────────────────────────────────────────────────────

class TestStateConstants:
    def test_init_value(self):
        assert State.INIT == "Initialized"

    def test_idle_value(self):
        assert State.IDLE == "Idle"

    def test_error_value(self):
        assert State.ERROR == "Error"

    def test_loading_value(self):
        assert State.LOADING == "Loading"

    def test_unloading_value(self):
        assert State.UNLOADING == "Unloading"

    def test_ejecting_lane_value(self):
        assert State.EJECTING_LANE == "Ejecting"

    def test_moving_lane_value(self):
        assert State.MOVING_LANE == "Moving"

    def test_restoring_pos_value(self):
        assert State.RESTORING_POS == "Restoring"

    def test_all_constants_are_strings(self):
        attrs = [a for a in dir(State) if not a.startswith("_")]
        for attr in attrs:
            assert isinstance(getattr(State, attr), str)

    def test_all_constants_unique(self):
        attrs = [a for a in dir(State) if not a.startswith("_")]
        values = [getattr(State, a) for a in attrs]
        assert len(values) == len(set(values))


# ── AFC_VERSION ───────────────────────────────────────────────────────────────

class TestAfcVersion:
    def test_version_is_string(self):
        assert isinstance(AFC_VERSION, str)

    def test_version_has_dots(self):
        assert "." in AFC_VERSION

    def test_version_parts_are_numeric(self):
        parts = AFC_VERSION.split(".")
        for part in parts:
            assert part.isdigit(), f"Non-numeric version part: {part!r}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_afc():
    """Build an afc instance bypassing __init__."""
    obj = afc.__new__(afc)

    from tests.conftest import MockAFC, MockLogger, MockPrinter

    inner = MockAFC()
    printer = MockPrinter(afc=inner)
    obj.printer = printer
    obj.logger = MockLogger()
    obj.reactor = inner.reactor
    obj.moonraker = None
    obj.function = MagicMock()
    obj.message_queue = []
    obj.current = None
    obj.current_loading = None
    obj.next_lane_load = None
    obj.current_state = State.IDLE
    obj.error_state = False
    obj.position_saved = False
    obj.spoolman = None
    obj._td1_present = False
    obj.lane_data_enabled = False
    obj.units = {}
    obj.lanes = {}
    obj.tools = {}
    obj.hubs = {}
    obj.buffers = {}
    obj.led_state = True
    obj.current_toolchange = 0
    obj.number_of_toolchanges = 0
    obj._get_bypass_state = MagicMock(return_value=False)
    obj._get_quiet_mode = MagicMock(return_value=False)
    return obj


# ── _remove_after_last ────────────────────────────────────────────────────────

class TestRemoveAfterLast:
    def test_removes_after_last_slash(self):
        obj = _make_afc()
        result = obj._remove_after_last("/home/user/file.txt", "/")
        assert result == "/home/user/"

    def test_no_char_returns_original(self):
        obj = _make_afc()
        result = obj._remove_after_last("nodots", ".")
        assert result == "nodots"

    def test_char_at_end(self):
        obj = _make_afc()
        result = obj._remove_after_last("trailing/", "/")
        assert result == "trailing/"

    def test_single_char_string(self):
        obj = _make_afc()
        result = obj._remove_after_last("/", "/")
        assert result == "/"

    def test_multiple_occurrences_uses_last(self):
        obj = _make_afc()
        result = obj._remove_after_last("a/b/c/d", "/")
        assert result == "a/b/c/"


# ── _get_message ──────────────────────────────────────────────────────────────

class TestGetMessage:
    def test_empty_queue_returns_empty_strings(self):
        obj = _make_afc()
        msg = obj._get_message()
        assert msg["message"] == ""
        assert msg["type"] == ""

    def test_peek_does_not_remove(self):
        obj = _make_afc()
        obj.message_queue = [("hello", "info")]
        obj._get_message(clear=False)
        assert len(obj.message_queue) == 1

    def test_peek_returns_message(self):
        obj = _make_afc()
        obj.message_queue = [("hello", "info")]
        msg = obj._get_message(clear=False)
        assert msg["message"] == "hello"
        assert msg["type"] == "info"

    def test_clear_removes_first_item(self):
        obj = _make_afc()
        obj.message_queue = [("first", "error"), ("second", "warning")]
        obj._get_message(clear=True)
        assert len(obj.message_queue) == 1
        assert obj.message_queue[0][0] == "second"

    def test_clear_returns_popped_message(self):
        obj = _make_afc()
        obj.message_queue = [("popped", "error")]
        msg = obj._get_message(clear=True)
        assert msg["message"] == "popped"
        assert msg["type"] == "error"

    def test_clear_on_empty_returns_empty(self):
        obj = _make_afc()
        msg = obj._get_message(clear=True)
        assert msg["message"] == ""
        assert msg["type"] == ""


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_returns_required_keys(self):
        obj = _make_afc()
        status = obj.get_status()
        required = {
            "current_load", "current_state", "error_state",
            "lanes", "extruders", "hubs", "buffers", "units",
            "message", "position_saved",
        }
        for key in required:
            assert key in status, f"Missing key: {key}"

    def test_lanes_is_list(self):
        obj = _make_afc()
        assert isinstance(obj.get_status()["lanes"], list)

    def test_extruders_is_list(self):
        obj = _make_afc()
        assert isinstance(obj.get_status()["extruders"], list)

    def test_hubs_is_list(self):
        obj = _make_afc()
        assert isinstance(obj.get_status()["hubs"], list)

    def test_units_is_list(self):
        obj = _make_afc()
        assert isinstance(obj.get_status()["units"], list)

    def test_error_state_reflects_attribute(self):
        obj = _make_afc()
        obj.error_state = True
        assert obj.get_status()["error_state"] is True

    def test_current_load_none_when_nothing_loaded(self):
        obj = _make_afc()
        assert obj.get_status()["current_load"] is None

    def test_message_from_queue(self):
        obj = _make_afc()
        obj.message_queue = [("test msg", "warning")]
        msg = obj.get_status()["message"]
        assert msg["message"] == "test msg"
