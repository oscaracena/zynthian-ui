#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "Akai MPK mini mk3"
#
# Copyright (C) 2024 Oscar Aceña <oscaracena@gmail.com>
#
#******************************************************************************
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
#******************************************************************************

import time
from zyngine.zynthian_signal_manager import zynsigman
from zyncoder.zyncore import lib_zyncore
from zyngine.ctrldev.zynthian_ctrldev_base import (
    zynthian_ctrldev_zynmixer, ModeHandlerBase, CONST
)

# NOTE: some of these constants are taken from:
# https://github.com/tsmetana/mpk3-settings/blob/master/src/message.h

# Offsets from the beginning of the SYSEX message
OFF_PGM_NAME                = 7

# Message constants
MANUFACTURER_ID             = 0x47
PRODUCT_ID                  = 0x49
DATA_MSG_LEN                = 252
MSG_PAYLOAD_LEN             = 246
MSG_DIRECTION_OUT           = 0x7f
MSG_DIRECTION_IN            = 0x00

# Command values
CMD_WRITE_DATA              = 0x64
CMD_QUERY_DATA              = 0x66
CMD_INCOMING_DATA           = 0x67

# Name (program, knob) string length
NAME_STR_LEN                = 16

# Aftertouch settings
AFTERTOUCH_OFF              = 0x00
AFTERTOUCH_CHANNEL          = 0x01
AFTERTOUCH_POLYPHONIC       = 0x02

# Keybed octave
KEY_OCTAVE_MIN              = 0x00
KEY_OCTAVE_MAX              = 0x07

# Arpeggiator settings
ARP_ON                      = 0x7f
ARP_OFF                     = 0x00
ARP_OCTAVE_MIN              = 0x00
ARP_OCTAVE_MAX              = 0x03
ARP_MODE_UP                 = 0x00
ARP_MODE_DOWN               = 0x01
ARP_MODE_EXCL               = 0x02
ARP_MODE_INCL               = 0x03
ARP_MODE_ORDER              = 0x04
ARP_MODE_RAND               = 0x05
ARP_DIV_1_4                 = 0x00
ARP_DIV_1_4T                = 0x01
ARP_DIV_1_8                 = 0x02
ARP_DIV_1_8T                = 0x03
ARP_DIV_1_16                = 0x04
ARP_DIV_1_16T               = 0x05
ARP_DIV_1_32                = 0x06
ARP_DIV_1_32T               = 0x07
ARP_LATCH_OFF               = 0x00
ARP_LATCH_ON                = 0x01
ARP_SWING_MIN               = 0x00
ARP_SWING_MAX               = 0x19

# Clock settings
CLK_INTERNAL                = 0x00
CLK_EXTERNAL                = 0x01
TEMPO_TAPS_MIN              = 2
TEMPO_TAPS_MAX              = 4
BPM_MIN                     = 60
BPM_MAX                     = 240

# Joystick
JOY_MODE_PITCHBEND          = 0x00
JOY_MODE_SINGLE             = 0x01
JOY_MODE_DUAL               = 0x02

# Knobs
KNOB_MODE_ABS               = 0
KNOB_MODE_REL               = 1

# Device Layout constants
DEFAULT_KEYBED_CH           = 0
DEFAULT_PADS_CH             = 9

# PC numbers for related actions
PROG_MIXPAD_MODE            = 4
PROG_DEVICE_MODE            = 5
PROG_PATTERN_MODE           = 6
PROG_NOTEPAD_MODE           = 7
PROG_OPEN_MIXER             = 0
PROG_OPEN_ZYNPAD            = 1

# Function/State constants
FN_VOLUME                            = 0x01
FN_PAN                               = 0x02
FN_SOLO                              = 0x03
FN_MUTE                              = 0x04
FN_SELECT                            = 0x06
# FN_SCENE                             = 0x07


