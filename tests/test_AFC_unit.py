"""
Unit tests for extras/AFC_unit.py

Covers:
  - afcUnit.__str__: returns name
  - afcUnit._check_and_errorout: None vs non-None object
  - afcUnit.get_status: correct keys and content
  - afcUnit.check_runout: returns False
  - afcUnit.return_to_home: returns None
  - afcUnit.lane_loaded/unloaded/loading/tool_loaded/tool_unloaded: call afc_led
  - afcUnit.set_logo_color: calls afc_led when color present, skips when None/empty
"""

from __future__ import annotations

from unittest.mock import MagicMock, call
import pytest

from extras.AFC_unit import afcUnit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_unit(name="Turtle_1"):
    """Build an afcUnit bypassing the complex __init__."""
    unit = afcUnit.__new__(afcUnit)

    from tests.conftest import MockAFC, MockPrinter, MockLogger

    afc = MockAFC()
    printer = MockPrinter(afc=afc)
    afc.logger = MockLogger()

    unit.printer = printer
    unit.afc = afc
    unit.logger = afc.logger
    unit.name = name
    unit.full_name = ["AFC_BoxTurtle", name]
    unit.lanes = {}
    unit.hub_obj = None
    unit.extruder_obj = None
    unit.buffer_obj = None
    unit.hub = None
    unit.extruder = None
    unit.buffer_name = None
    unit.td1_defined = False
    unit.type = "Box_Turtle"
    unit.gcode = afc.gcode
    unit.led_logo_index = None

    return unit


def _make_lane(name="lane1", hub="hub1", extruder="ext1", buffer_name="buf1"):
    lane = MagicMock()
    lane.name = name
    lane.hub = hub
    lane.extruder_name = extruder
    lane.buffer_name = buffer_name
    lane.led_ready = "0,1,0,0"
    lane.led_not_ready = "0,0,0,0.25"
    lane.led_loading = "0,0,1,0"
    lane.led_tool_loaded = "0,1,0,0"
    lane.led_index = "1"
    lane.led_spool_illum = "1,1,1,0"
    lane.load_state = True
    return lane


# ── __str__ ───────────────────────────────────────────────────────────────────

class TestStr:
    def test_str_returns_name(self):
        unit = _make_unit("Turtle_1")
        assert str(unit) == "Turtle_1"

    def test_str_reflects_different_name(self):
        unit = _make_unit("NightOwl_2")
        assert str(unit) == "NightOwl_2"


# ── _check_and_errorout ────────────────────────────────────────────────────────

class TestCheckAndErrorOut:
    def test_returns_true_when_obj_is_none(self):
        unit = _make_unit()
        error, msg = unit._check_and_errorout(None, "AFC_hub testname", "hub")
        assert error is True

    def test_error_msg_not_empty_when_obj_none(self):
        unit = _make_unit()
        _, msg = unit._check_and_errorout(None, "AFC_hub testname", "hub")
        assert len(msg) > 0

    def test_error_msg_contains_config_name(self):
        unit = _make_unit()
        _, msg = unit._check_and_errorout(None, "AFC_hub testname", "hub")
        assert "AFC_hub testname" in msg

    def test_returns_false_when_obj_present(self):
        unit = _make_unit()
        obj = MagicMock()
        error, msg = unit._check_and_errorout(obj, "AFC_hub", "hub")
        assert error is False

    def test_msg_empty_when_obj_present(self):
        unit = _make_unit()
        obj = MagicMock()
        _, msg = unit._check_and_errorout(obj, "AFC_hub", "hub")
        assert msg == ""


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_has_lanes_key(self):
        unit = _make_unit()
        status = unit.get_status()
        assert "lanes" in status

    def test_has_extruders_key(self):
        unit = _make_unit()
        status = unit.get_status()
        assert "extruders" in status

    def test_has_hubs_key(self):
        unit = _make_unit()
        status = unit.get_status()
        assert "hubs" in status

    def test_has_buffers_key(self):
        unit = _make_unit()
        status = unit.get_status()
        assert "buffers" in status

    def test_lanes_list_contains_lane_name(self):
        unit = _make_unit()
        lane = _make_lane("lane1")
        unit.lanes = {"lane1": lane}
        status = unit.get_status()
        assert "lane1" in status["lanes"]

    def test_extruder_name_collected_from_lanes(self):
        unit = _make_unit()
        lane = _make_lane("lane1", extruder="my_extruder")
        unit.lanes = {"lane1": lane}
        status = unit.get_status()
        assert "my_extruder" in status["extruders"]

    def test_hub_name_collected_from_lanes(self):
        unit = _make_unit()
        lane = _make_lane("lane1", hub="my_hub")
        unit.lanes = {"lane1": lane}
        status = unit.get_status()
        assert "my_hub" in status["hubs"]

    def test_buffer_name_collected_from_lanes(self):
        unit = _make_unit()
        lane = _make_lane("lane1", buffer_name="my_buffer")
        unit.lanes = {"lane1": lane}
        status = unit.get_status()
        assert "my_buffer" in status["buffers"]

    def test_duplicate_extruder_not_repeated(self):
        """Two lanes sharing the same extruder should appear only once."""
        unit = _make_unit()
        lane1 = _make_lane("lane1", extruder="shared_ext")
        lane2 = _make_lane("lane2", extruder="shared_ext")
        unit.lanes = {"lane1": lane1, "lane2": lane2}
        status = unit.get_status()
        assert status["extruders"].count("shared_ext") == 1

    def test_empty_lanes_returns_empty_lists(self):
        unit = _make_unit()
        unit.lanes = {}
        status = unit.get_status()
        assert status["lanes"] == []
        assert status["extruders"] == []
        assert status["hubs"] == []
        assert status["buffers"] == []


