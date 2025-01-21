
#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "Nakama", a Progressive Web Application,
# to be used with a RTP-MIDI device.
#
# Copyright (C) 2024,2025 Oscar Aceña <oscaracena@gmail.com>
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

import logging
from hexdump import hexdump

from zyncoder.zyncore import lib_zyncore
from zynlibs.zynseq import zynseq

from .zynthian_ctrldev_base import zynthian_ctrldev_zynpad
from .zynthian_ctrldev_base_extended import FeedbackLEDsBase, CONST
from .zynthian_ctrldev_base_ui import ModeHandlerBase


# Define buttons for the matrix pad (16 x 8)
BTN_PAD_START     = 0x00
BTN_PAD_END       = 0x7F

# Define also some useful constants
LED_BRIGHT_10     = 0x00
LED_BRIGHT_25     = 0x01
LED_BRIGHT_50     = 0x02
LED_BRIGHT_65     = 0x03
LED_BRIGHT_75     = 0x04
LED_BRIGHT_90     = 0x05
LED_BRIGHT_100    = 0x06
LED_PULSING_16    = 0x07
LED_PULSING_8     = 0x08
LED_PULSING_4     = 0x09
LED_PULSING_2     = 0x0A
LED_BLINKING_24   = 0x0B
LED_BLINKING_16   = 0x0C
LED_BLINKING_8    = 0x0D
LED_BLINKING_4    = 0x0E
LED_BLINKING_2    = 0x0F

SYSEX_REQUEST     = 0x00
SYSEX_RESPONSE    = 0x01
SYSEX_CHECK_DEV   = 0x00
SYSEX_DEV_ACK     = 0x01
SYSEX_REFRESH     = 0x02
SYSEX_DEV_ID      = 0x7D

MIDI_CC_PADS_CHAN = 0x00


# --------------------------------------------------------------------------
# Feedback LEDs controller
# --------------------------------------------------------------------------
class FeedbackLEDs(FeedbackLEDsBase):
    PAD_BUTTONS = [btn for btn in range(BTN_PAD_START, BTN_PAD_END + 1)]


