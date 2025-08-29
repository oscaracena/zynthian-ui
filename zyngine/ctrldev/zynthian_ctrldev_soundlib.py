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
import json
from threading import Thread, current_thread
from pathlib import Path
from collections import namedtuple
from datetime import datetime
from queue import Queue, Empty
from typing import NamedTuple

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
        self._converter = MediaConverter()
        self._creator = SoundLibCreator(state_manager, self._converter)
        self._initialized = True


class SoundLibCreator(Thread):
    LOW_DB            = -50
    MIDI_CH           = 9
    SILENCE_THRESHOLD = 0.2  # in range [0, 1]

    def __init__(self, state_manager, converter: "MediaConverter"):
        super().__init__()
        self._state_manager = state_manager
        self._zynmixer = state_manager.zynmixer
        self._recorder = state_manager.audio_recorder
        self._converter = converter

        self._chain_id = None
        self._current_processor = None
        self._clips_dir = STORAGE / "clips"
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._clips_db = ClipsDB(STORAGE / "clips.json")

        self.dameon = True
        self.start()

    def run(self):
        self._wait_until_ready()
        self._create_chain("SoundLib")

        for engine in self._get_engine_list():
            self._clips_db.define_engine(engine)
            if engine.cat.lower() == "percussion":
                self._record_rhythmic_samples(engine)
            elif engine.cat.lower() == "synth":
                self._record_melodic_samples(engine)
            else:
                log.warning(f"{PSW} Skipping engine ({engine.spec_name}), "
                    f"unknown cat: {engine.cat}")

            break

        log.info(f"{PS1} Done! Waiting for converter to finish...")
        self._converter.wait_until_finish()
        self._clips_db.save()
        log.info(f"{PS1} Finished! You can now close this app.")

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
            if self._clips_db.exists(engine.spec_name, bank, preset):
                log.info(f"- Skipping existing preset {idx}: {bank} > {preset}")
                continue
            log.info(f"- Recording preset {idx}: {bank} > {preset}")
            name = self._get_clip_name_for_preset(engine.name, bank, preset)
            songs = self._record_melodic(name)
            self._clips_db.add_clips(engine.spec_name, bank, preset, songs)

            # FIXME!! REMOVE!!!
            if idx >= 10: return

    def _record_melodic(self, name):
        songs = {
            # Single note, C
            "A": dict(
                content="C4", clip=None),

            # Cmaj arpeggio and Cmin chord
            "B": dict(
                content="C4 Eb4 G4 -, [C4 Eb4 G4]",
                clip=None),

            # I-V-vi-IV chord progression on C major
            "C": dict(
                content="[C4 E4 G4], -, [G4 B4 D4], -, [A4 C4 E4], -, [F4 A4 C4]",
                clip=None),
        }

        for idx, song in songs.items():
            filename = self._clips_dir / f"{name}-{idx}.ogg"
            self._record_song(song["content"], bpm=30, filename=filename)
            song["clip"] = filename.relative_to(STORAGE)

        return songs

    def _record_song(self, song, bpm, filename: Path):
        # Some examples:
        # - 'C4', a single C4 sustained all the bar
        # - 'C4 E4 G4 -', a Cmaj chord, arpeggiated in a bar (with a final rest)
        # - '[C5 Eb5 G5]', a Cmin chord sustained all the bar
        # - '[C3 E3 G3], G5', a Cmaj chor and a G note, along two bars

        self._wait_for_silence(force=True)
        self._start_recording()

        log.info(f"  - 🔴 REC: '{song}', file: {filename.name}")
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

    def _play_notes(self, bar, as_chord=False, tempo=60, vel=60):
        duration = 60 / tempo

        if as_chord:
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_on(self.MIDI_CH, note, vel)
            time.sleep(duration)
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_off(self.MIDI_CH, note, 0)
        else:
            for note in bar:
                if note is not None:
                    lib_zyncore.ui_send_note_on(self.MIDI_CH, note, vel)
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

    def _stop_recording(self, filename: Path):
        self._recorder.stop_recording()
        source = Path(self._recorder.filename)
        if not source.exists():
            log.error(f"{PSE} ERROR: record file '{source}' does not exists!")
            return
        self._converter.add(source, filename)

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