class SysExSetProgram:
    def __init__(self, program=0, name="Zynthian", channels={}, aftertouch=AFTERTOUCH_OFF,
                 keybed_octave=4, arp={}, ext_clock=False, tempo_taps=3, tempo=90, joy={},
                 pads={}, knobs={}, transpose=0x0c):
        arp_swing = int(arp.get("swing", ARP_SWING_MIN))

        assert 0 <= program <= 8, "Invalid program number: {program} (valid: 0(RAM)-8)."
        assert aftertouch in [AFTERTOUCH_OFF, AFTERTOUCH_CHANNEL, AFTERTOUCH_POLYPHONIC], \
            f"Invalid aftertouch mode: {aftertouch} (valid: 0-2)."
        assert KEY_OCTAVE_MIN <= keybed_octave <= KEY_OCTAVE_MAX, \
            f"Invalid keybed octave: {keybed_octave} (valid: 0-8)."
        assert ARP_SWING_MIN <= arp_swing <= ARP_SWING_MAX, \
            f"Invalid swing value: {arp_swing} (valid: 0-25)."
        assert TEMPO_TAPS_MIN <= tempo_taps <= TEMPO_TAPS_MAX, \
            f"Invalid tempo taps: {tempo_taps} (valid: {TEMPO_TAPS_MIN}-{TEMPO_TAPS_MAX})."
        assert BPM_MIN <= tempo <= BPM_MAX, f"Invalid tempo: {tempo} (valid: 60-240)."
        for c in channels.values():
            assert 0 <= c <= 15, f"Invalid channel number: {c} (valid: 0-15)."
        for field in ["note", "pc", "cc"]:
            assert field in pads, f"Invalid pads definition, missing '{field}' list."
            assert len(pads[field]) == 16, f"Invalid pads definition, len('{field}') != 16."
            for v in pads[field]:
                assert 0 <= v <= 127, f"Invalid pads definition, invalid value: {v}."
        for field in ["mode", "cc", "min", "max", "name"]:
            assert field in knobs, f"Invalid knobs definition, missing '{field}' list."
            assert len(knobs[field]) == 8, f"Invalid knobs definition, len('{field}') != 8."

        self.data = [
            MANUFACTURER_ID, MSG_DIRECTION_OUT, PRODUCT_ID, CMD_WRITE_DATA,
            (MSG_PAYLOAD_LEN >> 7) & 127, MSG_PAYLOAD_LEN & 127, program,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            channels.get("pads", DEFAULT_PADS_CH),
            aftertouch,
            channels.get("keybed", DEFAULT_KEYBED_CH),
            keybed_octave,
            ARP_ON if arp.get("on") else ARP_OFF,
            arp.get("mode", ARP_MODE_UP),
            arp.get("division", ARP_DIV_1_4),
            CLK_EXTERNAL if ext_clock else CLK_INTERNAL,
            ARP_LATCH_ON if arp.get("latch", False) else ARP_LATCH_OFF,
            arp_swing,
            tempo_taps, (tempo >> 7) & 127, tempo & 127,
            arp.get("octave", ARP_OCTAVE_MIN),
            joy.get("x-mode", JOY_MODE_PITCHBEND), joy.get("x-neg-ch", 1), joy.get("x-pos-ch", 2),
            joy.get("y-mode", JOY_MODE_DUAL), joy.get("y-neg-ch", 1), joy.get("y-pos-ch", 2),
        ]

        for pidx in range(16):
            self.data.append(pads["note"][pidx])
            self.data.append(pads["pc"][pidx])
            self.data.append(pads["cc"][pidx])

        for kidx in range(8):
            self.data.append(knobs["mode"][kidx])
            self.data.append(knobs["cc"][kidx])
            self.data.append(knobs["min"][kidx])
            self.data.append(knobs["max"][kidx])
            padname = list(bytes(16))
            padname[:len(knobs["name"][kidx])] = [ord(c) for c in knobs["name"][kidx]]
            self.data += padname

        self.data.append(transpose)

        padname = list(bytes(16))
        padname[:len(name)] = [ord(c) for c in name]
        self.data[OFF_PGM_NAME:OFF_PGM_NAME + NAME_STR_LEN] = padname[:NAME_STR_LEN]

        assert len(self.data) == DATA_MSG_LEN, \
            f"ERROR, invalid message size!! ({len(self.data)} != {DATA_MSG_LEN})"

    def __repr__(self):
        return " ".join(f"{b:02X}" for b in self.data)


# --------------------------------------------------------------------------
#  Class to marshall/un-marshall saved state of those handlers that need it
# --------------------------------------------------------------------------
class SavedState:
    def __init__(self):
        self.is_empty = True
        self.pads_channel = None
        self.pad_notes = []

    def load(self, state: dict):
        self.pad_notes = state.get("pad_notes", list(range(16)))
        self.pads_channel = state.get("pads_channel", DEFAULT_PADS_CH)
        self.is_empty = False

    def save(self):
        return {
            "pad_notes": self.pad_notes,
            "pads_channel": self.pads_channel,
        }


