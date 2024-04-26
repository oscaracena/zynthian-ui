#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "Novation Launchpad Mini MK3"
#
# Copyright (C) 2024 Oscar Acena <oscaracena@gmail.com>
#
# ******************************************************************************
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the LICENSE.txt file.
#
# ******************************************************************************

import time
import logging
from functools import partial

# Zynthian specific modules
# from zynlibs.zynseq import zynseq
from zyncoder.zyncore import lib_zyncore
from zyngine.zynthian_signal_manager import zynsigman
from zyngine.zynthian_engine_audioplayer import zynthian_engine_audioplayer
from .zynthian_ctrldev_base import zynthian_ctrldev_zynpad
from .zynthian_ctrldev_base_ui import ModeHandlerBase
from .zynthian_ctrldev_base_extended import (
    RunTimer, CONST, ButtonTimer, IntervalTimer
)


# SysEx header and commands
SYSEX_HEADER            = "00 20 29 02 0D"
SYSEX_SET_LAYOUT        = "00"
SYSEX_LEDS_ON           = "09"
SYSEX_DAW_MODE          = "10"
SYSEX_DAW_CLEAR         = "12 01 00 01"

# Layout modes
LAYOUT_SESSION          = 0x00
LAYOUT_DRUMS            = 0x04
LAYOUT_KEYS             = 0x05
LAYOUT_USER             = 0x06
LAYOUT_FADERS           = 0x0D

# Special function buttons
CC_SESSION              = 95
CC_DRUMS                = 96
CC_KEYS                 = 97
CC_USER                 = 98

# LED colors and modes
COLOR_RED               = 0x05
COLOR_GREEN             = 0x15
COLOR_BLUE              = 0x29
COLOR_AQUA              = 0x25
COLOR_BLUE_DARK         = 0x2D
COLOR_WHITE             = 0x77
COLOR_EGYPT             = 0x6C
COLOR_ORANGE            = 0x09
COLOR_AMBER             = 0x54
COLOR_RUSSET            = 0x3D
COLOR_PURPLE            = 0x31
COLOR_PINK              = 0x39
COLOR_PINK_LIGHT        = 0x52
COLOR_PINK_WARM         = 0x38
COLOR_YELLOW            = 0x0D
COLOR_LIME              = 0x4B
COLOR_LIME_DARK         = 0x1B
COLOR_GREEN_YELLOW      = 0x4A
COLOR_BLUE_SKY          = 0x24

LED_MODE_STATIC_CH      = 0x00
LED_MODE_FLASHING_CH    = 0x01
LED_MODE_PULSING_CH     = 0x02

LED_LOGO                = 0x63


# ------------------------------------------------------------------------------
# Novation Launchpad Mini MK3
# ------------------------------------------------------------------------------
class zynthian_ctrldev_launchpad_mini_mk3_alt(zynthian_ctrldev_zynpad):

    dev_ids = ["Launchpad Mini MK3 IN 1"]

    # PAD_COLOURS = [6, 29, 17, 49, 66, 41, 23, 13, 96, 2, 81, 82, 83, 84, 85, 86, 87]
    # STARTING_COLOUR = 21
    # STOPPING_COLOUR = 5
    # SELECTED_BANK_COLOUR = 29
    # STOP_ALL_COLOUR = 5

    def __init__(self, state_manager, idev_in, idev_out=None):
        self._lp = LaunchpadDev(idev_out)
        self._leds = LPFeedbackLEDs(idev_out)

        # FIXME: set Zynpad as default (current) handler
        self._device_handler = LPDeviceHandler(state_manager, self._leds)
        self._mixer_handler = LPMixerHandler(state_manager, self._leds)
        self._current_handler = self._mixer_handler
        self._previous_handler = self._mixer_handler
        self._skip_mode_change = False

        self._signals = [
            (zynsigman.S_GUI,
                zynsigman.SS_GUI_SHOW_SCREEN,
                self._on_gui_show_screen),

            (zynsigman.S_AUDIO_PLAYER,
                zynthian_engine_audioplayer.SS_AUDIO_PLAYER_STATE,
                lambda handle, state:
                    self._on_media_change_state(state, f"audio-{handle}", "player")),

            (zynsigman.S_AUDIO_RECORDER,
                state_manager.audio_recorder.SS_AUDIO_RECORDER_STATE,
                partial(self._on_media_change_state, media="audio", kind="recorder")),

            (zynsigman.S_STATE_MAN,
                state_manager.SS_MIDI_PLAYER_STATE,
                partial(self._on_media_change_state, media="midi", kind="player")),

            (zynsigman.S_STATE_MAN,
                state_manager.SS_MIDI_RECORDER_STATE,
                partial(self._on_media_change_state, media="midi", kind="recorder")),
        ]

        # NOTE: init will call refresh(), so '_current_hanlder' must be ready!
        super().__init__(state_manager, idev_in, idev_out)

    # def get_note_xy(self, note):
    #     row = 8 - (note // 10)
    #     col = (note % 10) - 1
    #     return col, row

    # def get_state(self):
    #     return self._saved_state.save()

    # def set_state(self, state):
        # self._saved_state.load(state)
        # self._current_handler.set_active(True)

    def init(self):
        super().init()
        self.sleep_off()
        self._lp.enable_daw_mode(True)
        self._lp.select_layout(LAYOUT_SESSION)

        for signal, subsignal, callback in self._signals:
            zynsigman.register(signal, subsignal, callback)
        self._current_handler.set_active(True)

    def end(self):
        self._lp.enable_daw_mode(False)
        self._lp.select_layout(LAYOUT_KEYS)

        for signal, subsignal, callback in self._signals:
            zynsigman.unregister(signal, subsignal, callback)
        super().end()

    def refresh(self):
        print("- REFRESH (Driver)")
        self._current_handler.refresh()

#     def update_seq_bank(self):
#         if self.idev_out <= 0:
#             return
#         #logging.debug("Updating Launchpad MINI MK3 bank leds")
#         for row in range(0, 7):
#             note = 89 - 10 * row
#             if row == self.zynseq.bank - 1:
#                 lib_zyncore.dev_send_ccontrol_change(self.idev_out, 0, note, self.SELECTED_BANK_COLOUR)
#             else:
#                 lib_zyncore.dev_send_ccontrol_change(self.idev_out, 0, note, 0)
#         # Stop All button => Solid Red
#         lib_zyncore.dev_send_ccontrol_change(self.idev_out, 0, 19, self.STOP_ALL_COLOUR)

