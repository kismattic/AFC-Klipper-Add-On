"""
Unit tests for extras/AFC_extruder.py

Covers:
  - AFCExtruderStats: cut threshold warning/error logic
  - AFCExtruderStats.increase_cut_total: increments counts
  - AFCExtruderStats.increase_toolcount_change: increments total
  - AFCExtruderStats.reset_stats: resets all counts
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from extras.AFC_extruder import AFCExtruderStats


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_extruder_obj(name="extruder"):
    """Minimal AFCExtruder-like mock."""
    from tests.conftest import MockAFC, MockLogger
    afc = MockAFC()
    afc.afc_stats = MagicMock()
    obj = MagicMock()
    obj.name = name
    obj.afc = afc
    obj.logger = MockLogger()
    return obj


def _make_stats(extruder_name="extruder", cut_threshold=200, cut_since_changed=0):
    """Build an AFCExtruderStats bypassing heavy __init__ logic."""
    obj = _make_extruder_obj(extruder_name)
    stats = AFCExtruderStats.__new__(AFCExtruderStats)
    stats.name = extruder_name
    stats.obj = obj
    logger = obj.logger
    # AFC_extruder accesses self.logger.afc.message_queue; wire it up
    from tests.conftest import MockAFC
    afc_for_logger = MockAFC()
    logger.afc = afc_for_logger
    stats.logger = logger
    stats.cut_threshold_for_warning = cut_threshold
    stats.threshold_warning_sent = False
    stats.threshold_error_sent = False

    from tests.conftest import MockMoonraker
    mr = MockMoonraker()
    mr.update_afc_stats = MagicMock()
    stats.moonraker = mr

    # Create AFCStats_var mocks for the various stats
    def _make_var(value=0):
        v = MagicMock()
        v.value = value
        return v

    stats.cut_total = _make_var(0)
    stats.cut_total_since_changed = _make_var(cut_since_changed)
    stats.last_blade_changed = _make_var(0)
    stats.tc_total = _make_var(0)
    stats.tc_tool_unload = _make_var(0)
    stats.tc_tool_load = _make_var(0)
    stats.tool_selected = _make_var(0)
    stats.tool_unselected = _make_var(0)

    return stats


# ── AFCExtruderStats: initialization ──────────────────────────────────────────

class TestAFCExtruderStatsInit:
    def test_name_stored(self):
        stats = _make_stats("extruder")
        assert stats.name == "extruder"

    def test_cut_threshold_stored(self):
        stats = _make_stats(cut_threshold=300)
        assert stats.cut_threshold_for_warning == 300

    def test_threshold_warning_not_sent_initially(self):
        stats = _make_stats()
        assert stats.threshold_warning_sent is False

    def test_threshold_error_not_sent_initially(self):
        stats = _make_stats()
        assert stats.threshold_error_sent is False


# ── check_cut_threshold ───────────────────────────────────────────────────────

class TestCheckCutThreshold:
    def test_no_message_well_below_threshold(self):
        """No message when cuts < threshold - 1000."""
        stats = _make_stats(cut_threshold=2000, cut_since_changed=500)
        stats.check_cut_threshold()
        assert stats.threshold_warning_sent is False
        assert stats.threshold_error_sent is False

    def test_warning_sent_near_threshold(self):
        """Warning sent when cuts >= threshold - 1000."""
        stats = _make_stats(cut_threshold=2000, cut_since_changed=1001)
        stats.check_cut_threshold()
        assert stats.threshold_warning_sent is True

    def test_warning_logged_near_threshold(self):
        stats = _make_stats(cut_threshold=2000, cut_since_changed=1001)
        stats.check_cut_threshold()
        raw_msgs = [m for lvl, m in stats.logger.messages if lvl == "raw"]
        assert len(raw_msgs) >= 1

    def test_error_sent_at_threshold(self):
        """Error logged when cuts >= threshold."""
        stats = _make_stats(cut_threshold=200, cut_since_changed=200)
        stats.check_cut_threshold()
        assert stats.threshold_error_sent is True

    def test_error_sent_above_threshold(self):
        stats = _make_stats(cut_threshold=200, cut_since_changed=250)
        stats.check_cut_threshold()
        assert stats.threshold_error_sent is True

    def test_warning_not_resent_when_already_sent(self):
        """Warning should not spam logger if already sent."""
        stats = _make_stats(cut_threshold=2000, cut_since_changed=1001)
        stats.threshold_warning_sent = True
        stats.check_cut_threshold()
        raw_msgs = [m for lvl, m in stats.logger.messages if lvl == "raw"]
        assert len(raw_msgs) == 0  # no new messages

    def test_error_not_resent_when_already_sent(self):
        stats = _make_stats(cut_threshold=200, cut_since_changed=250)
        stats.threshold_error_sent = True
        stats.check_cut_threshold()
        raw_msgs = [m for lvl, m in stats.logger.messages if lvl == "raw"]
        assert len(raw_msgs) == 0


# ── increase_cut_total ────────────────────────────────────────────────────────

class TestIncreaseCutTotal:
    def test_increments_cut_total(self):
        stats = _make_stats()
        stats.check_cut_threshold = MagicMock()
        stats.increase_cut_total()
        stats.cut_total.increase_count.assert_called_once()

    def test_increments_cut_total_since_changed(self):
        stats = _make_stats()
        stats.check_cut_threshold = MagicMock()
        stats.increase_cut_total()
        stats.cut_total_since_changed.increase_count.assert_called_once()

    def test_calls_check_cut_threshold(self):
        stats = _make_stats()
        stats.check_cut_threshold = MagicMock()
        stats.increase_cut_total()
        stats.check_cut_threshold.assert_called_once()


# ── increase_toolcount_change ──────────────────────────────────────────────────

class TestIncreaseToolcountChange:
    def test_increments_tc_total(self):
        stats = _make_stats()
        stats.increase_toolcount_change()
        stats.tc_total.increase_count.assert_called_once()

    def test_increments_toolchange_wo_error_on_afc_stats(self):
        stats = _make_stats()
        stats.increase_toolcount_change()
        stats.obj.afc.afc_stats.increase_toolchange_wo_error.assert_called_once()


# ── reset_stats ────────────────────────────────────────────────────────────────

class TestResetStats:
    def test_resets_tc_total(self):
        stats = _make_stats()
        stats.reset_stats()
        stats.tc_total.reset_count.assert_called_once()

    def test_resets_tc_tool_unload(self):
        stats = _make_stats()
        stats.reset_stats()
        stats.tc_tool_unload.reset_count.assert_called_once()

    def test_resets_tc_tool_load(self):
        stats = _make_stats()
        stats.reset_stats()
        stats.tc_tool_load.reset_count.assert_called_once()

    def test_resets_tool_selected(self):
        stats = _make_stats()
        stats.reset_stats()
        stats.tool_selected.reset_count.assert_called_once()

    def test_resets_tool_unselected(self):
        stats = _make_stats()
        stats.reset_stats()
        stats.tool_unselected.reset_count.assert_called_once()
