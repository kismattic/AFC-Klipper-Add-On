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
      - Short press: cycle lanes (LANE_SELECT) / toggle action (ACTION_SELECT)
      - Long press: select lane / confirm action
      - Double short press (ACTION_SELECT): cancel back to lane select
      - Very long press (any time): cancel back to lane select
    """

    MODE_LANE = "lane"
    MODE_SINGLE = "single"

    UI_IDLE = "idle"
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

        # Which lanes are selectable in single-button mode:
        #   all   -> all lanes
        #   load  -> load_state True
        #   prep  -> prep_state True
        #   ready -> prep_state AND load_state True
        self.selectable_lanes = config.get("selectable_lanes", "ready").strip().lower()
        if self.selectable_lanes not in ("all", "load", "prep", "ready"):
            raise error("Invalid selectable_lanes for AFC_button. Valid: all|load|prep|ready")

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
        self._ui_state = self.UI_IDLE
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
            self._refresh_lane_names()
            if not self._lane_names:
                raise error("AFC_button single mode: no selectable lanes found (check selectable_lanes).")
            self._lane_index = max(0, min(self._lane_index, len(self._lane_names) - 1))
            self._ui_state = self.UI_IDLE
            self._selected_lane_name = None
            self._selected_action = None
            self._ui_led_lane_name = None
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
        # ... existing code ...
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
            pass

    def _restore_lane_led_default(self, lane_obj):
        # ... existing code ...
        if lane_obj is None:
            return
        idx = getattr(lane_obj, "led_index", None)
        if idx is None:
            return

        try:
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
        # ... existing code ...
        if self._ui_led_lane_name and self._ui_led_lane_name != lane_name:
            prev_obj = self._get_lane_obj_by_name(self._ui_led_lane_name)
            self._restore_lane_led_default(prev_obj)

        self._ui_led_lane_name = lane_name

        if lane_name:
            lane_obj = self._get_lane_obj_by_name(lane_name)
            self._set_lane_led(lane_obj, color)

    def _ui_led_clear(self):
        if self._ui_led_lane_name:
            lane_obj = self._get_lane_obj_by_name(self._ui_led_lane_name)
            self._restore_lane_led_default(lane_obj)
        self._ui_led_lane_name = None

    # ----------------------------
    # Helpers (single-button mode)
    # ----------------------------

    def _lane_is_selectable(self, lane_obj) -> bool:
        if self.selectable_lanes == "all":
            return True
        if lane_obj is None:
            return False
        prep = bool(getattr(lane_obj, "prep_state", False))
        load = bool(getattr(lane_obj, "load_state", False))
        if self.selectable_lanes == "load":
            return load
        if self.selectable_lanes == "prep":
            return prep
        return prep and load  # "ready"

    def _refresh_lane_names(self):
        names = sorted(list(self.afc.lanes.keys()))
        if self.selectable_lanes != "all":
            names = [n for n in names if self._lane_is_selectable(self._get_lane_obj_by_name(n))]
        self._lane_names = names

        if self._lane_names:
            self._lane_index = max(0, min(self._lane_index, len(self._lane_names) - 1))
        else:
            self._lane_index = 0

    def _get_highlight_lane_name(self) -> str:
        return self._lane_names[self._lane_index]

    def _get_lane_obj_by_name(self, lane_name: str):
        return self.afc.lanes.get(lane_name)

    def _exit_ui(self, reason: str):
        self.afc.logger.info(f"[AFC Button] Exit ({reason})")
        self._ui_state = self.UI_IDLE
        self._selected_lane_name = None
        self._selected_action = None
        self._ui_led_clear()

    def _enter_lane_select(self):
        self._refresh_lane_names()
        if not self._lane_names:
            self.afc.error.AFC_error("No selectable lanes.", pause=False)
            self._exit_ui("no_lanes")
            return
        self._ui_state = self.UI_LANE_SELECT
        self._selected_lane_name = None
        self._selected_action = None
        self._announce_lane_highlight()

    def _announce_lane_highlight(self):
        lane = self._get_highlight_lane_name()
        lane_obj = self._get_lane_obj_by_name(lane)
        loaded = self._is_lane_loaded(lane_obj) if lane_obj is not None else False
        self.afc.logger.info(f"[AFC Button] Select lane: {lane} (loaded={loaded})")
        self._ui_led_apply(lane, self.ui_led_yellow)

    def _cancel_to_lane_select(self, reason: str = "cancel"):
        self._ui_state = self.UI_LANE_SELECT
        self._selected_lane_name = None
        self._selected_action = None
        self.afc.logger.info(f"[AFC Button] Cancel -> lane select ({reason})")
        self._announce_lane_highlight()

    def _single_cycle_lane(self):
        self._refresh_lane_names()
        if not self._lane_names:
            self._exit_ui("no_lanes")
            return
        self._lane_index = (self._lane_index + 1) % len(self._lane_names)
        self._announce_lane_highlight()

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

        if held_time < 0.05:
            return

        # Single-button mode cancel: EXIT UI (restore LEDs), do NOT leave highlight yellow
        if self.mode == self.MODE_SINGLE and held_time >= self.cancel_press_duration:
            self._exit_ui("long_cancel")
            self._last_short_release = None
            return

        is_long = held_time >= self.long_press_duration
        is_short = not is_long

        if self.mode == self.MODE_SINGLE:
            is_double = False
            if is_short:
                if self._last_short_release is not None and (eventtime - self._last_short_release) <= self.double_press_window:
                    is_double = True
                    self._last_short_release = None
                else:
                    self._last_short_release = eventtime
            else:
                self._last_short_release = None

            # If UI is idle, any press starts lane selection (then behaves normally)
            if self._ui_state == self.UI_IDLE:
                if is_long:
                    self._enter_lane_select()
                    if self._ui_state == self.UI_LANE_SELECT:
                        self._single_select_lane()
                else:
                    self._enter_lane_select()
                return

            if self._ui_state == self.UI_LANE_SELECT:
                if is_long:
                    self._single_select_lane()
                else:
                    self._single_cycle_lane()
                return

            if self._ui_state == self.UI_ACTION_SELECT:
                if is_double:
                    self._exit_ui("double_press")
                    return
                if is_long:
                    self._single_confirm_action()
                else:
                    self._single_toggle_action()
                return

            self._exit_ui("unknown_state")
            return

        # ... existing lane-mode behavior unchanged ...


def load_config_prefix(config):
    return AFCButton(config)