#     def update_seq_state(self, bank, seq, state, mode, group):
#         if self.idev_out <= 0 or bank != self.zynseq.bank:
#             return
#         #logging.debug(f"Updating Launchpad MINI MK3 bank {bank} pad {seq} => state {state}, mode {mode}")
#         col, row = self.zynseq.get_xy_from_pad(seq)
#         note = 10 * (8 - row) + col + 1
#         try:
#             if mode == 0:
#                 chan = 0
#                 vel = 0
#             elif state == zynseq.SEQ_STOPPED:
#                 chan = 0
#                 vel = self.PAD_COLOURS[group]
#             elif state == zynseq.SEQ_PLAYING:
#                 chan = 2
#                 vel = self.PAD_COLOURS[group]
#             elif state == zynseq.SEQ_STOPPING:
#                 chan = 1
#                 vel = self.STOPPING_COLOUR
#             elif state == zynseq.SEQ_STARTING:
#                 chan = 1
#                 vel = self.STARTING_COLOUR
#             else:
#                 chan = 0
#                 vel = 0
#         except:
#             chan = 0
#             vel = 0
#         #logging.debug("Lighting PAD {}, group {} => {}, {}, {}".format(seq, group, chan, note, vel))
#         lib_zyncore.dev_send_note_on(self.idev_out, chan, note, vel)

#     # Light-Off the pad specified with column & row
#     def pad_off(self, col, row):
#         note = 10 * (8 - row) + col + 1
#         lib_zyncore.dev_send_note_on(self.idev_out, 0, note, 0)

    def midi_event(self, ev):
        print("- MIDI ev:", " ".join([f"{b:02X}" for b in ev]))

        evtype = (ev[0] >> 4) & 0x0F
        if evtype == CONST.MIDI_CC:
            ccnum = ev[1] & 0x7F
            ccval = ev[2] & 0x7F

            # On button release...
            if ccval == 0:
                if ccnum == CC_SESSION:
                    if self._skip_mode_change:
                       self._skip_mode_change = False
                    else:
                        self._toggle_previous_handler()
                    return True
                elif ccnum in (CC_KEYS, CC_DRUMS, CC_USER):
                    self._skip_mode_change = True

            return self._current_handler.cc_change(ccnum, ccval)

        # elif evtype == CONST.MIDI_PC:
        #     program = ev[1] & 0x7F
        #     if program == PROG_MIXER_MODE:
        #         self._change_handler(self._mixer_handler)
        #     elif program == PROG_DEVICE_MODE:
        #         self._change_handler(self._device_handler)
        #     elif program == PROG_PATTERN_MODE:
        #         self._change_handler(self._pattern_handler)
        #     elif program == PROG_NOTEPAD_MODE:
        #         self._change_handler(self._notepad_handler)
        #     elif program == PROG_USER_MODE:
        #         self._change_handler(self._user_handler)
        #     elif program == PROG_CONFIG_MODE:
        #         self._change_handler(self._config_handler)
        #     elif program == PROG_OPEN_MIXER:
        #         self.state_manager.send_cuia(
        #             "SCREEN_ALSA_MIXER" if self._current_screen == "audio_mixer" else
        #             "SCREEN_AUDIO_MIXER"
        #         )
        #     elif program == PROG_OPEN_ZYNPAD:
        #         self.state_manager.send_cuia({
        #             "zynpad": "SCREEN_ARRANGER",
        #             "arranger": "SCREEN_PATTERN_EDITOR"
        #         }.get(self._current_screen, "SCREEN_ZYNPAD"))
        #     elif program == PROG_OPEN_TEMPO:
        #         self.state_manager.send_cuia("TEMPO")
        #     elif program == PROG_OPEN_SNAPSHOT:
        #         self.state_manager.send_cuia(
        #             "SCREEN_SNAPSHOT" if self._current_screen == "zs3" else
        #             "SCREEN_ZS3"
        #         )
        #     else:
        #         self._current_handler.pg_change(program)

        elif evtype == CONST.MIDI_NOTE_ON:
            note = ev[1] & 0x7F
            velocity = ev[2] & 0x7F
            channel = ev[0] & 0x0F
            return self._current_handler.note_on(note, channel, velocity)

        elif evtype == CONST.MIDI_NOTE_OFF:
            note = ev[1] & 0x7F
            channel = ev[0] & 0x0F
            print(f" - MIDI note off: {note}, {channel}")

            # NOTE: Use note-off to avoid sending that event to the new handler
            if self._current_handler == self._device_handler:
                if note == self._device_handler.BTN_MODE_MIXER:
                    return self._change_handler(self._mixer_handler)

            return self._current_handler.note_off(note, channel)

        # elif ev[0] == CONST.MIDI_SYSEX:
        #     self._current_handler.sysex_message(ev[1:-1])

        else:
            print(f" - MIDI ev: {' '.join(f'{b:02X}' for b in ev)}")

        return False

    def light_off(self):
        print(" - light off")
        self._lp.send_sysex(SYSEX_DAW_CLEAR)

    def sleep_on(self):
        print(" - sleep on")
        self._lp.send_sysex(f"{SYSEX_LEDS_ON} 00")

    def sleep_off(self):
        print(" - sleep off")
        self._lp.send_sysex(f"{SYSEX_LEDS_ON} 01")

    def _on_gui_show_screen(self, screen):
        self._device_handler.on_screen_change(screen)
        # self._padmatrix_handler.on_screen_change(screen)
        # self._stepseq_handler.on_screen_change(screen)

    def _on_media_change_state(self, state, media, kind):
        self._device_handler.on_media_change(media, kind, state)
        self._current_handler.on_media_change(media, kind, state)

    def _toggle_previous_handler(self):
        if self._current_handler == self._device_handler:
            self._change_handler(self._previous_handler)
        else:
            self._change_handler(self._device_handler)

    def _change_handler(self, new_handler):
        print(f"- change handler to: {new_handler.__class__.__name__}")
        if new_handler == self._current_handler:
            return

        self._current_handler.set_active(False)
        if self._current_handler != self._device_handler:
            self._previous_handler = self._current_handler

        self._current_handler = new_handler
        if self._current_handler == self._device_handler:
            self._device_handler.set_previous_mode(
                getattr(self._previous_handler, "MODE_NAME", None))
        self._current_handler.set_active(True)


# ------------------------------------------------------------------------------
# Class to handle the actual hardware access
# ------------------------------------------------------------------------------
class LaunchpadDev:
    def __init__(self, idev_out):
        self._idev = idev_out

    def setup_faders(self, faders, vertical=True):
        assert len(faders) <= 8, "There could only be 8 faders!"
        msg = f"01 00 0{'0' if vertical else '1'}"
        for index, f in enumerate(faders):
            msg += f"{index:02X}"
            if f is None:
                msg += f"00 {index:02X} 00"
                continue
            msg += '01' if f.get("bipolar", False) else '00'
            cc = int(f.get("cc", index))
            msg += f"{cc:02X}"
            msg += f'{min(127, max(0, int(f.get("color", 37)))):02X}'

        self.send_sysex(msg)

    def select_layout(self, layout):
        self.send_sysex(f"{SYSEX_SET_LAYOUT} {layout:02X}")

    def show_faders(self, state):
        self.select_layout(LAYOUT_FADERS if state else LAYOUT_SESSION)

    def enable_daw_mode(self, enabled=True):
        self.send_sysex(f"{SYSEX_DAW_MODE} 0{1 if enabled else 0}")

    def send_sysex(self, data):
        if self._idev is not None:
            print(f" - SysEx: F0 {SYSEX_HEADER} {data} F7")
            msg = bytes.fromhex(f"F0 {SYSEX_HEADER} {data} F7")
            lib_zyncore.dev_send_midi_event(self._idev, msg, len(msg))


