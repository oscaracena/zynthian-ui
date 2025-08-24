#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "M-VAVE SMC Pad Pocket"
#
# Copyright (C) 2025 Oscar Aceña <oscaracena@gmail.com>
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

# import jack
import time
# import signal
import logging
# from bisect import bisect
# from copy import deepcopy
# import multiprocessing as mp
# from functools import partial
# from threading import Thread, RLock, Event

from zynlibs.zynseq import zynseq
from zyncoder.zyncore import lib_zyncore
# from zyngine.zynthian_signal_manager import zynsigman
# from zyngine.zynthian_engine_audioplayer import zynthian_engine_audioplayer
from zyngine.ctrldev.zynthian_ctrldev_base import (
    zynthian_ctrldev_zynmixer, zynthian_ctrldev_zynpad)
from zyngine.ctrldev.zynthian_ctrldev_base_extended import (
    RunTimer, IntervalTimer, KnobSpeedControl, ButtonTimer, CONST)
from zyngine.ctrldev.zynthian_ctrldev_base_ui import ModeHandlerBase

import colorsys

# Driver specification:
# - ZynPad mode, for launching sequences
# - Action button, for changing modes and setting. Could be hidden (reset to show again)
# - Device mode, for controling Zynthian UI
# - Mixer mode, with +/- for gain on 7+main chains. Support for banks, pan, mute and solo

# Useful constants
PAD_COUNT         = 16
PAD_LAST_IDX      = 15
PAD_FIRST_IDX     = 0

CC_PAD_PRESS      = 0x7F
CC_PAD_RELEASE    = 0x00

LED_BRIGHT_20     = 0.20
# LED_BRIGHT_25   = 0.25
# LED_BRIGHT_50   = 0.5
# LED_BRIGHT_65   = 0.65
# LED_BRIGHT_75   = 0.75
# LED_BRIGHT_90   = 0.90
LED_BRIGHT_100    = 1.0
LED_STILL         = 0x00
# LED_PULSING_16  = 0x07
# LED_PULSING_8   = 0x08
# LED_PULSING_4   = 0x09
LED_PULSING_2     = 0x0A
# LED_BLINKING_24 = 0x0B
LED_BLINKING_16   = 0x0C
LED_BLINKING_8    = 0x0D
# LED_BLINKING_4  = 0x0E
# LED_BLINKING_2  = 0x0F

# Controller preset/bank used by this driver
WORKING_PRESET  = 0
WORKING_BANK    = 0
WORKING_CHANNEL = 0

# --------------------------------------------------------------------------
# 'M-VAVE SMC Pad Pocket' device controller class
# --------------------------------------------------------------------------
class zynthian_ctrldev_mvave_smc_pad_pocket(zynthian_ctrldev_zynmixer, zynthian_ctrldev_zynpad):

    dev_ids = ["SINCO IN 1", "SMC-PAD Pocket", "SMC-PAD Pocket 787DEE63C6CA in"]
    driver_name = "SMC Pad Pocket"
    unroute_from_chains = False

    @classmethod
    def get_autoload_flag(cls):
        return True

    def __init__(self, state_manager, idev_in, idev_out):
        self._hw = SMCPadController(idev_out)

        self._leds = FeedbackLEDs(self._hw)
#         self._device_handler = DeviceHandler(state_manager, self._leds)
#         self._mixer_handler = MixerHandler(state_manager, self._leds)
        self._padmatrix_handler = PadMatrixHandler(state_manager, self._leds)
#         self._stepseq_handler = StepSeqHandler(state_manager, self._leds, idev_in)
        self._current_handler = self._padmatrix_handler
#         self._is_shifted = False

#         self._signals = [
#             (zynsigman.S_GUI,
#                 zynsigman.SS_GUI_SHOW_SCREEN,
#                 self._on_gui_show_screen),

#             (zynsigman.S_AUDIO_PLAYER,
#                 zynthian_engine_audioplayer.SS_AUDIO_PLAYER_STATE,
#                 lambda handle, state:
#                     self._on_media_change_state(state, f"audio-{handle}", "player")),

#             (zynsigman.S_AUDIO_RECORDER,
#                 state_manager.audio_recorder.SS_AUDIO_RECORDER_STATE,
#                 partial(self._on_media_change_state, media="audio", kind="recorder")),

#             (zynsigman.S_STATE_MAN,
#                 state_manager.SS_MIDI_PLAYER_STATE,
#                 partial(self._on_media_change_state, media="midi", kind="player")),

#             (zynsigman.S_STATE_MAN,
#                 state_manager.SS_MIDI_RECORDER_STATE,
#                 partial(self._on_media_change_state, media="midi", kind="recorder")),
#         ]

        # NOTE: init will call refresh(), so _current_hanlder must be ready!
        super().__init__(state_manager, idev_in, idev_out)

    def init(self):
        super().init()
