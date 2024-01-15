#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
#
# Zynthian GUI Step-Sequencer Pad Trigger Class
#
# Copyright (C) 2015-2023 Fernando Moyano <jofemodo@zynthian.org>
#                         Brian Walton <brian@riban.co.uk>
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

import tkinter
import logging
from time import sleep
from PIL import Image, ImageTk
from threading import Timer

# Zynthian specific modules
import zynautoconnect
from zynlibs.zynseq import zynseq
from zyncoder.zyncore import lib_zyncore
from zyngine.zynthian_signal_manager import zynsigman

from . import zynthian_gui_base
from zyngui import zynthian_gui_config
from zyngui.zynthian_gui_patterneditor import EDIT_MODE_NONE


SELECT_BORDER = zynthian_gui_config.color_on
INPUT_CHANNEL_LABELS = ['OFF', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16']
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ------------------------------------------------------------------------------
# Zynthian Step-Sequencer Sequence / Pad Trigger GUI Class
# ------------------------------------------------------------------------------

# Class implements step sequencer
class zynthian_gui_zynpad(zynthian_gui_base.zynthian_gui_base):

	# Function to initialise class
	def __init__(self):
		logging.getLogger('PIL').setLevel(logging.WARNING)

		super().__init__()

		# Zynthian Core objects
		self.state_manager = self.zyngui.state_manager
		self.zynseq = self.state_manager.zynseq
		self.chain_manager = self.state_manager.chain_manager

		self.ctrl_order = zynthian_gui_config.layout['ctrl_order']
		self.selected_pad = 0  # Index of selected pad
		self.redraw_pending = 2  # 0=no refresh pending, 1=update grid, 2=rebuild grid
		self.redrawing = False  # True to block further redraws until complete
		self.bank = self.zynseq.bank  # The last successfully selected bank - used to update stale views
		self.columns = self.zynseq.col_in_bank  # Columns used during last layout - used to update stale views
		self.midi_learn = False
		self.trigger_channel = 0
		self.ctrldev = None

		# Geometry vars
		self.select_thickness = 1 + int(self.width / 400) # Scale thickness of select border based on screen
		self.column_width = self.width / self.zynseq.col_in_bank
		self.row_height = self.height / self.zynseq.col_in_bank

		# Pad grid
		self.grid_canvas = tkinter.Canvas(self.main_frame,
			width=self.width,
			height=self.height,
			bd=0,
			highlightthickness=0,
			bg = zynthian_gui_config.color_bg)
		self.main_frame.columnconfigure(0, weight=1)
		self.main_frame.rowconfigure(0, weight=1)
		self.grid_canvas.grid()
		self.grid_timer = Timer(1.4, self.on_grid_timer) # Grid press and hold timer

		self.build_grid()

	# Function to set values of encoders
	def setup_zynpots(self):
		lib_zyncore.setup_behaviour_zynpot(0, 0)
		lib_zyncore.setup_behaviour_zynpot(1, 0)
		lib_zyncore.setup_behaviour_zynpot(2, 0)
		lib_zyncore.setup_behaviour_zynpot(3, 0)

	# Function to show GUI
	#   params: Misc parameters
	def build_view(self):
		self.zynseq.libseq.updateSequenceInfo()
		self.setup_zynpots()
		self.refresh_status(True)
		if self.param_editor_zctrl == None:
			self.set_title(f"Scene {self.bank}")
		zynsigman.register(zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PLAY_STATE, self.update_play_state)
		zynsigman.register(zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PROGRESS, self.update_progress)

	# Function to hide GUI
	def hide(self):
		if self.shown:
			zynsigman.unregister(zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PLAY_STATE, self.update_play_state)
			zynsigman.unregister(zynsigman.S_STEPSEQ, self.zynseq.SS_SEQ_PROGRESS, self.update_progress)
			super().hide()

	# Function to set quantity of pads
	def set_grid_size(self, value):
		columns = value + 1
		if columns > 8:
			columns = 8
		if self.zynseq.libseq.getSequencesInBank(self.bank) > columns ** 2:
			self.zyngui.show_confirm(f"Reducing the quantity of sequences in bank {self.bank} will delete sequences but patterns will still be available. Continue?", self._set_grid_size, columns)
		else:
			self._set_grid_size(columns)

	def _set_grid_size(self, value):
		self.zynseq.update_bank_grid(value)
		self.refresh_status(force=True)

	# Function to name selected sequence
	def rename_sequence(self, params=None):
		self.zyngui.show_keyboard(self.do_rename_sequence, self.zynseq.get_sequence_name(self.bank, self.selected_pad), 16)

	# Function to rename selected sequence
	def do_rename_sequence(self, name):
		self.zynseq.set_sequence_name(self.bank, self.selected_pad, name)

	def update_layout(self):
		super().update_layout()
		self.redraw_pending = 2
		self.update_grid()

	# Function to create 64 pads
	def build_grid(self):
		columns = 8
		column_width = self.width / columns
		row_height = self.height / columns
		fs1 = int(row_height * 0.15)
		fs2 = int(row_height * 0.11)
		self.selection = self.grid_canvas.create_rectangle(0, 0, int(self.column_width), int(self.row_height), fill="", outline=SELECT_BORDER, width=self.select_thickness, tags="selection")

		self.pads = []
		for pad in range(64):
			pad_struct = {}
			pad_x = int(pad / columns) * column_width
			pad_y = pad % columns * row_height
			header_h = int(0.28 * self.row_height)
			pad_struct["header"] = self.grid_canvas.create_rectangle(pad_x, pad_y, pad_x + self.column_width - 2, pad_y + header_h,
				fill='darkgrey',
				width=0,
				tags=(f"padh:{pad}", "gridcell", f"pad:{pad}", "pad"))
			pad_struct["body"] = self.grid_canvas.create_rectangle(pad_x, pad_y + header_h, pad_x + self.column_width - 2, pad_y + self.row_height - 2,
				fill='grey',
				width=0,
				tags=(f"padb:{pad}", "gridcell", f"pad:{pad}", "pad"))
			posx = pad_x + int(0.02 * self.column_width)
			posy = pad_y + int(0.04 * self.row_height)
			pad_struct["mode"] = self.grid_canvas.create_image(posx + int(0.125 * self.column_width), posy,
				anchor="nw",
				tags=(f"mode:{pad}", f"pad:{pad}", "pad"))
			posy = pad_y + int(0.05 * self.row_height)
			pad_struct["group"] = self.grid_canvas.create_text(posx + int(3 * 0.125 * self.column_width), posy,
				anchor="n",
				font=(zynthian_gui_config.font_family, fs2),
				fill=zynthian_gui_config.color_panel_tx,
				tags=(f"group:{pad}", f"pad:{pad}", "pad"))
			pad_struct["num"] = self.grid_canvas.create_text(posx + int(5 * 0.125 * self.column_width), posy,
				anchor="n",
				font=(zynthian_gui_config.font_family, fs2),
				fill=zynthian_gui_config.color_panel_tx,
				tags=(f"num:{pad}", f"pad:{pad}", "pad"))
			pad_struct["state"] = self.grid_canvas.create_image(posx + int(7 * 0.125 * self.column_width), posy,
				anchor="n",
				tags=(f"state:{pad}", f"pad:{pad}", "pad"))
			posx = pad_x + int(0.03 * self.column_width)
			pad_struct["title"] = self.grid_canvas.create_text(posx, posy + 2 * fs1,
				width=self.column_width - 0.06 * self.column_width,
				anchor="nw", justify="left",
				font=(zynthian_gui_config.font_family, fs1),
				fill=zynthian_gui_config.color_panel_tx,
				tags=(f"title:{pad}", f"pad:{pad}", "pad"))
			pad_struct["progress"] = self.grid_canvas.create_rectangle(0, 0, 0, 0,
				fill='white',
				width=0,
				tags=(f"progress:{pad}", f"pad:{pad}", "pad"))
			self.pads.append(pad_struct)
		self.grid_canvas.tag_bind("pad", '<Button-1>', self.on_pad_press)
		self.grid_canvas.tag_bind("pad", '<ButtonRelease-1>', self.on_pad_release)

		# Icons
		self.empty_icon = tkinter.PhotoImage()
		self.mode_icon = [[] for i in range(9)]
		self.state_icon = [[] for i in range(9)]

		for columns in range(1, 9):
			column_width = self.width / columns
			row_height = self.height / columns
			lst = [self.empty_icon] # Not sure this is right - should be a ImageTk.PhotoImage
			iconsize = (int(column_width * 0.22), int(row_height * 0.2))
			for f in ["zynpad_mode_oneshot", "zynpad_mode_loop", "zynpad_mode_oneshotall", "zynpad_mode_loopall", "zynpad_mode_oneshotsync", "zynpad_mode_loopsync"]:
				img = Image.open(f"/zynthian/zynthian-ui/icons/{f}.png")
				lst.append(ImageTk.PhotoImage(img.resize(iconsize)))
			self.mode_icon[columns] = lst.copy()
			iconsize = (int(row_height * 0.18), int(row_height * 0.18))
			lst = []
			for f in ["stopped", "playing", "stopping", "starting", "restarting", "stopping_sync"]:
				img = Image.open(f"/zynthian/zynthian-ui/icons/{f}.png")
				lst.append(ImageTk.PhotoImage(img.resize(iconsize)))
			self.state_icon[columns] = lst.copy()

	# Function to clear and calculate grid sizes
	def update_grid(self):
		self.redrawing = True
		self.column_width = self.width / self.zynseq.col_in_bank
		self.row_height = self.height / self.zynseq.col_in_bank

		# Update pads location / size
		fs1 = int(self.row_height * 0.15)
		fs2 = int(self.row_height * 0.11)
		self.grid_canvas.itemconfig("pad", state=tkinter.HIDDEN)
		self.update_selection_cursor()
		for col in range(self.zynseq.col_in_bank):
			pad_x = int(col * self.column_width)
			for row in range(self.zynseq.col_in_bank):
				pad_y = int(row * self.row_height)
				pad = row + col * self.zynseq.col_in_bank
				header_h = int(0.28 * self.row_height)
				self.grid_canvas.itemconfig(self.pads[pad]["group"], font=(zynthian_gui_config.font_family, fs2))
				self.grid_canvas.itemconfig(self.pads[pad]["num"], font=(zynthian_gui_config.font_family, fs2))
				self.grid_canvas.itemconfig(self.pads[pad]["title"], width=int(0.96 * self.column_width), font=(zynthian_gui_config.font_family, fs1))
				self.grid_canvas.itemconfig(f"pad:{pad}", state=tkinter.NORMAL)
				self.grid_canvas.coords(self.pads[pad]["header"], pad_x, pad_y, pad_x + self.column_width - 2, pad_y + header_h)
				self.grid_canvas.coords(self.pads[pad]["body"], pad_x, pad_y + header_h, pad_x + self.column_width - 2, pad_y + self.row_height - 2)
				posx = pad_x + int(0.02 * self.column_width)
				posy = pad_y + int(0.04 * self.row_height)
				self.grid_canvas.coords(self.pads[pad]["mode"], posx + int(0.125), posy)
				posy = pad_y + int(0.05 * self.row_height)
				self.grid_canvas.coords(self.pads[pad]["group"], posx + int(3 * 0.125 * self.column_width), posy)
				self.grid_canvas.coords(self.pads[pad]["num"], posx + int(5 * 0.125 * self.column_width), posy)
				self.grid_canvas.coords(self.pads[pad]["state"], posx + int(7 * 0.125 * self.column_width), posy)
				posx = pad_x + int(0.03 * self.column_width)
				self.grid_canvas.coords(self.pads[pad]["title"], posx, posy + 2 * fs1)

		self.redrawing = False
		self.columns = self.zynseq.col_in_bank

	# Function to refresh pad if it has changed
	#  pad: Pad index
	#  mode: Play mode
	#  state: Play state
	#  group: Sequence group
	def refresh_pad(self, pad, mode=None, state=None, group=None):
		if pad > 63:
			return

		# Get pad info if needed
		if mode is None or state is None or group is None:
			state = self.zynseq.libseq.getSequenceState(self.zynseq.bank, pad)
			mode = (state >> 8) & 0xFF
			group = (state >> 16) & 0xFF
			state &= 0xFF
			if state == zynseq.SEQ_RESTARTING:
				state = zynseq.SEQ_PLAYING
			elif state == zynseq.SEQ_STOPPINGSYNC:
				state = zynseq.SEQ_STOPPING

		foreground = "white"
		cellh = self.pads[pad]["header"]
		cellb = self.pads[pad]["body"]
		if self.zynseq.libseq.getSequenceLength(self.bank, pad) == 0 or mode == zynseq.SEQ_DISABLED:
			self.grid_canvas.itemconfig(cellh, fill=zynthian_gui_config.PAD_COLOUR_DISABLED)
			self.grid_canvas.itemconfig(cellb, fill=zynthian_gui_config.PAD_COLOUR_DISABLED_LIGHT)
		else:
			self.grid_canvas.itemconfig(cellh, fill=zynthian_gui_config.PAD_COLOUR_GROUP[group % 16])
			self.grid_canvas.itemconfig(cellb, fill=zynthian_gui_config.PAD_COLOUR_GROUP_LIGHT[group % 16])
		if self.zynseq.libseq.getSequenceLength(self.bank, pad) == 0:
			mode = 0
		group = chr(65 + group)
		#patnum = self.zynseq.libseq.getPatternAt(self.bank, pad, 0, 0)
		midi_chan = self.zynseq.libseq.getChannel(self.bank, pad, 0)
		title = self.zynseq.get_sequence_name(self.bank, pad)
		try:
			str(int(title)) # Test for default (integer index)
			preset_name = self.chain_manager.get_synth_preset_name(midi_chan)
			if preset_name:
				title = preset_name.replace("_", " ")
			else:
				title = ""
		except:
			pass
		self.grid_canvas.itemconfig(self.pads[pad]["title"], text=title, fill=foreground)
		self.grid_canvas.itemconfig(self.pads[pad]["group"], text=f"CH{midi_chan + 1}", fill=foreground)
		self.grid_canvas.itemconfig(self.pads[pad]["num"], text=f"{group}{pad+1}", fill=foreground)
		self.grid_canvas.itemconfig(self.pads[pad]["mode"], image=self.mode_icon[self.zynseq.col_in_bank][mode])
		if state == 0 and self.zynseq.libseq.isEmpty(self.bank, pad):
			self.grid_canvas.itemconfig(self.pads[pad]["state"], image=self.empty_icon)
		else:
			self.grid_canvas.itemconfig(self.pads[pad]["state"], image=self.state_icon[self.zynseq.col_in_bank][state])

	def update_play_state(self, bank, seq, state, mode, group):
		if bank == self.bank:
			self.refresh_pad(seq, mode=mode, state=state, group=group)

	def update_progress(self, bank, seq, progress):
		if bank == self.bank:
			x0 = int(seq / self.columns) * self.column_width
			y0 = (seq % self.columns + 1) * self.row_height - 8
			x1 = x0 + int(progress * self.column_width / 100)
			y1 = y0 + 4
			self.grid_canvas.coords(self.pads[seq]["progress"], x0, y0, x1, y1)


	# ------------------------------------------------------------------------------------------------------------------
	# Some useful functions
	# ------------------------------------------------------------------------------------------------------------------

	def set_bank(self, bank):
		self.zynseq.select_bank(bank)
		self.refresh_status(force=True)

	# ------------------------------------------------------------------------------------------------------------------
	# Trigger MIDI device integration
	# ------------------------------------------------------------------------------------------------------------------

	def sync_state(self):
		self.set_trigger_channel()

	# ------------------------------------------------------------------------------------------------------------------

	# Function to move selection cursor
	def update_selection_cursor(self):
		#TODO: Was update_selection_cursor removed during refactor and replaced during merge?
		if self.selected_pad >= self.zynseq.libseq.getSequencesInBank(self.bank):
			self.selected_pad = self.zynseq.libseq.getSequencesInBank(self.bank) - 1
		col = int(self.selected_pad / self.zynseq.col_in_bank)
		row = self.selected_pad % self.zynseq.col_in_bank
		self.grid_canvas.coords(self.selection,
				1 + col * self.column_width, 1 + row * self.row_height,
				(1 + col) * self.column_width - self.select_thickness, (1 + row) * self.row_height - self.select_thickness)
		self.grid_canvas.tag_raise(self.selection)

	# Function to handle pad press
	def on_pad_press(self, event):
		tags = self.grid_canvas.gettags(self.grid_canvas.find_withtag(tkinter.CURRENT))
		pad = int(tags[0].split(':')[1])
		self.select_pad(pad)
		if self.param_editor_zctrl:
			self.disable_param_editor()
		self.grid_timer = Timer(zynthian_gui_config.zynswitch_bold_seconds, self.on_grid_timer)
		self.grid_timer.start()

	# Function to handle pad release
	def on_pad_release(self, event):
		if self.grid_timer.is_alive():
			self.toggle_pad()
		self.grid_timer.cancel()

	# Function to toggle pad
	def toggle_pad(self):
		self.zynseq.libseq.togglePlayState(self.bank, self.selected_pad)

	# Function to handle grid press and hold
	def on_grid_timer(self):
		self.gridDragStart = None
		self.show_pattern_editor()

	# Function to add menus
	def show_menu(self):
		self.disable_param_editor()
		options = {}

		# Global Options
		if not zynthian_gui_config.check_wiring_layout(["Z2", "V5"]):
			options[f'Tempo ({self.zynseq.libseq.getTempo():0.1f})'] = 'Tempo'
			options[f'Scene ({self.bank})'] = 'Scene'
		if not zynthian_gui_config.check_wiring_layout(["Z2"]):
			options['Arranger'] = 'Arranger'
		options[f'Beats per bar ({self.zynseq.libseq.getBeatsPerBar()})'] = 'Beats per bar'
		options[f'Grid size ({self.zynseq.col_in_bank}x{self.zynseq.col_in_bank})'] = 'Grid size'

		# Single Pad Options
		options['> PAD OPTIONS'] = None
		options[f'Play mode ({zynseq.PLAY_MODES[self.zynseq.libseq.getPlayMode(self.bank, self.selected_pad)]})'] = 'Play mode'
		options[f'MIDI channel ({1 + self.zynseq.libseq.getChannel(self.bank, self.selected_pad, 0)})'] = 'MIDI channel'
		options['Trigger learn'] = 'Trigger learn'

		#options['> MISC'] = None
		options['Rename sequence'] = 'Rename sequence'

		self.zyngui.screens['option'].config("ZynPad Menu", options, self.menu_cb)
		self.zyngui.show_screen('option')

	def toggle_menu(self):
		if self.shown:
			self.show_menu()
		elif self.zyngui.current_screen == "option":
			self.close_screen()

	def menu_cb(self, option, params):
		if params == 'Tempo':
			self.zyngui.show_screen('tempo')
		elif params == 'Arranger':
			self.zyngui.show_screen('arranger')
		elif params == 'Beats per bar':
			self.enable_param_editor(self, 'bpb', 'Beats per bar', {'value_min':1, 'value_max':64, 'value_default':4, 'value':self.zynseq.libseq.getBeatsPerBar()})
		elif params == 'Scene':
			self.enable_param_editor(self, 'bank', 'Scene', {'value_min':1, 'value_max':64, 'value':self.bank})
		elif params == 'Grid size':
			labels = []
			for i in range(1, 9):
				labels.append(f'{i}x{i}')
			self.enable_param_editor(self, 'grid_size', 'Grid size', {'labels': labels, 'value': self.zynseq.col_in_bank - 1, 'value_default': 3}, self.set_grid_size)
		elif params == 'Trigger learn':
			self.zyngui.cuia_enable_midi_learn()
		elif params == 'Play mode':
			self.enable_param_editor(self, 'playmode', 'Play mode', {'labels':zynseq.PLAY_MODES, 'value':self.zynseq.libseq.getPlayMode(self.zynseq.bank, self.selected_pad), 'value_default':zynseq.SEQ_LOOPALL}, self.set_play_mode)
		elif params == 'MIDI channel':
			labels = []
			for midi_chan in range(16):
				preset_name = self.chain_manager.get_synth_preset_name(midi_chan)
				if preset_name:
					labels.append(f"{midi_chan + 1} ({preset_name})")
				else:
					labels.append(f"{midi_chan + 1}")
			self.enable_param_editor(self, 'midi_chan', 'MIDI channel', {'labels': labels, 'value_default': self.zyngui.state_manager.zynseq.libseq.getChannel(self.bank, self.selected_pad, 0), 'value':self.zyngui.state_manager.zynseq.libseq.getChannel(self.bank, self.selected_pad, 0)})
		elif params == 'Rename sequence':
			self.rename_sequence()

	def send_controller_value(self, zctrl):
		if zctrl.symbol == 'bank':
			self.zynseq.select_bank(zctrl.value)
			self.set_title(f"Scene {self.zynseq.bank}")
		elif zctrl.symbol == 'tempo':
			self.zynseq.set_tempo(zctrl.value)
		elif zctrl.symbol == 'metro_vol':
			self.zynseq.libseq.setMetronomeVolume(zctrl.value / 100.0)
		elif zctrl.symbol == 'bpb':
			self.zynseq.libseq.setBeatsPerBar(zctrl.value)
		elif zctrl.symbol == 'playmode':
			self.set_play_mode(zctrl.value)
			#self.refresh_pad(self.selected_pad, force=True) #TODO Is this required?
		elif zctrl.symbol == 'midi_chan':
			self.zynseq.set_midi_channel(self.bank, self.selected_pad, 0, zctrl.value)
			self.zynseq.set_group(self.bank, self.selected_pad, zctrl.value)

	#	Function to set the playmode of the selected pad
	def set_play_mode(self, mode):
		self.zynseq.set_play_mode(self.bank, self.selected_pad, mode)

	# Function to show the editor (pattern or arranger based on sequence content)
	def show_pattern_editor(self):
		tracks_in_sequence = self.zynseq.libseq.getTracksInSequence(self.bank, self.selected_pad)
		patterns_in_track = self.zynseq.libseq.getPatternsInTrack(self.bank, self.selected_pad, 0)
		pattern = self.zynseq.libseq.getPattern(self.bank, self.selected_pad, 0, 0)
		if tracks_in_sequence != 1 or patterns_in_track !=1 or pattern == -1:
			self.zyngui.screens["arranger"].sequence = self.selected_pad
			self.zyngui.toggle_screen("arranger")
			return True
		self.zyngui.screens['pattern_editor'].channel = self.zynseq.libseq.getChannel(self.bank, self.selected_pad, 0)
		self.zyngui.screens['pattern_editor'].bank = self.bank
		self.zyngui.screens['pattern_editor'].sequence = self.selected_pad
		self.zyngui.screens['pattern_editor'].load_pattern(pattern)
		self.zyngui.show_screen("pattern_editor")
		return True

	# Function to refresh pads
	def refresh_status(self, force=False):
		super().refresh_status()

		if self.redrawing and not force:
			return

		force |= self.zynseq.bank != self.bank
		if force:
			self.bank = self.zynseq.bank
			self.set_title(f"Scene {self.bank}")
			if self.columns != self.zynseq.col_in_bank:
				self.update_grid()
			for pad in range(self.zynseq.col_in_bank ** 2):
				self.refresh_pad(pad)

	# Function to select a pad
	#	pad: Index of pad to select (Default: refresh existing selection)
	def select_pad(self, pad=None):
		if pad is not None:
			self.selected_pad = pad
		if self.selected_pad >= self.zynseq.libseq.getSequencesInBank(self.zynseq.bank):
			self.selected_pad = self.zynseq.libseq.getSequencesInBank(self.zynseq.bank) - 1
		col = int(self.selected_pad / self.columns)
		row = self.selected_pad % self.columns
		self.grid_canvas.coords(self.selection,
			1 + col * self.column_width, 1 + row * self.row_height,
			(1 + col) * self.column_width - self.select_thickness, (1 + row) * self.row_height - self.select_thickness)
		self.grid_canvas.tag_raise(self.selection)

	# Function to handle zynpots value change
	#   encoder: Zynpot index [0..n]
	#   dval: Zynpot value change
	def zynpot_cb(self, encoder, dval):
		if super().zynpot_cb(encoder, dval):
			return
		if encoder == self.ctrl_order[3]:
			pad = self.selected_pad + self.zynseq.col_in_bank * dval
			col = int(pad / self.zynseq.col_in_bank)
			row = pad % self.zynseq.col_in_bank
			if col >= self.zynseq.col_in_bank:
				col = 0
				row += 1
				pad = row + self.zynseq.col_in_bank * col
			elif pad < 0:
				col = self.zynseq.col_in_bank -1
				row -= 1
				pad = row + self.zynseq.col_in_bank * col
			if row < 0 or row >= self.zynseq.col_in_bank or col >= self.zynseq.col_in_bank:
				return
			self.select_pad(pad)
		elif encoder == self.ctrl_order[2]:
			pad = self.selected_pad + dval
			if pad < 0 or pad >= self.zynseq.libseq.getSequencesInBank(self.bank):
				return
			self.select_pad(pad)
		elif encoder == self.ctrl_order[1]:
			self.set_bank(self.bank + dval)
		elif encoder == self.ctrl_order[0] and zynthian_gui_config.transport_clock_source <= 1:
			self.zynseq.update_tempo()
			self.zynseq.nudge_tempo(dval)
			self.set_title(f"Tempo: {self.zynseq.get_tempo():.1f}", None, None, 2)

	# Function to handle SELECT button press
	#	type: Button press duration ["S"=Short, "B"=Bold, "L"=Long]
	def switch_select(self, type='S'):
		if super().switch_select(type):
			return True
		if type == 'S':
			self.toggle_pad()
		elif type == "B":
			self.show_pattern_editor()

	def back_action(self):
		if self.midi_learn:
			self.zyngui.cuia_disable_midi_learn()
			return True
		else:
			return super().back_action()

	# Function to handle switch press
	#	switch: Switch index [0=Layer, 1=Back, 2=Snapshot, 3=Select]
	#	type: Press type ["S"=Short, "B"=Bold, "L"=Long]
	#	returns True if action fully handled or False if parent action should be triggered
	def switch(self, switch, type):
		if switch == zynthian_gui_config.ENC_LAYER and type == 'B':
			self.show_menu()
			return True
		return False

	# CUIA Actions

	# Function to handle CUIA ARROW_RIGHT
	def arrow_right(self):
		self.zynpot_cb(self.ctrl_order[3], 1)

	# Function to handle CUIA ARROW_LEFT
	def arrow_left(self):
		self.zynpot_cb(self.ctrl_order[3], -1)

	# Function to handle CUIA ARROW_UP
	def arrow_up(self):
		if self.param_editor_zctrl:
			self.zynpot_cb(self.ctrl_order[3], 1)
		else:
			self.zynpot_cb(self.ctrl_order[2], -1)

	# Function to handle CUIA ARROW_DOWN
	def arrow_down(self):
		if self.param_editor_zctrl:
			self.zynpot_cb(self.ctrl_order[3], -1)
		else:
			self.zynpot_cb(self.ctrl_order[2], 1)

	# **************************************************************************
	# MIDI learning management
	# **************************************************************************

	def enter_midi_learn(self):
		if self.ctrldev:
			return
		self.midi_learn = True
		labels = ['None']
		for note in range(128):
			labels.append(f"{NOTE_NAMES[note % 12]}{note // 12 - 1}")
		value = self.zyngui.state_manager.zynseq.libseq.getTriggerNote(self.bank, self.selected_pad) + 1
		if value > 128:
			value = 0
		self.enable_param_editor(self, 'trigger_note', 'Trigger note', {'labels': labels, 'value': value})

	def exit_midi_learn(self):
		self.midi_learn = False
		self.disable_param_editor()

	# Zynpad's default midi learn mechanism
	def midi_event(self, ev):
		evtype = (ev & 0xF00000) >> 20
		if evtype == 9:
			# If trigger channel is set, filter events from other channels
			note = (ev >> 8) & 0x7F
			if self.midi_learn:
				self.zynseq.libseq.setTriggerNote(self.bank, self.selected_pad, note)
				self.zyngui.exit_midi_learn()
				return True

#------------------------------------------------------------------------------