# --------------------------------------------------------------------------
# Feedback LEDs controller
# FIXME: this is a candidate for DRY, keep it decoupled!
# --------------------------------------------------------------------------
class FeedbackLEDs:
    def __init__(self, idev):
        self._idev = idev
        self._state = {}
        self._timer = RunTimer()

    def all_off(self):
        """Overwrite in derived class if there is a better approach."""
        # FIXME: define the set of LEDs in derived class, and iter here to switch them off
        raise NotImplementedError()

    #     self.control_leds_off()
    #     self.pad_leds_off()

    # def control_leds_off(self):
    #     buttons = [
    #         BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_KNOB_CTRL_VOLUME,
    #         BTN_KNOB_CTRL_PAN, BTN_KNOB_CTRL_SEND, BTN_KNOB_CTRL_DEVICE,
    #         BTN_SOFT_KEY_CLIP_STOP, BTN_SOFT_KEY_MUTE, BTN_SOFT_KEY_SOLO,
    #         BTN_SOFT_KEY_REC_ARM, BTN_SOFT_KEY_SELECT,
    #     ]
    #     for btn in buttons:
    #         self.led_off(btn)

    # def pad_leds_off(self):
    #     buttons = [btn for btn in range(BTN_PAD_START, BTN_PAD_END + 1)]
    #     for btn in buttons:
    #         self.led_off(btn)

    def led_off(self, led, overlay=False):
        self.led_state(led, False, overlay=overlay)

    def led_on(self, led, color=COLOR_WHITE, mode=LED_MODE_STATIC_CH, overlay=False):
        self.led_state(led, True, color, mode, overlay)

    def led_state(self, led, state, color=COLOR_WHITE, mode=LED_MODE_STATIC_CH, overlay=False):
        self._timer.remove(led)
        if not state:
            mode = 0
            color = 0
        self._set_led(led, color, mode)
        if not overlay:
            self._state[led] = (color, mode)

    # def led_blink(self, led):
    #     self._timer.remove(led)
    #     lib_zyncore.dev_send_note_on(self._idev, 0, led, 2)

    # def remove_overlay(self, led):
    #     old_state = self._state.get(led)
    #     if old_state:
    #         self.led_on(led, *old_state)
    #     else:
    #         self._timer.remove(led)
    #         lib_zyncore.dev_send_note_on(self._idev, 0, led, 0)

    # def delayed(self, action, timeout, led, *args, **kwargs):
    #     action = getattr(self, action)
    #     self._timer.add(led, timeout, action, *args, **kwargs)

    # def clear_delayed(self, led):
    #     self._timer.remove(led)

    def _set_led(self, led, color, mode):
        """Overwrite in derived class if needed."""
        lib_zyncore.dev_send_note_on(self._idev, mode, led, color)


# --------------------------------------------------------------------------
# Feedback LEDs controller
# --------------------------------------------------------------------------
class LPFeedbackLEDs(FeedbackLEDs):
    def __init__(self, idev):
        super().__init__(idev)
        self._lp = LaunchpadDev(idev)

    def all_off(self):
        # print(" - LEDs: all off")
        self._lp.send_sysex(SYSEX_DAW_CLEAR)

    def _set_led(self, led, color, mode):
        if led > 88 or str(led)[1:] == "9":
            # print(f" - set LED {led} as CC to CH:{mode}, VAL:{color}")
            lib_zyncore.dev_send_ccontrol_change(
                self._idev, mode, led, color)
        else:
            # print(f" - set LED {led} as NOTE_ON to CH:{mode}, VEL:{color}")
            lib_zyncore.dev_send_note_on(
                self._idev, mode, led, color)