#         for signal, subsignal, callback in self._signals:
#             zynsigman.register(signal, subsignal, callback)

        # Wait until the pipeline is ready (when the driver receives response to a sync command)
        self._hw.sync(callback=self._on_synced)

    def _on_synced(self):
        # Setup device: change to working preset/bank, set PADs as CC mode, channel 0, nums 0-15
        self._hw.change_preset(WORKING_PRESET)
        self._hw.change_bank(WORKING_BANK)
        for pad in range(16):
            self._hw.set_pad_mode(pad, "pad")
            self._hw.set_pad_type(pad, "cc")
            self._hw.set_pad_note(pad, pad)
            self._hw.set_pad_channel(pad, WORKING_CHANNEL)

            # FIXME: also set CC press/release values

        # FIXME: save current controller layout

    def end(self):
#         for signal, subsignal, callback in self._signals:
#             zynsigman.unregister(signal, subsignal, callback)
        super().end()

        # FIXME: restore previous controller layout

    def refresh(self):
        self._current_handler.refresh()

    def midi_event(self, ev: bytes):
        # print("MIDI EVENT:", " ".join(f"{b:02X}" for b in ev))

#         if self._on_midi_event(ev):
#             while True:
#                 action = self._current_handler.pop_action_request()
#                 if not action:
#                     return True

#                 # NOTE: Add other receivers as needed
#                 receiver, action, args, kwargs = action
#                 if receiver == "stepseq":
#                     self._stepseq_handler.run_action(action, args, kwargs)
#                 elif receiver == "mixpad":
#                     self._padmatrix_handler.run_action(action, args, kwargs)
#         return False

#     def _on_midi_event(self, ev):
        evtype = (ev[0] >> 4) & 0x0F

        if evtype == CONST.MIDI_CC:
            ccnum = ev[1] & 0x7F
            ccval = ev[2] & 0x7F
            channel = ev[0] & 0xF

            if channel != WORKING_CHANNEL:
                return

#             if note == BTN_SHIFT:
#                 return self._on_shift_changed(True)

#             if self._is_shifted:
#                 old_handler = self._current_handler
#                 # Change global mode here
#                 if note == BTN_KNOB_CTRL_DEVICE:
#                     self._current_handler = self._device_handler
#                 elif note in [BTN_KNOB_CTRL_PAN, BTN_KNOB_CTRL_VOLUME]:
#                     self._current_handler = self._mixer_handler
#                     self._padmatrix_handler.refresh()
#                 elif note == BTN_KNOB_CTRL_SEND:
#                     self._current_handler = self._stepseq_handler

#                 if old_handler != self._current_handler:
#                     old_handler.set_active(False)
#                     self._current_handler.set_active(True)

#                 # Change sub-modes here
#                 if self._current_handler == self._mixer_handler:
#                     if note == BTN_SOFT_KEY_CLIP_STOP:
#                         self._padmatrix_handler.enable_seqman(True)
#                     elif BTN_SOFT_KEY_SOLO <= note <= BTN_SOFT_KEY_END:
#                         self._padmatrix_handler.enable_seqman(False)

            # Padmatrix related events
            if self._current_handler == self._padmatrix_handler:
#                 if BTN_PAD_START <= note <= BTN_PAD_END:

#                     # Launch StepSeq directly from SHIFT + PAD
#                     if self._is_shifted:
#                         seq = self._padmatrix_handler.get_sequence_from_pad(
#                             note)
#                         if seq is None:
#                             return False
#                         if self._current_handler != self._stepseq_handler:
#                             self._current_handler.set_active(False)
#                         self._current_handler = self._stepseq_handler
#                         self._current_handler.set_sequence(seq)
#                         self._current_handler.set_active(True)
#                         self._current_handler.refresh(
#                             shifted_override=self._is_shifted)
#                         return True

                if ccval == CC_PAD_PRESS:
                    return self._padmatrix_handler.pad_press(ccnum)

#                 # FIXME: move these events to padmatrix handler itself
#                 elif note == BTN_RECORD and not self._is_shifted:
#                     return self._padmatrix_handler.on_record_changed(True)
#                 elif note == BTN_PLAY:
#                     if not self._is_shifted:
#                         return self._padmatrix_handler.on_toggle_play()
#                     self._padmatrix_handler.note_on(
#                         note, vel, self._is_shifted)
#                 elif (BTN_SOFT_KEY_START <= note <= BTN_SOFT_KEY_END
#                       and not self._is_shifted):
#                     row = note - BTN_SOFT_KEY_START
#                     return self._padmatrix_handler.on_toggle_play_row(row)
#                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
#                     track = note - BTN_TRACK_1
#                     self._padmatrix_handler.on_track_changed(track, True)
#                     self._current_handler.note_on(note, vel, self._is_shifted)
#                     self._padmatrix_handler.refresh()
#                     return True
#                 elif note == BTN_STOP_ALL_CLIPS:
#                     self._padmatrix_handler.note_on(
#                         note, vel, self._is_shifted)

#             return self._current_handler.note_on(note, vel, self._is_shifted)

#         elif evtype == EV_NOTE_OFF:
#             note = ev[1] & 0x7F

#             if note == BTN_SHIFT:
#                 return self._on_shift_changed(False)

#             # Padmatrix related events
#             if self._current_handler == self._mixer_handler:
#                 if note == BTN_RECORD:
#                     return self._padmatrix_handler.on_record_changed(False)
#                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
#                     track = note - BTN_TRACK_1
#                     self._padmatrix_handler.on_track_changed(track, False)
#                 elif note == BTN_STOP_ALL_CLIPS:
#                     self._padmatrix_handler.note_off(note, self._is_shifted)

