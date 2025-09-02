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
import sys
import select
import re
import time
import logging
import shutil
import subprocess
import json
import readline  # do not remove!
from uuid import uuid4
from threading import Thread, current_thread
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
from queue import Queue, Empty

from zyncoder.zyncore import lib_zyncore
from zyngine.ctrldev.zynthian_ctrldev_base import zynthian_ctrldev_base
from zyngine import zynthian_lv2
from zyngui import zynthian_gui_config


# Storage directory
STORAGE = Path("./soundlib").absolute()
ex_data_dir = os.environ.get('ZYNTHIAN_EX_DATA_DIR', "/media/root")
exdirs = zynthian_gui_config.get_external_storage_dirs(ex_data_dir)
if exdirs:
    STORAGE = (Path(exdirs[0]) / "soundlib").absolute()

# Global logger
log_level = int(os.environ.get('ZYNTHIAN_LOG_LEVEL', logging.INFO))
log = logging.getLogger("SoundLibCreator")
log.propagate = False
log.setLevel(log_level)
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(log_handler)

# File handler for logger, to save a record of this execution
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
PSP = "::\033[1;34mSndLib\033[0m>"
PSD = "::\033[1;36mSndLib\033[0m>"


# TODO: REPL, add 're-do current', useful if the level is too high, to do a
# stop, adjust mixer, re-do, and keep going

# --------------------------------------------------------------------------
# SoundLib, a library of sounds for Zynthian
# --------------------------------------------------------------------------
class zynthian_ctrldev_sound_scrapper(zynthian_ctrldev_base):
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
            cls._instance = super(zynthian_ctrldev_sound_scrapper, cls).__new__(cls)
        return cls._instance

    def __init__(self, state_manager, idev_in, idev_out):
        if self._initialized:
            return

        super().__init__(state_manager, idev_in, idev_out)
        self._converter = MediaConverter()
        self._creator = SoundLibCreator(state_manager, self._converter)
        self._initialized = True

        # Keep Zynthian on, even when there is no user interaction (as this is an
        # automated tool)
        zynthian_gui_config.power_save_secs = 0


