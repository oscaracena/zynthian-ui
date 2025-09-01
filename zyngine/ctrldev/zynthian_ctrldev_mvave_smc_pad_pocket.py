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

import os
import jack
import time
# # import signal
import logging
import colorsys
# # from bisect import bisect
# # from copy import deepcopy
# # import multiprocessing as mp
# # from functools import partial
from threading import Thread, RLock, Event, current_thread
from queue import Queue, Full

import mido

from zynlibs.zynseq import zynseq
from zyncoder.zyncore import lib_zyncore
# # from zyngine.zynthian_signal_manager import zynsigman
# # from zyngine.zynthian_engine_audioplayer import zynthian_engine_audioplayer
from zyngine.ctrldev.zynthian_ctrldev_base import (
    zynthian_ctrldev_zynmixer, zynthian_ctrldev_zynpad)
from zyngine.ctrldev.zynthian_ctrldev_base_extended import \
    RunTimer, IntervalTimer, KnobSpeedControl, ButtonTimer, CONST
from zyngine.ctrldev.zynthian_ctrldev_base_ui import ModeHandlerBase


log_level = int(os.environ.get('ZYNTHIAN_LOG_LEVEL', logging.INFO))
logger = logging.getLogger(__name__)
logger.setLevel(log_level)
DEBUG = False

# Driver specification:
# - ZynPad mode, for launching sequences
# - Action button, for changing modes and setting. Could be hidden (reset to show again)
# - Device mode, for controling Zynthian UI
# - Mixer mode, with +/- for gain on 7+main chains. Support for banks, pan, mute and solo

# Useful constants
PAD_COUNT         = 16
PAD_LAST_IDX      = 15
PAD_FIRST_IDX     = 0

PAD_SHIFT         = 0x03

CC_PAD_PRESS      = 0x7F
CC_PAD_RELEASE    = 0x00

LED_BRIGHT_20     = 0.20
# LED_BRIGHT_25   = 0.25
# LED_BRIGHT_50   = 0.5
# LED_BRIGHT_65   = 0.65
# LED_BRIGHT_75   = 0.75
# LED_BRIGHT_90   = 0.90
LED_BRIGHT_100    = 1.0
LED_BRIGHT_MAX    = 1.0
LED_BRIGHT_MIN    = 0.25
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

# Controller preset/bank used by handlers of this driver
WORKING_PRESET    = 0
WORKING_CHANNEL   = 0

BANK_CONTROL      = 0
BANK_ZYNPAD       = 1
OFFSET_CONTROL    = 0
OFFSET_ZYNPAD     = 16


mido.set_backend("mido.backends.rtmidi/UNIX_JACK")


class MidoMidiBridge:
    def __init__(self, in_name, out_name, on_message_cb):
        self._in_port = None
        self._out_port = None
        self._on_message_cb = on_message_cb

        in_name, out_name = self._find_device(in_name, out_name)
        if in_name is None or out_name is None:
            raise RuntimeError(f"NoDeviceFound: {in_name}, {out_name}")

        self._in_port = mido.open_input(in_name, callback=self._on_message)
        self._out_port = mido.open_output(out_name)

    def __del__(self):
        if self._in_port is not None:
            self._in_port.close()
        if self._out_port is not None:
            self._out_port.close()

    def send_sysex(self, data):
        if not self._out_port:
            print("WARNING: message but port not ready, discarded")
            return

        msg = mido.Message(type="sysex", data=data[1:-1])
        self._out_port.send(msg)

    def _on_message(self, msg):
        # print(msg)
        ev = None
        if msg.type == "sysex":
            if msg.data is None:
                return
            ev = b"\xF0" + bytes(msg.data) + b"\xF7"
        elif msg.type == "control_change":
            ev = bytes((
                (CONST.MIDI_CC << 4) | msg.channel,
                msg.control, msg.value))

        if ev is not None:
            self._on_message_cb(ev)

    def _find_device(self, in_name, out_name):
        print (f"SEARCH FOR OUT: {out_name}, IN: {in_name}")
        for dev_name in mido.get_output_names():
            print(f"OUT: {dev_name}: {out_name in dev_name}")
            if out_name in dev_name:
                out_name = dev_name
                break
        for dev_name in mido.get_input_names():
            print(f"IN: {dev_name}: {in_name in dev_name}")
            if in_name in dev_name:
                in_name = dev_name
                break
        # print(in_name, out_name)
        return in_name, out_name


class ZynthianMidiBridge:
    def __init__(self, izmop):
        self._izmop = izmop

    def send_sysex(self, data):
        lib_zyncore.dev_send_midi_event(self._izmop, data, len(data))


class JackMidiBridge:
    def __init__(self, in_name, out_name, on_message_cb):
        self._on_message_cb = on_message_cb
        self._send_queue = Queue()
        self._recv_queue = Queue()

        self._client = jack.Client("smc_pad_pocket_midi_bridge")
        self._in_port = self._client.midi_inports.register("input")
        self._out_port = self._client.midi_outports.register("output")
        self._client.set_process_callback(self._process)
        self._client.set_xrun_callback(lambda status: print(f"+++ Jack: xrun occurred: {status}"))
        self._client.activate()

        ext_src, ext_dst = self._find_device(in_name, out_name)
        print(f"CONNECT: [SRC]{ext_src} -> [DST]{self._in_port.name}")
        print(f"CONNECT: [SRC]{self._out_port.name} -> [DST]{ext_dst}")
        self._client.connect(ext_src, self._in_port.name)
        self._client.connect(self._out_port.name, ext_dst)

        self._thread = Thread(target=self._user_loop, daemon=True)
        self._thread.start()

    def send_sysex(self, data: bytes):
        self._send_queue.put(data)

    def _process(self, frames):
        self._out_port.clear_buffer()

        # Receive events
        for offset, data in self._in_port.incoming_midi_events():
            if data is None:
                continue
            data = bytes(data)
            data_hex = " ".join(f"{b:02X}" for b in data)
            if DEBUG: print(f"+++ Jack: incomming data, offset: {offset}, frames: {frames}, data: {data_hex}")
            if data[0] == 0xF0:
                self._recv_queue.put(data)
                if DEBUG: print("+++ Jack: buffer enqueued")
            else:
                if DEBUG: print("+++ Jack: ignored event")

        # Send events
        while not self._send_queue.empty():
            msg = self._send_queue.get_nowait()
            if DEBUG: print(f"+++ Jack: sending data, {msg}")
            self._out_port.write_midi_event(0, msg)

    def _user_loop(self):
        while True:
            data = self._recv_queue.get()
            try:
                self._on_message_cb(data)
            except Exception as err:
                logging.warning(f"Error on message callback: {err}")

    def _find_device(self, in_name, out_name):
        ext_src, ext_dst = None, None
        print (f"SEARCH FOR OUT: {out_name}, IN: {in_name}")
        for p in self._client.get_ports(is_midi=True, is_output=True):
            print(f"IN: {p.name}: {in_name in p.name}")
            if hasattr(p, "alias"): print(f" - alias:", p.alias)
            if in_name in p.name:
                ext_src = p.name
                break
        for p in self._client.get_ports(is_midi=True, is_input=True):
            print(f"OUT: {p.name}: {out_name in p.name}")
            if hasattr(p, "alias"): print(f" - alias:", p.alias)
            if out_name in p.name:
                ext_dst = p.name
                break
        return ext_src, ext_dst