# --------------------------------------------------------------------------
# 'Nakama' device controller class
# --------------------------------------------------------------------------
class zynthian_ctrldev_nakama(zynthian_ctrldev_zynpad):

    dev_ids = ["RTP MIDI"]

    def __init__(self, state_manager, idev_in, idev_out=None):
        self._leds = FeedbackLEDs(idev_out)
        # self._device_handler = DeviceHandler(state_manager, self._leds)
        # self._mixer_handler = MixerHandler(state_manager, self._leds)
        self._padmatrix_handler = PadMatrixHandler(state_manager, self._leds)
        # self._stepseq_handler = StepSeqHandler(state_manager, self._leds, idev_in)
        self._current_handler = self._padmatrix_handler
        # self._is_shifted = False

        # self._signals = [
        #     (zynsigman.S_GUI,
        #         zynsigman.SS_GUI_SHOW_SCREEN,
        #         self._on_gui_show_screen),

        #     (zynsigman.S_AUDIO_PLAYER,
        #         zynthian_engine_audioplayer.SS_AUDIO_PLAYER_STATE,
        #         lambda handle, state:
        #             self._on_media_change_state(state, f"audio-{handle}", "player")),

        #     (zynsigman.S_AUDIO_RECORDER,
        #         state_manager.audio_recorder.SS_AUDIO_RECORDER_STATE,
        #         partial(self._on_media_change_state, media="audio", kind="recorder")),

        #     (zynsigman.S_STATE_MAN,
        #         state_manager.SS_MIDI_PLAYER_STATE,
        #         partial(self._on_media_change_state, media="midi", kind="player")),

        #     (zynsigman.S_STATE_MAN,
        #         state_manager.SS_MIDI_RECORDER_STATE,
        #         partial(self._on_media_change_state, media="midi", kind="recorder")),
        # ]

        # NOTE: init will call refresh(), so _current_hanlder must be ready!
        super().__init__(state_manager, idev_in, idev_out)

    @classmethod
    def get_autoload_flag(cls):
        return True

    # def init(self):
    #     super().init()
    #     for signal, subsignal, callback in self._signals:
    #         zynsigman.register(signal, subsignal, callback)

    # def end(self):
    #     for signal, subsignal, callback in self._signals:
    #         zynsigman.unregister(signal, subsignal, callback)
    #     super().end()

    def refresh(self):
        self._current_handler.refresh()

    def midi_event(self, ev):
        hexdump(ev)

        if self._on_midi_event(ev):
            pass
        #     while True:
        #         action = self._current_handler.pop_action_request()
        #         if not action:
        #             return

        #         # NOTE: Add other receivers as needed
        #         receiver, action, args, kwargs = action
        #         if receiver == "stepseq":
        #             self._stepseq_handler.run_action(action, args, kwargs)

    def _on_midi_event(self, ev):
        evtype = ev[0] & 0xF0
        channel = ev[0] & 0x0F

        if evtype == CONST.MIDI_NOTE_ON:
            pass
    #         note = ev[1] & 0x7F
    #         vel = ev[2] & 0x7F

    #         if note == BTN_SHIFT:
    #             return self._on_shift_changed(True)

    #         if self._is_shifted:
    #             old_handler = self._current_handler
    #             # Change global mode here
    #             if note == BTN_KNOB_CTRL_DEVICE:
    #                 self._current_handler = self._device_handler
    #             elif note in [BTN_KNOB_CTRL_PAN, BTN_KNOB_CTRL_VOLUME]:
    #                 self._current_handler = self._mixer_handler
    #                 self._padmatrix_handler.refresh()
    #             elif note == BTN_KNOB_CTRL_SEND:
    #                 self._current_handler = self._stepseq_handler

    #             if old_handler != self._current_handler:
    #                 old_handler.set_active(False)
    #                 self._current_handler.set_active(True)

    #             # Change sub-modes here
    #             if self._current_handler == self._mixer_handler:
    #                 if note == BTN_SOFT_KEY_CLIP_STOP:
    #                     self._padmatrix_handler.enable_seqman(True)
    #                 elif BTN_SOFT_KEY_SOLO <= note <= BTN_SOFT_KEY_END:
    #                     self._padmatrix_handler.enable_seqman(False)

    #         # Padmatrix related events
    #         if self._current_handler == self._mixer_handler:
    #             if BTN_PAD_START <= note <= BTN_PAD_END:

    #                 # Launch StepSeq directly from SHIFT + PAD
    #                 if self._is_shifted:
    #                     seq = self._padmatrix_handler.get_sequence_from_pad(
    #                         note)
    #                     if seq is None:
    #                         return False
    #                     if self._current_handler != self._stepseq_handler:
    #                         self._current_handler.set_active(False)
    #                     self._current_handler = self._stepseq_handler
    #                     self._current_handler.set_sequence(seq)
    #                     self._current_handler.set_active(True)
    #                     self._current_handler.refresh(
    #                         shifted_override=self._is_shifted)
    #                     return True

    #                 return self._padmatrix_handler.pad_press(note)

    #             # FIXME: move these events to padmatrix handler itself
    #             elif note == BTN_RECORD and not self._is_shifted:
    #                 return self._padmatrix_handler.on_record_changed(True)
    #             elif note == BTN_PLAY:
    #                 if not self._is_shifted:
    #                     return self._padmatrix_handler.on_toggle_play()
    #                 self._padmatrix_handler.note_on(
    #                     note, vel, self._is_shifted)
    #             elif (BTN_SOFT_KEY_START <= note <= BTN_SOFT_KEY_END
    #                   and not self._is_shifted):
    #                 row = note - BTN_SOFT_KEY_START
    #                 return self._padmatrix_handler.on_toggle_play_row(row)
    #             elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
    #                 track = note - BTN_TRACK_1
    #                 self._padmatrix_handler.on_track_changed(track, True)
    #                 self._current_handler.note_on(note, vel, self._is_shifted)
    #                 self._padmatrix_handler.refresh()
    #                 return True
    #             elif note == BTN_STOP_ALL_CLIPS:
    #                 self._padmatrix_handler.note_on(
    #                     note, vel, self._is_shifted)

    #         return self._current_handler.note_on(note, vel, self._is_shifted)

    #     elif evtype == EV_NOTE_OFF:
    #         note = ev[1] & 0x7F

    #         if note == BTN_SHIFT:
    #             return self._on_shift_changed(False)

    #         # Padmatrix related events
    #         if self._current_handler == self._mixer_handler:
    #             if note == BTN_RECORD:
    #                 return self._padmatrix_handler.on_record_changed(False)
    #             elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
    #                 track = note - BTN_TRACK_1
    #                 self._padmatrix_handler.on_track_changed(track, False)
    #             elif note == BTN_STOP_ALL_CLIPS:
    #                 self._padmatrix_handler.note_off(note, self._is_shifted)

    #         return self._current_handler.note_off(note, self._is_shifted)

        elif evtype == CONST.MIDI_CC:
            ccnum = ev[1] & 0x7F
            if self._current_handler == self._padmatrix_handler:
                if channel == MIDI_CC_PADS_CHAN:
                    return self._padmatrix_handler.pad_press(ccnum)

            ccval = ev[2] & 0x7F
            return self._current_handler.cc_change(ccnum, ccval)

        elif ev[0] == CONST.MIDI_SYSEX_START:
            dev_id = ev[1] & 0x7F
            if dev_id != SYSEX_DEV_ID:
                return

            if len(ev) != 5:
                logging.warning(f"invalid SysEx received => {ev}")
                return

            ev_type = ev[2]
            ev_arg = ev[3]
            if ev_type == SYSEX_REQUEST:
                if ev_arg == SYSEX_CHECK_DEV:
                    self._send_sysex(SYSEX_DEV_ID, SYSEX_RESPONSE, SYSEX_DEV_ACK)
                elif ev_arg == SYSEX_REFRESH:
                    self.refresh()

    def light_off(self):
        self._leds.all_off()

    # def update_mixer_strip(self, chan, symbol, value):
    #     if self._current_handler == self._mixer_handler:
    #         self._current_handler.update_strip(chan, symbol, value)

    # def update_mixer_active_chain(self, active_chain):
    #     refresh = self._current_handler == self._mixer_handler
    #     self._mixer_handler.set_active_chain(active_chain, refresh)

    def update_seq_state(self, *args, **kwargs):
        if self._current_handler == self._padmatrix_handler:
            self._current_handler.update_seq_state(*args, **kwargs)
    #     elif self._current_handler == self._stepseq_handler:
    #         self._current_handler.update_seq_state(*args, **kwargs)

    # def get_state(self):
    #     state = {}
    #     state.update(self._stepseq_handler.get_state())
    #     return state

    # def set_state(self, state):
    #     self._stepseq_handler.set_state(state)

    # def _on_shift_changed(self, state):
    #     self._is_shifted = state
    #     self._current_handler.on_shift_changed(state)
    #     if self._current_handler == self._mixer_handler:
    #         self._padmatrix_handler.on_shift_changed(state)
    #     return True

    # def _on_gui_show_screen(self, screen):
    #     self._device_handler.on_screen_change(screen)
    #     self._padmatrix_handler.on_screen_change(screen)
    #     self._stepseq_handler.on_screen_change(screen)
    #     if self._current_handler == self._device_handler:
    #         self._current_handler.refresh()

    # def _on_media_change_state(self, state, media, kind):
    #     self._current_handler.on_media_change(media, kind, state)
    #     if self._current_handler == self._device_handler:
    #         self._current_handler.refresh()

    def _send_sysex(self, *payload):
        if not self.idev_out:
            logging.warning("send SysEx but idev is not available! Ignoring.")
            return

        msg = bytes([CONST.MIDI_SYSEX_START, *payload, CONST.MIDI_SYSEX_END])
        lib_zyncore.dev_send_midi_event(self.idev_out, msg, len(msg))


