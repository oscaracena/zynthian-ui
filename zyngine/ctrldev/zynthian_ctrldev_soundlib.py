#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian tool to generate a sound library
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
import re
import time
import logging
import shutil
import subprocess
from threading import Thread
from pathlib import Path
from collections import namedtuple
from datetime import datetime

from zyncoder.zyncore import lib_zyncore
from zyngine.ctrldev.zynthian_ctrldev_base import zynthian_ctrldev_base
from zyngine import zynthian_lv2
from zyngui import zynthian_gui_config


STORAGE = Path("./soundlib").absolute()

# global logger
log_level = int(os.environ.get('ZYNTHIAN_LOG_LEVEL', logging.INFO))
log = logging.getLogger("SoundLibCreator")
log.propagate = False
log.setLevel(log_level)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(log_handler)

# file handler for logger, to save a record of this execution
log_dir = STORAGE / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter("%(asctime)s|%(levelname)s %(message)s")
file_handler.setFormatter(file_formatter)
log.addHandler(file_handler)

# Some global constants
PS1 = "::\033[1;32mSndLib\033[0m>"
PSE = "::\033[1;31mSndLib\033[0m>"
PSW = "::\033[1;33mSndLib\033[0m>"


# --------------------------------------------------------------------------
# SoundLib, a library of sounds for Zynthian
# --------------------------------------------------------------------------
class zynthian_ctrldev_soundlib(zynthian_ctrldev_base):
    _instance = None
    _initialized = False

    dev_ids = [None]
    driver_name = "SoundLib"
    unroute_from_chains = True

    @classmethod
    def get_autoload_flag(cls):
        return True

    # NOTE: This class is a singleton because Zynthian wants to create many instances of it
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(zynthian_ctrldev_soundlib, cls).__new__(cls)
        return cls._instance

    def __init__(self, state_manager, idev_in, idev_out):
        if self._initialized:
            return

        super().__init__(state_manager, idev_in, idev_out)
        self._creator = SoundLibCreator(state_manager)
        self._initialized = True