# --------------------------------------------------------------------------
# 'M-VAVE SMC Pad Pocket' device controller class
# --------------------------------------------------------------------------
class zynthian_ctrldev_mvave_smc_pad_pocket(zynthian_ctrldev_zynmixer, zynthian_ctrldev_zynpad):
    # _instance = None

    dev_ids = ["SINCO IN 1"]
    driver_name = "SMC Pad Pocket"
    unroute_from_chains = False

    @classmethod
    def get_autoload_flag(cls):
        return False

    # # NOTE: this class is a singleton because Zynthian creates many instances of it!
    # def __new__(cls, *args, **kwargs):
    #     if cls._instance is None:
    #         cls._instance = super(zynthian_ctrldev_mvave_smc_pad_pocket, cls).__new__(cls)
    #     return cls._instance

    def __init__(self, state_manager, idev_in, idev_out):
        # Prevent re-initialization in singleton
        # if getattr(self, "_initialized", False):
        #     return

        super().__init__(state_manager, idev_in, idev_out)
        print(".DRIVER __init__", idev_in, idev_out)

        # Option 1: use Zynthian MIDI pipeline
        # proxy = ZynthianMIDIProxy(idev_out)
        # self.midi_event = self._recv_midi_event

        # Option 2: bypass Zynthian, and use mido
        # proxy = MidoMidiBridge(
        #     "system:midi_capture_1", "system:midi_playback_1", self._recv_midi_event)

        # Option 3: bypass Zynthian, and use jack
        proxy = JackMidiBridge(
            "system:midi_capture_1", "system:midi_playback_1", self._recv_midi_event)

        self._setup_done = Event()
        self._hw = SMCPadController(proxy)
        self._hw.on_synced(self._setup_banks)
        self._hw.start()

        self._leds = FeedbackLEDs(self._hw)

        self._zynpad_handler = ZynpadHandler(state_manager, self._leds)
        # self._device_handler = DeviceHandler(state_manager, self._leds)
        # self._mixer_handler = MixerHandler(state_manager, self._leds)
        # self._stepseq_handler = StepSeqHandler(state_manager, self._leds, idev_in)
        self._control_handler = ControlHandler(state_manager, self._hw, self._leds)
        self._current_handler = self._zynpad_handler

        # By default, SHIFT is enabled on al modes
        self._zynpad_handler.enable_shift(PAD_SHIFT, True)
        self._control_handler.enable_shift(PAD_SHIFT, True)
        self._is_shifted = False

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

        # self._initialized = True

    # def init(self):
    #     super().init()
    #     self._sync_device()
    #     self._setup_banks()

    def end(self):
        # for signal, subsignal, callback in self._signals:
        #     zynsigman.unregister(signal, subsignal, callback)
        super().end()

        # Light on some LEDs so the user knows that his controller is on
        if not self._setup_done.is_set():
            return

        self._leds.led_on(0, (00, 10, 20))
        self._leds.led_on(6, (20, 20, 20))
        self._leds.led_on(9, (20, 20, 20))
        self._leds.led_on(15, (0, 10, 20))
        self._hw.wait_finish()

    def refresh(self):
        # print(f"REFRESH, setup done: {self._setup_done.is_set()}")
        if not self._setup_done.is_set():
            return
        self._current_handler.refresh()

    def _recv_midi_event(self, ev: bytes):
        if DEBUG:
            print(f" -- midi_event IN, ts:  {time.monotonic_ns() / 1000000}")
            print(f"MIDI EVENT:", " ".join(f"{b:02X}" for b in ev))

# #         if self._on_midi_event(ev):
# #             while True:
# #                 action = self._current_handler.pop_action_request()
# #                 if not action:
# #                     return True

# #                 # NOTE: Add other receivers as needed
# #                 receiver, action, args, kwargs = action
# #                 if receiver == "stepseq":
# #                     self._stepseq_handler.run_action(action, args, kwargs)
# #                 elif receiver == "mixpad":
# #                     self._zynpad_handler.run_action(action, args, kwargs)
# #         return False

# #     def _on_midi_event(self, ev):

        evtype = (ev[0] >> 4) & 0x0F

        if evtype == CONST.MIDI_CC:
            channel = ev[0] & 0xF
            if channel != WORKING_CHANNEL:
                return

            ccnum = ev[1] & 0x7F
            ccval = ev[2] & 0x7F
            if ccnum <= OFFSET_CONTROL + 15:
                self._control_handler.on_cc_event(ccnum, ccval)
            elif ccnum <= OFFSET_ZYNPAD + 15:
                self._zynpad_handler.on_cc_event(ccnum, ccval)

        elif ev[0] == CONST.MIDI_SYSEX:
            self._hw.on_sysex_message(ev[1:-1])

        # print("MIDI EVENT, thread free")

#             ccnum = ev[1] & 0x7F
#             ccval = ev[2] & 0x7F
#             channel = ev[0] & 0xF

#             if channel != WORKING_CHANNEL:
#                 return

#             if ccnum == PAD_SHIFT:
#                 return self._on_shift_changed(ccval == CC_PAD_PRESS)

# #             if self._is_shifted:
# #                 old_handler = self._current_handler
# #                 # Change global mode here
# #                 if note == BTN_KNOB_CTRL_DEVICE:
# #                     self._current_handler = self._device_handler
# #                 elif note in [BTN_KNOB_CTRL_PAN, BTN_KNOB_CTRL_VOLUME]:
# #                     self._current_handler = self._mixer_handler
# #                     self._zynpad_handler.refresh()
# #                 elif note == BTN_KNOB_CTRL_SEND:
# #                     self._current_handler = self._stepseq_handler

# #                 if old_handler != self._current_handler:
# #                     old_handler.set_active(False)
# #                     self._current_handler.set_active(True)

# #                 # Change sub-modes here
# #                 if self._current_handler == self._mixer_handler:
# #                     if note == BTN_SOFT_KEY_CLIP_STOP:
# #                         self._zynpad_handler.enable_seqman(True)
# #                     elif BTN_SOFT_KEY_SOLO <= note <= BTN_SOFT_KEY_END:
# #                         self._zynpad_handler.enable_seqman(False)

#             # Padmatrix related events
#             if self._current_handler == self._zynpad_handler:
# #                 if BTN_PAD_START <= note <= BTN_PAD_END:

# #                     # Launch StepSeq directly from SHIFT + PAD
# #                     if self._is_shifted:
# #                         seq = self._zynpad_handler.get_sequence_from_pad(
# #                             note)
# #                         if seq is None:
# #                             return False
# #                         if self._current_handler != self._stepseq_handler:
# #                             self._current_handler.set_active(False)
# #                         self._current_handler = self._stepseq_handler
# #                         self._current_handler.set_sequence(seq)
# #                         self._current_handler.set_active(True)
# #                         self._current_handler.refresh(
# #                             shifted_override=self._is_shifted)
# #                         return True

#                 if ccval == CC_PAD_PRESS:
#                     return self._zynpad_handler.pad_press(ccnum)

# #                 # FIXME: move these events to padmatrix handler itself
# #                 elif note == BTN_RECORD and not self._is_shifted:
# #                     return self._zynpad_handler.on_record_changed(True)
# #                 elif note == BTN_PLAY:
# #                     if not self._is_shifted:
# #                         return self._zynpad_handler.on_toggle_play()
# #                     self._zynpad_handler.note_on(
# #                         note, vel, self._is_shifted)
# #                 elif (BTN_SOFT_KEY_START <= note <= BTN_SOFT_KEY_END
# #                       and not self._is_shifted):
# #                     row = note - BTN_SOFT_KEY_START
# #                     return self._zynpad_handler.on_toggle_play_row(row)
# #                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
# #                     track = note - BTN_TRACK_1
# #                     self._zynpad_handler.on_track_changed(track, True)
# #                     self._current_handler.note_on(note, vel, self._is_shifted)
# #                     self._zynpad_handler.refresh()
# #                     return True
# #                 elif note == BTN_STOP_ALL_CLIPS:
# #                     self._zynpad_handler.note_on(
# #                         note, vel, self._is_shifted)