# --------------------------------------------------------------------------
#  Handle pad matrix for Zynseq
# --------------------------------------------------------------------------
class PadMatrixHandler(ModeHandlerBase):

    GROUP_COLORS = [
        0x01,   # #662426, Red Granate
        0x02,   # #3c6964, Blue Aguamarine
        0x03,   # #4d6817, Green Pistacho
        0x04,   # #664980, Lila
        0x05,   # #4C709A, Mid Blue
        0x06,   # #4C94CC, Sky Blue
        0x07,   # #006000, Dark Green
        0x08,   # #B7AA5E, Ocre
        0x09,   # #996633, Maroon
        0x0a,   # #746360, Dark Grey
        0x0b,   # #D07272, Pink
        0x0c,   # #000060, Blue sat.
        0x0d,   # #048C8C, Turquesa
        0x0e,   # #f46815, Orange
        0x0f,   # #BF9C7C, Light Maroon
        0x10,   # #56A556, Light Green

        0x11,   # #FC6CB4, 7 medium
        0x12,   # #CC8464, 8 medium
        0x13,   # #4C94CC, 9 medium
        0x14,   # #B454CC, 10 medium
        0x15,   # #B08080, 11 medium
        0x16,   # #0404FC, 12 light
        0x17,   # #9EBDAC, 13 light
        0x18,   # #FF13FC, 14 light
        0x19,   # #3080C0, 15 light
        0x1a,   # #9C7CEC, 16 light

        0x00,   # #000000, Black
        0x7F,   # #FFFFFF, White
    ]

    def __init__(self, state_manager, leds: FeedbackLEDs):
        super().__init__(state_manager)
        self._leds = leds
        self._libseq = self._zynseq.libseq
        self._cols = 16
        self._rows = 8
