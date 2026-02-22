"""
Unit tests for extras/AFC_hub.py

Covers:
  - afc_hub.get_status: returns dict with expected keys and correct values
  - afc_hub.state property: physical vs virtual hub sensor
  - afc_hub.switch_pin_callback: updates internal _state
  - afc_hub.__str__: returns name
  - afc_hub.handle_runout: only triggers for the currently-loaded lane
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from extras.AFC_hub import afc_hub


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_hub(switch_pin="PA0", name="test_hub", extra_values=None):
    """Build an afc_hub instance by bypassing __init__ and setting attrs."""
    hub = afc_hub.__new__(afc_hub)

    from tests.conftest import MockAFC, MockPrinter, MockReactor, MockLogger

    afc = MockAFC()
    reactor = MockReactor()
    printer = MockPrinter(afc=afc)
    printer._reactor = reactor

    hub.printer = printer
    hub.afc = afc
    hub.reactor = reactor
    hub.gcode = afc.gcode

    hub.fullname = f"AFC_hub {name}"
    hub.name = name
    hub.unit = None
    hub.lanes = {}
    hub._state = False
    hub.switch_pin = switch_pin

    # Default config values
    hub.hub_clear_move_dis = 65.0
    hub.afc_bowden_length = 900.0
    hub.td1_bowden_length = 850.0
    hub.afc_unload_bowden_length = 900.0
    hub.assisted_retract = False
    hub.move_dis = 75.0
    hub.cut = False
    hub.cut_cmd = None
    hub.cut_servo_name = "cut"
    hub.cut_dist = 50.0
    hub.cut_clear = 120.0
    hub.cut_min_length = 200.0
    hub.cut_servo_pass_angle = 0.0
    hub.cut_servo_clip_angle = 160.0
    hub.cut_servo_prep_angle = 75.0
    hub.cut_confirm = False
    hub.config_bowden_length = hub.afc_bowden_length
    hub.config_unload_bowden_length = hub.afc_unload_bowden_length
    hub.enable_sensors_in_gui = False
    hub.debounce_delay = 0.1
    hub.enable_runout = False

    # Filament sensor mock (used in handle_runout)
    hub.fila = MagicMock()
    hub.fila.runout_helper.min_event_systime = 0.0
    hub.fila.runout_helper.event_delay = 0.5
    hub.debounce_button = MagicMock()

    if extra_values:
        for k, v in extra_values.items():
            setattr(hub, k, v)

    return hub


# ── __str__ ───────────────────────────────────────────────────────────────────

class TestAFCHubStr:
    def test_str_returns_name(self):
        hub = _make_hub(name="hub1")
        assert str(hub) == "hub1"


# ── switch_pin_callback ───────────────────────────────────────────────────────

class TestSwitchPinCallback:
    def test_callback_sets_state_true(self):
        hub = _make_hub()
        hub.switch_pin_callback(100.0, True)
        assert hub._state is True

    def test_callback_sets_state_false(self):
        hub = _make_hub()
        hub._state = True
        hub.switch_pin_callback(101.0, False)
        assert hub._state is False


# ── state property ────────────────────────────────────────────────────────────

class TestStateProperty:
    def test_physical_switch_returns_internal_state(self):
        hub = _make_hub(switch_pin="PA0")
        hub._state = True
        assert hub.state is True

    def test_physical_switch_false(self):
        hub = _make_hub(switch_pin="PA0")
        hub._state = False
        assert hub.state is False

    def test_virtual_hub_true_when_any_lane_load_state_true(self):
        hub = _make_hub(switch_pin="virtual")
        lane1 = MagicMock()
        lane1._load_state = False
        lane2 = MagicMock()
        lane2._load_state = True
        hub.lanes = {"lane1": lane1, "lane2": lane2}
        assert hub.state is True

    def test_virtual_hub_false_when_all_lanes_not_loaded(self):
        hub = _make_hub(switch_pin="virtual")
        lane1 = MagicMock()
        lane1._load_state = False
        lane2 = MagicMock()
        lane2._load_state = False
        hub.lanes = {"lane1": lane1, "lane2": lane2}
        assert hub.state is False

    def test_virtual_hub_false_when_no_lanes(self):
        hub = _make_hub(switch_pin="virtual")
        hub.lanes = {}
        assert hub.state is False


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_get_status_returns_dict(self):
        hub = _make_hub()
        result = hub.get_status()
        assert isinstance(result, dict)

    def test_get_status_contains_state(self):
        hub = _make_hub()
        hub._state = False
        result = hub.get_status()
        assert "state" in result
        assert result["state"] is False

    def test_get_status_cut_flag(self):
        hub = _make_hub()
        hub.cut = True
        result = hub.get_status()
        assert result["cut"] is True

    def test_get_status_cut_cmd_default_none(self):
        hub = _make_hub()
        result = hub.get_status()
        assert result["cut_cmd"] is None

    def test_get_status_bowden_length(self):
        hub = _make_hub()
        hub.afc_bowden_length = 1200.0
        result = hub.get_status()
        assert result["afc_bowden_length"] == 1200.0

    def test_get_status_lanes_list(self):
        hub = _make_hub()
        lane1 = MagicMock()
        lane1.name = "lane1"
        lane2 = MagicMock()
        lane2.name = "lane2"
        hub.lanes = {"lane1": lane1, "lane2": lane2}
        result = hub.get_status()
        assert set(result["lanes"]) == {"lane1", "lane2"}

    def test_get_status_servo_angles(self):
        hub = _make_hub()
        hub.cut_servo_pass_angle = 10.0
        hub.cut_servo_clip_angle = 170.0
        hub.cut_servo_prep_angle = 80.0
        result = hub.get_status()
        assert result["cut_servo_pass_angle"] == 10.0
        assert result["cut_servo_clip_angle"] == 170.0
        assert result["cut_servo_prep_angle"] == 80.0

    def test_get_status_cut_distances(self):
        hub = _make_hub()
        hub.cut_dist = 60.0
        hub.cut_clear = 130.0
        hub.cut_min_length = 250.0
        result = hub.get_status()
        assert result["cut_dist"] == 60.0
        assert result["cut_clear"] == 130.0
        assert result["cut_min_length"] == 250.0


# ── handle_runout ─────────────────────────────────────────────────────────────

class TestHandleRunout:
    def test_runout_triggers_current_lane_in_hub(self):
        hub = _make_hub()
        lane = MagicMock()
        hub.lanes = {"lane1": lane}
        hub.afc.current = "lane1"
        hub.handle_runout(100.0)
        lane.handle_hub_runout.assert_called_once_with(sensor=hub.name)

    def test_runout_does_not_trigger_if_current_lane_not_in_hub(self):
        hub = _make_hub()
        lane = MagicMock()
        hub.lanes = {"lane1": lane}
        hub.afc.current = "lane2"  # Different lane
        hub.handle_runout(100.0)
        lane.handle_hub_runout.assert_not_called()

    def test_runout_does_not_trigger_when_no_current(self):
        hub = _make_hub()
        lane = MagicMock()
        hub.lanes = {"lane1": lane}
        hub.afc.current = None
        hub.handle_runout(100.0)
        lane.handle_hub_runout.assert_not_called()

    def test_runout_updates_min_event_systime(self):
        hub = _make_hub()
        hub.lanes = {}
        hub.afc.current = None
        initial_time = hub.fila.runout_helper.min_event_systime
        hub.handle_runout(150.0)
        # min_event_systime should be updated to monotonic + event_delay
        assert hub.fila.runout_helper.min_event_systime != initial_time
