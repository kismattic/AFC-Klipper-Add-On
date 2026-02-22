"""
Unit tests for extras/AFC_error.py

Covers:
  - set_error_state: sets error_state and current_state on AFC
  - reset_failure: resets error_state, pause, position_saved, in_toolchange
  - PauseUserIntervention: only pauses when homed and not already paused
  - pause_print: calls PAUSE script
  - handle_lane_failure: disables stepper, sets lane status, calls AFC_error
  - AFC_error: logs error, optionally calls pause_print
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_afc_error():
    """Create an afcError instance bypassing __init__ and wiring up mocks."""
    from extras.AFC_error import afcError
    from extras.AFC_lane import AFCLaneState
    from extras.AFC import State
    from tests.conftest import MockAFC, MockPrinter, MockLogger

    afc = MockAFC()
    afc.error_state = False
    afc.current_state = State.IDLE
    afc.function = MagicMock()
    afc.function.is_homed = MagicMock(return_value=True)
    afc.function.is_paused = MagicMock(return_value=False)
    afc.save_pos = MagicMock()
    afc.save_vars = MagicMock()

    pause_resume = MagicMock()
    idle_timeout = MagicMock()
    idle_timeout.idle_timeout = 600

    printer = MockPrinter(afc=afc)
    printer._objects["pause_resume"] = pause_resume
    printer._objects["idle_timeout"] = idle_timeout

    # Build afcError without running __init__ (it needs a Klipper config)
    err = afcError.__new__(afcError)
    err.printer = printer
    err.afc = afc
    err.logger = MockLogger()
    err.pause = False
    err.pause_resume = pause_resume
    err.error_timeout = 600
    err.idle_timeout_obj = idle_timeout
    err.idle_timeout_val = idle_timeout.idle_timeout
    err.BASE_RESUME_NAME = "RESUME"
    err.AFC_RENAME_RESUME_NAME = "_AFC_RENAMED_RESUME_"
    err.BASE_PAUSE_NAME = "PAUSE"
    err.AFC_RENAME_PAUSE_NAME = "_AFC_RENAMED_PAUSE_"
    err.errorLog = {}

    return err, afc


# ── set_error_state ───────────────────────────────────────────────────────────

class TestSetErrorState:
    def test_set_true_sets_error_state(self):
        err, afc = _make_afc_error()
        err.set_error_state(True)
        assert afc.error_state is True

    def test_set_true_changes_current_state_to_error(self):
        from extras.AFC import State
        err, afc = _make_afc_error()
        err.set_error_state(True)
        assert afc.current_state == State.ERROR

    def test_set_false_clears_error_state(self):
        err, afc = _make_afc_error()
        afc.error_state = True
        err.set_error_state(False)
        assert afc.error_state is False

    def test_set_false_changes_current_state_to_idle(self):
        from extras.AFC import State
        err, afc = _make_afc_error()
        afc.error_state = True
        err.set_error_state(False)
        assert afc.current_state == State.IDLE

    def test_set_true_when_not_yet_error_calls_save_pos(self):
        err, afc = _make_afc_error()
        afc.error_state = False
        err.set_error_state(True)
        afc.save_pos.assert_called_once()

    def test_set_true_when_already_error_does_not_duplicate_save_pos(self):
        err, afc = _make_afc_error()
        afc.error_state = True
        err.set_error_state(True)
        afc.save_pos.assert_not_called()


# ── reset_failure ─────────────────────────────────────────────────────────────

class TestResetFailure:
    def test_reset_failure_clears_error_state(self):
        err, afc = _make_afc_error()
        afc.error_state = True
        err.reset_failure()
        assert afc.error_state is False

    def test_reset_failure_clears_pause_flag(self):
        err, afc = _make_afc_error()
        err.pause = True
        err.reset_failure()
        assert err.pause is False

    def test_reset_failure_clears_position_saved(self):
        err, afc = _make_afc_error()
        afc.position_saved = True
        err.reset_failure()
        assert afc.position_saved is False

    def test_reset_failure_clears_in_toolchange(self):
        err, afc = _make_afc_error()
        afc.in_toolchange = True
        err.reset_failure()
        assert afc.in_toolchange is False

    def test_reset_failure_logs_debug(self):
        err, afc = _make_afc_error()
        err.reset_failure()
        debug_msgs = [m for lvl, m in err.logger.messages if lvl == "debug"]
        assert len(debug_msgs) > 0


# ── PauseUserIntervention ─────────────────────────────────────────────────────

class TestPauseUserIntervention:
    def test_pause_when_homed_and_not_paused(self):
        err, afc = _make_afc_error()
        err.pause = True
        err.pause_print = MagicMock()
        afc.function.is_homed.return_value = True
        afc.function.is_paused.return_value = False
        err.PauseUserIntervention("Some message")
        err.pause_print.assert_called_once()

    def test_no_pause_when_not_homed(self):
        err, afc = _make_afc_error()
        err.pause = True
        err.pause_print = MagicMock()
        afc.function.is_homed.return_value = False
        err.PauseUserIntervention("Some message")
        err.pause_print.assert_not_called()

    def test_no_pause_when_already_paused(self):
        err, afc = _make_afc_error()
        err.pause = True
        err.pause_print = MagicMock()
        afc.function.is_homed.return_value = True
        afc.function.is_paused.return_value = True
        err.PauseUserIntervention("Some message")
        err.pause_print.assert_not_called()

    def test_error_is_logged(self):
        err, afc = _make_afc_error()
        err.pause_print = MagicMock()
        afc.function.is_homed.return_value = True
        afc.function.is_paused.return_value = False
        err.PauseUserIntervention("Bad thing happened")
        error_msgs = [m for lvl, m in err.logger.messages if lvl == "error"]
        assert any("Bad thing happened" in m for m in error_msgs)


# ── pause_print ───────────────────────────────────────────────────────────────

class TestPausePrint:
    def test_pause_print_calls_gcode_pause(self):
        err, afc = _make_afc_error()
        err.set_error_state = MagicMock()
        afc.function.log_toolhead_pos = MagicMock()
        afc.gcode.run_script_from_command = MagicMock()
        err.pause_print()
        afc.gcode.run_script_from_command.assert_called()
        script_arg = afc.gcode.run_script_from_command.call_args[0][0]
        assert "PAUSE" in script_arg

    def test_pause_print_sets_error_state(self):
        err, afc = _make_afc_error()
        err.set_error_state = MagicMock()
        afc.function.log_toolhead_pos = MagicMock()
        afc.gcode.run_script_from_command = MagicMock()
        err.pause_print()
        err.set_error_state.assert_called_once_with(True)


# ── handle_lane_failure ───────────────────────────────────────────────────────

class TestHandleLaneFailure:
    def test_disables_lane_stepper(self):
        from extras.AFC_lane import AFCLaneState
        err, afc = _make_afc_error()
        err.AFC_error = MagicMock()
        cur_lane = MagicMock()
        cur_lane.name = "lane1"
        cur_lane.do_enable = MagicMock()
        cur_lane.led_index = "1"
        err.handle_lane_failure(cur_lane, "jammed", pause=False)
        cur_lane.do_enable.assert_called_once_with(False)

    def test_sets_lane_status_to_error(self):
        from extras.AFC_lane import AFCLaneState
        err, afc = _make_afc_error()
        err.AFC_error = MagicMock()
        cur_lane = MagicMock()
        cur_lane.name = "lane1"
        err.handle_lane_failure(cur_lane, "jammed", pause=False)
        assert cur_lane.status == AFCLaneState.ERROR

    def test_calls_afc_error_with_lane_name_in_message(self):
        err, afc = _make_afc_error()
        err.AFC_error = MagicMock()
        cur_lane = MagicMock()
        cur_lane.name = "lane2"
        cur_lane.led_index = "2"
        err.handle_lane_failure(cur_lane, "overheated", pause=False)
        called_msg = err.AFC_error.call_args[0][0]
        assert "lane2" in called_msg
        assert "overheated" in called_msg


# ── AFC_error (the method) ────────────────────────────────────────────────────

class TestAFCErrorMethod:
    def test_logs_error_message(self):
        err, afc = _make_afc_error()
        err.pause_print = MagicMock()
        err.AFC_error("Catastrophic failure", pause=False)
        error_msgs = [m for lvl, m in err.logger.messages if lvl == "error"]
        assert any("Catastrophic failure" in m for m in error_msgs)

    def test_pause_true_calls_pause_print(self):
        err, afc = _make_afc_error()
        err.pause_print = MagicMock()
        err.AFC_error("Uh oh", pause=True)
        err.pause_print.assert_called_once()

    def test_pause_false_skips_pause_print(self):
        err, afc = _make_afc_error()
        err.pause_print = MagicMock()
        err.AFC_error("Uh oh", pause=False)
        err.pause_print.assert_not_called()