#             return self._current_handler.note_off(note, self._is_shifted)

        elif ev[0] == CONST.MIDI_SYSEX:
            self._hw.on_sysex_message(ev[1:-1])

    def light_off(self):
        self._leds.all_off()

#     def update_mixer_strip(self, chan, symbol, value):
#         if self._current_handler == self._mixer_handler:
#             self._current_handler.update_strip(chan, symbol, value)

#     def update_mixer_active_chain(self, active_chain):
#         refresh = self._current_handler == self._mixer_handler
#         self._mixer_handler.set_active_chain(active_chain, refresh)

    def update_seq_state(self, *args, **kwargs):
        if self._current_handler == self._padmatrix_handler:
            self._padmatrix_handler.update_seq_state(*args, **kwargs)
#         elif self._current_handler == self._stepseq_handler:
#             self._current_handler.update_seq_state(*args, **kwargs)

#     def get_state(self):
#         state = {}
#         state.update(self._stepseq_handler.get_state())
#         return state

#     def set_state(self, state):
#         self._stepseq_handler.set_state(state)

#     def _on_shift_changed(self, state):
#         self._is_shifted = state
#         self._current_handler.on_shift_changed(state)
#         if self._current_handler == self._mixer_handler:
#             self._padmatrix_handler.on_shift_changed(state)
#         return True

#     def _on_gui_show_screen(self, screen):
#         self._device_handler.on_screen_change(screen)
#         self._padmatrix_handler.on_screen_change(screen)
#         self._stepseq_handler.on_screen_change(screen)
#         if self._current_handler == self._device_handler:
#             self._current_handler.refresh()

#     def _on_media_change_state(self, state, media, kind):
#         self._current_handler.on_media_change(media, kind, state)
#         if self._current_handler == self._device_handler:
#             self._current_handler.refresh()


