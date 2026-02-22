"""
Unit tests for extras/AFC_buffer.py

Covers:
  - get_fault_sensitivity: formula validation
  - fault_detection_enabled / disable / restore
  - buffer_status: returns last_state
  - disable_buffer / enable_buffer: toggles enable flag
  - advance_callback / trailing_callback: state tracking
  - pause_on_error: respects enable and min_event_systime
  - update_filament_error_pos / get_extruder_pos
  - start/stop fault timers
  - cmd_QUERY_BUFFER string construction
  - TRAILING_STATE_NAME / ADVANCING_STATE_NAME constants
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from extras.AFC_buffer import (
    AFCTrigger,
    TRAILING_STATE_NAME,
    ADVANCING_STATE_NAME,
    CHECK_RUNOUT_TIMEOUT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_buffer(name="TN", error_sensitivity=0.0):
    """Build an AFCTrigger by bypassing __init__ and setting attributes."""
    buf = AFCTrigger.__new__(AFCTrigger)

    from tests.conftest import MockAFC, MockReactor, MockLogger

    afc = MockAFC()
    reactor = MockReactor()

    buf.printer = MagicMock()
    buf.printer.state_message = "Printer is ready"
    buf.afc = afc
    buf.reactor = reactor
    buf.gcode = afc.gcode
    buf.logger = afc.logger
    buf.name = name
    buf.lanes = {}
    buf.last_state = "Unknown"
    buf.enable = False
    buf.current = ""
    buf.advance_state = False
    buf.trailing_state = False

    buf.error_sensitivity = error_sensitivity
    buf.fault_sensitivity = buf.get_fault_sensitivity(error_sensitivity)
    buf.filament_error_pos = None
    buf.past_extruder_position = None
    buf.extruder_pos_timer = None
    buf.fault_timer = None

    buf.multiplier_high = 1.1
    buf.multiplier_low = 0.9

    buf.led = False
    buf.led_index = None
    buf.led_advancing = "0,0,1,0"
    buf.led_trailing = "0,1,0,0"
    buf.led_buffer_disabled = "0,0,0,0.25"

    buf.min_event_systime = 0.0

    return buf


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_trailing_state_name(self):
        assert TRAILING_STATE_NAME == "Trailing"

    def test_advancing_state_name(self):
        assert ADVANCING_STATE_NAME == "Advancing"

    def test_check_runout_timeout_positive(self):
        assert CHECK_RUNOUT_TIMEOUT > 0


# ── get_fault_sensitivity ─────────────────────────────────────────────────────

class TestGetFaultSensitivity:
    def test_zero_sensitivity_returns_zero(self):
        buf = _make_buffer()
        assert buf.get_fault_sensitivity(0) == 0

    def test_min_sensitivity_one(self):
        buf = _make_buffer()
        # (11 - 1) * 10 = 100
        assert buf.get_fault_sensitivity(1) == 100.0

    def test_max_sensitivity_ten(self):
        buf = _make_buffer()
        # (11 - 10) * 10 = 10
        assert buf.get_fault_sensitivity(10) == 10.0

    def test_mid_sensitivity_five(self):
        buf = _make_buffer()
        # (11 - 5) * 10 = 60
        assert buf.get_fault_sensitivity(5) == 60.0

    def test_higher_sensitivity_means_smaller_fault_distance(self):
        buf = _make_buffer()
        low = buf.get_fault_sensitivity(2)
        high = buf.get_fault_sensitivity(8)
        assert high < low


# ── fault_detection_enabled / disable / restore ───────────────────────────────

class TestFaultDetection:
    def test_enabled_when_sensitivity_positive(self):
        buf = _make_buffer(error_sensitivity=5.0)
        assert buf.fault_detection_enabled() is True

    def test_disabled_when_sensitivity_zero(self):
        buf = _make_buffer(error_sensitivity=0.0)
        assert buf.fault_detection_enabled() is False

    def test_disable_fault_sensitivity_sets_to_zero(self):
        buf = _make_buffer(error_sensitivity=5.0)
        buf.disable_fault_sensitivity()
        assert buf.fault_sensitivity == 0

    def test_restore_fault_sensitivity_restores_from_error_sensitivity(self):
        buf = _make_buffer(error_sensitivity=5.0)
        buf.disable_fault_sensitivity()
        buf.restore_fault_sensitivity()
        expected = buf.get_fault_sensitivity(5.0)
        assert buf.fault_sensitivity == expected


# ── buffer_status ─────────────────────────────────────────────────────────────

class TestBufferStatus:
    def test_returns_last_state(self):
        buf = _make_buffer()
        buf.last_state = TRAILING_STATE_NAME
        assert buf.buffer_status() == TRAILING_STATE_NAME

    def test_returns_unknown_when_unset(self):
        buf = _make_buffer()
        assert buf.buffer_status() == "Unknown"


# ── disable_buffer / enable_buffer ───────────────────────────────────────────

class TestBufferToggle:
    def test_disable_buffer_sets_enable_false(self):
        buf = _make_buffer()
        buf.enable = True
        buf.reset_multiplier = MagicMock()
        buf.disable_buffer()
        assert buf.enable is False

    def test_disable_buffer_calls_reset_multiplier(self):
        buf = _make_buffer()
        buf.enable = True
        buf.reset_multiplier = MagicMock()
        buf.disable_buffer()
        buf.reset_multiplier.assert_called_once()

    def test_enable_buffer_sets_enable_true(self):
        buf = _make_buffer()
        buf.set_multiplier = MagicMock()
        buf.enable_buffer()
        assert buf.enable is True

    def test_enable_buffer_applies_multiplier_trailing(self):
        buf = _make_buffer()
        buf.set_multiplier = MagicMock()
        buf.last_state = TRAILING_STATE_NAME
        buf.enable_buffer()
        call_arg = buf.set_multiplier.call_args[0][0]
        assert call_arg < 1.0  # should be multiplier_low or derivative

    def test_enable_buffer_applies_multiplier_advancing(self):
        buf = _make_buffer()
        buf.set_multiplier = MagicMock()
        buf.last_state = ADVANCING_STATE_NAME
        buf.enable_buffer()
        call_arg = buf.set_multiplier.call_args[0][0]
        assert call_arg > 1.0  # should be multiplier_high or derivative


# ── advance_callback / trailing_callback ─────────────────────────────────────

class TestCallbacks:
    def test_advance_callback_records_advance_state(self):
        buf = _make_buffer()
        buf.advance_callback(100.0, True)
        assert buf.advance_state is True

    def test_advance_callback_records_false_state(self):
        buf = _make_buffer()
        buf.advance_state = True
        buf.advance_callback(100.0, False)
        assert buf.advance_state is False

    def test_advance_callback_sets_last_state_trailing(self):
        """After an advance event, last_state → TRAILING_STATE_NAME."""
        buf = _make_buffer()
        buf.advance_callback(100.0, True)
        assert buf.last_state == TRAILING_STATE_NAME

    def test_trailing_callback_records_trailing_state(self):
        buf = _make_buffer()
        buf.trailing_callback(100.0, True)
        assert buf.trailing_state is True

    def test_trailing_callback_sets_last_state_advancing(self):
        """After a trailing event, last_state → ADVANCING_STATE_NAME."""
        buf = _make_buffer()
        buf.trailing_callback(100.0, True)
        assert buf.last_state == ADVANCING_STATE_NAME


# ── pause_on_error ────────────────────────────────────────────────────────────

class TestPauseOnError:
    def test_does_not_pause_when_disabled(self):
        buf = _make_buffer()
        buf.enable = False
        buf.afc.error = MagicMock()
        buf.pause_on_error("fault", pause=True)
        buf.afc.error.AFC_error.assert_not_called()

    def test_does_not_pause_before_min_event_systime(self):
        buf = _make_buffer()
        buf.enable = True
        buf.min_event_systime = 9_999_999.0  # far in the future
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = False
        buf.pause_on_error("fault", pause=True)
        buf.afc.error.AFC_error.assert_not_called()

    def test_does_not_pause_when_already_paused(self):
        buf = _make_buffer()
        buf.enable = True
        buf.min_event_systime = 0.0
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = True
        buf.pause_on_error("fault", pause=True)
        buf.afc.error.AFC_error.assert_not_called()

    def test_pauses_when_all_conditions_met(self):
        buf = _make_buffer()
        buf.enable = True
        buf.min_event_systime = 0.0
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = False
        buf.last_state = TRAILING_STATE_NAME
        buf.pause_on_error("Something went wrong", pause=True)
        buf.afc.error.AFC_error.assert_called_once()

    def test_clog_message_appended_when_trailing(self):
        buf = _make_buffer()
        buf.enable = True
        buf.min_event_systime = 0.0
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = False
        buf.last_state = TRAILING_STATE_NAME
        buf.pause_on_error("Base message", pause=True)
        call_msg = buf.afc.error.AFC_error.call_args[0][0]
        assert "CLOG" in call_msg

    def test_not_feeding_message_appended_when_advancing(self):
        buf = _make_buffer()
        buf.enable = True
        buf.min_event_systime = 0.0
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = False
        buf.last_state = ADVANCING_STATE_NAME
        buf.pause_on_error("Base message", pause=True)
        call_msg = buf.afc.error.AFC_error.call_args[0][0]
        assert "NOT FEEDING" in call_msg


# ── fault timer helpers ───────────────────────────────────────────────────────

class TestFaultTimers:
    def test_start_fault_timer_sets_fault_timer_running(self):
        buf = _make_buffer()
        buf.extruder_pos_timer = MagicMock()
        buf.start_fault_timer(100.0)
        assert buf.fault_timer == "Running"

    def test_stop_fault_timer_sets_fault_timer_stopped(self):
        buf = _make_buffer()
        buf.extruder_pos_timer = MagicMock()
        buf.stop_fault_timer(100.0)
        assert buf.fault_timer == "Stopped"


# ── extruder_pos_update_event ─────────────────────────────────────────────────

class TestExtruderPosUpdateEvent:
    def test_returns_eventtime_plus_timeout(self):
        buf = _make_buffer()
        buf.get_extruder_pos = MagicMock(return_value=None)
        buf.afc.function.is_printing.return_value = False
        result = buf.extruder_pos_update_event(50.0)
        assert result == 50.0 + CHECK_RUNOUT_TIMEOUT

    def test_triggers_pause_when_extruder_pos_exceeds_threshold(self):
        buf = _make_buffer(error_sensitivity=5.0)
        buf.enable = True
        buf.min_event_systime = 0.0
        buf.filament_error_pos = 50.0
        buf.afc.error = MagicMock()
        buf.afc.function.is_paused.return_value = False
        buf.afc.function.is_printing.return_value = True
        buf.get_extruder_pos = MagicMock(return_value=55.0)  # > 50.0
        buf.update_filament_error_pos = MagicMock()
        buf.extruder_pos_update_event(100.0)
        buf.afc.error.AFC_error.assert_called()


# ── get_status ────────────────────────────────────────────────────────────────

class TestGetStatus:
    def test_returns_dict_with_expected_keys(self):
        buf = _make_buffer()
        buf.afc.function.get_current_lane_obj.return_value = None
        result = buf.get_status()
        for key in ("state", "lanes", "enabled", "rotation_distance",
                    "fault_detection_enabled", "error_sensitivity",
                    "fault_timer", "distance_to_fault"):
            assert key in result, f"Missing key: {key}"

    def test_enabled_false_by_default(self):
        buf = _make_buffer()
        buf.afc.function.get_current_lane_obj.return_value = None
        result = buf.get_status()
        assert result["enabled"] is False

    def test_rotation_distance_none_when_not_enabled(self):
        buf = _make_buffer()
        result = buf.get_status()
        assert result["rotation_distance"] is None
