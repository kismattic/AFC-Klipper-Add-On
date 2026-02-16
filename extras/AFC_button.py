# Armored Turtle Automated Filament Changer
#
# Copyright (C) 2025 Armored Turtle
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from __future__ import annotations

from configfile import error


class AFCButton:
    """
    AFC button controls.

    Supports two modes:
      - mode = "lane"   (default): button is bound to a specific lane (existing behavior)
      - mode = "single": one button cycles lanes, selects lane, then selects LOAD/EJECT, confirm, cancel

    Single-button UI (mode="single"):
      - UI is normally idle (no LED override) until first interaction
      - Short press: cycle lanes (LANE_SELECT) / toggle action (ACTION_SELECT)
      - Long press: select lane / confirm action
      - Double short press: cancel/exit UI (restore LEDs)
      - Very long press: cancel/exit UI (restore LEDs)
    """

    MODE_LANE = "lane"
    MODE_SINGLE = "single"

    UI_LANE_SELECT = "lane_select"
    UI_ACTION_SELECT = "action_select"

    ACTION_LOAD = "load"
    ACTION_EJECT = "eject"

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.load_object(config, "gcode")
        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.reactor = self.printer.get_reactor()

        self.afc = self.printer.load_object(config, "AFC")

        # Mode selection
        self.mode = config.get("mode", self.MODE_LANE).strip().lower()
        if self.mode not in (self.MODE_LANE, self.MODE_SINGLE):
            raise error(f"Invalid AFC_button mode '{self.mode}'. Valid: lane|single")

        # Timings
        self.long_press_duration = config.getfloat("long_press_duration", 1.2)
        self.cancel_press_duration = config.getfloat("cancel_press_duration", 2.8)
        self.double_press_window = config.getfloat("double_press_window", 0.35)

        # LED colors for the UI (R,G,B,W in 0..1)
        self.ui_led_yellow = config.get("ui_led_yellow", "1,1,0,0")
        self.ui_led_green = config.get("ui_led_green", "0,1,0,0")
        self.ui_led_red = config.get("ui_led_red", "1,0,0,0")

        pin_name = config.get("pin")

        # Internal state for press timing
        self._press_time = None
        self._last_short_release = None

        # Lane-mode binding (existing behavior)
        self.lane_id = config.get_name().split()[-1]
        self.lane_obj = None

        # Single-button state
        self._ui_state = self.UI_LANE_SELECT
        self._lane_names: list[str] = []
        self._lane_index = 0
        self._selected_lane_name: str | None = None
        self._selected_action: str | None = None

        # Track which lane LED we are currently overriding (so we can restore it)
        self._ui_led_lane_name: str | None = None

        # Register the button callback
        buttons = self.printer.load_object(config, "buttons")
        buttons.register_buttons([pin_name], self._button_callback)

        if self.mode == self.MODE_SINGLE:
            self.afc.logger.info(f"AFC_button initialized in SINGLE mode on pin: {pin_name}")
        else:
            self.afc.logger.info(f"AFC_button for {self.lane_id} initialized on pin: {pin_name}")

    def _handle_ready(self):
        if self.mode == self.MODE_SINGLE:
            # Snapshot available lanes for cycling
            # (sorted for predictability)
            self._lane_names = sorted(list(self.afc.lanes.keys()))
            if not self._lane_names:
                raise error("AFC_button single mode: no lanes found in configuration.")
            self._lane_index = max(0, min(self._lane_index, len(self._lane_names) - 1))
            self._ui_state = self.UI_LANE_SELECT
            self._selected_lane_name = None
            self._selected_action = None
            self._ui_led_lane_name = None
            self._announce_lane_highlight()
            return

        # Lane mode (existing behavior)
        self.lane_obj = self.afc.lanes.get(self.lane_id)
        if not self.lane_obj:
            raise error(
                f"Lane {self.lane_id} is not defined/found in your configuration file. "
                f"Please define lane or verify lane name is correct."
            )

    # ----------------------------
    # Helpers (LED handling)
    # ----------------------------

    def _set_lane_led(self, lane_obj, color: str | None):
        """
        Safely set a lane LED color if lane has led_index.
        color is expected to be "R,G,B,W" floats in 0..1.
        """
        if lane_obj is None:
            return
        idx = getattr(lane_obj, "led_index", None)
        if idx is None:
            return
        if not color:
            return
        try:
            self.afc.function.afc_led(color, idx)
        except Exception:
            # Don't let UI LEDs break core behavior
            pass

    def _restore_lane_led_default(self, lane_obj):
        """
        Restore a lane LED to its normal AFC state based on sensor/tool state.
        """
        if lane_obj is None:
            return
        idx = getattr(lane_obj, "led_index", None)
        if idx is None:
            return

        try:
            # Tool-loaded takes priority if this lane is the one actually loaded in the extruder
            extruder_obj = getattr(lane_obj, "extruder_obj", None)
            if getattr(lane_obj, "tool_loaded", False) and extruder_obj is not None:
                if getattr(extruder_obj, "lane_loaded", "") == getattr(lane_obj, "name", ""):
                    self._set_lane_led(lane_obj, getattr(lane_obj, "led_tool_loaded", None))
                    return

            prep = bool(getattr(lane_obj, "prep_state", False))
            load = bool(getattr(lane_obj, "load_state", False))

            if prep and load:
                self._set_lane_led(lane_obj, getattr(lane_obj, "led_ready", None))
            elif prep and not load:
                self._set_lane_led(lane_obj, getattr(lane_obj, "led_prep_loaded", None))
            else:
                self._set_lane_led(lane_obj, getattr(lane_obj, "led_not_ready", None))
        except Exception:
            pass

    def _ui_led_apply(self, lane_name: str | None, color: str | None):
        """
        Apply a UI LED override to a lane, restoring the previously overridden lane first.
        """
        # Restore previous override lane (if switching)
        if self._ui_led_lane_name and self._ui_led_lane_name != lane_name:
            prev_obj = self._get_lane_obj_by_name(self._ui_led_lane_name)
            self._restore_lane_led_default(prev_obj)

        self._ui_led_lane_name = lane_name

        # Apply new override
        if lane_name:
            lane_obj = self._get_lane_obj_by_name(lane_name)
            self._set_lane_led(lane_obj, color)

    def _ui_led_clear(self):
        """
        Clear any UI LED override and restore that lane to default state.
        """
        if self._ui_led_lane_name:
            lane_obj = self._get_lane_obj_by_name(self._ui_led_lane_name)
            self._restore_lane_led_default(lane_obj)
        self._ui_led_lane_name = None

    # ----------------------------
    # Helpers (single-button mode)
    # ----------------------------

    def _get_highlight_lane_name(self) -> str:
        return self._lane_names[self._lane_index]

    def _get_lane_obj_by_name(self, lane_name: str):
        return self.afc.lanes.get(lane_name)

    def _is_lane_loaded(self, lane_obj) -> bool:
        # "Loaded" in the sense that a spool is in the lane path (not necessarily tooled)
        # Prefer sensor state when available.
        try:
            if hasattr(lane_obj, "load_state"):
                return bool(lane_obj.load_state)
        except Exception:
            pass
        # Fallback to status flags if present
        try:
            return str(getattr(lane_obj, "status", "")).lower() in (
                "loaded",
                "tooled",
                "tool loaded",
                "tool loading",
                "hub loading",
            )
        except Exception:
            return False

    def _default_action_for_lane(self, lane_obj) -> str:
        # If lane is loaded -> user likely wants to eject, else load it
        return self.ACTION_EJECT if self._is_lane_loaded(lane_obj) else self.ACTION_LOAD

    def _announce_lane_highlight(self):
        lane = self._get_highlight_lane_name()
        lane_obj = self._get_lane_obj_by_name(lane)
        loaded = self._is_lane_loaded(lane_obj) if lane_obj is not None else False
        self.afc.logger.info(f"[AFC Button] Select lane: {lane} (loaded={loaded})")

        # UI LED: highlighted lane in yellow
        self._ui_led_apply(lane, self.ui_led_yellow)

    def _announce_action(self):
        lane = self._selected_lane_name
        action = self._selected_action
        self.afc.logger.info(f"[AFC Button] Lane={lane} action={action.upper() if action else None}")

        # UI LED: selected lane green for LOAD, red for EJECT
        if lane and action:
            color = self.ui_led_green if action == self.ACTION_LOAD else self.ui_led_red
            self._ui_led_apply(lane, color)

    def _cancel_to_lane_select(self, reason: str = "cancel"):
        self._ui_state = self.UI_LANE_SELECT
        self._selected_lane_name = None
        self._selected_action = None
        self.afc.logger.info(f"[AFC Button] Cancel -> lane select ({reason})")
        self._announce_lane_highlight()

    def _single_cycle_lane(self):
        self._lane_index = (self._lane_index + 1) % len(self._lane_names)
        self._announce_lane_highlight()

    def _single_select_lane(self):
        self._selected_lane_name = self._get_highlight_lane_name()
        lane_obj = self._get_lane_obj_by_name(self._selected_lane_name)
        if lane_obj is None:
            self.afc.error.AFC_error(f"Selected lane '{self._selected_lane_name}' not found.", pause=False)
            self._cancel_to_lane_select("lane_missing")
            return
        self._selected_action = self._default_action_for_lane(lane_obj)
        self._ui_state = self.UI_ACTION_SELECT
        self.afc.logger.info(f"[AFC Button] Selected lane: {self._selected_lane_name}")
        self._announce_action()

    def _single_toggle_action(self):
        if self._selected_action == self.ACTION_LOAD:
            self._selected_action = self.ACTION_EJECT
        else:
            self._selected_action = self.ACTION_LOAD
        self._announce_action()

    def _execute_action(self, lane_obj, action: str):
        cur_lane = self.afc.function.get_current_lane_obj()

        if action == self.ACTION_LOAD:
            self.afc.logger.info(f"[AFC Button] Loading tool to {lane_obj.name}.")
            self.afc.CHANGE_TOOL(lane_obj)
            return

        # EJECT
        self.afc.logger.info(f"[AFC Button] Ejecting {lane_obj.name}.")
        if cur_lane is not None and cur_lane.name == lane_obj.name:
            self.afc.logger.info(f"[AFC Button] Unloading {lane_obj.name} before eject.")
            if self.afc.TOOL_UNLOAD(lane_obj):
                self.afc.LANE_UNLOAD(lane_obj)
        else:
            self.afc.LANE_UNLOAD(lane_obj)

    def _single_confirm_action(self):
        lane_name = self._selected_lane_name
        action = self._selected_action
        if not lane_name or not action:
            self._cancel_to_lane_select("invalid_state")
            return

        lane_obj = self._get_lane_obj_by_name(lane_name)
        if lane_obj is None:
            self.afc.error.AFC_error(f"Lane '{lane_name}' not found.", pause=False)
            self._cancel_to_lane_select("lane_missing")
            return

        self._execute_action(lane_obj, action)
        # Return to lane select after running the command
        self._cancel_to_lane_select("done")

    # ----------------------------
    # Button callback
    # ----------------------------

    def _button_callback(self, eventtime, state):
        if state:
            self._press_time = eventtime
            return
        if self._press_time is None:
            return

        if self.afc.function.is_printing(check_movement=True):
            self.afc.error.AFC_error("Cannot use buttons while printer is actively moving or homing", False)
            self._press_time = None
            return

        held_time = eventtime - self._press_time
        self._press_time = None

        # Debounce tiny pulses
        if held_time < 0.05:
            return

        # Global cancel (very long press) for single-button mode
        if self.mode == self.MODE_SINGLE and held_time >= self.cancel_press_duration:
            self._cancel_to_lane_select("long_cancel")
            self._last_short_release = None
            return

        is_long = held_time >= self.long_press_duration
        is_short = not is_long

        # ----------------------------
        # Single-button mode
        # ----------------------------
        if self.mode == self.MODE_SINGLE:
            # Detect double short press (used for cancel in ACTION_SELECT)
            is_double = False
            if is_short:
                if self._last_short_release is not None and (eventtime - self._last_short_release) <= self.double_press_window:
                    is_double = True
                    self._last_short_release = None
                else:
                    self._last_short_release = eventtime
            else:
                self._last_short_release = None

            if self._ui_state == self.UI_LANE_SELECT:
                if is_long:
                    self._single_select_lane()
                else:
                    self._single_cycle_lane()
                return

            if self._ui_state == self.UI_ACTION_SELECT:
                if is_double:
                    self._cancel_to_lane_select("double_press")
                    return
                if is_long:
                    self._single_confirm_action()
                else:
                    self._single_toggle_action()
                return

            # Unknown state recovery
            self._cancel_to_lane_select("unknown_state")
            return

        # ----------------------------
        # Lane mode (existing behavior)
        # ----------------------------
        cur_lane = self.afc.function.get_current_lane_obj()

        if is_long:
            self.afc.logger.info(f"{self.lane_id}: Long press detected.")
            if cur_lane is not None and cur_lane.name == self.lane_id:
                self.afc.logger.info(f"Unloading {self.lane_id} before ejecting.")
                if self.afc.TOOL_UNLOAD(self.lane_obj):
                    self.afc.LANE_UNLOAD(self.lane_obj)
            else:
                self.afc.logger.info(f"Ejecting {self.lane_id}.")
                self.afc.LANE_UNLOAD(self.lane_obj)
        else:
            self.afc.logger.info(f"{self.lane_id}: Short press detected.")
            if cur_lane is not None and cur_lane.name == self.lane_id:
                self.afc.logger.info(f"Unloading tool from {self.lane_id}.")
                self.afc.TOOL_UNLOAD(cur_lane)
            else:
                self.afc.logger.info(f"Loading tool to {self.lane_id}.")
                self.afc.CHANGE_TOOL(self.lane_obj)


def load_config_prefix(config):
    return AFCButton(config)