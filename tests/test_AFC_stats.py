"""
Unit tests for extras/AFC_stats.py

Covers:
  - AFCStats_var: init, value retrieval, increment, reset, average_time,
    get_average, update_database, set_current_time, __str__, value property
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from extras.AFC_stats import AFCStats_var


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_moonraker(stats_data=None):
    from tests.conftest import MockMoonraker
    mr = MockMoonraker()
    mr._stats = stats_data or {}
    return mr


def make_var(parent_name, name, data=None, moonraker=None, new_parent_name="", new_average=False):
    mr = moonraker or make_moonraker()
    return AFCStats_var(parent_name, name, data, mr, new_parent_name, new_average)


# ── AFCStats_var ──────────────────────────────────────────────────────────────

class TestAFCStatsVarInit:
    def test_init_no_data_defaults_to_zero(self):
        var = make_var("extruder", "cut_total", data=None)
        assert var.value == 0

    def test_init_data_missing_parent_defaults_to_zero(self):
        data = {"other_parent": {"cut_total": 5}}
        var = make_var("extruder", "cut_total", data=data)
        assert var.value == 0

    def test_init_data_with_matching_parent_single_level(self):
        data = {"extruder": {"cut_total": 42}}
        var = make_var("extruder", "cut_total", data=data)
        assert var.value == 42

    def test_init_data_with_matching_parent_two_levels(self):
        data = {"extruder": {"cut": {"cut_total": 7}}}
        var = make_var("extruder.cut", "cut_total", data=data)
        assert var.value == 7

    def test_init_data_float_value(self):
        data = {"timing": {"avg": "3.14"}}
        var = make_var("timing", "avg", data=data)
        assert abs(var.value - 3.14) < 1e-9

    def test_init_data_int_value_as_string(self):
        data = {"extruder": {"count": "5"}}
        var = make_var("extruder", "count", data=data)
        assert var.value == 5
        assert isinstance(var.value, int)

    def test_init_data_non_numeric_string(self):
        data = {"extruder": {"date": "2024-01-01"}}
        var = make_var("extruder", "date", data=data)
        assert var.value == "2024-01-01"

    def test_init_new_parent_renames_and_deletes_old(self):
        mr = make_moonraker()
        mr.remove_database_entry = MagicMock()
        mr.update_afc_stats = MagicMock()
        data = {"old_parent": {"count": 3}}
        var = AFCStats_var("old_parent", "count", data, mr, new_parent_name="new_parent")
        assert var.parent_name == "new_parent"
        mr.update_afc_stats.assert_called()

    def test_str_representation(self):
        var = make_var("extruder", "cut_total", data={"extruder": {"cut_total": 10}})
        assert str(var) == "10"

    def test_value_property_getter(self):
        var = make_var("extruder", "cut_total")
        var.value = 99
        assert var.value == 99

    def test_value_property_setter(self):
        var = make_var("extruder", "cut_total")
        var.value = 55
        assert var._value == 55


class TestAFCStatsVarIncrement:
    def test_increase_count_increments_by_one(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr)
        var.increase_count()
        assert var.value == 1
        mr.update_afc_stats.assert_called_once()

    def test_increase_count_multiple_times(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr)
        for _ in range(5):
            var.increase_count()
        assert var.value == 5


class TestAFCStatsVarReset:
    def test_reset_count_sets_to_zero(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr)
        var._value = 100
        var.reset_count()
        assert var.value == 0

    def test_reset_count_enables_new_average(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr, new_average=False)
        var._value = 50
        var.reset_count()
        assert var.new_average is True

    def test_reset_count_calls_update_database(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr)
        var._value = 10
        var.reset_count()
        mr.update_afc_stats.assert_called()


class TestAFCStatsVarAverageTime:
    def test_average_time_first_value_sets_value(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("timing", "avg", moonraker=mr)
        var.average_time(10.0)
        assert var.value == 10.0

    def test_average_time_old_method_divides_by_two(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("timing", "avg", moonraker=mr, new_average=False)
        var._value = 10.0
        var.average_time(20.0)
        assert var.value == 15.0  # (10+20)/2

    def test_average_time_new_method_sums(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("timing", "avg", moonraker=mr, new_average=True)
        var._value = 10.0
        var.average_time(20.0)
        assert var.value == 30.0  # 10 + 20 (no division)

    def test_get_average_new_method_divides_by_total(self):
        var = make_var("timing", "avg", new_average=True)
        var._value = 30.0
        result = var.get_average(total=3)
        assert result == 10.0

    def test_get_average_new_method_zero_total(self):
        var = make_var("timing", "avg", new_average=True)
        var._value = 30.0
        result = var.get_average(total=0)
        assert result == 30.0

    def test_get_average_old_method_returns_value(self):
        var = make_var("timing", "avg", new_average=False)
        var._value = 15.0
        result = var.get_average(total=5)
        assert result == 15.0


class TestAFCStatsVarUpdateDatabase:
    def test_update_database_calls_moonraker_with_correct_key(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder", "cut_total", moonraker=mr)
        var._value = 7
        var.update_database()
        mr.update_afc_stats.assert_called_once_with("extruder.cut_total", 7)

    def test_update_database_two_level_parent(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("extruder.cut", "cut_total", moonraker=mr)
        var._value = 3
        var.update_database()
        mr.update_afc_stats.assert_called_once_with("extruder.cut.cut_total", 3)


class TestAFCStatsVarSetCurrentTime:
    def test_set_current_time_updates_value_and_database(self):
        mr = make_moonraker()
        mr.update_afc_stats = MagicMock()
        var = make_var("error_stats", "last_load_error", moonraker=mr)
        var.set_current_time()
        assert isinstance(var.value, str)
        assert len(var.value) > 0
        mr.update_afc_stats.assert_called()