# --------------------------------------------------------------------------
# 'Akai MPK mini mk3' device controller class
# --------------------------------------------------------------------------
class zynthian_ctrldev_akai_mpk_mini_mk3(zynthian_ctrldev_zynmixer):

    dev_ids = ["MPK mini 3 IN 1"]
    unroute_from_chains = False

    def __init__(self, state_manager, idev_in, idev_out):
        self._saved_state = SavedState()
        self._mixpad_handler = MixPadHandler(state_manager, idev_out, self._saved_state)
        self._device_handler = DeviceHandler(state_manager, idev_out, self._saved_state)
        self._pattern_handler = PatternHandler(state_manager, idev_out, self._saved_state)
        self._notepad_handler = NotePadHandler(state_manager, idev_out, self._saved_state)
        self._current_handler = self._mixpad_handler

        self._signals = [
            (zynsigman.S_GUI,
                zynsigman.SS_GUI_SHOW_SCREEN,
                self._on_gui_show_screen),
        ]
        super().__init__(state_manager, idev_in, idev_out)

    def init(self):
        super().init()
        for signal, subsignal, callback in self._signals:
            zynsigman.register(signal, subsignal, callback)

        #!FIXME: just for developing, remove when set_state/get_state hooks are ready!
        from pathlib import Path
        import json
        saved = Path("/root/mpk-mini-mk3-save.json")
        if saved.exists():
            self.set_state(json.load(saved.open()))

        self._current_handler.set_active(True)

    def end(self):
        for signal, subsignal, callback in self._signals:
            zynsigman.unregister(signal, subsignal, callback)
        super().end()

        #!FIXME: just for developing, remove when set_state/get_state hooks are ready!
        from pathlib import Path
        import json
        with Path("/root/mpk-mini-mk3-save.json").open("w") as dst:
            json.dump(self.get_state(), dst, indent=4)

    def get_state(self):
        return self._saved_state.save()

    def set_state(self, state):
        self._saved_state.load(state)

    def midi_event(self, ev: int):
        # print(" ".join(f"{b:02X}" for b in ev.to_bytes(3, "big")))
        evtype = (ev & 0xF00000) >> 20
        channel = (ev & 0x0F0000) >> 16

        if evtype == CONST.MIDI_PC:
            program = (ev >> 8) & 0x7F
            if program == PROG_MIXPAD_MODE:
                self._change_handler(self._mixpad_handler)
            elif program == PROG_DEVICE_MODE:
                self._change_handler(self._device_handler)
            elif program == PROG_PATTERN_MODE:
                self._change_handler(self._pattern_handler)
            elif program == PROG_NOTEPAD_MODE:
                self._change_handler(self._notepad_handler)
            elif program == PROG_OPEN_MIXER:
                self.state_manager.send_cuia("SCREEN_AUDIO_MIXER")
            elif program == PROG_OPEN_ZYNPAD:
                self.state_manager.send_cuia("SCREEN_ZYNPAD")

        elif evtype == CONST.MIDI_NOTE_ON:
            note = (ev >> 8) & 0x7F
            velocity = ev & 0x7F
            self._current_handler.note_on(note, channel, velocity)

        elif evtype == CONST.MIDI_NOTE_OFF:
            note = (ev >> 8) & 0x7F
            self._current_handler.note_off(note, channel)

        elif evtype == CONST.MIDI_CC:
            ccnum = (ev >> 8) & 0x7F
            ccval = ev & 0x7F
            self._current_handler.cc_change(ccnum, ccval)

    def _change_handler(self, new_handler):
        if new_handler == self._current_handler:
            return
        self._current_handler.set_active(False)
        self._current_handler = new_handler
        self._current_handler.set_active(True)

    def _on_gui_show_screen(self, screen):
        print(f"GUI show screen: {screen}")
        for handler in [self._device_handler, self._mixpad_handler, self._pattern_handler]:
            handler.on_screen_change(screen)