class SoundLibCreator(Thread):
    LOW_DB            = -50
    MIDI_CH           = 9
    SILENCE_THRESHOLD = 0  # in range [0, 1]
    NOTE_NAMES        = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

    # Songs played for melodic instruments, NAME: [bpm, notes]
    SONGS = {
        # Single note, middle C
        "A": [30, "C4"],
        # Cmin arpeggio and Cmin chords
        "B": [60, "C4 Eb4 G4 -, [C4 Eb4 G4]"],
        # I-V-vi-IV chord progression on C major
        "C": [60, "[C4 E4 G4], -2, [G4 B4 D4], -2, [A4 C4 E4], -2, [F4 A4 C4]"],
    }

    def __init__(self, state_manager, converter: "MediaConverter"):
        super().__init__()
        self._state_manager = state_manager
        self._zynmixer = state_manager.zynmixer
        self._recorder = state_manager.audio_recorder
        self._converter = converter

        self._chain_id = None
        self._current_processor = None
        self._current_midi_ch = None
        self._clips_dir = STORAGE / "clips"
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._clips_db = ClipsDB(STORAGE / "clips.json")
        {self._clips_db.define_song(name, spec) for name, spec in self.SONGS.items()}

        self._edit_mode = False
        self._force_overwrite = False

        self.dameon = True
        self.start()

    def run(self):
        self._wait_until_ready()
        self._create_chain("SoundLib")

        try:
            log.info(f"{PS1} Controller is ready. Press ENTER to start, R+ENTER for REPL.")
            log.info(f"{PS1} Press ENTER again (while processing) to begin a REPL.")
            cmd = input().lower().strip()
            if cmd == "r":
                self._process_repl(force=True)

            self._scrap_engines()
        except SystemExit:
            pass

        self._converter.wait_until_finish()
        self._clips_db.save()
        if self._edit_mode:
            self._process_edit_mode()

        self._clips_db.print_stats()
        log.info(f"{PS1} Finished! You can now CLOSE this app (Ctrl+C).")
        os.system('stty sane')  # Recover echo stealed by readline in input()

    def _process_repl(self, force=False):
        if not force:
            request, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not request:
                return
            sys.stdin.readline()

        log.info(f"{PS1} REPL mode entered")
        self._converter.wait_until_finish()
        log.info(f"{PS1} Ready. Send 'h' for help, 'c' to continue, 'q' to exit.")

        while True:
            cmd = input(f"{PSP} ").lower().strip()
            if cmd == "c":
                return
            elif cmd == "h":
                log.info("Available options:")
                log.info("  h  - Show this help message")
                log.info("  st - Print current DB stats")
                log.info("  cl - Scan DB and clean orphaned .ogg files")
                log.info("  e  - Enter EDIT mode")
                log.info("  c  - Continue processing")
                log.info("  q  - Quit")

            elif cmd == "cl":
                self._clips_db.remove_unlinked_media()

            elif cmd == "st":
                self._clips_db.print_stats()

            elif cmd == "q":
                sys.exit()

            elif cmd == "e":
                self._edit_mode = True
                sys.exit()

            else:
                log.error(f"{PSE} Command not found.")

    def _process_edit_mode(self):
        log.info("\n" + "=" * 50)
        log.info(f"{PS1} EDIT mode entered. Here you can record specific engines/presets/notes..")
        log.info(f"{PS1} Send 'h' for a list of available actions.")

        while True:
            cmd = input(f"{PSD} ").strip()
            if cmd == "h":
                log.info("Available options:")
                log.info("  h  - Show this help message")
                log.info("  p  - Proccess an engine, preset or note. Use '-f' to force.")
                log.info("       Format: engine [[[|| bank] || preset] || NOTE1[,NOTE2...]]")
                log.info("  cl - Scan DB and clean orphaned .ogg files")
                log.info("  q  - Quit")

            elif cmd == "q":
                break

            elif cmd == "cl":
                self._clips_db.remove_unlinked_media()

            elif cmd.startswith("p"):
                fields = cmd.split()
                self._force_overwrite = "-f" in fields
                if (self._force_overwrite and len(fields) < 3) or (len(fields) < 2):
                    log.error(f"{PSE} Invalid command syntax. Send 'h' for help.")
                    continue
                if self._force_overwrite:
                    fields.remove("-f")
                self._scrap_by_name(" ".join(fields[1:]))

            else:
                log.error(f"{PSE} Command not found.")

        log.info(f"{PS1} Exiting EDIT mode...")
        log.info("=" * 50 + "\n")

    def _scrap_by_name(self, spec):
        r_engine, r_bank, r_preset, r_notes = (spec.split("||") + [None] * 4)[:4]
        if r_notes is not None:
            r_notes = [self._to_midi_numbers([n])[0] for n in r_notes.split(",")]

        self._scrap_engines(r_engine, r_bank, r_preset, r_notes)
        self._converter.wait_until_finish()

    def _scrap_engines(self, r_engine=None, r_bank=None, r_preset=None, r_notes=None):
        if r_engine is not None:
            for engine in self._get_engine_list():
                if engine.name != r_engine:
                    continue
                if not engine.enabled:
                    log.warning(f"{PSW} Skipping engine '{engine.name}' as its not enabled")
                else:
                    self._record_clips(engine, r_bank, r_preset, r_notes)
                break
            else:
                log.error(f"{PSE} ERROR: Given engine '{r_engine}' not found!")
            return

        for engine in self._get_engine_list():
            if not engine.enabled:
                log.warning(f"{PSW} Skipping engine '{engine.name}' as its not enabled")
                continue
            self._record_clips(engine, r_bank, r_preset, r_notes)

    def _get_engine_list(self):
        # FIXME: shall we include other categories? (Audio Generator, Effects, etc.)
        for idx, (name, spec) in enumerate(zynthian_lv2.engines_by_type["MIDI Synth"].items()):
            engine = SimpleNamespace(spec_idx=idx, spec_name=name, channel=self.MIDI_CH,
                **{k.lower():v for k, v in spec.items()})

            # ADLplug has an aditional percussion kit on channel 10
            if engine.name == "ADLplug":
                engine.name = f"{engine.name}_CH0"
                engine.channel = 0
                engine.cat = "Synth"
                yield engine
                engine.name = f"{engine.name}_CH10"
                engine.channel = 9
                engine.cat = "Percussion"
                yield engine
                continue

            yield engine

    def _iter_over_presets(self, processor, r_bank=None, r_preset=None):
        self._process_repl()

        banks = processor.get_bank_list()
        for bank_idx, bank in enumerate(banks):
            bank_name = bank[2]
            if not bank_name or bank_name == "None":
                bank_name = "Default"

            if r_bank is not None and bank_name != r_bank:
                continue
            if bank[0] == "*FAVS*":  # Skip favorites pseudo-bank
                continue

            processor.set_bank(bank_idx)
            processor.load_preset_list()

            for preset in processor.preset_list:
                preset_name = preset[2]
                if not preset_name or preset_name == "None":
                    preset_name = "Default"
                if r_preset is not None and preset_name != r_preset:
                    continue
                if preset_name[0] == "❤":  # Remove favs marker
                    preset_name = preset_name[1:]

                yield bank_name, preset_name
                self._process_repl()

    # def _load_preset(self, processor, preset_name):
    #     processor.set_preset_by_name(preset_name)

    #     # NOTE: There is a bug (or something), and first note of first preset
    #     # sounds bad; flush it here
    #     # FIXME: maybe, this needs to be done only the first time...
    #     # NOTE: not sure if it only happens when preloading
    #     lib_zyncore.ui_send_note_on(self._current_midi_ch, 60, 0)
    #     time.sleep(0.5)
    #     lib_zyncore.ui_send_note_off(self._current_midi_ch, 60, 0)
    #     self._state_manager.all_sounds_off()

    def _record_clips(self, engine, bank=None, preset=None, notes=None):
        start = time.monotonic()

        if engine.channel != self._current_midi_ch:
            self._chain_manager.set_midi_chan(self._chain_id, engine.channel)
            self._current_midi_ch = engine.channel

        self._clips_db.define_engine(engine)
        if engine.cat.lower() == "percussion":
            self._record_rhythmic_samples(engine, bank, preset, notes)
        elif engine.cat.lower() in ("synth", "organ", "piano"):
            self._record_melodic_samples(engine, bank, preset)
        else:
            log.error(f"{PSE} Skipping engine ({engine.name}), "
                f"unknown cat: {engine.cat}")
            return

        elapsed = int(time.monotonic() - start)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        log.info(f"{PS1} Engine '{engine.name}' processed (took {h}h {m}m {s}s)")

    def _record_rhythmic_samples(self, engine, bank=None, preset=None, notes=None):
        log.info(f"{PS1} Processing '{engine.name}' as rhythmic")

        processor = self._create_processor(engine)
        for idx, (bank, preset) in enumerate(self._iter_over_presets(processor, bank, preset)):
            log.info(f" - Looking for instruments in {bank} > {preset}...")

            # If not given, iterate over every 127 possible notes, to find all instruments
            if notes is None:
                notes = list(range(127))

            counter = 0
            for note in notes:
                self._process_repl()
                print(f"   [note: {note}/127] ...\r", end="", flush=True)
                note_name = self._midi_note_to_name(note)
                instrument = f"{preset}_{note_name}"
                if not self._force_overwrite:
                    if self._clips_db.exists(engine.name, bank, instrument):
                        log.info(f" - Skipping existing instrument {idx}: {bank} > {instrument}")
                        continue
                # self._load_preset(processor, preset)
                processor.set_preset_by_name(preset)
                if not self._has_instrument(note):
                    continue

                log.info(f" - Recording instrument {idx}: {bank} > {instrument}")
                name = self._get_clip_name_for_preset(engine.name, bank, instrument)
                song = self._record_rhythmic(name, note_name)
                clip = {"note": note_name, "song": song}
                self._clips_db.add_clips(engine.name, bank, instrument, clip)
                counter += 1

                self._converter_breathe()

            log.info(f" - {len(notes)} notes scanned, found {counter} instruments.")

    def _record_melodic_samples(self, engine, bank=None, preset=None):
        log.info(f"{PS1} Processing '{engine.name}' as melodic")

        processor = self._create_processor(engine)
        for idx, (bank, preset) in enumerate(self._iter_over_presets(processor, bank, preset)):
            if not self._force_overwrite:
                if self._clips_db.exists(engine.name, bank, preset):
                    log.info(f"  - Skipping existing preset {idx}: {bank} > {preset}")
                    continue
            log.info(f" - Recording preset {idx}: {bank} > {preset}")
            # self._load_preset(processor, preset)
            processor.set_preset_by_name(preset)
            name = self._get_clip_name_for_preset(engine.name, bank, preset)
            songs = self._record_melodic(name)
            self._clips_db.add_clips(engine.name, bank, preset, songs)

            self._converter_breathe()

    def _record_melodic(self, name):
        clips = {}
        for song_name, spec in self.SONGS.items():
            bpm, notes = spec
            filename = self._clips_dir / f"{name}-{song_name}.ogg"
            self._record_song(notes, bpm=bpm, filename=filename)
            clips[song_name] = filename.relative_to(STORAGE)
        return clips

    def _record_rhythmic(self, name: str, note: str):
        filename = self._clips_dir / f"{name}.ogg"
        self._record_song(note, bpm=60, filename=filename, vel=127)
        return filename.relative_to(STORAGE)

    def _record_song(self, song, bpm, filename: Path, vel=60):
        # Some examples:
        # - 'C4', a single C4 sustained all the bar
        # - 'C4 E4 G4 -', a Cmaj chord, arpeggiated in a bar (with a final rest)
        # - '[C5 Eb5 G5]', a Cmin chord sustained all the bar
        # - '[C3 E3 G3], G5', a Cmaj chor and a G note, along two bars
        # - '-, -2', a rest of one bar, and a rest of half bar

        self._wait_for_silence(force=True)
        self._start_recording()
        # NOTE: Keep a silence at the beggining, it can be stripped of later
        time.sleep(0.6)

        log.info(f"  - 🔴 REC: '{song}', file: {filename.name}")
        bars = map(str.strip, song.split(","))
        for bar in bars:
            is_chord = False
            if bar.startswith("["):
                is_chord = True
                bar = bar[1:-1]
            notes = map(str.strip, bar.split())
            notes = self._to_midi_numbers(notes)
            self._play_notes(notes, is_chord, bpm, vel)

        self._wait_for_silence()
        self._stop_recording(filename)

    def _to_midi_numbers(self, notes):
        midi_notes = []
        note_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
        for note in notes:
            if note.startswith("-"):
                midi_notes.append(int(note) if len(note) == 2 else -1)
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
                if note >= 0:
                    lib_zyncore.ui_send_note_on(self._current_midi_ch, note, vel)
            time.sleep(duration)
            for note in bar:
                if note >= 0:
                    lib_zyncore.ui_send_note_off(self._current_midi_ch, note, 0)
        else:
            for note in bar:
                note_length = duration / len(bar)
                if note >= 0:
                    lib_zyncore.ui_send_note_on(self._current_midi_ch, note, vel)
                else:
                    note_length /= abs(note)
                time.sleep(note_length)
                if note >= 0:
                    lib_zyncore.ui_send_note_off(self._current_midi_ch, note, 0)

    def _wait_for_silence(self, force=False):
        if force:
            self._state_manager.all_notes_off()
            self._state_manager.all_sounds_off()

        start = time.monotonic()
        while True:
            if self._get_sound_level() <= self.SILENCE_THRESHOLD:
                return
            time.sleep(0.1)

            # Keep waiting up to N seconds, otherwise force silence
            if time.monotonic() - start > 10:
                self._state_manager.all_notes_off()
                self._state_manager.all_sounds_off()
                time.sleep(0.3)
                return

    def _has_instrument(self, note):
        # Wait for silence, play note, and check levels in the following time. If not levels,
        # it means that there is no instrument there
        self._wait_for_silence(True)
        lib_zyncore.ui_send_note_on(self._current_midi_ch, note, 127)
        levels = []
        for _ in range(3):
            time.sleep(0.1)
            levels.append(self._get_sound_level())
        lib_zyncore.ui_send_note_off(self._current_midi_ch, note, 0)
        self._wait_for_silence(True)
        return sum(levels) > 0.05

    def _start_recording(self):
        if not self._recorder.start_recording():
            log.error(f"{PSE} ERROR: could not start recording engine!")
            return
        time.sleep(0.3)

    def _stop_recording(self, filename: Path):
        self._recorder.stop_recording()
        source = Path(self._recorder.filename)
        if not source.exists():
            log.error(f"{PSE} ERROR: record file '{source}' does not exist!")
            return
        self._converter.add(source, filename)

    def _create_chain(self, name, midi_ch=None):
        if self._chain_id is not None:
            log.error(f"{PSE} ERROR: chain already created!")
            return

        midi_ch = self.MIDI_CH if midi_ch is None else midi_ch
        self._chain_id = self._ensure("create soundlib chain",
            self._chain_manager.add_chain, None, midi_chan=midi_ch, title=name)
        self._chain_manager.set_active_chain_by_id(self._chain_id)
        self._current_midi_ch = midi_ch

    def _create_processor(self, engine):
        if self._current_processor is not None:
            self._ensure("remove current processor from chain",
                self._chain_manager.remove_processor, self._chain_id, self._current_processor)

        self._current_processor = self._ensure("add processor to chain",
            self._chain_manager.add_processor, self._chain_id, engine.spec_name)
        return self._current_processor

    def _converter_breathe(self):
        if self._converter.is_overloaded():
            log.warning(f"{PSW} Too much work for the converter!")
            self._converter.wait_until_finish()
            log.info(f"{PS1} Ok, let's keep going!")

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

    def _get_sound_level(self):
        last_chan = self._zynmixer.MAX_NUM_CHANNELS - 1
        state = self._zynmixer.get_dpm_states(last_chan, last_chan)[0]
        dpm_a, dpm_b, hold_a, hold_b, mono = state[:5]
        level_a = max(dpm_a, self.LOW_DB) / self.LOW_DB
        level_b = max(dpm_b, self.LOW_DB) / self.LOW_DB
        return 1 - max(level_a, level_b)

    def _get_clip_name_for_preset(self, engine, bank, preset):
        return str(uuid4())

    def _midi_note_to_name(self, note):
        octave = (note // 12) - 1
        note_name = self.NOTE_NAMES[note % 12]
        return f"{note_name}{octave}"


class MediaConverter(Thread):
    def __init__(self):
        super().__init__()

        if shutil.which("cpulimit") is None:
            log.error(f"{PSE} 'cpulimit' command not found. Please install it.")
            raise RuntimeError("'cpulimit' command not found.")

        self._tasks = Queue()
        self._remaining = 0
        self._running_p = None
        self._finished = False
        self._parent_t = current_thread()

        self.daemon = False
        self.start()

    def add(self, source: Path, destination: Path):
        self._tasks.put((source, destination))
        self._remaining += 1

    def is_overloaded(self):
        return self._remaining > 5

    def run(self):
        while not self._finished:
            try:
                src, dst = self._tasks.get(timeout=0.25)
                self._remaining = max(0, self._remaining - 1)
                self._handle_request(src, dst)
                self._tasks.task_done()
            except Empty:
                if not self._parent_t.is_alive():
                    break

        if not self._tasks.empty():
            log.warning(f"{PSW} WARNING: There are pending files to be converted!")

    def wait_until_finish(self):
        if self._remaining > 0:
            log.info(f"{PS1} Waiting for converter to finish...")
        self._tasks.join()

    def _handle_request(self, input_file: Path, output_file: Path):
        # NOTE: Limit resources heavily to avoid xruns on jack
        try:
            cmd = (
                "nice -n 15 cpulimit -l 25 -f -- "
                f"ffmpeg -y -i '{input_file}' "

                # remove silence > 0.2s at the start
                "-af \"silenceremove=start_periods=1:start_silence=0.2:start_threshold=-50dB,"

                # remove silence > 0.2s at the end
                # "areverse,"
                # "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-50dB,"
                # "areverse,"

                # normalize
                "loudnorm=I=-16:TP=-1.5:LRA=11\" "

                # store using the Opus codec
                f"-c:a libopus -threads 2 '{output_file}'"
            )
            self._running_p = subprocess.Popen(cmd, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

            while True:
                try:
                    if self._running_p.wait(0.25) == 0:
                        log.info(f"  - {output_file} ready (remains: {self._remaining})")

                    # If result file size is very small, then it must be a problem
                    stat = output_file.stat()
                    if stat.st_size < 850:
                        log.error(f"{PSE} ERROR: File size is too small ({stat.st_size} bytes), corrupt file?")
                        log.error(f"{PSE} Removing file '{output_file}'...")
                        log.error(f"{PSE} Keeping the original ({input_file}).")
                        os.remove(output_file)
                    else:
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
    SONG_NAMES = list(SoundLibCreator.SONGS.keys()) + ["song"]

    def __init__(self, filename: Path, auto_save: int = 30):
        self._filename = filename
        self._autosave_time = auto_save
        self._last_saved = 0
        self._last_snapshot = 0
        self._snapshots_dir = self._filename.parent / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._dirty = False

        self._engines = {}
        self._clips = {}
        self._songs = {}
        self._stats = dict(clips=0, engines=0, banks=0)

        if self._filename.exists():
            self.load()

    def define_engine(self, engine: SimpleNamespace):
        keys = [
            "name", "type", "cat", "url", "descr",
            "quality", "complex", "spec_idx"
        ]

        values = vars(engine)
        self._engines[engine.name] = {k:values[k] for k in keys}
        self._dirty = True
        self.save(auto=True)

    def define_song(self, name, spec):
        self._songs[name] = dict(bpm=spec[0], notes=spec[1])
        self._dirty = True

    def add_clips(self, engine_n: str, bank_n: str, preset_n: str, clips: dict):
        def_engine = {}
        def_bank = {}

        engine = self._clips.setdefault(engine_n, def_engine)
        bank = engine.setdefault(bank_n, def_bank)
        replaced = preset_n in bank
        bank[preset_n] = clips

        if "note" in clips and preset_n.endswith(f"_{clips['note']}"):
            preset_n = preset_n[:-len(f"_{clips['note']}")]

        clips["tags"] = TagClassifer.extract_tags(engine_n, bank_n, preset_n)

        if engine == def_engine:
            self._stats["engines"] += 1
        if bank == def_bank:
            self._stats["banks"] += 1
        if not replaced:
            self._stats["clips"] += 1

        self._dirty = True
        self.save(auto=True)

    def exists(self, engine: str, bank: str, preset: str):
        clips = self._clips.get(engine, {}).get(bank, {}).get(preset)
        if clips is None:
            return False
        if not isinstance(clips, dict) or len(clips) < 1:
            return False
        for k, v in clips.items():
            if not isinstance(v, str):
                continue
            if k not in self.SONG_NAMES:
                continue
            path = STORAGE / (v or "/must-not-exist")
            if not path.exists():
                return False
        return True

    def load(self):
        with self._filename.open("r") as src:
            data = json.load(src)

        for field in ["engines", "clips", "songs"]:
            value = data.get(field)
            if value is None:
                log.error(f"{PSW} ERROR: loading DB from {self._filename}, missing '{field}'!")
                value = {}
            setattr(self, f"_{field}", value )

        # Update stats after loading
        self._stats["engines"] = len(self._clips)
        self._stats["banks"] = sum(len(engine) for engine in self._clips.values())
        self._stats["clips"] = sum(
            len(banks)
            for engine in self._clips.values()
            for banks in engine.values()
        )
        log.info(f"{PS1} Loaded DB, stats: {self._stats}")
        self._dirty = False

    def save(self, auto=False):
        if not self._dirty:
            return

        if auto:
            elapsed = time.monotonic() - self._last_saved
            if elapsed < self._autosave_time:
                return

        data = {
            "engines": self._engines,
            "clips": self._clips,
            "songs": self._songs,
            "meta": dict(
                date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                stats=self._stats,
            )
        }

        bkup = self._filename.with_suffix(self._filename.suffix + ".old")
        if self._filename.exists():
            shutil.copy(self._filename, bkup)

        try:
            with self._filename.open("w") as dst:
                json.dump(data, dst, indent=3, ensure_ascii=False, default=str)
                self._dirty = False
        except Exception as err:
            log.error(f"{PSE} ERROR: Could not save DB to disk: {err}")
            if bkup.exists():
                shutil.copy(bkup, self._filename)

        # Create a new snapshot of the DB (each 5 mins)
        if time.monotonic() - self._last_snapshot > 300:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            snapshot = self._snapshots_dir / f"{self._filename.stem}_{ts}.json"
            shutil.copy(self._filename, snapshot)
            self._last_snapshot = time.monotonic()

        size = f"{self._filename.stat().st_size:,}".replace(",", ".")
        log.info(f"{PS1} Clips DB saved (size: {size} bytes)")
        self._last_saved = time.monotonic()
        bkup.unlink()

    def print_stats(self):
        log.info(f"{PS1} Current DB, stats: {self._stats}")

    def remove_unlinked_media(self):
        log.info(f"{PS1} Scanning for unused media files...")
        clip_files = set()
        for engine in self._clips.values():
            for bank in engine.values():
                for preset in bank.values():
                    for song in self.SONG_NAMES:
                        if song in preset:
                            path = Path(preset[song])
                            clip_files.add(path.name)

        media_dir = STORAGE / "clips"
        to_remove = []
        for file in media_dir.glob("*.ogg"):
            if file.name not in clip_files:
                to_remove.append(file)

        if not to_remove:
            log.info(f"{PS1} Scan complete. No orphaned files found.")
            return

        answer = input(f"{PSW} {len(to_remove)} files found to remove. Proceed? (y/N) ") == "y"
        if answer:
            for file in to_remove:
                try:
                    file.unlink()
                    log.info(f"{PS1} Removed orphaned file: {file.name}")
                except Exception as e:
                    log.error(f"{PSE} Could not remove {file.name}: {e}")

            log.info(f"{PS1} Clean complete.")
        else:
            log.info(f"{PS1} Clean cancelled, no files removed.")


class TagClassifer:
    KNOWN_TAGS = {
        # Roland
        "tb303", "tr606", "tr707", "tr727", "tr808", "tr909",
        "jp8000", "jp8080", "juno6", "juno60", "juno106",
        "jupiter4", "jupiter6", "jupiter8",
        "sh101",

        # Yamaha
        "dx7", "dx21", "dx100", "tx81z", "cs80",

        # Korg
        "ms20", "poly800", "dw8000", "m1", "wavestation",

        # Sequential / Oberheim
        "prophet5", "prophet6", "prophet10", "prophet12", "obx", "obxa", "ob8",

        # Casio
        "cz101", "cz1000", "vz1",

        # Akai / samplers
        "s950", "s1000", "s3000", "mpc60", "mpc2000", "mpc2500", "mpc3000",

        # Other
        "rd808", "mc202", "esq1", "matrix1000"
    }

    CATEGORIES = {
        # Keyboards
        "piano": ["piano", "ep", "rhodes", "clav", "upright", "grand"],
        "organ": ["organ", "hammond", "tonewheel", "drawbar"],
        "keys": ["key", "keys", "cp80", "wurli"],

        # Synths
        "pad": ["pad", "string", "choir", "vox", "atmo", "amb", "texture"],
        "lead": ["lead", "solo", "synthlead"],
        "bass": ["bass", "sub", "808", "moog", "acid"],
        "arp": ["arp", "sequence", "seq"],
        "poly": ["poly", "chord"],
        "mono": ["mono", "monosynth"],

        # Drums and percussion
        "drums": ["drum", "kit", "perc", "percussion"],
        "kick": ["kick", "bd", "bassdrum"],
        "snare": ["snare", "sd"],
        "hihat": ["hh", "hihat", "closed", "openhat"],
        "cymbal": ["cymbal", "ride", "crash", "splash"],
        "tom": ["tom", "toms"],
        "clap": ["clap"],
        "fxdrums": ["rim", "cowbell", "clave", "woodblock"],

        # Acoustic instruments
        "guitar": ["guitar", "acoustic", "strum", "plucked"],
        "electric_guitar": ["eguitar", "dist", "overdrive", "powerchord"],
        "bass_guitar": ["ebass", "bassguitar", "slap"],
        "strings": ["violin", "viola", "cello", "contrabass", "strings"],
        "brass": ["trumpet", "trombone", "horn", "brass"],
        "woodwind": ["flute", "clarinet", "oboe", "bassoon", "sax"],
        "ethnic": ["sitar", "koto", "shamisen", "oud", "erhu", "duduk"],

        # Mallets and tonal percussion
        "bell": ["bell", "mallet", "xylophone", "vibe", "celesta", "glock", "tubular"],
        "chime": ["chime", "windchime", "tinkle"],
        "marimba": ["marimba", "balafon"],

        # Effects
        "fx": ["fx", "effect", "noise", "sweep", "rise", "fall", "impact", "hit"],
        "soundscape": ["dron", "drone", "ambient", "scape", "cinematic"],
        "vox": ["vox", "voice", "vocal", "choir", "shout"],
        "hitstab": ["stab", "hit", "orchestra hit"],
        "riser": ["riser", "uplifter", "build"],
        "downer": ["downer", "fall", "drop"],

        # Specific electronic
        "chiptune": ["chip", "8bit", "gameboy", "sid"],
        "trance": ["supersaw", "trance", "plucksaw"],
        "house": ["house", "deep", "tech"],
        "techno": ["techno", "acid"],
        "dubstep": ["dubstep", "wobble", "growl"],
        "trap": ["trap", "808", "hi-hat triplet"],

        # Etnic percussion
        "latin": ["conga", "bongo", "timbale", "cuica"],
        "african": ["djembe", "talkingdrum"],
        "middle_east": ["darbuka", "doumbek", "tabla"],
        "asian": ["taiko", "gong", "koto"],
    }

    BLACK_LIST = [
        "bank", "default", "of", "in", "at", "the", "on", "a", "an", "and", "or", "for",
        "to", "with", "by", "from", "is", "are", "was", "were", "be", "been", "has",
        "have", "had", "it", "this", "that", "these", "those", "as", "but", "if", "then",
        "so", "than", "too", "very", "just", "not", "no", "yes", "do", "does", "did",
        "can", "could", "will", "would", "shall", "should", "may", "might", "must", "such",
        "which", "who", "whom", "whose", "what", "when", "where", "why", "how",
        "all", "any", "some", "each", "every", "either", "neither", "both", "few", "many",
        "more", "most", "other", "another", "much", "own", "same", "new", "old", "first",
        "last", "next", "previous", "again", "once", "here", "there", "out", "up", "down",
        "over", "under", "into", "about", "after", "before", "between", "during", "without",
        "within", "above", "below", "off", "across", "through", "around", "outside",
        "inside", "upon", "per", "via",
    ]

    @classmethod
    def extract_tags(cls, engine, bank, preset):
        tags = {f"engine:{engine.split('/')[-1].lower()}"}
        words = set()

        bank_parts = re.findall(r'[A-Z]?[a-z]+|\d+', bank)
        for bp in bank_parts:
            tag = bp.lower()
            if tag.isdigit() or tag in cls.BLACK_LIST:
                continue
            words.add(tag)

        preset_clean = preset.split(":", 1)[-1].strip()
        preset_parts = re.findall(r'[A-Z]?[a-z]+|\d+', preset_clean)
        for pp in preset_parts:
            tag = pp.lower()
            if tag.isdigit() and tag not in cls.KNOWN_TAGS:
                continue
            if tag in cls.BLACK_LIST:
                continue
            words.add(tag)

        for cat, keywords in cls.CATEGORIES.items():
            for kw in keywords:
                if any(kw in t for t in words):
                    tags.add(cat)
                    break

        return sorted(tags)