#         self._is_record_pressed = False
#         self._track_btn_pressed = None
        self._playing_seqs = set()
#         self._btn_timer = ButtonTimer(self._handle_timed_button)

        # Seqman sub-mode
        self._seqman_func = None
#         self._seqman_src_seq = None

        # FIXME: this value should be updated by a signal, to be in sync with UI state
        self._recording_seq = None

        # Sort pads in the same order that libseq uses
        self._pads = []
        for c in range(self._cols):
            for r in range(self._rows):
                self._pads.append(c * self._rows + r)

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
                self._update_pad(seq, False)

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
            return

        if self._seqman_func is not None:
            pass
#             self._seqman_handle_pad_press(seq)
#         elif self._track_btn_pressed is not None:
#             self._clear_sequence(self._zynseq.bank, seq)
#         elif self._is_record_pressed:
#             self._start_pattern_record(seq)
#         elif self._recording_seq == seq:
#             self._stop_pattern_record()
        else:
            self._libseq.togglePlayState(self._zynseq.bank, seq)

    def pad_off(self, col, row):
        index = col * self._rows + row
        self._leds.led_off(self._pads[index])

    def update_seq_state(self, bank, seq, state=None, mode=None, group=None, refresh=True):
        col, row = self._zynseq.get_xy_from_pad(seq)
        idx = col * self._rows + row
        if idx >= len(self._pads):
            return
        btn = self._pads[idx]

        is_empty = all(
            self._zynseq.is_pattern_empty(pattern)
            for pattern in self._get_sequence_patterns(bank, seq))
        color = self.GROUP_COLORS[group]

        # If seqman is enabled, update according to it's function
        if self._seqman_func is not None:
            pass
#             led_mode = LED_BRIGHT_25 if is_empty else LED_BRIGHT_100
#             if (self._seqman_func in (FN_COPY_SEQUENCE, FN_MOVE_SEQUENCE)
#                     and self._seqman_src_seq is not None):
#                 src_scene, src_seq = self._seqman_src_seq
#                 if src_scene == self._zynseq.bank and src_seq == seq:
#                     led_mode = LED_BLINKING_24

        # Otherwise, update according to sequence state
        else:
            if self._recording_seq == seq:
                led_mode = LED_BLINKING_16
            elif state == zynseq.SEQ_PLAYING:
                led_mode = LED_BLINKING_8
                self._playing_seqs.add(seq)
            elif state in (zynseq.SEQ_STOPPING, zynseq.SEQ_STARTING):
                led_mode = LED_PULSING_2
            else:
                led_mode = LED_BRIGHT_25 if is_empty else LED_BRIGHT_100
                self._playing_seqs.discard(seq)

        self._leds.led_on(btn, color, led_mode)

#         if refresh:
#             self._refresh_tool_buttons()

    def get_sequence_from_pad(self, pad):
        index = self._pads.index(pad)
        col = index // self._rows
        row = index % self._rows

        # Pad outside grid, discarded
        if col >= self._zynseq.col_in_bank or row >= self._zynseq.col_in_bank:
            return None
        return col * self._zynseq.col_in_bank + row

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

    def _update_pad(self, seq, refresh=True):
        state = self._libseq.getSequenceState(self._zynseq.bank, seq)
        mode = (state >> 8) & 0xFF
        group = (state >> 16) & 0xFF
        state &= 0xFF
        self.update_seq_state(
            bank=self._zynseq.bank, seq=seq, state=state, mode=mode, group=group,
            refresh=refresh)

#     def _refresh_tool_buttons(self):
#         # If SHIFT is pressed, tracks & soft keys are handled by MixerHandler
#         if self._is_shifted:
#             return

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