# --------------------------------------------------------------------------
# Handle GUI (device mode)
# FIXME: this is a candidate for DRY, keep it decoupled!
# --------------------------------------------------------------------------
class DeviceHandler(ModeHandlerBase):

    MODE_NAME           = "device"

    # NOTE: Define these constants according to your hardware setup, in a derived class
    BTN_UP              = 1
    BTN_DOWN            = 2
    BTN_LEFT            = 3
    BTN_RIGHT           = 4
    BTN_SEL_YES         = 5
    BTN_BACK_NO         = 6
    BTN_F1              = 7
    BTN_F2              = 8
    BTN_F3              = 9
    BTN_F4              = 10
    BTN_ALT             = 11
    BTN_RECORD          = 13
    BTN_STOP            = 20
    BTN_PLAY            = 12
    BTN_OPT_ADMIN       = 14
    BTN_MIX_LEVEL       = 15
    BTN_CTRL_PRESET     = 16
    BTN_ZS3_SHOT        = 17
    BTN_PAD_STEP        = 18
    BTN_METRONOME       = 19
    BTN_KNOB_1          = 21
    BTN_KNOB_2          = 22
    BTN_KNOB_3          = 23
    BTN_KNOB_4          = 24

    LED_STATIC_BRIGHT   = 1
    LED_BLINKING        = 2

    COLOR_RED           = 1
    COLOR_GREEN         = 2
    COLOR_BLUE          = 3
    COLOR_BLUE_DARK     = 4
    COLOR_BLUE_LIGHT    = 10
    COLOR_GREEN_LIGHT   = 9
    COLOR_YELLOW        = 5
    COLOR_ORANGE        = 6
    COLOR_PURPLE        = 7
    COLOR_WHITE         = 8

    def __init__(self, state_manager, leds: FeedbackLEDs):
        super().__init__(state_manager)
        self._leds = leds
    #     self._knobs_ease = KnobSpeedControl()
        self._is_alt_active = False
        self._is_playing = set()
        self._is_recording = set()
        self._btn_timer = ButtonTimer(self._handle_timed_button)

        self._btn_actions = {
            self.BTN_OPT_ADMIN:      ("MENU", "SCREEN_ADMIN"),
            self.BTN_MIX_LEVEL:      ("SCREEN_AUDIO_MIXER", "SCREEN_ALSA_MIXER"),
            self.BTN_CTRL_PRESET:    ("SCREEN_CONTROL", "PRESET", "SCREEN_BANK"),
            self.BTN_ZS3_SHOT:       ("SCREEN_ZS3", "SCREEN_SNAPSHOT"),
            self.BTN_PAD_STEP:       ("SCREEN_ZYNPAD", "SCREEN_PATTERN_EDITOR"),
            self.BTN_METRONOME:      ("TEMPO",),
            self.BTN_RECORD:         ("TOGGLE_RECORD",),
            self.BTN_PLAY: (
                lambda is_bold: [
                    "AUDIO_FILE_LIST" if is_bold else "TOGGLE_PLAY"
                ]
            ),
            self.BTN_STOP: (
                lambda is_bold: [
                    "ALL_SOUNDS_OFF" if is_bold else "STOP"
                ]
            ),
            self.BTN_KNOB_1: (lambda is_bold: [f"V5_ZYNPOT_SWITCH:0,{'B' if is_bold else 'S'}"]),
            self.BTN_KNOB_2: (lambda is_bold: [f"V5_ZYNPOT_SWITCH:1,{'B' if is_bold else 'S'}"]),
            self.BTN_KNOB_3: (lambda is_bold: [f"V5_ZYNPOT_SWITCH:2,{'B' if is_bold else 'S'}"]),
            self.BTN_KNOB_4: (lambda is_bold: [f"V5_ZYNPOT_SWITCH:3,{'B' if is_bold else 'S'}"]),
        }

        self._btn_states = {k:-1 for k in self._btn_actions}

    def refresh(self):
        self._leds.all_off()

        # Lit up fixed buttons
        for btn in [self.BTN_UP, self.BTN_DOWN, self.BTN_LEFT, self.BTN_RIGHT]:
            self._leds.led_on(btn, self.COLOR_YELLOW, self.LED_STATIC_BRIGHT)
        self._leds.led_on(self.BTN_SEL_YES, self.COLOR_GREEN, self.LED_STATIC_BRIGHT)
        self._leds.led_on(self.BTN_BACK_NO, self.COLOR_RED, self.LED_STATIC_BRIGHT)

        # Lit up alt-related buttons
        alt_color = self.COLOR_BLUE_DARK if not self._is_alt_active else self.COLOR_PURPLE
        fn_color = self.COLOR_WHITE if not self._is_alt_active else self.COLOR_PURPLE
        for btn in [self.BTN_F1, self.BTN_F2, self.BTN_F3, self.BTN_F4]:
            self._leds.led_on(btn, fn_color, self.LED_STATIC_BRIGHT)
        self._leds.led_on(self.BTN_ALT, alt_color, self.LED_STATIC_BRIGHT)

        self._refresh_transport_buttons()
        self._refresh_knob_buttons()
        self._refresh_screen_buttons()

    def _refresh_knob_buttons(self):
        # Overwrite this method if your controller does not have Knob button LEDs
        for btn in [self.BTN_KNOB_1, self.BTN_KNOB_2, self.BTN_KNOB_3, self.BTN_KNOB_4]:
            self._leds.led_on(btn, self.COLOR_GREEN_LIGHT, self.LED_STATIC_BRIGHT)

    def _refresh_screen_buttons(self):
        for btn in [self.BTN_OPT_ADMIN, self.BTN_MIX_LEVEL, self.BTN_CTRL_PRESET,
                    self.BTN_ZS3_SHOT, self.BTN_PAD_STEP, self.BTN_METRONOME]:
            state = self._btn_states[btn]
            color = [self.COLOR_GREEN, self.COLOR_ORANGE, self.COLOR_BLUE][state]
            self._leds.led_on(btn, color, self.LED_STATIC_BRIGHT)

    def _refresh_transport_buttons(self):
        self._leds.led_on(self.BTN_STOP, self.COLOR_BLUE_LIGHT, self.LED_STATIC_BRIGHT)

        if self._is_playing:
            self._leds.led_off(self.BTN_PLAY)
            self._leds.led_on(self.BTN_PLAY, self.COLOR_GREEN, self.LED_BLINKING)
        else:
            self._leds.led_on(self.BTN_PLAY, self.COLOR_BLUE_LIGHT, self.LED_STATIC_BRIGHT)

        if self._is_recording:
            self._leds.led_off(self.BTN_RECORD)
            self._leds.led_on(self.BTN_RECORD, self.COLOR_RED, self.LED_BLINKING)
        else:
            self._leds.led_on(self.BTN_RECORD, self.COLOR_BLUE_LIGHT, self.LED_STATIC_BRIGHT)

    def note_on(self, note, channel, velocity, shifted_override=None):
        self._on_shifted_override(shifted_override)
        if self._is_shifted:
            pass
    #         if note == BTN_KNOB_CTRL_DEVICE:
    #             self.refresh()
    #             return True
        else:
            if note == self.BTN_UP:
                self._state_manager.send_cuia("ARROW_UP")
            elif note == self.BTN_DOWN:
                self._state_manager.send_cuia("ARROW_DOWN")
            elif note == self.BTN_LEFT:
                self._state_manager.send_cuia("ARROW_LEFT")
            elif note == self.BTN_RIGHT:
                self._state_manager.send_cuia("ARROW_RIGHT")
            elif note == self.BTN_SEL_YES:
                self._state_manager.send_cuia("V5_ZYNPOT_SWITCH", [3, 'S'])
            elif note == self.BTN_BACK_NO:
                self._state_manager.send_cuia("BACK")
            elif note == self.BTN_ALT:
                self._is_alt_active = not self._is_alt_active
                self._state_manager.send_cuia("TOGGLE_ALT_MODE")
                self.refresh()
            else:
                # Function buttons (F1-F4)
                fn_btns = {self.BTN_F1: 1, self.BTN_F2: 2, self.BTN_F3: 3, self.BTN_F4: 4}
                pgm = fn_btns.get(note)
                if pgm is not None:
                    pgm += 4 if self._is_alt_active else 0
                    self._state_manager.send_cuia("PROGRAM_CHANGE", [pgm])
                    return True

                # Buttons that may have bold/long press
                self._btn_timer.is_pressed(note, time.time())
            return True

    def note_off(self, note, shifted_override=None):
        self._on_shifted_override(shifted_override)
        self._btn_timer.is_released(note)

    # def cc_change(self, ccnum, ccval):
    #     delta = self._knobs_ease.feed(ccnum, ccval, self._is_shifted)
    #     if delta is None:
    #         return

    #     zynpot = {
    #         KNOB_LAYER: 0,
    #         KNOB_BACK: 1,
    #         KNOB_SNAPSHOT: 2,
    #         KNOB_SELECT: 3
    #     }.get(ccnum, None)
    #     if zynpot is None:
    #         return

    #     self._state_manager.send_cuia("ZYNPOT", [zynpot, delta])

    def on_screen_change(self, screen):
        print(f"- screen change: {screen}")
        screen_map = {
            "option":         (self.BTN_OPT_ADMIN, 0),
            "main_menu":      (self.BTN_OPT_ADMIN, 0),
            "admin":          (self.BTN_OPT_ADMIN, 1),
            "audio_mixer":    (self.BTN_MIX_LEVEL, 0),
            "alsa_mixer":     (self.BTN_MIX_LEVEL, 1),
            "control":        (self.BTN_CTRL_PRESET, 0),
            "engine":         (self.BTN_CTRL_PRESET, 0),
            "preset":         (self.BTN_CTRL_PRESET, 1),
            "bank":           (self.BTN_CTRL_PRESET, 1),
            "zs3":            (self.BTN_ZS3_SHOT, 0),
            "snapshot":       (self.BTN_ZS3_SHOT, 1),
            "zynpad":         (self.BTN_PAD_STEP, 0),
            "pattern_editor": (self.BTN_PAD_STEP, 1),
            "arranger":       (self.BTN_PAD_STEP, 1),
            "tempo":          (self.BTN_METRONOME, 0),
        }

        self._btn_states = {k:-1 for k in self._btn_states}
        try:
            btn, idx = screen_map[screen]
            self._btn_states[btn] = idx
            if self._is_active:
                self._refresh_screen_buttons()
        except KeyError:
            pass

    def on_media_change(self, media, kind, state):
        print(f"- media change: {media}, {kind}, {state}")
        flags = self._is_playing if kind == "player" else self._is_recording
        flags.add(media) if state else flags.discard(media)
        if self._is_active:
            self._refresh_transport_buttons()

    def _handle_timed_button(self, btn, press_type):
        if press_type == CONST.PT_LONG:
            cuia = {
                self.BTN_OPT_ADMIN:   "POWER_OFF",
                self.BTN_CTRL_PRESET: "PRESET_FAV",
                self.BTN_PAD_STEP:    "SCREEN_ARRANGER",
            }.get(btn)
            if cuia:
                self._state_manager.send_cuia(cuia)
            return True

        actions = self._btn_actions.get(btn)
        if actions is None:
            return
        if callable(actions):
            actions = actions(press_type == CONST.PT_BOLD)

        idx = -1
        if press_type == CONST.PT_SHORT:
            idx = self._btn_states[btn]
            idx = (idx + 1) % len(actions)
            cuia = actions[idx]
        elif press_type == CONST.PT_BOLD:
            # In buttons with 2 functions, the default on bold press is the second
            idx = 1 if len(actions) > 1 else 0
            cuia = actions[idx]

        # Split params, if given
        params = []
        if ":" in cuia:
            cuia, params = cuia.split(":")
            params = params.split(",")
            params[0] = int(params[0])

        self._state_manager.send_cuia(cuia, params)
        return True