# --------------------------------------------------------------------------
# Audio mixer and (a sort of) Zynpad handler (MixPad mode)
# --------------------------------------------------------------------------
class MixPadHandler(ModeHandlerBase):

    CC_PAD_START_A   = 8
    CC_PAD_START_B   = 16
    CC_PAD_END_A     = 15
    CC_PAD_END_B     = 23
    CC_KNOBS_START   = 24

    CC_PAD_VOLUME_A  = 8
    CC_PAD_VOLUME_B  = 16
    CC_PAD_PAN_A     = 9
    CC_PAD_PAN_B     = 17
    CC_PAD_MUTE_A    = 10
    CC_PAD_MUTE_B    = 18
    CC_PAD_SOLO_A    = 11
    CC_PAD_SOLO_B    = 19

    def __init__(self, state_manager, idev_out, saved_state: SavedState):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._saved_state = saved_state
        self._knobs_function = FN_VOLUME
        self._pads_action = None
        self._pressed_pads = {}
        self._chains_bank = 0

    def set_active(self, active):
        super().set_active(active)
        if active:
            self._upload_mode_layout_to_device()

    def cc_change(self, ccnum, ccval):
        print(f"MIXPAD cc change {ccnum}, {ccval}")
        # Is a PAD press
        if self.CC_PAD_START_A <= ccnum <= self.CC_PAD_END_B:

            # This will happend when FULL LEVEL is on (or with a very strong press)
            if ccval == 127:
                if self._current_screen in ["audio_mixer", "zynpad"]:
                    self._pads_action = FN_SELECT
                    return self._change_chain(ccnum, ccval)
            elif ccval == 0:
                if self._pads_action != None:
                    self._pads_action = None
                    return
                self._chains_bank = 0
            elif self.CC_PAD_START_B <= ccnum <= self.CC_PAD_END_B:
                self._chains_bank = 1

            if self._current_screen in ["audio_mixer", "zynpad"]:
                if ccnum in (self.CC_PAD_VOLUME_A, self.CC_PAD_VOLUME_B):
                    self._knobs_function = FN_VOLUME
                elif ccnum in (self.CC_PAD_PAN_A, self.CC_PAD_PAN_B):
                    self._knobs_function = FN_PAN
                elif ccnum in (self.CC_PAD_MUTE_A, self.CC_PAD_MUTE_B):
                    self._knobs_function = FN_MUTE
                elif ccnum in (self.CC_PAD_SOLO_A, self.CC_PAD_SOLO_B):
                    self._knobs_function = FN_SOLO

        # Is a Knob rotation
        else:
            if self._current_screen in ["audio_mixer", "zynpad"]:
                if self._knobs_function == FN_VOLUME:
                    self._update_volume(ccnum, ccval)
                elif self._knobs_function == FN_PAN:
                    self._update_pan(ccnum, ccval)
                elif self._knobs_function == FN_MUTE:
                    self._update_mute(ccnum, ccval)
                elif self._knobs_function == FN_SOLO:
                    self._update_solo(ccnum, ccval)

    def _upload_mode_layout_to_device(self):
        cmd = SysExSetProgram(
            name = "Zynthian MIXPAD",
            channels = {
                "pads":  self._saved_state.pads_channel,
                "keybed": DEFAULT_KEYBED_CH,
            },
            pads = {
                "note": self._saved_state.pad_notes,
                "pc": range(16),
                "cc": range(self.CC_PAD_START_A, self.CC_PAD_END_B + 1),
            },
            knobs = {
                "mode": [KNOB_MODE_REL] * 8,
                "cc": range(self.CC_KNOBS_START, self.CC_KNOBS_START + 8),
                "min": [0] * 8,
                "max": [127] * 8,
                "name": [f"Chain {i}/{i+8}" for i in range(1, 9)],
            }
        )

        msg = bytes.fromhex("F0 {} F7".format(cmd))
        lib_zyncore.dev_send_midi_event(self._idev_out, msg, len(msg))
        print("UPLOAD layout: Zynthian MIXPAD")

    # FIXME: candidate to DRY
    def _change_chain(self, ccnum, ccval):
        # CCNUM is a PAD, but we expect a KNOB; offset it
        ccnum = ccnum + self.CC_KNOBS_START - self.CC_PAD_START_A
        return self._update_chain("select", ccnum, ccval)

    # FIXME: candidate to DRY
    def _update_volume(self, ccnum, ccval):
        return self._update_chain("level", ccnum, ccval, 0, 100)

    # FIXME: candidate to DRY
    def _update_pan(self, ccnum, ccval):
        return self._update_chain("balance", ccnum, ccval, -100, 100)

    # FIXME: candidate to DRY
    def _update_mute(self, ccnum, ccval):
        return self._update_chain("mute", ccnum, ccval)

    # FIXME: candidate to DRY
    def _update_solo(self, ccnum, ccval):
        return self._update_chain("solo", ccnum, ccval)

    # FIXME: candidate to DRY
    def _update_chain(self, type, ccnum, ccval, minv=None, maxv=None):
        index = ccnum - self.CC_KNOBS_START + self._chains_bank * 8
        chain = self._chain_manager.get_chain_by_index(index)
        if chain is None or chain.chain_id == 0:
            return False
        mixer_chan = chain.mixer_chan

        if type == "level":
            print(f" -- level chain {chain.chain_id}")
            value = self._zynmixer.get_level(mixer_chan)
            set_value = self._zynmixer.set_level
        elif type == "balance":
            print(f" -- pan chain {chain.chain_id}")
            value = self._zynmixer.get_balance(mixer_chan)
            set_value = self._zynmixer.set_balance
        elif type == "mute":
            print(f" -- mute chain {chain.chain_id}")
            value = ccval < 64
            set_value = lambda c, v: self._zynmixer.set_mute(c, v, True)
        elif type == "solo":
            print(f" -- solo chain {chain.chain_id}")
            value = ccval < 64
            set_value = lambda c, v: self._zynmixer.set_solo(c, v, True)
        elif type == "select":
            print(f" -- select chain {chain.chain_id}")
            return self._chain_manager.set_active_chain_by_id(chain.chain_id)
        else:
            return False

        # NOTE: knobs are encoders, not pots (so ccval is relative)
        if minv is not None and maxv is not None:
            value *= 100
            value += ccval if ccval < 64 else ccval - 128
            value = max(minv, min(value, maxv))
            value /= 100

        set_value(mixer_chan, value)
        return True


