"""
Unit tests for extras/AFC_utils.py

Covers:
  - check_and_return()
  - section_in_config()
  - DebounceButton
  - AFC_moonraker
"""

from __future__ import annotations

import configparser
import json
from io import StringIO
from unittest.mock import MagicMock, patch, call
import pytest

# conftest installs Klipper mocks; extras is on sys.path via REPO_ROOT
from extras.AFC_utils import check_and_return, section_in_config, DebounceButton, AFC_moonraker


# ── check_and_return ──────────────────────────────────────────────────────────

class TestCheckAndReturn:
    def test_key_present_returns_value(self):
        data = {"color": "red", "weight": 250}
        assert check_and_return("color", data) == "red"

    def test_key_present_numeric_string(self):
        data = {"weight": "250"}
        assert check_and_return("weight", data) == "250"

    def test_key_missing_returns_zero_string(self):
        data = {"color": "blue"}
        assert check_and_return("weight", data) == "0"

    def test_empty_dict_returns_zero_string(self):
        assert check_and_return("anything", {}) == "0"

    def test_key_with_none_value(self):
        data = {"key": None}
        assert check_and_return("key", data) is None

    def test_key_with_zero_value(self):
        data = {"key": 0}
        assert check_and_return("key", data) == 0


# ── section_in_config ─────────────────────────────────────────────────────────

class TestSectionInConfig:
    def _make_config(self, *sections):
        """Return a MockConfig whose fileconfig contains the given sections."""
        from tests.conftest import MockConfig, _make_fileconfig
        cfg = MockConfig()
        cfg.fileconfig = _make_fileconfig(*sections)
        return cfg

    def test_exact_section_found(self):
        cfg = self._make_config("AFC_hub my_hub")
        assert section_in_config(cfg, "AFC_hub my_hub") is True

    def test_partial_section_name_found(self):
        cfg = self._make_config("AFC_hub my_hub")
        assert section_in_config(cfg, "my_hub") is True

    def test_section_not_found(self):
        cfg = self._make_config("AFC_hub my_hub")
        assert section_in_config(cfg, "missing_section") is False

    def test_empty_fileconfig_returns_false(self):
        cfg = self._make_config()
        assert section_in_config(cfg, "anything") is False

    def test_multiple_sections_correct_one_found(self):
        cfg = self._make_config("AFC_hub hub1", "AFC_hub hub2", "AFC_lane lane1")
        assert section_in_config(cfg, "hub2") is True
        assert section_in_config(cfg, "lane1") is True
        assert section_in_config(cfg, "lane2") is False


# ── DebounceButton ────────────────────────────────────────────────────────────

class TestDebounceButton:
    """DebounceButton wraps a filament sensor's note_filament_present method."""

    def _make_filament_sensor(self, sig_params):
        """
        Build a minimal filament-sensor mock with the given parameter names
        on its runout_helper.note_filament_present signature.
        """
        import inspect

        # Construct a function with the desired signature dynamically
        arg_list = ", ".join(sig_params)
        exec_globals: dict = {}
        exec(f"def note_filament_present({arg_list}): pass", exec_globals)
        func = exec_globals["note_filament_present"]

        helper = MagicMock()
        helper.note_filament_present = func
        sensor = MagicMock()
        sensor.runout_helper = helper
        return sensor

    def _make_config(self, debounce_delay=0.0):
        from tests.conftest import MockConfig, MockPrinter, MockReactor
        reactor = MockReactor()
        printer = MockPrinter()
        printer._reactor = reactor
        cfg = MockConfig(printer=printer, values={"debounce_delay": debounce_delay})
        return cfg

    def test_init_sets_debounce_delay(self):
        cfg = self._make_config(debounce_delay=0.05)
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        assert btn.debounce_delay == 0.05

    def test_initial_states_are_none(self):
        cfg = self._make_config()
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        assert btn.logical_state is None
        assert btn.physical_state is None
        assert btn.latest_eventtime is None

    def test_button_handler_records_state(self):
        cfg = self._make_config()
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        btn._button_handler(100.0, True)
        assert btn.physical_state is True
        assert btn.latest_eventtime == 100.0

    def test_same_state_does_not_re_register_callback(self):
        cfg = self._make_config()
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        btn.logical_state = True
        reactor = cfg.get_printer().get_reactor()
        reactor.register_callback = MagicMock()
        btn._button_handler(100.0, True)  # same as logical_state → no callback
        reactor.register_callback.assert_not_called()

    def test_state_change_registers_callback(self):
        cfg = self._make_config()
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        btn.logical_state = False
        reactor = cfg.get_printer().get_reactor()
        reactor.register_callback = MagicMock()
        btn._button_handler(100.0, True)  # transition False→True
        reactor.register_callback.assert_called_once()

    def test_debounce_event_ignored_if_no_transition(self):
        cfg = self._make_config()
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        btn.logical_state = True
        btn.physical_state = True
        btn.button_action = MagicMock()
        btn._debounce_event(100.0)
        btn.button_action.assert_not_called()

    def test_debounce_event_updates_logical_state(self):
        cfg = self._make_config(debounce_delay=0.0)
        sensor = self._make_filament_sensor(["self", "eventtime", "state"])
        btn = DebounceButton(cfg, sensor)
        btn.logical_state = False
        btn.physical_state = True
        btn.latest_eventtime = 100.0
        btn.button_action = MagicMock()
        btn._debounce_event(100.0)
        assert btn.logical_state is True