# #             return self._current_handler.note_on(note, vel, self._is_shifted)

# #         elif evtype == EV_NOTE_OFF:
# #             note = ev[1] & 0x7F

# #             if note == BTN_SHIFT:
# #                 return self._on_shift_changed(False)

# #             # Padmatrix related events
# #             if self._current_handler == self._mixer_handler:
# #                 if note == BTN_RECORD:
# #                     return self._zynpad_handler.on_record_changed(False)
# #                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
# #                     track = note - BTN_TRACK_1
# #                     self._zynpad_handler.on_track_changed(track, False)
# #                 elif note == BTN_STOP_ALL_CLIPS:
# #                     self._zynpad_handler.note_off(note, self._is_shifted)

# #             return self._current_handler.note_off(note, self._is_shifted)

#         elif ev[0] == CONST.MIDI_SYSEX:
#             self._hw.on_sysex_message(ev[1:-1])

        if DEBUG:
            print(f" -- midi_event OUT, ts: {time.monotonic_ns() / 1000000}")

    def light_off(self):
        self._leds.all_off()

# #     def update_mixer_strip(self, chan, symbol, value):
# #         if self._current_handler == self._mixer_handler:
# #             self._current_handler.update_strip(chan, symbol, value)

# #     def update_mixer_active_chain(self, active_chain):
# #         refresh = self._current_handler == self._mixer_handler
# #         self._mixer_handler.set_active_chain(active_chain, refresh)

    def update_seq_state(self, *args, **kwargs):
        if self._current_handler == self._zynpad_handler:
            self._zynpad_handler.update_seq_state(*args, **kwargs)
#         elif self._current_handler == self._stepseq_handler:
#             self._current_handler.update_seq_state(*args, **kwargs)

# #     def get_state(self):
# #         state = {}
# #         state.update(self._stepseq_handler.get_state())
# #         return state

# #     def set_state(self, state):
# #         self._stepseq_handler.set_state(state)

#     def _on_shift_changed(self, state):
#         self._is_shifted = state
#         self._current_handler.on_shift_changed(state)
#         # if self._current_handler == self._mixer_handler:
#         #     self._zynpad_handler.on_shift_changed(state)
#         self._control_handler.on_shift_changed(state)
#         return True

# #     def _on_gui_show_screen(self, screen):
# #         self._device_handler.on_screen_change(screen)
# #         self._zynpad_handler.on_screen_change(screen)
# #         self._stepseq_handler.on_screen_change(screen)
# #         if self._current_handler == self._device_handler:
# #             self._current_handler.refresh()

# #     def _on_media_change_state(self, state, media, kind):
# #         self._current_handler.on_media_change(media, kind, state)
# #         if self._current_handler == self._device_handler:
# #             self._current_handler.refresh()

    def _setup_banks(self):
        if DEBUG: print("\nDRIVER setup_banks()")
        self._hw.change_preset(WORKING_PRESET)

        # Setup control handler first, and then change to it
        self._control_handler.set_hw_layout(self._hw)
        self._hw.change_bank(self._control_handler.BANK)

        # Then, setup every other handler
        self._zynpad_handler.set_hw_layout(self._hw)

        # Finally, move to the current bank to show current handler
        self._hw.change_bank(self._current_handler.BANK)

        def on_finish():
            self._setup_done.set()
            self.refresh()

        self._hw.on_batch_finish(on_finish)


# --------------------------------------------------------------------------
# MIDI events processor, in a thread to avoid hanging the MIDI thread, so the
# ACK messages are received as fast as possible
# # --------------------------------------------------------------------------
# class EventProcessor(Thread):

#     def __init__(self, state_manager, hw: "SMCPadController"):
#         super().__init__()
#         self._messages = Queue(maxsize=100)
#         self._leds = FeedbackLEDs(hw)
#         self._hw = hw

#         self._zynpad_handler = ZynpadHandler(state_manager, self._leds)
# # #         self._device_handler = DeviceHandler(state_manager, self._leds)
# # #         self._mixer_handler = MixerHandler(state_manager, self._leds)
# # #         self._stepseq_handler = StepSeqHandler(state_manager, self._leds, idev_in)
# #         self._control_handler = ControlHandler(state_manager, self._leds)

# #         # By default, SHIFT is enabled on al modes
# #         self._zynpad_handler.enable_shift(PAD_SHIFT, True)

#         self._current_handler = self._zynpad_handler
# #         self._is_shifted = False

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

    #     self.daemon = True
    #     self.name = "EventProcessorT"
    #     self.start()

    # def add(self, ev):
    #     try:
    #         self._messages.put_nowait(ev)
    #     except Full:
    #         logger.warning("EventProcessor: could not add message, queue is full!")

    # def run(self):
    #     print(f"EventProcessor Thread: {current_thread().name}")
    #     self._sync_device()
    #     self._setup_banks()

    #     while True:
    #         ev = self._messages.get()
    #         self._process(ev)

#     def init(self):
#         print("PROCESSOR: init()")
#         for signal, subsignal, callback in self._signals:
#             zynsigman.register(signal, subsignal, callback)

#         # Wait until the pipeline is ready (when the driver receives response to a sync command)
#         self._hw.sync(callback=self._on_synced)

#     def refresh(self):
#         if not self._hw.is_synced:
#             return

#         self._current_handler.refresh()
# #         self._control_handler.refresh()

#     def _setup_banks(self):
#         self._zynpad_handler.set_hw_layout(self._hw)

#         self._hw.change_preset(WORKING_PRESET)
#         self._hw.change_bank(self._current_handler.BANK)

#     def _sync_device(self):
#         logger.debug("Processor: wait for hardware sync...")
#         for i in range(5):
#             if self._hw.sync(timeout=2):
#                 logger.debug(f"Processor: hardware sync completed (({self._hw}), waiting MIDI events")
#                 return True

#         logger.error(f"Processor: Unable to sync with hardware controller ({self._hw}), no response!")
#         return False

    # def _process(self, ev):
    #     print("P-MIDI EVENT:", " ".join(f"{b:02X}" for b in ev))


# # --------------------------------------------------------------------------
# # 'M-VAVE SMC Pad Pocket' device controller class
# # --------------------------------------------------------------------------
# class zynthian_ctrldev_mvave_smc_pad_pocket(zynthian_ctrldev_zynmixer, zynthian_ctrldev_zynpad):

#     dev_ids = ["SINCO IN 1", "SMC-PAD Pocket"]
#     driver_name = "SMC Pad Pocket"
#     unroute_from_chains = False

#     @classmethod
#     def get_autoload_flag(cls):
#         return True

#     def __init__(self, state_manager, idev_in, idev_out):
#         self._hw = SMCPadController(idev_out)
#         self._leds = FeedbackLEDs(self._hw)

# #         self._device_handler = DeviceHandler(state_manager, self._leds)
# #         self._mixer_handler = MixerHandler(state_manager, self._leds)
#         self._zynpad_handler = ZynpadHandler(state_manager, self._leds)
# #         self._stepseq_handler = StepSeqHandler(state_manager, self._leds, idev_in)
#         self._control_handler = ControlHandler(state_manager, self._leds)

#         # By default, SHIFT is enabled on al modes
#         self._zynpad_handler.enable_shift(PAD_SHIFT, True)

#         self._current_handler = self._zynpad_handler
#         self._is_shifted = False

# #         self._signals = [
# #             (zynsigman.S_GUI,
# #                 zynsigman.SS_GUI_SHOW_SCREEN,
# #                 self._on_gui_show_screen),

# #             (zynsigman.S_AUDIO_PLAYER,
# #                 zynthian_engine_audioplayer.SS_AUDIO_PLAYER_STATE,
# #                 lambda handle, state:
# #                     self._on_media_change_state(state, f"audio-{handle}", "player")),