# --------------------------------------------------------------------------
# Handle GUI (Device mode)
# --------------------------------------------------------------------------
class DeviceHandler(ModeHandlerBase):
    def __init__(self, state_manager, idev_out, saved_state: SavedState):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._saved_state = saved_state

    def set_active(self, active):
        super().set_active(active)
        if active:
            self._upload_mode_layout_to_device()

    def _upload_mode_layout_to_device(self):
        print("UPLOAD layout: Zynthian DEVICE")
        cmd = SysExSetProgram(
            name = "Zynthian DEVICE",
            channels = {
                "pads":  self._saved_state.pads_channel,
            },
            pads = {
                "note": self._saved_state.pad_notes,
                "pc": range(16),
                "cc": range(8, 24),
            },
            knobs = {
                "mode": [KNOB_MODE_REL] * 8,
                "cc": range(24, 32),
                "min": [0] * 8,
                "max": [127] * 8,
                "name": [f"K{i}" for i in range(1, 9)],
            }
        )

        msg = bytes.fromhex("F0 {} F7".format(cmd))
        lib_zyncore.dev_send_midi_event(self._idev_out, msg, len(msg))


# --------------------------------------------------------------------------
# Handle pattern editor (Pattern mode)
# --------------------------------------------------------------------------
class PatternHandler(ModeHandlerBase):
    def __init__(self, state_manager, idev_out, saved_state: SavedState):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._saved_state = saved_state

    def set_active(self, active):
        super().set_active(active)
        if active:
            self._upload_mode_layout_to_device()

    def _upload_mode_layout_to_device(self):
        print("UPLOAD layout: Zynthian PATTERN")
        cmd = SysExSetProgram(
            name = "Zynthian PATTERN",
            channels = {
                "pads":  self._saved_state.pads_channel,
            },
            pads = {
                "note": self._saved_state.pad_notes,
                "pc": range(16),
                "cc": range(8, 24),
            },
            knobs = {
                "mode": [KNOB_MODE_REL] * 8,
                "cc": range(24, 32),
                "min": [0] * 8,
                "max": [127] * 8,
                "name": [
                    "Duration", "Velocity", "Stutter Count", "Stutter Duration",
                    "Cursor H", "Cursor V", "K7", "K8",
                ],
            }
        )

        msg = bytes.fromhex("F0 {} F7".format(cmd))
        lib_zyncore.dev_send_midi_event(self._idev_out, msg, len(msg))