# --------------------------------------------------------------------------
# Handle GUI (device mode)
# --------------------------------------------------------------------------
class LPDeviceHandler(DeviceHandler):

    # These constants are overriden from base class
    BTN_UP              = 52
    BTN_DOWN            = 42
    BTN_LEFT            = 41
    BTN_RIGHT           = 43
    BTN_SEL_YES         = 53
    BTN_BACK_NO         = 51
    BTN_OPT_ADMIN       = 81
    BTN_MIX_LEVEL       = 82
    BTN_CTRL_PRESET     = 83
    BTN_ZS3_SHOT        = 84
    BTN_METRONOME       = 72
    BTN_PAD_STEP        = 73
    BTN_F1              = 74
    BTN_F2              = 64
    BTN_F3              = 54
    BTN_F4              = 44
    BTN_ALT             = 71
    BTN_RECORD          = 61
    BTN_STOP            = 62
    BTN_PLAY            = 63
    BTN_KNOB_1          = 88
    BTN_KNOB_2          = 78
    BTN_KNOB_3          = 68
    BTN_KNOB_4          = 58

    LED_STATIC_BRIGHT   = LED_MODE_STATIC_CH
    LED_BLINKING        = LED_MODE_FLASHING_CH

    COLOR_RED           = COLOR_RED
    COLOR_GREEN         = COLOR_GREEN
    COLOR_BLUE          = COLOR_BLUE
    COLOR_BLUE_DARK     = COLOR_BLUE_DARK
    COLOR_BLUE_LIGHT    = COLOR_BLUE_SKY
    COLOR_GREEN_LIGHT   = COLOR_GREEN_YELLOW
    COLOR_YELLOW        = COLOR_YELLOW
    COLOR_ORANGE        = COLOR_ORANGE
    COLOR_PURPLE        = COLOR_PURPLE
    COLOR_WHITE         = COLOR_WHITE

    # These constants are specific of this derived class
    BTN_SHIFT           = 19
    BTN_MODE_MIXER      = 13
    BTN_MODE_ZYNPAD     = 14
    BTN_MODE_STEPSEQ    = 15

    COLOR_KNOB_DEC      = 0x53
    COLOR_KNOB_INC      = 0x09
    COLOR_KNOB_BTN      = COLOR_LIME
    COLOR_MODE          = COLOR_YELLOW

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._button_repeater = IntervalTimer()
        self._alt_mode = "mixer"

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.refresh()

    def refresh(self):
        super().refresh()
        print("- REFRESH (LPDeviceHandler)")
        self._leds.led_on(LED_LOGO, self.COLOR_MODE)
        self._leds.led_on(self.BTN_SHIFT, self.COLOR_WHITE)

        # Light up mode buttons
        self._leds.led_on(self.BTN_MODE_MIXER, self.COLOR_GREEN,
            LED_MODE_PULSING_CH if self._alt_mode == "mixer" else self.LED_STATIC_BRIGHT)
        self._leds.led_on(self.BTN_MODE_ZYNPAD, self.COLOR_RED,
            LED_MODE_PULSING_CH if self._alt_mode == "zynpad" else self.LED_STATIC_BRIGHT)
        self._leds.led_on(self.BTN_MODE_STEPSEQ, self.COLOR_BLUE,
            LED_MODE_PULSING_CH if self._alt_mode == "stepseq" else self.LED_STATIC_BRIGHT)

    def _refresh_knob_buttons(self):
        for btn in [self.BTN_KNOB_1, self.BTN_KNOB_2, self.BTN_KNOB_3, self.BTN_KNOB_4]:
            self._leds.led_on(btn - 2, self.COLOR_KNOB_DEC, self.LED_STATIC_BRIGHT)
            self._leds.led_on(btn - 1, self.COLOR_KNOB_INC, self.LED_STATIC_BRIGHT)
            self._leds.led_on(btn, self.COLOR_KNOB_BTN, self.LED_STATIC_BRIGHT)

    def note_on(self, note, channel, velocity, shifted_override=None):
        self._on_shifted_override(shifted_override)

        speed = 120 if not self._is_shifted else 10
        delta = 1 if not self._is_shifted else 2
        pot_index = 0
        for btn in [self.BTN_KNOB_1, self.BTN_KNOB_2, self.BTN_KNOB_3, self.BTN_KNOB_4]:
            if note == btn - 2:
                self._button_repeater.add(
                    note, speed, lambda _:
                        self._state_manager.send_cuia("ZYNPOT", [pot_index, -delta]))
                return True
            if note == btn - 1:
                self._button_repeater.add(
                    note, speed, lambda _:
                        self._state_manager.send_cuia("ZYNPOT", [pot_index, delta]))
                return True
            pot_index += 1

        return super().note_on(note, channel, velocity, shifted_override)

    def note_off(self, note, channel):
        for btn in [self.BTN_KNOB_1, self.BTN_KNOB_2, self.BTN_KNOB_3, self.BTN_KNOB_4]:
            if note in (btn - 2, btn - 1):
                self._button_repeater.remove(note)
                return True

        return super().note_off(note, channel)

    def cc_change(self, ccnum, ccval):
        if ccnum == self.BTN_SHIFT:
            self.on_shift_changed(ccval > 0)
            return True

        return super().cc_change(ccnum, ccval)

    def set_previous_mode(self, name):
        self._alt_mode = name or "mixer"