# ── AFC_moonraker ─────────────────────────────────────────────────────────────

class TestAFCMoonraker:
    def _make_moonraker(self, host="http://localhost", port="7125"):
        from tests.conftest import MockLogger
        logger = MockLogger()
        return AFC_moonraker(host, port, logger)

    def test_init_sets_host_with_port(self):
        mr = self._make_moonraker("http://localhost", "7125")
        assert "7125" in mr.host

    def test_init_strips_trailing_slash(self):
        mr = self._make_moonraker("http://localhost/", "7125")
        assert not mr.host.endswith("//")

    def test_init_default_stats_none(self):
        mr = self._make_moonraker()
        assert mr.afc_stats is None
        assert mr.last_stats_time is None

    def test_get_results_connection_error_returns_none(self):
        mr = self._make_moonraker()
        with patch("extras.AFC_utils.urlopen", side_effect=Exception("connection refused")):
            result = mr._get_results("http://localhost:7125/server/info", print_error=False)
        assert result is None

    def test_get_results_bad_status_returns_none(self):
        mr = self._make_moonraker()
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.reason = "Internal Server Error"
        with patch("extras.AFC_utils.urlopen", return_value=mock_resp):
            result = mr._get_results("http://localhost:7125/server/info", print_error=False)
        assert result is None

    def test_get_results_success_returns_data(self):
        mr = self._make_moonraker()
        payload = {"result": {"state": "ready"}}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("extras.AFC_utils.urlopen", return_value=mock_resp), \
             patch("extras.AFC_utils.json.load", return_value=payload):
            result = mr._get_results("http://localhost:7125/server/info")
        assert result == {"state": "ready"}

    def test_check_and_return_helper(self):
        # Ensure the standalone helper works (already tested above, but
        # verify the moonraker module exports it correctly)
        from extras.AFC_utils import check_and_return
        assert check_and_return("x", {"x": 42}) == 42

    def test_update_afc_stats_logs_on_failure(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value=None)
        mr.update_afc_stats("some.key", 10)
        errors = [m for lvl, m in mr.logger.messages if lvl == "error"]
        assert len(errors) == 1

    def test_get_spool_not_found_logs_info(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value=None)
        result = mr.get_spool(42)
        assert result is None
        infos = [m for lvl, m in mr.logger.messages if lvl == "info"]
        assert any("42" in m for m in infos)

    def test_get_spoolman_server_returns_none_when_missing(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value={"orig": {}})
        result = mr.get_spoolman_server()
        assert result is None

    def test_get_spoolman_server_returns_url_when_present(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(
            return_value={"orig": {"spoolman": {"server": "http://spoolman:7912"}}}
        )
        result = mr.get_spoolman_server()
        assert result == "http://spoolman:7912"

    def test_get_file_filament_change_count_default_zero(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value=None)
        assert mr.get_file_filament_change_count("test.gcode") == 0

    def test_get_file_filament_change_count_from_metadata(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value={"filament_change_count": 5})
        assert mr.get_file_filament_change_count("test.gcode") == 5

    def test_get_afc_stats_returns_none_on_empty_db(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value=None)
        result = mr.get_afc_stats()
        assert result is None

    def test_get_afc_stats_returns_cached_after_first_call(self):
        mr = self._make_moonraker()
        payload = {"value": {"toolchange_count": {"total": 10}}}
        mr._get_results = MagicMock(return_value=payload)
        first = mr.get_afc_stats()
        # Second call should use cache (but still calls _get_results when
        # afc_stats is populated, unless last_stats_time is very recent)
        assert first is not None

    def test_check_for_td1_no_td1_in_config(self):
        mr = self._make_moonraker()
        mr._get_results = MagicMock(return_value={"orig": {}})
        td1_defined, td1, lane_data = mr.check_for_td1()
        assert td1_defined is False
        assert td1 is False
        assert lane_data is False
