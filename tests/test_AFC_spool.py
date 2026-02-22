"""
Unit tests for extras/AFC_spool.py

Covers:
  - AFCSpool: initialization
  - cmd_SET_MAP: validates lane mapping
  - cmd_SET_COLOR / cmd_SET_MATERIAL / cmd_SET_WEIGHT: attribute updates
  - cmd_SET_SPOOL_ID: spoolman interaction
  - cmd_SET_RUNOUT: runout lane assignment
  - cmd_RESET_AFC_MAPPING: clears mappings
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from extras.AFC_spool import AFCSpool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_spool():
    """Build an AFCSpool instance bypassing __init__."""
    spool = AFCSpool.__new__(AFCSpool)

    from tests.conftest import MockAFC, MockPrinter, MockLogger, MockGcode

    afc = MockAFC()
    printer = MockPrinter(afc=afc)
    afc.logger = MockLogger()
    afc.gcode = MockGcode()
    afc.reactor = MagicMock()
    afc.spoolman = None
    afc.tool_cmds = {}
    afc.lanes = {}

    spool.printer = printer
    spool.afc = afc
    spool.error = afc.error
    spool.reactor = afc.reactor
    spool.gcode = afc.gcode
    spool.logger = afc.logger
    spool.disable_weight_check = False
    spool.next_spool_id = None

    return spool


def _make_lane(name="lane1"):
    lane = MagicMock()
    lane.name = name
    lane.map = None
    lane.color = ""
    lane.material = ""
    lane.weight = 0
    lane.spool_id = None
    lane.runout_lane = None
    lane.unit_obj = MagicMock()
    lane.hub_obj = MagicMock()
    lane.extruder_obj = MagicMock()
    return lane


def _make_gcmd(**kwargs):
    """Build a gcmd mock that returns values from kwargs."""
    gcmd = MagicMock()
    gcmd.get = lambda key, default=None: kwargs.get(key, default)
    def _get_float(key, default=0.0, **kw):
        val = kwargs.get(key, default)
        return float(val) if val is not None else None
    gcmd.get_float = _get_float
    gcmd.get_int = lambda key, default=0, **kw: int(kwargs.get(key, default))
    return gcmd


# ── cmd_SET_MAP ────────────────────────────────────────────────────────────────

class TestSetMap:
    def test_set_map_assigns_lane_mapping(self):
        spool = _make_spool()
        lane1 = _make_lane("lane1")
        lane2 = _make_lane("lane2")
        lane2.map = "T0"
        # T0 is currently mapped to lane2; we want to remap it to lane1
        spool.afc.tool_cmds = {"T0": "lane2"}
        spool.afc.lanes = {"lane1": lane1, "lane2": lane2}
        gcmd = _make_gcmd(LANE="lane1", MAP="T0")
        spool.cmd_SET_MAP(gcmd)
        assert lane1.map == "T0"
        assert spool.afc.tool_cmds.get("T0") == "lane1"

    def test_set_map_invalid_lane_logs_error(self):
        spool = _make_spool()
        spool.afc.lanes = {}
        gcmd = _make_gcmd(LANE="nonexistent", MAP="T1")
        spool.cmd_SET_MAP(gcmd)
        # Should log an error about invalid lane
        error_msgs = [m for lvl, m in spool.logger.messages if lvl == "error"]
        assert len(error_msgs) > 0


# ── cmd_SET_COLOR ──────────────────────────────────────────────────────────────

class TestSetColor:
    def test_set_color_updates_lane_color(self):
        spool = _make_spool()
        lane = _make_lane("lane1")
        spool.afc.lanes = {"lane1": lane}
        gcmd = _make_gcmd(LANE="lane1", COLOR="#FF0000")
        spool.cmd_SET_COLOR(gcmd)
        assert lane.color == "#FF0000"

    def test_set_color_saves_vars(self):
        spool = _make_spool()
        lane = _make_lane("lane1")
        spool.afc.lanes = {"lane1": lane}
        spool.afc.save_vars = MagicMock()
        gcmd = _make_gcmd(LANE="lane1", COLOR="red")
        spool.cmd_SET_COLOR(gcmd)
        spool.afc.save_vars.assert_called()


# ── cmd_SET_MATERIAL ───────────────────────────────────────────────────────────

class TestSetMaterial:
    def test_set_material_updates_lane_material(self):
        spool = _make_spool()
        lane = _make_lane("lane1")
        spool.afc.lanes = {"lane1": lane}
        gcmd = _make_gcmd(LANE="lane1", MATERIAL="PLA")
        spool.cmd_SET_MATERIAL(gcmd)
        assert lane.material == "PLA"

    def test_set_material_saves_vars(self):
        spool = _make_spool()
        lane = _make_lane("lane1")
        spool.afc.lanes = {"lane1": lane}
        spool.afc.save_vars = MagicMock()
        gcmd = _make_gcmd(LANE="lane1", MATERIAL="ABS")
        spool.cmd_SET_MATERIAL(gcmd)
        spool.afc.save_vars.assert_called()


# ── cmd_SET_WEIGHT ─────────────────────────────────────────────────────────────

class TestSetWeight:
    def test_set_weight_updates_lane_weight(self):
        spool = _make_spool()
        lane = _make_lane("lane1")
        spool.afc.lanes = {"lane1": lane}
        gcmd = _make_gcmd(LANE="lane1", WEIGHT=250)
        spool.cmd_SET_WEIGHT(gcmd)
        assert lane.weight == 250

    def test_set_weight_invalid_lane_logs_info(self):
        spool = _make_spool()
        spool.afc.lanes = {}
        gcmd = _make_gcmd(LANE="missing", WEIGHT=100)
        spool.cmd_SET_WEIGHT(gcmd)
        info_msgs = [m for lvl, m in spool.logger.messages if lvl == "info"]
        assert len(info_msgs) > 0


# ── cmd_SET_RUNOUT ─────────────────────────────────────────────────────────────

class TestSetRunout:
    def test_set_runout_assigns_runout_lane(self):
        spool = _make_spool()
        lane1 = _make_lane("lane1")
        lane2 = _make_lane("lane2")
        spool.afc.lanes = {"lane1": lane1, "lane2": lane2}
        gcmd = _make_gcmd(LANE="lane1", RUNOUT="lane2")
        spool.cmd_SET_RUNOUT(gcmd)
        assert lane1.runout_lane == "lane2"

    def test_set_runout_saves_vars(self):
        spool = _make_spool()
        lane1 = _make_lane("lane1")
        lane2 = _make_lane("lane2")
        spool.afc.lanes = {"lane1": lane1, "lane2": lane2}
        spool.afc.save_vars = MagicMock()
        gcmd = _make_gcmd(LANE="lane1", RUNOUT="lane2")
        spool.cmd_SET_RUNOUT(gcmd)
        spool.afc.save_vars.assert_called()


# ── cmd_RESET_AFC_MAPPING ─────────────────────────────────────────────────────

class TestResetAFCMapping:
    def _make_reset_gcmd(self, runout="yes"):
        gcmd = MagicMock()
        gcmd.get = lambda key, default=None: runout if key == "RUNOUT" else default
        return gcmd

    def _make_lane_for_reset(self, name, map_cmd="T0"):
        """Lane mock with explicit _map=None and map=map_cmd."""
        lane = _make_lane(name)
        lane.map = map_cmd
        lane._map = None  # not manually assigned
        lane.runout_lane = None
        return lane

    def test_reset_saves_vars(self):
        spool = _make_spool()
        lane1 = self._make_lane_for_reset("lane1", "T0")
        spool.afc.lanes = {"lane1": lane1}
        spool.afc.units = {}  # no units, loop skips mapping reassignment
        gcmd = self._make_reset_gcmd()
        spool.cmd_RESET_AFC_MAPPING(gcmd)
        spool.afc.save_vars.assert_called()

    def test_reset_clears_runout_lanes(self):
        spool = _make_spool()
        lane1 = self._make_lane_for_reset("lane1", "T0")
        lane1.runout_lane = "lane2"
        spool.afc.lanes = {"lane1": lane1}
        spool.afc.units = {}
        gcmd = self._make_reset_gcmd(runout="yes")
        spool.cmd_RESET_AFC_MAPPING(gcmd)
        assert lane1.runout_lane is None

    def test_reset_skips_runout_when_no(self):
        spool = _make_spool()
        lane1 = self._make_lane_for_reset("lane1", "T0")
        lane1.runout_lane = "lane2"
        spool.afc.lanes = {"lane1": lane1}
        spool.afc.units = {}
        gcmd = self._make_reset_gcmd(runout="no")
        spool.cmd_RESET_AFC_MAPPING(gcmd)
        assert lane1.runout_lane == "lane2"  # not cleared


# ── cmd_SET_NEXT_SPOOL_ID ─────────────────────────────────────────────────────

class TestSetNextSpoolId:
    def test_stores_next_spool_id(self):
        spool = _make_spool()
        gcmd = _make_gcmd(SPOOL_ID=42)
        spool.cmd_SET_NEXT_SPOOL_ID(gcmd)
        assert spool.next_spool_id == 42