# ------------------------------------------------------------------------------
# Audio mixer handler (Mixer mode)
# FIXME: this is a candidate for DRY, keep it decoupled!
# ------------------------------------------------------------------------------
class MixerHandler(ModeHandlerBase):

    MODE_NAME                = "mixer"

    # CC_PAD_START_A           = 8
    # CC_PAD_VOLUME_A          = 8
    # CC_PAD_PAN_A             = 9
    # CC_PAD_MUTE_A            = 10
    # CC_PAD_SOLO_A            = 11
    # CC_PAD_PANIC_STOP_A      = 12
    # CC_PAD_AUDIO_RECORD      = 13
    # CC_PAD_AUDIO_STOP        = 14
    # CC_PAD_AUDIO_PLAY        = 15
    # CC_PAD_END_A             = 15

    # CC_PAD_START_B           = 16
    # CC_PAD_VOLUME_B          = 16
    # CC_PAD_PAN_B             = 17
    # CC_PAD_MUTE_B            = 18
    # CC_PAD_SOLO_B            = 19
    # CC_PAD_PANIC_STOP_B      = 20
    # CC_PAD_MIDI_RECORD       = 21
    # CC_PAD_MIDI_STOP         = 22
    # CC_PAD_MIDI_PLAY         = 23
    # CC_PAD_END_B             = 23

    # CC_KNOBS_START           = 24
    # CC_KNOBS_END             = 31

    # CC_JOY_X_NEG             = 32
    # CC_JOY_X_POS             = 33

    FN_VOLUME                = 0x01
    FN_PAN                   = 0x02
    FN_SOLO                  = 0x03
    FN_MUTE                  = 0x04
    # FN_REC_ARM               = 0x05
    FN_SELECT                = 0x06

    def __init__(self, state_manager, leds: FeedbackLEDs):
        super().__init__(state_manager)
        self._leds = leds

    #     self._saved_state = saved_state
    #     self._knobs_function = FN_VOLUME
    #     self._pads_action = None
    #     self._pressed_pads = {}
    #     self._chains_bank = 0

    def set_active(self, active):
        super().set_active(active)
        if active:
            self.refresh()

    #     if active:
    #         self._upload_mode_layout_to_device()

    # def cc_change(self, ccnum, ccval):
    #     # Is a PAD press
    #     if self.CC_PAD_START_A <= ccnum <= self.CC_PAD_END_B:

    #         # This will happend when FULL LEVEL is on (or with a very strong press)
    #         if ccval == 127:
    #             if self._current_screen in ["audio_mixer", "zynpad"]:
    #                 self._pads_action = FN_SELECT
    #                 return self._change_chain(ccnum, ccval)

    #         # Single step actions
    #         cuia = {
    #             self.CC_PAD_PANIC_STOP_A: "ALL_SOUNDS_OFF",
    #             self.CC_PAD_PANIC_STOP_B: "ALL_SOUNDS_OFF",
    #             self.CC_PAD_AUDIO_RECORD: "TOGGLE_AUDIO_RECORD",
    #             self.CC_PAD_AUDIO_STOP: "STOP_AUDIO_PLAY",
    #             self.CC_PAD_AUDIO_PLAY: "TOGGLE_AUDIO_PLAY",
    #             self.CC_PAD_MIDI_RECORD: "TOGGLE_MIDI_RECORD",
    #             self.CC_PAD_MIDI_STOP: "STOP_MIDI_PLAY",
    #             self.CC_PAD_MIDI_PLAY: "TOGGLE_MIDI_PLAY",
    #         }.get(ccnum)
    #         if cuia is not None:
    #             if ccval > 0:
    #                 if cuia == "ALL_SOUNDS_OFF":
    #                     self._stop_all_sounds()
    #                 else:
    #                     self._state_manager.send_cuia(cuia)
    #             return

    #         if ccval == 0:
    #             if self._pads_action != None:
    #                 self._pads_action = None
    #                 return
    #             self._chains_bank = 0
    #         elif self.CC_PAD_START_B <= ccnum <= self.CC_PAD_END_B:
    #             self._chains_bank = 1

    #         if self._current_screen in ["audio_mixer", "zynpad"]:
    #             if ccnum in (self.CC_PAD_VOLUME_A, self.CC_PAD_VOLUME_B):
    #                 self._knobs_function = FN_VOLUME
    #             elif ccnum in (self.CC_PAD_PAN_A, self.CC_PAD_PAN_B):
    #                 self._knobs_function = FN_PAN
    #             elif ccnum in (self.CC_PAD_MUTE_A, self.CC_PAD_MUTE_B):
    #                 self._knobs_function = FN_MUTE
    #             elif ccnum in (self.CC_PAD_SOLO_A, self.CC_PAD_SOLO_B):
    #                 self._knobs_function = FN_SOLO

    #     # Is a Knob rotation
    #     elif self.CC_KNOBS_START <= ccnum <= self.CC_KNOBS_END:
    #         if self._current_screen in ["audio_mixer", "zynpad"]:
    #             if self._knobs_function == FN_VOLUME:
    #                 self._update_volume(ccnum, ccval)
    #             elif self._knobs_function == FN_PAN:
    #                 self._update_pan(ccnum, ccval)
    #             elif self._knobs_function == FN_MUTE:
    #                 self._update_mute(ccnum, ccval)
    #             elif self._knobs_function == FN_SOLO:
    #                 self._update_solo(ccnum, ccval)

    # def _upload_mode_layout_to_device(self):
    #     cmd = SysExSetProgram(
    #         name="Zynthian MIXER",
    #         tempo=self._saved_state.tempo,
    #         arp=self._saved_state.arpeggiator,
    #         tempo_taps=self._saved_state.tempo_taps,
    #         aftertouch=self._saved_state.aftertouch,
    #         keybed_octave=self._saved_state.keybed_octave,
    #         channels={
    #             "pads": self._saved_state.pads_channel,
    #             "keybed": self._saved_state.keybed_channel
    #         },
    #         pads={
    #             "note": self._saved_state.pad_notes,
    #             "pc": range(16),
    #             "cc": range(self.CC_PAD_START_A, self.CC_PAD_END_B + 1)
    #         },
    #         knobs={
    #             "mode": [KNOB_MODE_REL] * 8,
    #             "cc": range(self.CC_KNOBS_START, self.CC_KNOBS_END + 1),
    #             "min": [0] * 8,
    #             "max": [127] * 8,
    #             "name": [f"Chain {i}/{i+8}" for i in range(1, 9)]
    #         },
    #         joy={
    #             "x-mode": JOY_MODE_DUAL,
    #             "x-neg-ch": self.CC_JOY_X_NEG,
    #             "x-pos-ch": self.CC_JOY_X_POS,
    #             "y-mode": JOY_MODE_PITCHBEND
    #         }
    #     )
    #     msg = bytes.fromhex("F0 {} F7".format(cmd))
    #     lib_zyncore.dev_send_midi_event(self._idev_out, msg, len(msg))

    # def _query_mode_layout_from_device(self):
    #     cmd = SysExQueryProgram()
    #     query = bytes.fromhex("F0 {} F7".format(cmd))
    #     lib_zyncore.dev_send_midi_event(self._idev_out, query, len(query))

    # def _change_chain(self, ccnum, ccval):
    #     # CCNUM is a PAD, but we expect a KNOB; offset it
    #     ccnum = ccnum + self.CC_KNOBS_START - self.CC_PAD_START_A
    #     return self._update_chain("select", ccnum, ccval)

    # def _update_volume(self, ccnum, ccval):
    #     return self._update_chain("level", ccnum, ccval, 0, 100)

    # def _update_pan(self, ccnum, ccval):
    #     return self._update_chain("balance", ccnum, ccval, -100, 100)

    # def _update_mute(self, ccnum, ccval):
    #     return self._update_chain("mute", ccnum, ccval)

    # def _update_solo(self, ccnum, ccval):
    #     return self._update_chain("solo", ccnum, ccval)

    # def _update_chain(self, type, ccnum, ccval, minv=None, maxv=None):
    #     index = ccnum - self.CC_KNOBS_START + self._chains_bank * 8
    #     chain = self._chain_manager.get_chain_by_index(index)
    #     if chain is None or chain.chain_id == 0:
    #         return False
    #     mixer_chan = chain.mixer_chan

    #     if type == "level":
    #         value = self._zynmixer.get_level(mixer_chan)
    #         set_value = self._zynmixer.set_level
    #     elif type == "balance":
    #         value = self._zynmixer.get_balance(mixer_chan)
    #         set_value = self._zynmixer.set_balance
    #     elif type == "mute":
    #         value = ccval < 64
    #         set_value = lambda c, v: self._zynmixer.set_mute(c, v, True)
    #     elif type == "solo":
    #         value = ccval < 64
    #         set_value = lambda c, v: self._zynmixer.set_solo(c, v, True)
    #     elif type == "select":
    #         return self._chain_manager.set_active_chain_by_id(chain.chain_id)
    #     else:
    #         return False

    #     # NOTE: knobs are encoders, not pots (so ccval is relative)
    #     if minv is not None and maxv is not None:
    #         value *= 100
    #         value += ccval if ccval < 64 else ccval - 128
    #         value = max(minv, min(value, maxv))
    #         value /= 100

    #     set_value(mixer_chan, value)
    #     return True