# #             (zynsigman.S_AUDIO_RECORDER,
# #                 state_manager.audio_recorder.SS_AUDIO_RECORDER_STATE,
# #                 partial(self._on_media_change_state, media="audio", kind="recorder")),

# #             (zynsigman.S_STATE_MAN,
# #                 state_manager.SS_MIDI_PLAYER_STATE,
# #                 partial(self._on_media_change_state, media="midi", kind="player")),

# #             (zynsigman.S_STATE_MAN,
# #                 state_manager.SS_MIDI_RECORDER_STATE,
# #                 partial(self._on_media_change_state, media="midi", kind="recorder")),
# #         ]

#         # NOTE: init will call refresh(), so _current_hanlder must be ready!
#         super().__init__(state_manager, idev_in, idev_out)

#     def init(self):
#         super().init()
# #         for signal, subsignal, callback in self._signals:
# #             zynsigman.register(signal, subsignal, callback)

#         # Wait until the pipeline is ready (when the driver receives response to a sync command)
#         self._hw.sync(callback=self._on_synced)

#     def _on_synced(self):
#         # Setup device: change to working preset/bank, set PADs as CC mode, channel 0, nums 0-15
#         self._hw.change_preset(WORKING_PRESET)
#         self._hw.change_bank(WORKING_BANK)
#         for pad in range(16):
#             self._hw.set_pad_mode(pad, "pad")
#             self._hw.set_pad_type(pad, "cc")
#             self._hw.set_pad_note(pad, pad)
#             self._hw.set_pad_channel(pad, WORKING_CHANNEL)

#             # FIXME: also set CC press/release values

#         # FIXME: save current controller layout

#     def end(self):
# #         for signal, subsignal, callback in self._signals:
# #             zynsigman.unregister(signal, subsignal, callback)
#         super().end()

#         # Light on some LEDs so the user knows that his controller is on
#         self._leds.led_on(0, (00, 10, 20))
#         self._leds.led_on(6, (20, 20, 20))
#         self._leds.led_on(9, (20, 20, 20))
#         self._leds.led_on(15, (0, 10, 20))

#         # FIXME: restore previous controller layout

#     def refresh(self):
#         self._current_handler.refresh()
#         self._control_handler.refresh()

#     def midi_event(self, ev: bytes):
#         # print("MIDI EVENT:", " ".join(f"{b:02X}" for b in ev))

# #         if self._on_midi_event(ev):
# #             while True:
# #                 action = self._current_handler.pop_action_request()
# #                 if not action:
# #                     return True

# #                 # NOTE: Add other receivers as needed
# #                 receiver, action, args, kwargs = action
# #                 if receiver == "stepseq":
# #                     self._stepseq_handler.run_action(action, args, kwargs)
# #                 elif receiver == "mixpad":
# #                     self._zynpad_handler.run_action(action, args, kwargs)
# #         return False

# #     def _on_midi_event(self, ev):
#         evtype = (ev[0] >> 4) & 0x0F

#         if evtype == CONST.MIDI_CC:
#             ccnum = ev[1] & 0x7F
#             ccval = ev[2] & 0x7F
#             channel = ev[0] & 0xF

#             if channel != WORKING_CHANNEL:
#                 return

#             if ccnum == PAD_SHIFT:
#                 return self._on_shift_changed(ccval == CC_PAD_PRESS)

# #             if self._is_shifted:
# #                 old_handler = self._current_handler
# #                 # Change global mode here
# #                 if note == BTN_KNOB_CTRL_DEVICE:
# #                     self._current_handler = self._device_handler
# #                 elif note in [BTN_KNOB_CTRL_PAN, BTN_KNOB_CTRL_VOLUME]:
# #                     self._current_handler = self._mixer_handler
# #                     self._zynpad_handler.refresh()
# #                 elif note == BTN_KNOB_CTRL_SEND:
# #                     self._current_handler = self._stepseq_handler

# #                 if old_handler != self._current_handler:
# #                     old_handler.set_active(False)
# #                     self._current_handler.set_active(True)

# #                 # Change sub-modes here
# #                 if self._current_handler == self._mixer_handler:
# #                     if note == BTN_SOFT_KEY_CLIP_STOP:
# #                         self._zynpad_handler.enable_seqman(True)
# #                     elif BTN_SOFT_KEY_SOLO <= note <= BTN_SOFT_KEY_END:
# #                         self._zynpad_handler.enable_seqman(False)

#             # Padmatrix related events
#             if self._current_handler == self._zynpad_handler:
# #                 if BTN_PAD_START <= note <= BTN_PAD_END:

# #                     # Launch StepSeq directly from SHIFT + PAD
# #                     if self._is_shifted:
# #                         seq = self._zynpad_handler.get_sequence_from_pad(
# #                             note)
# #                         if seq is None:
# #                             return False
# #                         if self._current_handler != self._stepseq_handler:
# #                             self._current_handler.set_active(False)
# #                         self._current_handler = self._stepseq_handler
# #                         self._current_handler.set_sequence(seq)
# #                         self._current_handler.set_active(True)
# #                         self._current_handler.refresh(
# #                             shifted_override=self._is_shifted)
# #                         return True

#                 if ccval == CC_PAD_PRESS:
#                     return self._zynpad_handler.pad_press(ccnum)

# #                 # FIXME: move these events to padmatrix handler itself
# #                 elif note == BTN_RECORD and not self._is_shifted:
# #                     return self._zynpad_handler.on_record_changed(True)
# #                 elif note == BTN_PLAY:
# #                     if not self._is_shifted:
# #                         return self._zynpad_handler.on_toggle_play()
# #                     self._zynpad_handler.note_on(
# #                         note, vel, self._is_shifted)
# #                 elif (BTN_SOFT_KEY_START <= note <= BTN_SOFT_KEY_END
# #                       and not self._is_shifted):
# #                     row = note - BTN_SOFT_KEY_START
# #                     return self._zynpad_handler.on_toggle_play_row(row)
# #                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
# #                     track = note - BTN_TRACK_1
# #                     self._zynpad_handler.on_track_changed(track, True)
# #                     self._current_handler.note_on(note, vel, self._is_shifted)
# #                     self._zynpad_handler.refresh()
# #                     return True
# #                 elif note == BTN_STOP_ALL_CLIPS:
# #                     self._zynpad_handler.note_on(
# #                         note, vel, self._is_shifted)

# #             return self._current_handler.note_on(note, vel, self._is_shifted)

# #         elif evtype == EV_NOTE_OFF:
# #             note = ev[1] & 0x7F

# #             if note == BTN_SHIFT:
# #                 return self._on_shift_changed(False)

# #             # Padmatrix related events
# #             if self._current_handler == self._mixer_handler:
# #                 if note == BTN_RECORD:
# #                     return self._zynpad_handler.on_record_changed(False)
# #                 elif BTN_TRACK_1 <= note <= BTN_TRACK_8:
# #                     track = note - BTN_TRACK_1
# #                     self._zynpad_handler.on_track_changed(track, False)
# #                 elif note == BTN_STOP_ALL_CLIPS:
# #                     self._zynpad_handler.note_off(note, self._is_shifted)

# #             return self._current_handler.note_off(note, self._is_shifted)

#         elif ev[0] == CONST.MIDI_SYSEX:
#             self._hw.on_sysex_message(ev[1:-1])

#     def light_off(self):
#         self._leds.all_off()

# #     def update_mixer_strip(self, chan, symbol, value):
# #         if self._current_handler == self._mixer_handler:
# #             self._current_handler.update_strip(chan, symbol, value)