# ── check_runout ──────────────────────────────────────────────────────────────

class TestCheckRunout:
    def test_returns_false(self):
        unit = _make_unit()
        assert unit.check_runout() is False


# ── return_to_home ────────────────────────────────────────────────────────────

class TestReturnToHome:
    def test_returns_none(self):
        unit = _make_unit()
        result = unit.return_to_home()
        assert result is None


# ── LED helpers ───────────────────────────────────────────────────────────────

class TestLaneStatusLeds:
    def test_lane_loaded_calls_afc_led_with_ready_color(self):
        unit = _make_unit()
        lane = _make_lane()
        unit.lane_loaded(lane)
        unit.afc.function.afc_led.assert_called_once_with(lane.led_ready, lane.led_index)

    def test_lane_unloaded_calls_afc_led_with_not_ready_color(self):
        unit = _make_unit()
        lane = _make_lane()
        unit.lane_unloaded(lane)
        unit.afc.function.afc_led.assert_called_once_with(lane.led_not_ready, lane.led_index)

    def test_lane_loading_calls_afc_led_with_loading_color(self):
        unit = _make_unit()
        lane = _make_lane()
        unit.lane_loading(lane)
        unit.afc.function.afc_led.assert_called_once_with(lane.led_loading, lane.led_index)

    def test_lane_tool_loaded_calls_afc_led_with_tool_loaded_color(self):
        unit = _make_unit()
        lane = _make_lane()
        unit.lane_tool_loaded(lane)
        unit.afc.function.afc_led.assert_called_once_with(lane.led_tool_loaded, lane.led_index)

    def test_lane_tool_unloaded_calls_afc_led_with_ready_color(self):
        unit = _make_unit()
        lane = _make_lane()
        unit.lane_tool_unloaded(lane)
        unit.afc.function.afc_led.assert_called_once_with(lane.led_ready, lane.led_index)


# ── set_logo_color ────────────────────────────────────────────────────────────

class TestSetLogoColor:
    def test_calls_afc_led_when_color_present(self):
        unit = _make_unit()
        unit.led_logo_index = "0"
        unit.afc.function.HexToLedString = MagicMock(return_value="0,0,0,0")
        unit.set_logo_color("FF0000")
        unit.afc.function.afc_led.assert_called()

    def test_no_call_when_color_is_none(self):
        unit = _make_unit()
        unit.set_logo_color(None)
        unit.afc.function.afc_led.assert_not_called()

    def test_no_call_when_color_is_empty_string(self):
        unit = _make_unit()
        unit.set_logo_color("")
        unit.afc.function.afc_led.assert_not_called()