# --------------------------------------------------------------------------
# Controller interaction layer
# --------------------------------------------------------------------------
class SMCPadController:
    DEVID_CTRL            = [0x00, 0x32, 0x09]
    DEVID_STAT            = [0x00, 0x32, 0x0D]

    PRESETS_0             = [0x70, 0x16]
    PRESETS_1             = [0x63, 0x2D]
    PRESETS_2             = [0x56, 0x44]
    PRESETS_3             = [0x49, 0x5B]

    PROP_LED_OFFSET       = 0x05
    PROP_NOTE_OFFSET      = 0x02
    PROP_CHANNEL_OFFSET   = 0x01
    PROP_TYPE_OFFSET      = 0x00
    PROP_MODE_OFFSET      = 2912

    def __init__(self, idev):
        self._idev = idev
        self._preset = 0
        self._bank = 0

        self._on_sync_cbs = []

    def change_preset(self, preset: int):
        # Message format:
        # - DEVID[3] 49 00 00 00 02 07 00 00 00 10 00 00 00 PRESET[1] CRC[2]

        assert 0 <= preset <= 3, "presets page should be in range [0, 3]"

        cmd = [0x49, 0, 0, 0, 0x02, 0x07, 0, 0, 0, 0x10, 0, 0, 0, preset]
        checksum = self._get_checksum([4, preset])
        cmd += self._pack_bytes(checksum.to_bytes(1, "little"), 1)

        self._send_sysex(cmd)
        self._preset = preset

    def change_bank(self, bank: int):
        # Message format:
        # - DEVID[3] 49 00 00 40 02 PRESET[2] 00 00 10 00 00 00 BANK[1] CRC[2]

        assert 0 <= bank <= 6, "bank should be in range [0, 6]"

        preset_addr = getattr(self, f"PRESETS_{self._preset}")
        cmd = [0x49, 0, 0, 0x40, 0x02]
        cmd += preset_addr
        cmd += [0, 0, 0x10, 0, 0, 0, bank]

        preset_addr = [(preset_addr[1] << 7) + preset_addr[0] - 2]
        checksum = self._get_checksum(preset_addr + [bank])
        cmd += self._pack_bytes(checksum.to_bytes(1, "little"), 1)

        self._send_sysex(cmd)
        self._bank = bank

    def set_pad_mode(self, pad: int, mode: str, preset: int = None, bank: int = None):
        modes = {"pad": 0, "control": 1}
        assert mode in modes, f"mode must be one of {list(modes.keys())}"
        self._set_property(pad, [modes.get(mode)], self.PROP_MODE_OFFSET, 0, preset)

    def set_pad_type(self, pad: int, ptype: str, preset: int = None, bank: int = None):
        types = {"note": 0, "cc-toggle": 1, "cc": 2, "pc": 3, "custom": 4}
        assert ptype in types, f"type must be one of {list(types.keys())}"
        self._set_property(pad, [types.get(ptype)], self.PROP_TYPE_OFFSET, 0, preset)

    def set_pad_note(self, pad: int, note: int, preset: int = None, bank: int = None):
        assert 0 <= note <= 0x7F, "note number should be in range [0, 127]"
        self._set_property(pad, [note], self.PROP_NOTE_OFFSET, bank, preset)

    def set_pad_channel(self, pad: int, channel: int, bank: int = None, preset: int = None):
        assert 0 <= channel <= 15, "channel should be in range [0, 15]"
        self._set_property(pad, [channel], self.PROP_CHANNEL_OFFSET, bank, preset)

    def set_pad_led(self, pad: int, color: tuple, bank: int = None, preset: int = None):
        # Message format:
        # - DEVID[3] 59 00 00 40 02 ADDR[2] 00 00 30 00 00 00 R[1] G[1] B+CRC[1] CRC[1]

        color = (
            max(0, min(255, color[0])),
            max(0, min(255, color[1])),
            max(0, min(255, color[2])),
        )

        pad, bank, preset = self._clean_fields(pad, bank, preset)
        led_addr = self._get_prop_addr(pad, bank, preset, self.PROP_LED_OFFSET)

        cmd = [0x59, 0, 0, 0x40, 0x02]
        cmd += list(self._pack_bytes(led_addr.to_bytes(2, "little")))[:2]
        cmd += [0, 0, 0x30, 0, 0, 0]
        cmd += self._pack_bytes(bytes(color))

        checksum = self._get_checksum([led_addr] + list(color))
        cs_bytes = self._pack_bytes(checksum.to_bytes(1, "little"), 3)
        cmd[-1] |= cs_bytes[0]
        cmd.append(cs_bytes[1])

        self._send_sysex(cmd)

    def pad_led_off(self, pad: int, bank: int = None, preset: int = None):
        self.set_pad_led(pad, (0, 0, 0), bank, preset)

    def sync(self, callback: None):
        # Message format:
        # - DEVID[3] 41 00 00 00 02 00 00 00 00 00 01 00 00 73 01

        self._send_sysex("41 00 00 00 02 00 00 00 00 00 01 00 00 73 01", self.DEVID_STAT)
        if callable(callback):
            self._on_sync_cbs.append(callback)

    def on_sysex_message(self, data: bytes):
        # Status message format:
        # - DEVID[3] 01 01 00 00 02 00 00 00 00 00 01 00 00 20 01 58 11 00 00 00 00
        # - PRESET[1] CRC[2]

        # Response to a sync request
        if data[3:8] == bytes((1, 1, 0, 0, 2)):
            print("--- SYNC response---")
            self._preset = data[-3]
            for cb in self._on_sync_cbs:
                try:
                    cb()
                except Exception as err:
                    logging.error(f"on sync callback, {err}")

    def _set_property(self, pad: int, value: list, offset: int,
            bank: int = None, preset: int = None):

        # Message format:
        # - DEVID[3] 49 00 00 40 02 ADDR[2] 00 00 10 00 00 00 VALUE[1] CRC[2]

        pad, bank, preset = self._clean_fields(pad, bank, preset)
        prop_addr = self._get_prop_addr(pad, bank, preset, offset)

        cmd = [0x49, 0, 0, 0x40, 0x02]
        cmd += list(self._pack_bytes(prop_addr.to_bytes(2, "little")))[:2]
        cmd += [0, 0, 0x10, 0, 0, 0] + value

        checksum = self._get_checksum([0xFE, prop_addr] + value)
        cmd += self._pack_bytes(checksum.to_bytes(1, "little"), 1)

        self._send_sysex(cmd)

    def _clean_fields(self, pad: int, bank: int, preset: int):
        bank = bank if bank is not None else self._bank
        preset = preset if preset is not None else self._preset

        assert 0 <= preset <= 3, "preset should be in range [0, 3]"
        assert 0 <= bank <= 6, "bank should be in range [0, 6]"
        assert 0 <= pad <= 15, "pad should be in range [0, 5]"

        return pad, bank, preset

    def _get_prop_addr(self, pad: int, bank: int, preset: int, offset: int):
        # Magic numbers:
        # - 19: distance between presets
        # - 26: distance between pads
        # - 16: number of pads
        # - 7: number of banks
        # - 2916: distance between presets for PAD mode addressing

        if offset == self.PROP_MODE_OFFSET:
            return offset + (2916 + 15) * preset + pad
        return offset + 19 * preset + (preset * 7 * 16 + bank * 16 + pad) * 26

    def _get_checksum(self, data: list):
        magic = 0xF7
        ds = 0
        for x in data:
            y = x
            while y > 0:
                ds += (y & 0xFF)
                y >>= 8
        return (magic - (ds & 0xFF)) & 0xFF

    def _pack_bytes(self, data: bytes, bit_offset: int = 0):
        retval = [0]
        for b in data:
            retval[-1] |= (b << bit_offset) & 0x7F
            retval.append(b >> (7 - bit_offset))
            bit_offset += 1
            if bit_offset > 6:
                bit_offset = 0

        return bytes(retval)

    def _send_sysex(self, cmd, devid=DEVID_CTRL, debug=False):
        if isinstance(cmd, str):
            cmd = bytes.fromhex(cmd)
        elif isinstance(cmd, (list, tuple)):
            cmd = bytes(cmd)

        query = b"\xF0" + bytes(devid) + cmd + b"\xF7"

        if debug:
            print(f"SysEx:", " ".join(f"{b:02X}" for b in query))

        lib_zyncore.dev_send_midi_event(self._idev, query, len(query))

        # NOTE: I see a problem when sending two messages too quickly, neither of them
        # arrived. Adding a little wait here appears to fix it.
        time.sleep(0.01)


