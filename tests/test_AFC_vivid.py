"""
Unit tests for extras/AFC_vivid.py

Covers:
  - AFC_vivid: class constants
  - _get_lane_selector_state: returns correct bool from fila_selector
  - _get_selector_enabled: returns stepper enabled status
  - calibration_lane_message: returns informative string
  - cmd_AFC_SELECT_LANE: dispatches to select_lane or gcmd.error
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from extras.AFC_vivid import AFC_vivid
from extras.AFC_BoxTurtle import afcBoxTurtle


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vivid(name="ViViD_1"):
    """Build an AFC_vivid bypassing the complex __init__."""
    unit = AFC_vivid.__new__(AFC_vivid)

    from tests.conftest import MockAFC, MockPrinter, MockLogger, MockReactor

    afc = MockAFC()
    reactor = MockReactor()
    afc.reactor = reactor
    afc.logger = MockLogger()
    printer = MockPrinter(afc=afc)

    unit.printer = printer
    unit.afc = afc
    unit.logger = afc.logger
    unit.reactor = reactor
    unit.name = name
    unit.full_name = ["AFC_vivid", name]
    unit.lanes = {}
    unit.hub_obj = None
    unit.extruder_obj = None
    unit.buffer_obj = None
    unit.hub = None
    unit.extruder = None
    unit.buffer_name = None
    unit.td1_defined = False
    unit.type = "ViViD"
    unit.gcode = afc.gcode
    unit.drive_stepper = "drive_stepper"
    unit.selector_stepper = "selector_stepper"
    unit.drive_stepper_obj = MagicMock()
    unit.selector_stepper_obj = MagicMock()
    unit.current_selected_lane = None
    unit.home_state = False
    unit.prep_homed = False
    unit.failed_to_home = False
    unit.selector_homing_speed = 150
    unit.selector_homing_accel = 150
    unit.max_selector_movement = 800

    return unit


def _make_lane(name="lane1", has_selector=True):
    lane = MagicMock()
    lane.name = name
    lane.selector_endstop = "selector_pin" if has_selector else None
    lane.selector_endstop_name = "lane1_selector"
    lane.load_endstop_name = "lane1_load"
    lane.prep_endstop_name = "lane1_prep"
    lane.dist_hub = 200
    lane.calibrated_lane = True
    if has_selector:
        lane.fila_selector = MagicMock()
        lane.fila_selector.get_status.return_value = {"filament_detected": False}
    else:
        del lane.fila_selector  # make attribute not exist
    return lane


# ── Class constants ───────────────────────────────────────────────────────────

class TestVivdConstants:
    def test_valid_cam_angles(self):
        assert AFC_vivid.VALID_CAM_ANGLES == [30, 45, 60]

    def test_calibration_distance(self):
        assert AFC_vivid.CALIBRATION_DISTANCE == 5000

    def test_lane_overshoot(self):
        assert AFC_vivid.LANE_OVERSHOOT == 200

    def test_is_subclass_of_box_turtle(self):
        assert issubclass(AFC_vivid, afcBoxTurtle)


# ── _get_lane_selector_state ──────────────────────────────────────────────────

class TestGetLaneSelectorState:
    def test_returns_filament_detected_when_selector_present(self):
        unit = _make_vivid()
        lane = _make_lane(has_selector=True)
        lane.fila_selector.get_status.return_value = {"filament_detected": True}
        result = unit._get_lane_selector_state(lane)
        assert result is True

    def test_returns_false_when_selector_not_detected(self):
        unit = _make_vivid()
        lane = _make_lane(has_selector=True)
        lane.fila_selector.get_status.return_value = {"filament_detected": False}
        result = unit._get_lane_selector_state(lane)
        assert result is False

    def test_returns_false_when_no_selector_attribute(self):
        unit = _make_vivid()
        lane = MagicMock(spec=[])  # No attributes
        result = unit._get_lane_selector_state(lane)
        assert result is False


# ── _get_selector_enabled ─────────────────────────────────────────────────────

class TestGetSelectorEnabled:
    def test_returns_true_when_stepper_enabled(self):
        unit = _make_vivid()
        stepper_enable = MagicMock()
        stepper_enable.get_status.return_value = {
            "steppers": {f"AFC_stepper {unit.selector_stepper}": True}
        }
        unit.printer._objects["stepper_enable"] = stepper_enable
        result = unit._get_selector_enabled()
        assert result is True

    def test_returns_false_when_stepper_not_found(self):
        unit = _make_vivid()
        # No stepper_enable in printer objects → returns False
        unit.printer._objects = {}
        result = unit._get_selector_enabled()
        assert result is False


# ── calibration_lane_message ──────────────────────────────────────────────────

class TestCalibrationLaneMessage:
    def test_returns_non_empty_string(self):
        unit = _make_vivid()
        msg = unit.calibration_lane_message()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_message_mentions_reinsert(self):
        unit = _make_vivid()
        msg = unit.calibration_lane_message()
        assert "reinsert" in msg.lower() or "insert" in msg.lower()

    def test_message_mentions_vivid(self):
        unit = _make_vivid()
        msg = unit.calibration_lane_message()
        assert "vivid" in msg.lower() or "ViViD" in msg


# ── cmd_AFC_SELECT_LANE ────────────────────────────────────────────────────────

class TestCmdAfcSelectLane:
    def test_calls_select_lane_when_lane_found(self):
        unit = _make_vivid()
        lane = _make_lane("lane1")
        unit.afc.lanes = {"lane1": lane}
        unit.select_lane = MagicMock(return_value=(True, 15.0))
        gcmd = MagicMock()
        gcmd.get.return_value = "lane1"
        unit.cmd_AFC_SELECT_LANE(gcmd)
        unit.select_lane.assert_called_once_with(lane)

    def test_logs_success_when_homed(self):
        unit = _make_vivid()
        lane = _make_lane("lane1")
        unit.afc.lanes = {"lane1": lane}
        unit.select_lane = MagicMock(return_value=(True, 15.0))
        gcmd = MagicMock()
        gcmd.get.return_value = "lane1"
        unit.cmd_AFC_SELECT_LANE(gcmd)
        info_msgs = [m for lvl, m in unit.logger.messages if lvl == "info"]
        assert any("lane1" in m for m in info_msgs)

    def test_logs_error_when_homing_fails(self):
        unit = _make_vivid()
        lane = _make_lane("lane1")
        unit.afc.lanes = {"lane1": lane}
        unit.select_lane = MagicMock(return_value=(False, 0))
        gcmd = MagicMock()
        gcmd.get.return_value = "lane1"
        unit.cmd_AFC_SELECT_LANE(gcmd)
        error_msgs = [m for lvl, m in unit.logger.messages if lvl == "error"]
        assert any("lane1" in m for m in error_msgs)

    def test_calls_gcmd_error_when_lane_not_found(self):
        unit = _make_vivid()
        unit.afc.lanes = {}
        gcmd = MagicMock()
        gcmd.get.return_value = "missing_lane"
        unit.cmd_AFC_SELECT_LANE(gcmd)
        gcmd.error.assert_called()