# --------------------------------------------------------------
#     # To control main level, use SHIFT + K1
#     main_chain_knob = KNOB_1

#     def __init__(self, state_manager, leds: FeedbackLEDs):
#         super().__init__(state_manager)
#         self._leds = leds
#         self._knobs_function = FN_VOLUME
#         self._track_buttons_function = FN_SELECT
#         self._chains_bank = 0

#         active_chain = self._chain_manager.get_active_chain()
#         self._active_chain = active_chain.chain_id if active_chain else 0

    def refresh(self):
        self._leds.all_off()

#         self._leds.control_leds_off()

#         # If SHIFT is pressed, show active knob's function
#         if self._is_shifted:
#             # Knob Ctrl buttons
#             btn = {
#                 FN_VOLUME: BTN_KNOB_CTRL_VOLUME,
#                 FN_PAN: BTN_KNOB_CTRL_PAN,
#             }[self._knobs_function]
#             self._leds.led_on(btn)

#             # Soft Keys buttons
#             btn = {
#                 FN_SEQUENCE_MANAGER: BTN_SOFT_KEY_CLIP_STOP,
#                 FN_MUTE: BTN_SOFT_KEY_MUTE,
#                 FN_SOLO: BTN_SOFT_KEY_SOLO,
#                 FN_SELECT: BTN_SOFT_KEY_SELECT,
#                 FN_SCENE: BTN_SOFT_KEY_REC_ARM,
#             }[self._track_buttons_function]
#             self._leds.led_on(btn)

#             # Clips bank selection
#             btn = BTN_LEFT if self._chains_bank == 0 else BTN_RIGHT
#             self._leds.led_on(btn)

#         # Otherwise, show current function status
#         else:
#             if self._track_buttons_function == FN_SCENE:
#                 for i in range(8):
#                     scene = i + (8 if self._chains_bank == 1 else 0)
#                     state = scene == (self._zynseq.bank - 1)
#                     self._leds.led_state(BTN_TRACK_1 + i, state)
#                 return

#             if self._track_buttons_function == FN_SEQUENCE_MANAGER:
#                 self._leds.led_blink(BTN_SOFT_KEY_CLIP_STOP)
#                 return

#             query = {
#                 FN_MUTE: self._zynmixer.get_mute,
#                 FN_SOLO: self._zynmixer.get_solo,
#                 FN_SELECT: self._is_active_chain,
#             }[self._track_buttons_function]
#             for i in range(8):
#                 index = i + (8 if self._chains_bank == 1 else 0)
#                 chain = self._chain_manager.get_chain_by_index(index)
#                 if not chain:
#                     break
#                 # Main channel ignored
#                 if chain.chain_id == 0:
#                     continue
#                 self._leds.led_state(BTN_TRACK_1 + i, query(index))

#     def on_shift_changed(self, state):
#         retval = super().on_shift_changed(state)
#         self.refresh()
#         return retval

#     def note_on(self, note, velocity, shifted_override=None):
#         self._on_shifted_override(shifted_override)