# --------------------------------------------------------------------------
# Feedback LEDs controller
# --------------------------------------------------------------------------
class FeedbackLEDs:

    BLINK_NAME    = "LEDS"
    BLINK_TIMEOUT = 500
    BLINK_STEPS   = 12

    def __init__(self, hwdev: SMCPadController):
        self._hw = hwdev
    #     self._state = {}
    #     self._timer = RunTimer()

        self._blinker = IntervalTimer()
        self._blinker_state = [0, True]
        self._blinker_leds = {}

    def all_off(self):
        for pad in range(16):
            self.led_off(pad)

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

    # def led_state(self, led, state):
    #     (self.led_on if state else self.led_off)(led)

    def led_off(self, led, overlay=False):
    #     self._timer.remove(led)
        # self._blinker.remove(led)
        self._blinker_leds.pop(led, None)

        self._hw.pad_led_off(led)
    #     lib_zyncore.dev_send_note_on(self._idev, 0, led, 0)
    #     if not overlay:
    #         self._state[led] = (0, 0)

    def led_on(self, led, color=(255, 255, 255), mode=LED_STILL,
            brightness=LED_BRIGHT_100, overlay=False):

    #     self._timer.remove(led)
        # self._blinker.remove(led)
        self._blinker_leds.pop(led, None)

        color = self._adjust_brightness(color, brightness)
        self._hw.set_pad_led(led, color)

        if mode != LED_STILL:
            colors = [
                color,
                *([None] * (self.BLINK_STEPS - 2)),
                self._adjust_brightness(color, LED_BRIGHT_20),
            ]

            if mode == LED_PULSING_2:
                for i in range(1, self.BLINK_STEPS - 1):
                    step_br = LED_BRIGHT_100 - i * \
                        (LED_BRIGHT_100 - LED_BRIGHT_20) / self.BLINK_STEPS
                    colors[i] = self._adjust_brightness(color, step_br)

            if not self._blinker_leds:
                self._blinker.add(self.BLINK_NAME, self.BLINK_TIMEOUT // self.BLINK_STEPS,
                    self._do_blink)
            self._blinker_leds[led] = colors

    #     if not overlay:
    #         self._state[led] = (color, brightness)

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

    def _do_blink(self, name):
        # Ping-pong between 0 and len(colors)-1 using state[1] for
        # direction (True=forward, False=backward)
        idx = self._blinker_state[0]
        if self._blinker_state[1]:  # Forward
            if idx >= self.BLINK_STEPS - 1:
                self._blinker_state[1] = False
                idx -= 1
            else:
                idx += 1
        else:  # Backward
            if idx <= 0:
                self._blinker_state[1] = True
                idx += 1
            else:
                idx -= 1

        for led, colors in self._blinker_leds.copy().items():
            color = colors[idx]
            if led not in self._blinker_leds or color is None:
                continue
            self._hw.set_pad_led(led, color)
        self._blinker_state[0] = idx

    def _adjust_brightness(self, color, brightness):
        r, g, b = color
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        r2, g2, b2 = colorsys.hsv_to_rgb(h, s, brightness)
        return int(r2 * 255), int(g2 * 255), int(b2 * 255)


# --------------------------------------------------------------------------
# Handle pad matrix for Zynpad
# --------------------------------------------------------------------------
class PadMatrixHandler(ModeHandlerBase):

    GROUP_COLORS = [
        (0xFF, 0x00, 0x00),  # Red Granate
        (0x0D, 0x50, 0x38),  # Blue Aguamarine
        (0x1D, 0x59, 0x00),  # Green Pistacho
        (0x54, 0x00, 0xFF),  # Lila
        (0x00, 0xA9, 0xFF),  # Mid Blue
        (0xFF, 0xFF, 0xFF),  # Sky Blue
        (0x00, 0xFF, 0x00),  # Dark Green
        (0xFF, 0xFF, 0x00),  # Ocre
        (0x59, 0x1D, 0x00),  # Maroon
        (0x69, 0x3C, 0x1C),  # Dark Grey
        (0xFF, 0x4C, 0x4C),  # Pink
        (0x00, 0x00, 0xFF),  # Blue sat.
        (0x00, 0xFF, 0x87),  # Turquesa
        (0xFF, 0x15, 0x00),  # Orange
        (0xD8, 0x6A, 0x1C),  # Light Maroon
        (0x72, 0xFF, 0x15),  # Light Green
    ]

    def __init__(self, state_manager, leds: FeedbackLEDs):
        super().__init__(state_manager)
        self._leds = leds
        self._libseq = self._zynseq.libseq
        self._cols = 4
        self._rows = 4
#         self._is_record_pressed = False
#         self._track_btn_pressed = None
        self._playing_seqs = set()
#         self._btn_timer = ButtonTimer(self._handle_timed_button)
#         self._pattern_template = None

