from __future__ import annotations

from configfile import error


class AFCButton:
    # ... existing class docstring / constants ...

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

        self.mode = config.get("mode", self.MODE_LANE).strip().lower()
        if self.mode not in (self.MODE_LANE, self.MODE_SINGLE):
            raise error(f"Invalid AFC_button mode '{self.mode}'. Valid: lane|single")

        self.long_press_duration = config.getfloat("long_press_duration", 1.2)
        self.cancel_press_duration = config.getfloat("cancel_press_duration", 2.8)
        self.double_press_window = config.getfloat("double_press_window", 0.35)

        # Lane filtering for selector:
        #   ready => prep_state AND load_state
        #   prep  => prep_state
        #   load  => load_state
        #   all   => no filtering
        self.selectable_lanes = config.get("selectable_lanes", "ready").strip().lower()
        if self.selectable_lanes not in ("ready", "prep", "load", "all"):
            raise error("Invalid selectable_lanes for AFC_button. Valid: ready|prep|load|all")

        self.ui_led_yellow = config.get("ui_led_yellow", "1,1,0,0")
        self.ui_led_green = config.get("ui_led_green", "0,1,0,0")
        self.ui_led_red = config.get("ui_led_red", "1,0,0,0")

        pin_name = config.get("pin")

        self._press_time = None

        # Deferred short press (double-press detection) - IMPORTANT:
        # register the timer ONCE and arm/disarm it with update_timer().
        self._pending_short_timer = self.reactor.register_timer(self._pending_short_fire, self.reactor.NEVER)
        self._pending_short_context = None  # tuple(ui_state, eventtime)

        # Lane-mode binding
        self.lane_id = config.get_name().split()[-1]
        self.lane_obj = None

        # Single-button state
        self._ui_state = self.UI_IDLE
        self._lane_names: list[str] = []
        self._lane_index = 0
        self._selected_lane_name: str | None = None
        self._selected_action: str | None = None

        self._ui_led_lane_name: str | None = None

        buttons = self.printer.load_object(config, "buttons")
        buttons.register_buttons([pin_name], self._button_callback)

        if self.mode == self.MODE_SINGLE:
            self.afc.logger.info(f"AFC_button initialized in SINGLE mode on pin: {pin_name}")
        else:
            self.afc.logger.info(f"AFC_button for {self.lane_id} initialized on pin: {pin_name}")

    # ... existing code ...

    def _exit_ui(self, reason: str = "cancel"):
        """
        Exit UI entirely and restore LEDs.
        """
        self._ui_state = self.UI_IDLE
        self._selected_lane_name = None
        self._selected_action = None
        self._ui_led_clear()
        # Force a refresh of all lane LEDs (helps avoid a stuck override look)
        try:
            self.afc.function.handle_activate_extruder()
        except Exception:
            pass
        self.afc.logger.info(f"[AFC Button] Exit UI ({reason})")

    def _cancel_pending_short(self):
        self._pending_short_context = None
        try:
            self.reactor.update_timer(self._pending_short_timer, self.reactor.NEVER)
        except Exception:
            pass

    def _pending_short_fire(self, eventtime):
        """
        Reactor timer callback for deferred short press.
        If a second press happens before this fires, we cancel it and treat as double-press.
        """
        ctx = self._pending_short_context
        self._pending_short_context = None

        if ctx is None:
            return self.reactor.NEVER

        ui_state, _ = ctx

        if ui_state == self.UI_IDLE:
            self._enter_lane_select()
            return self.reactor.NEVER

        if ui_state == self.UI_LANE_SELECT:
            self._single_cycle_lane()
            return self.reactor.NEVER

        if ui_state == self.UI_ACTION_SELECT:
            self._single_toggle_action()
            return self.reactor.NEVER

        self._exit_ui("unknown_state")
        return self.reactor.NEVER

    def _lane_is_selectable(self, lane_obj) -> bool:
        if lane_obj is None:
            return False
        prep = bool(getattr(lane_obj, "prep_state", False))
        load = bool(getattr(lane_obj, "load_state", False))

        if self.selectable_lanes == "all":
            return True
        if self.selectable_lanes == "load":
            return load
        if self.selectable_lanes == "prep":
            return prep
        # ready
        return prep and load

    def _refresh_lane_names(self):
        names = sorted(list(self.afc.lanes.keys()))
        if self.selectable_lanes != "all":
            filtered = []
            for n in names:
                obj = self._get_lane_obj_by_name(n)
                if self._lane_is_selectable(obj):
                    filtered.append(n)
            names = filtered

        self._lane_names = names
        if not self._lane_names:
            self._lane_index = 0
        else:
            self._lane_index = max(0, min(self._lane_index, len(self._lane_names) - 1))

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

        if self.mode == self.MODE_SINGLE:
            # Very long press => exit UI and restore LEDs
            if held_time >= self.cancel_press_duration:
                self._cancel_pending_short()
                self._exit_ui("long_cancel")
                return

            is_long = held_time >= self.long_press_duration
            is_short = not is_long

            if is_long:
                self._cancel_pending_short()

                if self._ui_state == self.UI_IDLE:
                    self._enter_lane_select()
                    if self._ui_state == self.UI_LANE_SELECT:
                        self._single_select_lane()
                    return

                if self._ui_state == self.UI_LANE_SELECT:
                    self._single_select_lane()
                    return

                if self._ui_state == self.UI_ACTION_SELECT:
                    self._single_confirm_action()
                    return

                self._exit_ui("unknown_state")
                return

            # Short press: deferred single / double press cancels
            if is_short:
                if self._pending_short_context is not None:
                    # Second short press within the window => double press (exit UI)
                    self._cancel_pending_short()
                    self._exit_ui("double_press")
                    return

                # Arm deferred short action
                self._pending_short_context = (self._ui_state, eventtime)
                try:
                    self.reactor.update_timer(self._pending_short_timer, eventtime + self.double_press_window)
                except Exception:
                    # Fallback: if update fails, just do the short action immediately
                    self._pending_short_fire(eventtime)
                return

        # ... existing lane-mode behavior unchanged ...