# --------------------------------------------------------------------------
# Handle an editor of note pads (NotePad mode)
# --------------------------------------------------------------------------
class NotePadHandler(ModeHandlerBase):

    CC_KNOB_CHANNEL          = 0
    CC_PAD_CHANGE_CHANNEL    = 8

    def __init__(self, state_manager, idev_out, saved_state: SavedState):
        super().__init__(state_manager)
        self._saved_state = saved_state
        if saved_state.is_empty:
            saved_state.pads_channel = DEFAULT_PADS_CH
            saved_state.pad_notes = list(range(16))
            saved_state.is_empty = False

        self._idev_out = idev_out
        self._channel_to_commit = None
        self._notes_to_commit = {}
        self._pressed_pads = {}

    def set_active(self, active):
        super().set_active(active)
        if active:
            self._channel_to_commit = None
            self._notes_to_commit.clear()
            self._upload_mode_layout_to_device()

    def note_on(self, note, channel, velocity):
        print(f"NOTEPAD note on, note: {note}, ch: {channel}, vel: {velocity}")
        if channel == self._saved_state.pads_channel:
            try:
                pad = self._saved_state.pad_notes.index(note)
                self._pressed_pads[pad] = time.time()
                print(f" -- add pressed pad: {pad} ({self._pressed_pads})")
            except ValueError:
                print(f" -- note is not a notepad")
                pass

        # NOTE: Keybed channel and pad channel may be the same
        if channel == DEFAULT_KEYBED_CH:
            if len(self._pressed_pads) == 1:
                pad = next(iter(self._pressed_pads))
                if note not in self._saved_state.pad_notes:
                    print(f" -- ASIGN note {note} to pad {pad}")
                    self._notes_to_commit[pad] = note

    def note_off(self, note, channel):
        print(f"NOTEPAD note off, note: {note}, ch: {channel}")
        if channel == self._saved_state.pads_channel:
            try:
                pad = self._saved_state.pad_notes.index(note)
                self._pressed_pads.pop(pad, None)
                print(f" -- remove pressed pad: {pad} ({self._pressed_pads})")
            except ValueError:
                print(f" -- note not in pressed pads")
                pass

        if len(self._pressed_pads) == 0:
            if self._notes_to_commit:
                while self._notes_to_commit:
                    pad, note = self._notes_to_commit.popitem()
                    self._saved_state.pad_notes[pad] = note
                self._upload_mode_layout_to_device()

    def cc_change(self, ccnum, ccval):
        print(f"NOTEPAD cc change {ccnum}, {ccval}")
        if ccnum == self.CC_PAD_CHANGE_CHANNEL:
            if ccval > 0:
                self._pressed_pads[ccnum - 8] = time.time()
            else:
                if self._channel_to_commit is not None:
                    self._saved_state.pads_channel = self._channel_to_commit
                    self._channel_to_commit = None
                    self._upload_mode_layout_to_device()

        elif ccnum == self.CC_KNOB_CHANNEL:
            if self._pressed_pads and (self.CC_PAD_CHANGE_CHANNEL - 8) in self._pressed_pads:
                self._channel_to_commit = ccval - 1

    def _upload_mode_layout_to_device(self):
        print("UPLOAD layout: Zynthian NOTEPAD")
        cmd = SysExSetProgram(
            name = "Zynthian NOTEPAD",
            channels = {
                "pads":  self._saved_state.pads_channel,
                "keybed": DEFAULT_KEYBED_CH,
            },
            pads = {
                "note": self._saved_state.pad_notes,
                "pc": range(16),
                "cc": range(8, 24),
            },
            knobs = {
                "mode": [KNOB_MODE_ABS] + [KNOB_MODE_REL] * 7,
                "cc": range(24, 32),
                "min": [1] + [0] * 7,
                "max": [16] + [127] * 7,
                "name": ["Channel"] + [f"K{i}" for i in range(2, 9)],
            }
        )

        msg = bytes.fromhex("F0 {} F7".format(cmd))
        lib_zyncore.dev_send_midi_event(self._idev_out, msg, len(msg))