#         # Seqman sub-mode
#         self._seqman_func = None
#         self._seqman_src_seq = None

        # FIXME: this value should be updated by a signal, to be in sync with UI state
        self._recording_seq = None

        # Sort pads in the same order that libseq uses
        self._pads = []
        for c in reversed(range(self._cols)):
            for r in range(self._rows):
                self._pads.append(PAD_LAST_IDX - (r * self._cols + c))

#     def on_record_changed(self, state):
#         self._is_record_pressed = state

#         # Only STOP recording allowed, as START conflicts with RECORD + PAD
#         if state and self._recording_seq is not None:
#             if self._libseq.isMidiRecord():
#                 self._stop_pattern_record()

#     def on_toggle_play(self):
#         self._state_manager.send_cuia("TOGGLE_PLAY")

#     def on_toggle_play_row(self, row):
#         # If seqman is enabled, ignore row functions
#         if self._seqman_func is not None:
#             return False
#         if row >= self._zynseq.col_in_bank:
#             return True

#         # Get overall status: playing if at least one sequence is playing
#         is_playing = False
#         for col in range(self._zynseq.col_in_bank):
#             seq = col * self._zynseq.col_in_bank + row
#             if seq in self._playing_seqs:
#                 is_playing = True
#                 break

#         stop_states = (zynseq.SEQ_STOPPED, zynseq.SEQ_STOPPING,
#                        zynseq.SEQ_STOPPINGSYNC)
#         play_states = (zynseq.SEQ_RESTARTING,
#                        zynseq.SEQ_STARTING, zynseq.SEQ_PLAYING)
#         for col in range(self._zynseq.col_in_bank):
#             seq = col * self._zynseq.col_in_bank + row
#             # We only play sequences that are not empty
#             if not is_playing and self._libseq.isEmpty(self._zynseq.bank, seq):
#                 continue
#             state = self._libseq.getPlayState(self._zynseq.bank, seq)
#             if is_playing and state in stop_states:
#                 continue
#             if not is_playing and state in play_states:
#                 continue
#             self._libseq.togglePlayState(self._zynseq.bank, seq)

#     def on_track_changed(self, track, state):
#         self._track_btn_pressed = track if state else None

#         # Switch seqman function (if seqman enabled and SHIFT is not pressed)
#         if state and self._seqman_func is not None and not self._is_shifted:
#             btn = BTN_TRACK_1 + track

#             if btn == BTN_LEFT:
#                 return self._change_scene(-1)
#             if btn == BTN_RIGHT:
#                 return self._change_scene(1)

#             func = {
#                 BTN_KNOB_CTRL_VOLUME: FN_COPY_SEQUENCE,
#                 BTN_KNOB_CTRL_PAN: FN_MOVE_SEQUENCE,
#                 BTN_KNOB_CTRL_SEND: FN_CLEAR_SEQUENCE,
#             }.get(btn)
#             if func is not None:
#                 self._seqman_func = func
#                 self._refresh_tool_buttons()

#                 # Function CLEAR does not have source sequence, remove it
#                 if func == FN_CLEAR_SEQUENCE and self._seqman_src_seq is not None:
#                     scene, seq = self._seqman_src_seq
#                     self._seqman_src_seq = None
#                     if scene == self._zynseq.bank:
#                         self._update_pad(seq)

#     def on_shift_changed(self, state):
#         retval = super().on_shift_changed(state)
#         # Update tool buttons only when SHIFT is not pressed
#         if not state:
#             self._refresh_tool_buttons()
#         return retval

#     def enable_seqman(self, state):
#         if state:
#             if self._seqman_func is None:
#                 self._seqman_func = FN_COPY_SEQUENCE
#         else:
#             self._seqman_func = None
#             self._seqman_src_seq = None
#         self.refresh()

    def refresh(self):
#         if not self._libseq.isMidiRecord():
#             self._recording_seq = None

        for c in range(self._cols):
            for r in range(self._rows):
                # Pad outside grid, switch off
                if c >= self._zynseq.col_in_bank or r >= self._zynseq.col_in_bank:
                    self.pad_off(c, r)
                    continue

                seq = c * self._zynseq.col_in_bank + r
                self._update_pad(seq)

#         self._refresh_tool_buttons()

#     def note_on(self, note, velocity, shifted_override=None):
#         self._on_shifted_override(shifted_override)
#         if not self._is_shifted:
#             if note == BTN_STOP_ALL_CLIPS:
#                 self._btn_timer.is_pressed(note, time.time())

#     def note_off(self, note, shifted_override=None):
#         if note == BTN_STOP_ALL_CLIPS:
#             self._btn_timer.is_released(note)

    def pad_press(self, pad):
        # Pad outside grid, discarded
        seq = self.get_sequence_from_pad(pad)
        if seq is None:
            return True