class SoundLibCreator(Thread):
    LOW_DB            = -50
    MIDI_CH           = 9
    SILENCE_THRESHOLD = 0.2  # in range [0, 1]

    def __init__(self, state_manager):
        super().__init__()
        self._state_manager = state_manager
        self._zynmixer = state_manager.zynmixer
        self._recorder = state_manager.audio_recorder

        self._chain_id = None
        self._current_processor = None
        self._clips_dir = STORAGE / "clips"
        self._clips_dir.mkdir(parents=True, exist_ok=True)

        self.dameon = True
        self.start()

    def run(self):
        self._wait_until_ready()
        self._create_chain("SoundLib")

        for engine in self._get_engine_list():
            if engine.cat.lower() == "percussion":
                self._record_rhythmic_samples(engine)
            elif engine.cat.lower() == "synth":
                self._record_melodic_samples(engine)
            else:
                log.warning(f"{PSW} Skipping engine ({engine.spec_name}), "
                    f"unknown cat: {engine.cat}")

            break

        # # start audio recording
        # recorder.start_recording()
        # time.sleep(1)

        # send a C4 for 2 seconds to chain
        # print(self._get_level())
        # time.sleep(1)
        # lib_zyncore.ui_send_note_on(midi_ch, 60, 127)
        # time.sleep(1)
        # print(self._get_level())
        # time.sleep(1)
        # lib_zyncore.ui_send_note_off(midi_ch, 60, 0)
        # time.sleep(1)
        # print(self._get_level())

        # stop audio recording and save audio file
        # FIXME: monitor out level, and stop on silence
        # recorder.stop_recording()
        # print(f"RECORD at: '{recorder.filename}'")

        # # stop all sounds
        # self._state_manager.all_notes_off()
        # self._state_manager.all_sounds_off()
        # time.sleep(1)
        # print(self._get_level())

        # # remove processor from chain
        # if not chain_manager.remove_processor(chain_id, processor):
        #     log.error(f"FAILED to remove processor from chain {chain_id}")

        # create another processor
        # eng_code = "JV/amsynth"  # melodic synth, presets and banks
        # processor = chain_manager.add_processor(chain_id, eng_code)
        # if not processor:
        #     log.error(f"FAILED to create the engine {eng_code}")
        # chain_manager.set_active_chain_by_id(chain_id)

        # # NOTE: there is a bug, and first note of first preset sounds bad; flush it here
        # lib_zyncore.ui_send_note_on(midi_ch, 60, 0)
        # time.sleep(0.5)
        # lib_zyncore.ui_send_note_off(midi_ch, 60, 0)

        # lib_zyncore.ui_send_note_on(midi_ch, 60, 60)
        # time.sleep(1)
        # lib_zyncore.ui_send_note_off(midi_ch, 60, 0)
        # time.sleep(1)

        # processor.preload_preset(1)
        # lib_zyncore.ui_send_note_on(midi_ch, 60, 60)
        # time.sleep(1)
        # lib_zyncore.ui_send_note_off(midi_ch, 60, 0)
        # time.sleep(1)

        print("FINISH")

    def _get_engine_list(self):
        # FIXME: shall we include other categories? (Audio Generator, Effects, etc.)
        for idx, (name, spec) in enumerate(zynthian_lv2.engines_by_type["MIDI Synth"].items()):
            EngineSpec = namedtuple("EngineSpec", list(map(str.lower, spec.keys())) \
                + ["spec_idx", "spec_name"])

            # FIXME!! REMOVE!!!
            if idx != 3: continue

            yield EngineSpec(spec_idx=idx, spec_name=name,
                **{k.lower():v for k, v in spec.items()})

    def _iter_over_presets(self, processor, preload=True):
        banks = processor.get_bank_list()
        if len(banks) == 1 and banks[0][2] == None:
            yield None, None
            return

        for bank_idx, bank in enumerate(banks):
            bank_name = bank[2]
            processor.set_bank(bank_idx)
            processor.load_preset_list()

            for preset_idx, preset in enumerate(processor.preset_list):
                preset_name = preset[2]
                if preload:
                    processor.reset_preset()
                    processor.preload_preset(preset_idx)

                    # NOTE: There is a bug (or something), and first note of first preset
                    # sounds bad; flush it here
                    lib_zyncore.ui_send_note_on(self.MIDI_CH, 60, 0)
                    time.sleep(0.5)
                    lib_zyncore.ui_send_note_off(self.MIDI_CH, 60, 0)

                yield bank_name, preset_name

    def _record_rhythmic_samples(self, engine):
        log.info(f"{PS1} Processing '{engine.spec_name}' as rhythmic")
        processor = self._create_processor(engine)
        for bank, preset in self._iter_over_presets(processor):
            print(f"- {bank} > {preset}")

    def _record_melodic_samples(self, engine):
        log.info(f"{PS1} Processing '{engine.spec_name}' as melodic")
        processor = self._create_processor(engine)
        for idx, (bank, preset) in enumerate(self._iter_over_presets(processor)):
            log.info(f"- Recording preset {idx}: {bank} > {preset}")
            name = self._get_clip_name_for_preset(engine.name, bank, preset)
            self._record_melodic(name)

            # FIXME!! REMOVE!!!
            if idx >= 1: return

    def _record_melodic(self, name):
        self._record_song("C4",
            bpm=30, filename=self._clips_dir / f"{name}-A.ogg")
        self._record_song("C4 E4 G4 -, [C4 E4 G4]",
            bpm=30, filename=self._clips_dir / f"{name}-B.ogg")
        self._record_song("[C3 Eb3 G3], -, [C5 Eb5 G5]",
            bpm=60, filename=self._clips_dir / f"{name}-C.ogg")

    def _record_song(self, song, bpm, filename):
        # Some examples:
        # - 'C4', a single C4 sustained all the bar
        # - 'C4 E4 G4 -', a Cmaj chord, arpeggiated in a bar (with a final rest)
        # - '[C5 Eb5 G5]', a Cmin chord sustained all the bar
        # - '[C3 E3 G3], G5', a Cmaj chor and a G note, along two bars

        self._wait_for_silence(force=True)
        self._start_recording()

        log.info(f"  - 🔴 REC: '{song}', file: {filename}")
        bars = map(str.strip, song.split(","))
        for bar in bars:
            is_chord = False
            if bar.startswith("["):
                is_chord = True
                bar = bar[1:-1]
            notes = map(str.strip, bar.split())
            notes = self._to_midi_numbers(notes)
            self._play_notes(notes, is_chord, bpm)

        self._wait_for_silence()
        self._stop_recording(filename)

    def _to_midi_numbers(self, notes):
        midi_notes = []
        note_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
        for note in notes:
            if note == "-":
                midi_notes.append(None)
                continue
            match = re.match(r'^([A-G])([#b]?)(\d*)$', note)
            if not match:
                continue
            n, accidental, octave = match.groups()
            semitone = note_map[n]
            if accidental == '#':
                semitone += 1
            elif accidental == 'b':
                semitone -= 1
            octave = int(octave) if octave else 4
            midi_num = (octave + 1) * 12 + semitone
            midi_notes.append(midi_num)
        return midi_notes

    def _play_notes(self, bar, as_chord=False, tempo=60):
        duration = 60 / tempo

        if as_chord:
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_on(self.MIDI_CH, note, 100)
            time.sleep(duration)
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_off(self.MIDI_CH, note, 0)
        else:
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_on(self.MIDI_CH, note, 100)
                time.sleep(duration / len(bar))
                if note is not None:
                    lib_zyncore.ui_send_note_off(self.MIDI_CH, note, 0)

    def _wait_for_silence(self, force=False):
        if force:
            self._state_manager.all_notes_off()
            self._state_manager.all_sounds_off()

        while True:
            if self._get_sound_level() < self.SILENCE_THRESHOLD:
                return
            time.sleep(0.1)

    def _start_recording(self):
        self._recorder.start_recording()

    def _stop_recording(self, filename):
        self._recorder.stop_recording()

        # FIXME: create a worker thread that make this job
        def compress_audio(input_file, output_file):
            try:
                subprocess.run([
                    "nice", "-n", "19",
                    "cpulimit", "-l", "30", "--",
                    "ffmpeg", "-y", "-i", input_file, "-c:a", "libopus",
                    "-threads", "2", output_file,
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(input_file)
                log.info(f"  - {output_file} ready")
            except Exception as e:
                log.error(f"{PSE} Failed to compress audio: {e}")

        Thread(target=compress_audio,
            args=(self._recorder.filename, str(filename)), daemon=True).start()

    def _create_chain(self, name, midi_ch=None):
        midi_ch = self.MIDI_CH if midi_ch is None else midi_ch
        self._chain_id = self._ensure("create soundlib chain",
            self._chain_manager.add_chain, None, midi_chan=midi_ch, title=name)
        self._chain_manager.set_active_chain_by_id(self._chain_id)

    def _create_processor(self, engine):
        if self._current_processor is not None:
            self._ensure("remove current processor from chain",
                self._chain_manager.remove_processor, self._chain_id, self._current_processor)

        self._current_processor = self._ensure("add processor to chain",
            self._chain_manager.add_processor, self._chain_id, engine.spec_name)
        return self._current_processor

    def _ensure(self, desc, func, *args, **kwargs):
        while True:
            retval = func(*args, **kwargs)
            if retval:
                return retval
            log.error(f"{PSE} ERROR: failed to {desc}. Press ENTER to retry.")
            input()

    def _wait_until_ready(self):
        # Check if cpulimit is available, as is needed for ogg convertion
        if shutil.which("cpulimit") is None:
            log.error(f"{PSE} 'cpulimit' command not found. Please install it.")
            raise RuntimeError("'cpulimit' command not found.")

        # Wait until Zynthian is fully initialized
        while True:
            if zynthian_gui_config.zyngui is not None:
                break
            time.sleep(0.5)

        # Give the system some time to breathe...
        time.sleep(2)

        self._zyngui = zynthian_gui_config.zyngui
        self._chain_manager = self._zyngui.chain_manager

        log.info(f"{PS1} Controller is ready. Press ENTER to start.")
        input()

    def _get_sound_level(self):
        last_chan = self._zynmixer.MAX_NUM_CHANNELS - 1
        state = self._zynmixer.get_dpm_states(last_chan, last_chan)[0]
        dpm_a, dpm_b, hold_a, hold_b, mono = state[:5]
        level_a = max(dpm_a, self.LOW_DB) / self.LOW_DB
        level_b = max(dpm_b, self.LOW_DB) / self.LOW_DB
        return 1 - max(level_a, level_b)

    def _get_clip_name_for_preset(self, engine, bank, preset):
        def camel_to_snake(name):
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
            s3 = re.sub(r'\s+', '_', s2)
            return re.sub(r'[^a-z0-9_]', '', s3)

        return "-".join([
            camel_to_snake(engine),
            camel_to_snake(bank),
            camel_to_snake(preset),
        ])