# #     def update_mixer_active_chain(self, active_chain):
# #         refresh = self._current_handler == self._mixer_handler
# #         self._mixer_handler.set_active_chain(active_chain, refresh)

#     def update_seq_state(self, *args, **kwargs):
#         if self._current_handler == self._zynpad_handler:
#             self._zynpad_handler.update_seq_state(*args, **kwargs)
# #         elif self._current_handler == self._stepseq_handler:
# #             self._current_handler.update_seq_state(*args, **kwargs)

# #     def get_state(self):
# #         state = {}
# #         state.update(self._stepseq_handler.get_state())
# #         return state

# #     def set_state(self, state):
# #         self._stepseq_handler.set_state(state)

#     def _on_shift_changed(self, state):
#         self._is_shifted = state
#         self._current_handler.on_shift_changed(state)
#         # if self._current_handler == self._mixer_handler:
#         #     self._zynpad_handler.on_shift_changed(state)
#         self._control_handler.on_shift_changed(state)
#         return True

# #     def _on_gui_show_screen(self, screen):
# #         self._device_handler.on_screen_change(screen)
# #         self._zynpad_handler.on_screen_change(screen)
# #         self._stepseq_handler.on_screen_change(screen)
# #         if self._current_handler == self._device_handler:
# #             self._current_handler.refresh()

# #     def _on_media_change_state(self, state, media, kind):
# #         self._current_handler.on_media_change(media, kind, state)
# #         if self._current_handler == self._device_handler:
# #             self._current_handler.refresh()


# --------------------------------------------------------------------------
# HW Controller interaction layer
#
# NOTE: The device sends back an ACK message for each SysEx request. This message
# gives us an idea of how fast the controller can process the incoming events.
# --------------------------------------------------------------------------
class SMCPadController(Thread):

    DEVID_CTRL            = [0x00, 0x32, 0x09]
    DEVID_STAT            = [0x00, 0x32, 0x0D]
    DEVID_INIT            = [0x00, 0x32, 0x45]

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
        super().__init__()
        self._idev = idev
        self._preset = WORKING_PRESET
        self._bank = 0

        self._messages = Queue()
        self._synced = Event()
        self._on_synced_cb = None
        self._on_batch_finish_cb = None
        self._acked = Event()
        self._acked.set()

        self.daemon = True
        self.name = "SMCPadControllerT"

    def run(self):
        self.sync(timeout=2)

        while True:
            try:
                if self._messages.empty() and self._on_batch_finish_cb:
                    self._on_batch_finish_cb()
                    self._on_batch_finish_cb = None
                request, expect_ack = self._messages.get()
                self._send_request(request, expect_ack)
                self._messages.task_done()
            except Exception as err:
                logger.error(f"ERROR on_batch_finish callback: {err}")

    def on_synced(self, cb):
        self._on_synced_cb = cb

    def on_batch_finish(self, cb):
        self._on_batch_finish_cb = cb

    def wait_finish(self):
        self._messages.join()

    def change_preset(self, preset: int):
        if DEBUG: print(f">> change preset to {preset}")
        # Message format:
        # - DEVID[3] 49 00 00 00 02 07 00 00 00 10 00 00 00 PRESET[1] CRC[2]

        assert 0 <= preset <= 3, "presets page should be in range [0, 3]"

        cmd = [0x49, 0, 0, 0, 0x02, 0x07, 0, 0, 0, 0x10, 0, 0, 0, preset]
        checksum = self._get_checksum([4, preset])
        cmd += self._pack_bytes(checksum.to_bytes(1, "little"), 1)

        self._queue_request(cmd)
        old_preset = self._preset
        self._preset = preset
        return old_preset

    def change_bank(self, bank: int):
        if DEBUG: print(f">> change bank to {bank}")
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

        self._queue_request(cmd)
        old_bank = self._bank
        self._bank = bank
        return old_bank

    def set_pad_mode(self, pad: int, mode: str, preset: int = None, bank: int = None):
        if DEBUG: print(f">> set pad mode, pad: {preset}.{bank}.{pad}, mode: {mode}")
        modes = {"pad": 0, "control": 1}
        assert mode in modes, f"mode must be one of {list(modes.keys())}"
        self._set_property(pad, [modes.get(mode)], self.PROP_MODE_OFFSET, bank, preset)

    def set_pad_type(self, pad: int, ptype: str, preset: int = None, bank: int = None):
        if DEBUG: print(f">> set pad type, pad: {preset}.{bank}.{pad}, type: {ptype}")
        types = {"note": 0, "cc-toggle": 1, "cc": 2, "pc": 3, "custom": 4}
        assert ptype in types, f"type must be one of {list(types.keys())}"
        self._set_property(pad, [types.get(ptype)], self.PROP_TYPE_OFFSET, bank, preset)

    def set_pad_note(self, pad: int, note: int, preset: int = None, bank: int = None):
        if DEBUG: print(f">> set pad note, pad: {preset}.{bank}.{pad}, note: {note}")
        assert 0 <= note <= 0x7F, "note number should be in range [0, 127]"
        self._set_property(pad, [note], self.PROP_NOTE_OFFSET, bank, preset)

    def set_pad_channel(self, pad: int, channel: int, bank: int = None, preset: int = None):
        if DEBUG: print(f">> set pad chan, pad: {preset}.{bank}.{pad}, channel: {channel}")
        assert 0 <= channel <= 15, "channel should be in range [0, 15]"
        self._set_property(pad, [channel], self.PROP_CHANNEL_OFFSET, bank, preset)

    def set_pad_led(self, pad: int, color: tuple, bank: int = None, preset: int = None):
        if DEBUG: print(f">> set pad led, pad:  {preset}.{bank}.{pad}, color: {color}")
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

        self._queue_request(cmd)

    def pad_led_off(self, pad: int, bank: int = None, preset: int = None):
        self.set_pad_led(pad, (0, 0, 0), bank, preset)

    def sync(self, timeout=0):
        # print("Start syncing, timeout:", timeout)

        # Step 1: F0 00 32 45 00 00 00 40 7F F7
        # - Response:
        # 0000   F0 00 32 45 58 01 00 40 29 4D 06 35 01 15 08 11
        # 0010   10 50 5E 0D 5B 56 0C 5D 2F 30 60 50 01 00 00 00
        # 0020   00 00 00 00 00 00 20 28 F7
        step1_req = self._create_sysex_request(
            "00 00 00 40 7F", self.DEVID_INIT)
        self._send_request(step1_req, False)
        if timeout is not None:
            if not self._synced.wait(timeout):
                logger.error("INIT: Device not responding!")
            self._synced.clear()

        # Step 2: F0 00 32 0D 41 00 00 00 02 00 00 00 00 00 01 00 00 73 01 F7
        # - Response:
        # 0000   F0 00 32 0D 01 01 00 00 02 00 00 00 00 00 01 00
        # 0010   00 20 01 6C 09 00 00 00 00 00 2E 00 F7
        step2_req = self._create_sysex_request(
            "41 00 00 00 02 00 00 00 00 00 01 00 00 73 01", self.DEVID_STAT)
        self._send_request(step2_req, False)
        if timeout is not None:
            self._synced.wait(timeout)

        if self.is_synced and callable(self._on_synced_cb):
            self._on_synced_cb()

    @property
    def is_synced(self):
        return self._synced.is_set()

    # NOTE: this method is called from within the MIDI thread
    def on_sysex_message(self, data: bytes):
        # Status message format:
        # - DEVID[3] 01 01 00 00 02 00 00 00 00 00 01 00 00 20 01 58 11 00 00 00 00
        # - PRESET[1] CRC[2]

        # ACK from many SysEx requests
        if data == bytes.fromhex("00 32 01 08 00 00 00 00 7F 01"):
            if DEBUG: print("ACK")
            self._acked.set()
            return

        # Response to a sync request
        if data[3:8] == bytes((1, 1, 0, 0, 2)):
            if DEBUG: print("SYNC response")
            self._preset = data[-3]
            self._synced.set()
            return

        # Response to an init request
        if data[:5] == bytes.fromhex("00 32 45 58 01"):
            if DEBUG: print("INIT response")
            self._synced.set()
            return

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

        self._queue_request(cmd)

    def _clean_fields(self, pad: int, bank: int, preset: int):
        bank = bank if bank is not None else self._bank
        preset = preset if preset is not None else self._preset

        assert 0 <= preset <= 3, f"preset ({preset}) should be in range [0, 3]"
        assert 0 <= bank <= 6, f"bank ({bank}) should be in range [0, 6]"
        assert 0 <= pad <= 15, f"pad ({pad}) should be in range [0, 15]"

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

    def _create_sysex_request(self, cmd, devid):
        if isinstance(cmd, str):
            cmd = bytes.fromhex(cmd)
        elif isinstance(cmd, (list, tuple)):
            cmd = bytes(cmd)

        return b"\xF0" + bytes(devid) + cmd + b"\xF7"

    def _queue_request(self, cmd, devid=DEVID_CTRL):
        request = self._create_sysex_request(cmd, devid)
        expect_ack = devid == self.DEVID_CTRL

        while True:
            try:
                self._messages.put_nowait((request, expect_ack))
                return
            except Full:
                logger.warning("EventProcessor: could not add message, queue is full!")
                self._messages.get_nowait()

    def _send_request(self, request, expect_ack=True, debug=True):
        if debug or log_level < logging.INFO:
            if DEBUG:
                print(f" -- midi_evnt SEND, ts: {time.monotonic_ns() / 1000000}")
                print(f"SEND SysEx: ({current_thread().name})", " ".join(f"{b:02X}" for b in request))

        if not expect_ack:
            # print("- DIRECT send")
            self._idev.send_sysex(request)
            return

        # print("- SEND and WAIT")
        # ts = time.monotonic_ns()
        self._acked.clear()
        self._idev.send_sysex(request)
        self._acked.wait(timeout=0.1)
        # elapsed = (time.monotonic_ns() - ts) / 1000000
        # print(f"  :: elapsed 1: {elapsed} ms\n")

    def __repr__(self):
        return f"<SMCPadController, izmop: {self._idev}>"