#         # If SHIFT is pressed, handle alternative functions
#         if self._is_shifted:
#             if note == BTN_KNOB_CTRL_VOLUME:
#                 self._knobs_function = FN_VOLUME
#             elif note == BTN_KNOB_CTRL_PAN:
#                 self._knobs_function = FN_PAN
#             elif note == BTN_SOFT_KEY_MUTE:
#                 self._track_buttons_function = FN_MUTE
#             elif note == BTN_SOFT_KEY_SOLO:
#                 self._track_buttons_function = FN_SOLO
#             elif note == BTN_SOFT_KEY_REC_ARM:
#                 self._track_buttons_function = FN_SCENE
#             elif note == BTN_SOFT_KEY_CLIP_STOP:
#                 self._track_buttons_function = FN_SEQUENCE_MANAGER
#             elif note == BTN_LEFT:
#                 self._chains_bank = 0
#             elif note == BTN_RIGHT:
#                 self._chains_bank = 1
#             elif note == BTN_STOP_ALL_CLIPS:
#                 self._stop_all_sounds()
#             elif note == BTN_PLAY:
#                 self._run_track_button_function_on_channel(255, FN_MUTE)
#             elif note == BTN_SOFT_KEY_SELECT:
#                 self._track_buttons_function = FN_SELECT
#             elif note == BTN_RECORD:
#                 self._state_manager.send_cuia("TOGGLE_RECORD")
#                 return True  # skip refresh
#             elif note == BTN_UP:
#                 self._state_manager.send_cuia("BACK")
#                 return True  # skip refresh
#             elif note == BTN_DOWN:
#                 self._state_manager.send_cuia("SCREEN_ZYNPAD")
#                 return True  # skip refresh
#             else:
#                 return False
#             self.refresh()
#             return True

#         # Otherwise, handle primary functions
#         else:
#             if BTN_TRACK_1 <= note <= BTN_TRACK_8:
#                 return self._run_track_button_function(note)

#     def cc_change(self, ccnum, ccval):
#         if self._knobs_function == FN_VOLUME:
#             return self._update_volume(ccnum, ccval)
#         if self._knobs_function == FN_PAN:
#             return self._update_pan(ccnum, ccval)

#     def update_strip(self, chan, symbol, value):
#         if {"mute": FN_MUTE, "solo": FN_SOLO}.get(symbol) != self._track_buttons_function:
#             return
#         chan -= self._chains_bank * 8
#         if 0 > chan > 8:
#             return
#         self._leds.led_state(BTN_TRACK_1 + chan, value)
#         return True

#     def set_active_chain(self, chain, refresh):
#         # Do not change chain if 'main' is selected
#         if chain == 0:
#             return
#         self._chains_bank = 0 if chain <= 8 else 1
#         self._active_chain = chain
#         if refresh:
#             self.refresh()

#     def _is_active_chain(self, position):
#         chain = self._chain_manager.get_chain_by_position(position)
#         if chain is None:
#             return False
#         return chain.chain_id == self._active_chain

#     def _update_volume(self, ccnum, ccval):
#         return self._update_control("level", ccnum, ccval, 0, 100)

#     def _update_pan(self, ccnum, ccval):
#         return self._update_control("balance", ccnum, ccval, -100, 100)

#     def _update_control(self, type, ccnum, ccval, minv, maxv):
#         if self._is_shifted:
#             # Only main chain is handled with SHIFT, ignore the rest
#             if ccnum != self.main_chain_knob:
#                 return False
#             mixer_chan = 255
#         else:
#             index = (ccnum - KNOB_1) + self._chains_bank * 8
#             chain = self._chain_manager.get_chain_by_index(index)
#             if chain is None or chain.chain_id == 0:
#                 return False
#             mixer_chan = chain.mixer_chan

#         if type == "level":
#             value = self._zynmixer.get_level(mixer_chan)
#             set_value = self._zynmixer.set_level
#         elif type == "balance":
#             value = self._zynmixer.get_balance(mixer_chan)
#             set_value = self._zynmixer.set_balance
#         else:
#             return False

#         # NOTE: knobs are encoders, not pots (so ccval is relative)
#         value *= 100
#         value += ccval if ccval < 64 else ccval - 128
#         value = max(minv, min(value, maxv))
#         set_value(mixer_chan, value / 100)
#         return True

#     def _run_track_button_function(self, note):
#         index = (note - BTN_TRACK_1) + self._chains_bank * 8

#         # FIXME: move this to padmatrix handler!
#         if self._track_buttons_function == FN_SCENE:
#             self._zynseq.select_bank(index + 1)
#             self._state_manager.send_cuia("SCREEN_ZYNPAD")
#             return True

#         chain = self._chain_manager.get_chain_by_index(index)
#         if chain is None or chain.chain_id == 0:
#             return False

#         return self._run_track_button_function_on_channel(chain)

#     def _run_track_button_function_on_channel(self, chain, function=None):
#         if isinstance(chain, int):
#             channel = chain
#             chain = None
#         else:
#             channel = chain.mixer_chan

#         if function is None:
#             function = self._track_buttons_function

#         if function == FN_MUTE:
#             val = self._zynmixer.get_mute(channel) ^ 1
#             self._zynmixer.set_mute(channel, val, True)
#             return True

#         if function == FN_SOLO:
#             val = self._zynmixer.get_solo(channel) ^ 1
#             self._zynmixer.set_solo(channel, val, True)
#             return True

#         if function == FN_SELECT and chain is not None:
#             self._chain_manager.set_active_chain_by_id(chain.chain_id)
#             return True


# ------------------------------------------------------------------------------
# Audio mixer handler (Mixer mode)
# ------------------------------------------------------------------------------
class LPMixerHandler(MixerHandler):

    COLOR_MODE          = COLOR_GREEN

    BTN_FUNCTION_VOLUME = 91
    BTN_FUNCTION_PAN    = 92
    BTN_FUNCTION_SOLO   = 93
    BTN_FUNCTION_MUTE   = 94

    def __init__(self, state_manager, leds: FeedbackLEDs):
        super().__init__(state_manager, leds)
        self._active_function = self.FN_SELECT

    def refresh(self):
        print("- REFRESH (LPMixerHandler)")
        super().refresh()
        self._leds.led_on(LED_LOGO, self.COLOR_MODE)

        # Light up function leds
        self._leds.led_on(self.BTN_FUNCTION_VOLUME,
            COLOR_BLUE_SKY if self._active_function == self.FN_VOLUME else COLOR_WHITE)
        self._leds.led_on(self.BTN_FUNCTION_PAN,
            COLOR_GREEN if self._active_function == self.FN_PAN else COLOR_WHITE)
        self._leds.led_on(self.BTN_FUNCTION_SOLO,
            COLOR_YELLOW if self._active_function == self.FN_SOLO else COLOR_WHITE)
        self._leds.led_on(self.BTN_FUNCTION_MUTE,
            COLOR_RED if self._active_function == self.FN_MUTE else COLOR_WHITE)