class MediaConverter(Thread):
    def __init__(self):
        super().__init__()

        if shutil.which("cpulimit") is None:
            log.error(f"{PSE} 'cpulimit' command not found. Please install it.")
            raise RuntimeError("'cpulimit' command not found.")

        self._tasks = Queue()
        self._running_p = None
        self._finished = False
        self._parent_t = current_thread()

        self.daemon = False
        self.start()

    def add(self, source: Path, destination: Path):
        self._tasks.put((source, destination))

    def run(self):
        while not self._finished:
            try:
                src, dst = self._tasks.get(timeout=0.25)
                self._handle_request(src, dst)
                self._tasks.task_done()
            except Empty:
                if not self._parent_t.is_alive():
                    break

        if not self._tasks.empty():
            log.warning(f"{PSW} WARNING: There are pending files to be converted!")

    def wait_until_finish(self):
        self._tasks.join()

    def _handle_request(self, input_file: Path, output_file: Path):
        # NOTE: Limit resources heavily to avoid xruns on jack
        try:
            cmd = (
                f"nice -n 15 cpulimit -l 25 -f -- "
                f"ffmpeg -y -i '{input_file}' -c:a libopus -threads 2 '{output_file}'"
            )
            self._running_p = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            while True:
                try:
                    if self._running_p.wait(0.25) == 0:
                        log.info(f"  - {output_file} ready (remains: {self._tasks.qsize()})")
                    os.remove(input_file)
                    break
                except subprocess.TimeoutExpired:
                    if self._parent_t.is_alive():
                        continue

                    self._finished = False
                    self._running_p.terminate()
                    try:
                        self._running_p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._running_p.kill()
                    break

        except Exception as e:
            log.error(f"{PSE} Failed to compress audio: {e}")
        finally:
            self._running_p = None


class ClipsDB:
    def __init__(self, filename: Path, auto_save: int = 30):
        self._filename = filename
        self._autosave_time = auto_save
        self._last_saved = 0

        self._engines = {}
        self._clips = {}

        if self._filename.exists():
            self.load()

    def define_engine(self, engine: NamedTuple):
        keys = [
            "name", "title", "type", "cat", "url", "descr",
            "quality", "complex", "spec_idx"
        ]
        values = engine._asdict()
        self._engines[engine.spec_name] = {k:values[k] for k in keys}
        self.save(auto=True)

    def add_clips(self, engine: str, bank: str, preset: str, clips: Path):
        self._clips.setdefault(engine, {}).setdefault(bank, {})[preset] = clips
        self.save(auto=True)

    def exists(self, engine: str, bank: str, preset: str):
        clips = self._clips.get(engine, {}).get(bank, {}).get(preset)
        if clips is None:
            return False
        if not isinstance(clips, dict) or len(clips) < 1:
            return False
        for song in clips.values():
            path = STORAGE / song.get("clip", "/not-exists")
            if not path.exists():
                return False
        return True

    def load(self):
        with self._filename.open("r") as src:
            data = json.load(src)

        self._engines = data.get("engines")
        self._clips = data.get("clips")

        if self._engines is None:
            log.error(f"{PSW} ERROR: loading DB from {self._filename}, missing 'engines'!")
            self._engines = {}
        if self._clips is None:
            log.error(f"{PSW} ERROR: loading DB from {self._filename}, missing 'clips'!")
            self._clips = {}

    def save(self, auto=False):
        if auto:
            elapsed = time.monotonic() - self._last_saved
            if elapsed < self._autosave_time:
                return

        bkup = self._filename.with_suffix(self._filename.suffix + ".old")
        data = {
            "engines": self._engines,
            "clips": self._clips,
        }

        if self._filename.exists():
            shutil.copy(self._filename, bkup)
        try:
            with self._filename.open("w") as dst:
                json.dump(data, dst, indent=3, ensure_ascii=False, default=str)
        except Exception as err:
            log.error(f"{PSE} ERROR: Could not save DB to disk: {err}")
            if bkup.exists():
                shutil.copy(bkup, self._filename)