# --------------------------------------------------------------------------
# Feedback LEDs controller
# --------------------------------------------------------------------------
class FeedbackLEDs:

    BLINK_NAME    = "LEDS"
    BLINK_TIMEOUT = 500
    BLINK_STEPS   = 13

    def __init__(self, hwdev: SMCPadController):
        self._hw = hwdev
        self._state = {}
    #     self._timer = RunTimer()

        self._blinker = IntervalTimer()
        self._blinker_state = [0, True]
        self._blinker_leds = {}

    def all_off(self, overlay=False):
        for pad in range(16):
            self.led_off(pad, overlay)

    # def led_state(self, led, state):
    #     (self.led_on if state else self.led_off)(led)

    def led_off(self, led, overlay=False):
    #     self._timer.remove(led)
        self._blinker_leds.pop(led, None)
        if not self._blinker_leds:
            self._blinker.remove(self.BLINK_NAME)

        self._hw.pad_led_off(led)
        if not overlay:
            self._state[led] = ((0, 0, 0), LED_STILL, LED_BRIGHT_MIN)

    def led_on(self, led, color=(255, 255, 255), mode=LED_STILL,
            brightness=LED_BRIGHT_MAX, overlay=False):

    #     self._timer.remove(led)
        self._blinker_leds.pop(led, None)

        base_color = self._adjust_brightness(color, brightness)
        self._hw.set_pad_led(led, base_color)

        if mode != LED_STILL:
            colors = [
                base_color,
                *([None] * ((self.BLINK_STEPS - 3) // 2)),
                (0, 0, 0),
                *([None] * ((self.BLINK_STEPS - 3) // 2)),
                base_color,
            ]

            if mode == LED_PULSING_2:
                for i in range(1, self.BLINK_STEPS):
                    step_br = LED_BRIGHT_MAX - i * \
                        (LED_BRIGHT_MAX - LED_BRIGHT_MIN) / self.BLINK_STEPS
                    colors[i] = self._adjust_brightness(base_color, step_br)

            if not self._blinker_leds:
                self._blinker.add(self.BLINK_NAME, self.BLINK_TIMEOUT // self.BLINK_STEPS,
                    self._do_blink)
            self._blinker_leds[led] = colors

        if not overlay:
            self._state[led] = (color, mode, brightness)

    def led_blink(self, led, color, brightness=LED_BRIGHT_MAX):
        self.led_on(led, color, LED_BLINKING_8, brightness)

    def remove_overlay(self, led=None):
        if led is not None:
            if led not in self._state:
                return
            leds = [led]
        else:
            leds = list(self._state.keys())

        for led in leds:
            old_state = self._state.get(led)
            self.led_on(led, *old_state)

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
# Base class for handlers, with specifi common methods
# --------------------------------------------------------------------------
class SMCModeHandlerBase(ModeHandlerBase):

    # NOTE: Define these value on subclass
    OFFSET = None
    BANK   = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pad_indexes = list(range(16))

    def set_hw_layout(self, hw: SMCPadController):
        if DEBUG: print(f"##### set layout for bank {self.BANK}")

        # Set PADs as CC mode, correct channel, and ccnums according to offset
        for pad in self._pad_indexes:
            hw.set_pad_mode(pad, "pad", bank=self.BANK)
            hw.set_pad_type(pad, "cc", bank=self.BANK)
            hw.set_pad_note(pad, self.OFFSET + pad, bank=self.BANK)
            hw.set_pad_channel(pad, WORKING_CHANNEL, bank=self.BANK)
            hw.set_pad_led(pad, (0, 0, 0), bank=self.BANK)
            if DEBUG: print("---")
            # FIXME: also set CC press/release values

    def enable_shift(self, pad, state):
        if state:
            self._pad_indexes.remove(pad)
        else:
            self._pad_indexes.append(pad)
            self._pad_indexes.sort()


# --------------------------------------------------------------------------
# Handler for pad matrix in Zynpad
# --------------------------------------------------------------------------
class ZynpadHandler(SMCModeHandlerBase):

    BANK         = BANK_ZYNPAD
    OFFSET       = OFFSET_ZYNPAD

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

# #         self._is_record_pressed = False
# #         self._track_btn_pressed = None
        self._playing_seqs = set()
# #         self._btn_timer = ButtonTimer(self._handle_timed_button)
# #         self._pattern_template = None

# #         # Seqman sub-mode
# #         self._seqman_func = None
# #         self._seqman_src_seq = None

        # FIXME: this value should be updated by a signal, to be in sync with UI state
        self._recording_seq = None

        # Sort pads in the same order that libseq uses
        self._pads = []
        for c in reversed(range(self._cols)):
            for r in range(self._rows):
                self._pads.append(PAD_LAST_IDX - (r * self._cols + c))

    def on_cc_event(self, cc, value):
        if value:
            self.pad_press(cc - self.OFFSET)

# #     def on_record_changed(self, state):
# #         self._is_record_pressed = state

# #         # Only STOP recording allowed, as START conflicts with RECORD + PAD
# #         if state and self._recording_seq is not None:
# #             if self._libseq.isMidiRecord():
# #                 self._stop_pattern_record()

# #     def on_toggle_play(self):
# #         self._state_manager.send_cuia("TOGGLE_PLAY")

# #     def on_toggle_play_row(self, row):
# #         # If seqman is enabled, ignore row functions
# #         if self._seqman_func is not None:
# #             return False
# #         if row >= self._zynseq.col_in_bank:
# #             return True

# #         # Get overall status: playing if at least one sequence is playing
# #         is_playing = False
# #         for col in range(self._zynseq.col_in_bank):
# #             seq = col * self._zynseq.col_in_bank + row
# #             if seq in self._playing_seqs:
# #                 is_playing = True
# #                 break

# #         stop_states = (zynseq.SEQ_STOPPED, zynseq.SEQ_STOPPING,
# #                        zynseq.SEQ_STOPPINGSYNC)
# #         play_states = (zynseq.SEQ_RESTARTING,
# #                        zynseq.SEQ_STARTING, zynseq.SEQ_PLAYING)
# #         for col in range(self._zynseq.col_in_bank):
# #             seq = col * self._zynseq.col_in_bank + row
# #             # We only play sequences that are not empty
# #             if not is_playing and self._libseq.isEmpty(self._zynseq.bank, seq):
# #                 continue
# #             state = self._libseq.getPlayState(self._zynseq.bank, seq)
# #             if is_playing and state in stop_states:
# #                 continue
# #             if not is_playing and state in play_states:
# #                 continue
# #             self._libseq.togglePlayState(self._zynseq.bank, seq)

# #     def on_track_changed(self, track, state):
# #         self._track_btn_pressed = track if state else None

# #         # Switch seqman function (if seqman enabled and SHIFT is not pressed)
# #         if state and self._seqman_func is not None and not self._is_shifted:
# #             btn = BTN_TRACK_1 + track

# #             if btn == BTN_LEFT:
# #                 return self._change_scene(-1)
# #             if btn == BTN_RIGHT:
# #                 return self._change_scene(1)

# #             func = {
# #                 BTN_KNOB_CTRL_VOLUME: FN_COPY_SEQUENCE,
# #                 BTN_KNOB_CTRL_PAN: FN_MOVE_SEQUENCE,
# #                 BTN_KNOB_CTRL_SEND: FN_CLEAR_SEQUENCE,
# #             }.get(btn)
# #             if func is not None:
# #                 self._seqman_func = func
# #                 self._refresh_tool_buttons()

# #                 # Function CLEAR does not have source sequence, remove it
# #                 if func == FN_CLEAR_SEQUENCE and self._seqman_src_seq is not None:
# #                     scene, seq = self._seqman_src_seq
# #                     self._seqman_src_seq = None
# #                     if scene == self._zynseq.bank:
# #                         self._update_pad(seq)

# #     def on_shift_changed(self, state):
# #         retval = super().on_shift_changed(state)
# #         # Update tool buttons only when SHIFT is not pressed
# #         if not state:
# #             self._refresh_tool_buttons()
# #         return retval

# #     def enable_seqman(self, state):
# #         if state:
# #             if self._seqman_func is None:
# #                 self._seqman_func = FN_COPY_SEQUENCE
# #         else:
# #             self._seqman_func = None
# #             self._seqman_src_seq = None
# #         self.refresh()

    def enable_shift(self, pad, state):
        super().enable_shift(pad, state)

        if state:
            if None not in self._pads:
                pos = self._pads.index(pad)
                self._pads[pos] = None
        else:
            if None in self._pads:
                pos = self._pads.index(None)
                self._pads[pos] = pad

    def refresh(self):
# #         if not self._libseq.isMidiRecord():
# #             self._recording_seq = None

        for c in range(self._cols):
            for r in range(self._rows):
                # Pad outside grid, switch off
                if c >= self._zynseq.col_in_bank or r >= self._zynseq.col_in_bank:
                    self.pad_off(c, r)
                    continue

                seq = c * self._zynseq.col_in_bank + r
                self._update_pad(seq)

# #         self._refresh_tool_buttons()

# #     def note_on(self, note, velocity, shifted_override=None):
# #         self._on_shifted_override(shifted_override)
# #         if not self._is_shifted:
# #             if note == BTN_STOP_ALL_CLIPS:
# #                 self._btn_timer.is_pressed(note, time.time())

# #     def note_off(self, note, shifted_override=None):
# #         if note == BTN_STOP_ALL_CLIPS:
# #             self._btn_timer.is_released(note)

    def pad_press(self, pad):
        # Pad outside grid, discarded
        seq = self.get_sequence_from_pad(pad)
        if seq is None:
            return True

# #         if self._seqman_func is not None:
# #             self._seqman_handle_pad_press(seq)
# #         elif self._track_btn_pressed is not None:
# #             self._clear_sequence(self._zynseq.bank, seq)
# #         elif self._is_record_pressed:
# #             self._start_pattern_record(seq)
# #         elif self._recording_seq == seq:
# #             self._stop_pattern_record()
# #         else:

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
        if btn is None:
            return

        is_empty = all(
            self._zynseq.is_pattern_empty(pattern)
            for pattern in self._get_sequence_patterns(bank, seq))
        color = self.GROUP_COLORS[group]

# #         # If seqman is enabled, update according to it's function
# #         if self._seqman_func is not None:
# #             led_mode = LED_BRIGHT_MIN if is_empty else LED_BRIGHT_MIN
# #             if (self._seqman_func in (FN_COPY_SEQUENCE, FN_MOVE_SEQUENCE)
# #                     and self._seqman_src_seq is not None):
# #                 src_scene, src_seq = self._seqman_src_seq
# #                 if src_scene == self._zynseq.bank and src_seq == seq:
# #                     led_mode = LED_BLINKING_24

# #         # Otherwise, update according to sequence state
# #         else:

        led_brightness = LED_BRIGHT_MAX
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
                led_brightness = LED_BRIGHT_MIN

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

# #     def _handle_timed_button(self, btn, ptype):
# #         if btn == BTN_STOP_ALL_CLIPS:
# #             if ptype == CONST.PT_LONG:
# #                 self._stop_all_sounds()
# #             else:
# #                 in_all_banks = ptype == CONST.PT_BOLD
# #                 self._stop_all_seqs(in_all_banks)

# #     def _seqman_handle_pad_press(self, seq):
# #         if self._seqman_func is None:
# #             return

# #         # FIXME: if pattern editor is open, and showing affected seq, update it!
# #         # FIXME: if Zynpad is open, also update it!
# #         # You can use self._current_screen...
# #         self._libseq.updateSequenceInfo()
# #         seq_is_empty = self._libseq.isEmpty(self._zynseq.bank, seq)
# #         if self._seqman_func == FN_CLEAR_SEQUENCE:
# #             if not seq_is_empty:
# #                 self._clear_sequence(self._zynseq.bank, seq)
# #             return

# #         # Set selected sequence as source
# #         if self._seqman_src_seq is None:
# #             if not seq_is_empty:
# #                 self._seqman_src_seq = (self._zynseq.bank, seq)
# #         else:
# #             # Clear source sequence
# #             if self._seqman_src_seq == (self._zynseq.bank, seq):
# #                 self._seqman_src_seq = None
# #             # Copy/Move source to selected sequence (will be overwritten)
# #             else:
# #                 if self._seqman_func == FN_COPY_SEQUENCE:
# #                     self._copy_sequence(
# #                         *self._seqman_src_seq, self._zynseq.bank, seq)
# #                 elif self._seqman_func == FN_MOVE_SEQUENCE:
# #                     self._copy_sequence(
# #                         *self._seqman_src_seq, self._zynseq.bank, seq)
# #                     self._clear_sequence(*self._seqman_src_seq)
# #                     self._seqman_src_seq = None

# #         self._update_pad(seq)

# #     def _change_scene(self, offset):
# #         scene = min(64, max(1, self._zynseq.bank + offset))
# #         if scene != self._zynseq.bank:
# #             self._zynseq.select_bank(scene)
# #             self._state_manager.send_cuia("SCREEN_ZYNPAD")

# #     def _refresh_tool_buttons(self):
# #         # Switch on seqman active function
# #         if self._seqman_func is not None:
# #             active = {
# #                 FN_COPY_SEQUENCE: BTN_KNOB_CTRL_VOLUME,
# #                 FN_MOVE_SEQUENCE: BTN_KNOB_CTRL_PAN,
# #                 FN_CLEAR_SEQUENCE: BTN_KNOB_CTRL_SEND,
# #             }[self._seqman_func]
# #             for idx in range(8):
# #                 btn = BTN_TRACK_1 + idx
# #                 self._leds.led_state(btn, btn == active)
# #             return

# #         # If seqman is disabled, show playing status in row launchers
# #         playing_rows = {
# #             seq % self._zynseq.col_in_bank for seq in self._playing_seqs}
# #         for row in range(5):
# #             state = row in playing_rows
# #             self._leds.led_state(BTN_SOFT_KEY_START + row, state)

# #     def _start_pattern_record(self, seq):
# #         # Set pad's chain as active
# #         channel = self._libseq.getChannel(self._zynseq.bank, seq, 0)
# #         chain_id = self._chain_manager.get_chain_id_by_mixer_chan(channel)
# #         if chain_id is None:
# #             return
# #         if self._libseq.isMidiRecord():
# #             self._state_manager.send_cuia("TOGGLE_RECORD")
# #         self._chain_manager.set_active_chain_by_id(chain_id)

# #         # Open Pattern Editor
# #         self._show_pattern_editor(seq, skip_arranger=True)

# #         # Start playing & recording
# #         if self._libseq.getPlayState(self._zynseq.bank, seq) == zynseq.SEQ_STOPPED:
# #             self._state_manager.send_cuia("TOGGLE_PLAY")
# #         if not self._libseq.isMidiRecord():
# #             self._state_manager.send_cuia("TOGGLE_RECORD")

# #         self._recording_seq = seq
# #         self._update_pad(seq)

# #     def _stop_all_seqs(self, in_all_banks=False):
# #         bank = 0 if in_all_banks else self._zynseq.bank
# #         while True:
# #             seq_num = self._libseq.getSequencesInBank(bank)
# #             for seq in range(seq_num):
# #                 state = self._libseq.getPlayState(bank, seq)
# #                 if state not in [zynseq.SEQ_STOPPED, zynseq.SEQ_STOPPING, zynseq.SEQ_STOPPINGSYNC]:
# #                     self._libseq.togglePlayState(bank, seq)
# #             if not in_all_banks:
# #                 break
# #             bank += 1
# #             if bank >= 64 or self._libseq.getPlayingSequences() == 0:
# #                 break

# #     def _stop_pattern_record(self):
# #         if self._libseq.isMidiRecord():
# #             self._state_manager.send_cuia("TOGGLE_RECORD")
# #         self._recording_seq = None
# #         self.refresh()

# #     def _clear_sequence(self, scene, seq, create_empty=True):
# #         # Remove all patterns in all tracks
# #         seq_len = self._libseq.getSequenceLength(scene, seq)
# #         if seq_len != 0:
# #             n_tracks = self._libseq.getTracksInSequence(scene, seq)
# #             for track in range(n_tracks):
# #                 n_patts = self._libseq.getPatternsInTrack(scene, seq, track)
# #                 if n_patts == 0:
# #                     continue
# #                 pos = 0
# #                 while pos < seq_len:
# #                     pattern = self._libseq.getPatternAt(scene, seq, track, pos)
# #                     if pattern != -1:
# #                         self._libseq.removePattern(scene, seq, track, pos)
# #                         pos += self._libseq.getPatternLength(pattern)
# #                     else:
# #                         # Arranger's offset step is a quarter note (24 clocks)
# #                         pos += 24

# #             if n_tracks > 0:
# #                 for track in range(n_tracks-1):
# #                     self._libseq.removeTrackFromSequence(scene, seq, track)

# #         # Add a new empty pattern at the beginning of first track
# #         if create_empty:
# #             pattern = self._libseq.createPattern()
# #             self._libseq.addPattern(scene, seq, 0, 0, pattern)
# #             self._libseq.selectPattern(pattern)

# #             if self._pattern_template is not None:
# #                 self._action_apply_pattern_template(pattern)

# #     def _copy_sequence(self, src_scene, src_seq, dst_scene, dst_seq):
# #         self._clear_sequence(dst_scene, dst_seq, create_empty=False)

# #         # Copy all patterns in all tracks
# #         seq_len = self._libseq.getSequenceLength(src_scene, src_seq)
# #         if seq_len != 0:
# #             n_tracks = self._libseq.getTracksInSequence(src_scene, src_seq)
# #             for track in range(n_tracks):
# #                 if track >= self._libseq.getTracksInSequence(dst_scene, dst_seq):
# #                     self._libseq.addTrackToSequence(dst_scene, dst_seq)
# #                 n_patts = self._libseq.getPatternsInTrack(
# #                     src_scene, src_seq, track)
# #                 if n_patts == 0:
# #                     continue
# #                 pos = 0
# #                 while pos < seq_len:
# #                     pattern = self._libseq.getPatternAt(
# #                         src_scene, src_seq, track, pos)
# #                     if pattern != -1:
# #                         new_pattern = self._libseq.createPattern()
# #                         self._libseq.copyPattern(pattern, new_pattern)
# #                         self._libseq.addPattern(
# #                             dst_scene, dst_seq, track, pos, new_pattern)
# #                         pos += self._libseq.getPatternLength(pattern)
# #                     else:
# #                         # Arranger's offset step is a quarter note (24 clocks)
# #                         pos += 24

# #         # Also copy StepSeq instrument pages
# #         self._request_action("stepseq", "sync-sequences",
# #             src_scene, src_seq, dst_scene, dst_seq)

# #     def _action_set_pattern_template(self, pattern):
# #         self._pattern_template = pattern

# #     def _action_apply_pattern_template(self, dst_pattern, callback=None):
# #         self._libseq.copyPattern(self._pattern_template, dst_pattern)
# #         if callback is not None and callable(callback):
# #             callback()


# --------------------------------------------------------------------------
# Handler for control overlay
# --------------------------------------------------------------------------
class ControlHandler(SMCModeHandlerBase):

    BANK         = BANK_CONTROL
    OFFSET       = OFFSET_CONTROL

    def __init__(self, state_manager, hw: SMCPadController, leds: FeedbackLEDs):
        super().__init__(state_manager)
        self._hw = hw
        self._leds = leds
        self._is_enabled = True
        self._old_bank = None

    def enable_shift(self, pad, state):
        super().enable_shift(pad, state)
        self._is_enabled = state

    def set_hw_layout(self, hw: SMCPadController):
        super().set_hw_layout(hw)
        if not self._is_enabled:
            return

        # I manage the SHIFT pad on all banks
        for bank in range(7):
            hw.set_pad_mode(PAD_SHIFT, "pad", bank=bank)
            hw.set_pad_type(PAD_SHIFT, "cc", bank=bank)
            hw.set_pad_note(PAD_SHIFT, self.OFFSET + PAD_SHIFT, bank=bank)
            hw.set_pad_channel(PAD_SHIFT, WORKING_CHANNEL, bank=bank)
            hw.set_pad_led(PAD_SHIFT, (255, 255, 255), bank=bank)

    def on_cc_event(self, cc, value):
        if cc == PAD_SHIFT:
            if value:
                self._old_bank = self._hw.change_bank(BANK_CONTROL)
            else:
                if self._old_bank is not None:
                    self._hw.change_bank(self._old_bank)