#         if self._seqman_func is not None:
#             self._seqman_handle_pad_press(seq)
#         elif self._track_btn_pressed is not None:
#             self._clear_sequence(self._zynseq.bank, seq)
#         elif self._is_record_pressed:
#             self._start_pattern_record(seq)
#         elif self._recording_seq == seq:
#             self._stop_pattern_record()
#         else:

        self._libseq.togglePlayState(self._zynseq.bank, seq)
        return True

    def pad_off(self, col, row):
        index = col * self._rows + row
        self._leds.led_off(index)

    def update_seq_state(self, bank, seq, state=None, mode=None, group=None):
        col, row = self._zynseq.get_xy_from_pad(seq)
        idx = col * self._rows + row
        if idx >= len(self._pads):
            return
        btn = self._pads[idx]

        is_empty = all(
            self._zynseq.is_pattern_empty(pattern)
            for pattern in self._get_sequence_patterns(bank, seq))
        color = self.GROUP_COLORS[group]

#         # If seqman is enabled, update according to it's function
#         if self._seqman_func is not None:
#             led_mode = LED_BRIGHT_20 if is_empty else LED_BRIGHT_100
#             if (self._seqman_func in (FN_COPY_SEQUENCE, FN_MOVE_SEQUENCE)
#                     and self._seqman_src_seq is not None):
#                 src_scene, src_seq = self._seqman_src_seq
#                 if src_scene == self._zynseq.bank and src_seq == seq:
#                     led_mode = LED_BLINKING_24

#         # Otherwise, update according to sequence state
#         else:

        led_brightness = LED_BRIGHT_100
        led_mode = LED_STILL
        if self._recording_seq == seq:
            led_mode = LED_BLINKING_16
        elif state == zynseq.SEQ_PLAYING:
            led_mode = LED_BLINKING_8
            self._playing_seqs.add(seq)
        elif state in (zynseq.SEQ_STOPPING, zynseq.SEQ_STARTING):
            led_mode = LED_PULSING_2
        else:
            self._playing_seqs.discard(seq)
            if is_empty:
                led_brightness = LED_BRIGHT_20

        self._leds.led_on(btn, color, led_mode, led_brightness)

    def get_sequence_from_pad(self, pad):
        index = self._pads.index(pad)
        col = index // self._rows
        row = index % self._rows

        # Pad outside grid, discarded
        if col >= self._zynseq.col_in_bank or row >= self._zynseq.col_in_bank:
            return None
        return col * self._zynseq.col_in_bank + row

    def _update_pad(self, seq):
        state = self._libseq.getSequenceState(self._zynseq.bank, seq)
        mode = (state >> 8) & 0xFF
        group = (state >> 16) & 0xFF
        state &= 0xFF
        self.update_seq_state(
            bank=self._zynseq.bank, seq=seq, state=state, mode=mode, group=group)

#     def _handle_timed_button(self, btn, ptype):
#         if btn == BTN_STOP_ALL_CLIPS:
#             if ptype == CONST.PT_LONG:
#                 self._stop_all_sounds()
#             else:
#                 in_all_banks = ptype == CONST.PT_BOLD
#                 self._stop_all_seqs(in_all_banks)

#     def _seqman_handle_pad_press(self, seq):
#         if self._seqman_func is None:
#             return

#         # FIXME: if pattern editor is open, and showing affected seq, update it!
#         # FIXME: if Zynpad is open, also update it!
#         # You can use self._current_screen...
#         self._libseq.updateSequenceInfo()
#         seq_is_empty = self._libseq.isEmpty(self._zynseq.bank, seq)
#         if self._seqman_func == FN_CLEAR_SEQUENCE:
#             if not seq_is_empty:
#                 self._clear_sequence(self._zynseq.bank, seq)
#             return

#         # Set selected sequence as source
#         if self._seqman_src_seq is None:
#             if not seq_is_empty:
#                 self._seqman_src_seq = (self._zynseq.bank, seq)
#         else:
#             # Clear source sequence
#             if self._seqman_src_seq == (self._zynseq.bank, seq):
#                 self._seqman_src_seq = None
#             # Copy/Move source to selected sequence (will be overwritten)
#             else:
#                 if self._seqman_func == FN_COPY_SEQUENCE:
#                     self._copy_sequence(
#                         *self._seqman_src_seq, self._zynseq.bank, seq)
#                 elif self._seqman_func == FN_MOVE_SEQUENCE:
#                     self._copy_sequence(
#                         *self._seqman_src_seq, self._zynseq.bank, seq)
#                     self._clear_sequence(*self._seqman_src_seq)
#                     self._seqman_src_seq = None

#         self._update_pad(seq)

#     def _change_scene(self, offset):
#         scene = min(64, max(1, self._zynseq.bank + offset))
#         if scene != self._zynseq.bank:
#             self._zynseq.select_bank(scene)
#             self._state_manager.send_cuia("SCREEN_ZYNPAD")

#     def _refresh_tool_buttons(self):
#         # Switch on seqman active function
#         if self._seqman_func is not None:
#             active = {
#                 FN_COPY_SEQUENCE: BTN_KNOB_CTRL_VOLUME,
#                 FN_MOVE_SEQUENCE: BTN_KNOB_CTRL_PAN,
#                 FN_CLEAR_SEQUENCE: BTN_KNOB_CTRL_SEND,
#             }[self._seqman_func]
#             for idx in range(8):
#                 btn = BTN_TRACK_1 + idx
#                 self._leds.led_state(btn, btn == active)
#             return

#         # If seqman is disabled, show playing status in row launchers
#         playing_rows = {
#             seq % self._zynseq.col_in_bank for seq in self._playing_seqs}
#         for row in range(5):
#             state = row in playing_rows
#             self._leds.led_state(BTN_SOFT_KEY_START + row, state)

#     def _start_pattern_record(self, seq):
#         # Set pad's chain as active
#         channel = self._libseq.getChannel(self._zynseq.bank, seq, 0)
#         chain_id = self._chain_manager.get_chain_id_by_mixer_chan(channel)
#         if chain_id is None:
#             return
#         if self._libseq.isMidiRecord():
#             self._state_manager.send_cuia("TOGGLE_RECORD")
#         self._chain_manager.set_active_chain_by_id(chain_id)

#         # Open Pattern Editor
#         self._show_pattern_editor(seq, skip_arranger=True)

#         # Start playing & recording
#         if self._libseq.getPlayState(self._zynseq.bank, seq) == zynseq.SEQ_STOPPED:
#             self._state_manager.send_cuia("TOGGLE_PLAY")
#         if not self._libseq.isMidiRecord():
#             self._state_manager.send_cuia("TOGGLE_RECORD")

#         self._recording_seq = seq
#         self._update_pad(seq)

#     def _stop_all_seqs(self, in_all_banks=False):
#         bank = 0 if in_all_banks else self._zynseq.bank
#         while True:
#             seq_num = self._libseq.getSequencesInBank(bank)
#             for seq in range(seq_num):
#                 state = self._libseq.getPlayState(bank, seq)
#                 if state not in [zynseq.SEQ_STOPPED, zynseq.SEQ_STOPPING, zynseq.SEQ_STOPPINGSYNC]:
#                     self._libseq.togglePlayState(bank, seq)
#             if not in_all_banks:
#                 break
#             bank += 1
#             if bank >= 64 or self._libseq.getPlayingSequences() == 0:
#                 break

#     def _stop_pattern_record(self):
#         if self._libseq.isMidiRecord():
#             self._state_manager.send_cuia("TOGGLE_RECORD")
#         self._recording_seq = None
#         self.refresh()

#     def _clear_sequence(self, scene, seq, create_empty=True):
#         # Remove all patterns in all tracks
#         seq_len = self._libseq.getSequenceLength(scene, seq)
#         if seq_len != 0:
#             n_tracks = self._libseq.getTracksInSequence(scene, seq)
#             for track in range(n_tracks):
#                 n_patts = self._libseq.getPatternsInTrack(scene, seq, track)
#                 if n_patts == 0:
#                     continue
#                 pos = 0
#                 while pos < seq_len:
#                     pattern = self._libseq.getPatternAt(scene, seq, track, pos)
#                     if pattern != -1:
#                         self._libseq.removePattern(scene, seq, track, pos)
#                         pos += self._libseq.getPatternLength(pattern)
#                     else:
#                         # Arranger's offset step is a quarter note (24 clocks)
#                         pos += 24

#             if n_tracks > 0:
#                 for track in range(n_tracks-1):
#                     self._libseq.removeTrackFromSequence(scene, seq, track)

#         # Add a new empty pattern at the beginning of first track
#         if create_empty:
#             pattern = self._libseq.createPattern()
#             self._libseq.addPattern(scene, seq, 0, 0, pattern)
#             self._libseq.selectPattern(pattern)

#             if self._pattern_template is not None:
#                 self._action_apply_pattern_template(pattern)

#     def _copy_sequence(self, src_scene, src_seq, dst_scene, dst_seq):
#         self._clear_sequence(dst_scene, dst_seq, create_empty=False)

#         # Copy all patterns in all tracks
#         seq_len = self._libseq.getSequenceLength(src_scene, src_seq)
#         if seq_len != 0:
#             n_tracks = self._libseq.getTracksInSequence(src_scene, src_seq)
#             for track in range(n_tracks):
#                 if track >= self._libseq.getTracksInSequence(dst_scene, dst_seq):
#                     self._libseq.addTrackToSequence(dst_scene, dst_seq)
#                 n_patts = self._libseq.getPatternsInTrack(
#                     src_scene, src_seq, track)
#                 if n_patts == 0:
#                     continue
#                 pos = 0
#                 while pos < seq_len:
#                     pattern = self._libseq.getPatternAt(
#                         src_scene, src_seq, track, pos)
#                     if pattern != -1:
#                         new_pattern = self._libseq.createPattern()
#                         self._libseq.copyPattern(pattern, new_pattern)
#                         self._libseq.addPattern(
#                             dst_scene, dst_seq, track, pos, new_pattern)
#                         pos += self._libseq.getPatternLength(pattern)
#                     else:
#                         # Arranger's offset step is a quarter note (24 clocks)
#                         pos += 24

#         # Also copy StepSeq instrument pages
#         self._request_action("stepseq", "sync-sequences",
#             src_scene, src_seq, dst_scene, dst_seq)

#     def _action_set_pattern_template(self, pattern):
#         self._pattern_template = pattern

#     def _action_apply_pattern_template(self, dst_pattern, callback=None):
#         self._libseq.copyPattern(self._pattern_template, dst_pattern)
#         if callback is not None and callable(callback):
#             callback()

