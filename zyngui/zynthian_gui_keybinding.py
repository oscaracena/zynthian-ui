#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
# 
# Zynthian Keyboard Binding Class
# 
# Copyright (C) 2019-2023 Brian Walton <brian@riban.co.uk>
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

import json
import logging
from subprocess import run, PIPE
from os import environ

# Zynthian specific modules
#from zyngui import zynthian_gui_config

#------------------------------------------------------------------------------
# Zynthian Keyboard Binding Class
#------------------------------------------------------------------------------

"""Provides interface to key binding"""

modifiers = {
	'shift': 1,
	'caps': 2,
	'ctrl': 4,
	'alt': 8,
	'num': 16,
	'shift_r': 32,
	'super': 64,
	'altgr': 128
}

html2tk = {
	"Escape": 9,
	"Digit0": 19,
	"Minus":20,
	"Equal": 21,
	"Backspace": 22,
	"Tab": 23,
	"BracketLeft": 34,
	"BracketRight": 35,
	"Enter": 36,
	"ControlLeft": 37,
	"Semicolon": 47,
	"Quote": 48,
	"Backquote": 49,
	"ShiftLeft": 50,
	"Comma": 59,
	"Period": 60,
	"Slash": 61,
	"ShiftRight": 62,
	"NumpadMultiply": 63,
	"AltLeft": 64,
	"Space": 65,
	"CapsLock": 66,
	"NumLock": 77,
	"ScrollLock": 78,
	"Numpad7": 79,
	"Numpad8": 80,
	"Numpad9": 81,
	"NumpadSubtract": 82,
	"Numpad4": 83,
	"Numpad5": 84,
	"Numpad6": 85,
	"NumpadAdd": 86,
	"Numpad1": 87,
	"Numpad2": 88,
	"Numpad3": 89,
	"Numpad0": 90,
	"NumpadDecimal": 91,
	"IntlBackslash": 94,
	"NumpadEnter": 104,
	"ControlRight": 105,
	"NumpadDivide": 106,
	"AltRight": 108,
	"Home": 110,
	"ArrowUp": 111,
	"PageUp": 112,
	"ArrowLeft": 113,
	"ArrowRight": 114,
	"End": 115,
	"ArrowDown": 116,
	"PageDown": 117,
	"Insert": 118,
	"Delete": 119,
	"Pause": 127,
	"ContextMenu": 135,
	"BrowserBack": 166,
	"BrowserForward": 167,
	"BrowserReload": 181
}
for i in range(12):
	html2tk[f"F{i + 1}"] = 66 + i #TODO: add F13..F24
for i in range(10):
	html2tk[f"Digit{i + 1}"] = 9 + i
for i in range(10):
	html2tk[f"Key{'QWERTYUIOP'[i]}"] = 24 + i
for i in range(9):
	html2tk[f"Key{'ASDFGHJKL'[i]}"] = 38 + i
for i in range(7):
	html2tk[f"Key{'ZXCVBNM'	[i]}"] = 52 + i
# Unsupported keys: NumpadEqual,KanaMode,Lang2,Lang1,IntlRo,Convert,NonConvert,IntlYen,AudioVolumeMute,LaunchApp2,MediaPlayPause,MediaStop,VolumeDown==AudioVolumeDown,VolumeUp==AudioVolumeUp,BrowserHome,PrintScreen,OSLeft==MetaLeft,OSRight==MetaRight,Power,Sleep,WakeUp,BrowserSearch,BrowserFavorites,BrowserRefresh,BrowserStop,LaunchApp1,LaunchMail,MediaSelect

tk2html = {}
for x, y in html2tk.items():
	tk2html[y] = x

default_map = {
	"Space": "ALL_NOTES_OFF",
	"Space,shift": "ALL_SOUNDS_OFF",

	"Home,shift": "RESTART_UI",
	"Home,ctrl": "REBOOT",
	"End,ctrl": "POWER_OFF",
	"Insert,ctrl": "RELOAD_MIDI_CONFIG",

	"KeyI": "ZYNSWITCH 0",
	"KeyK": "ZYNSWITCH 1",
	"Backspace": "ZYNSWITCH 1",
	"Escape": "ZYNSWITCH 1",
	"KeyO": "ZYNSWITCH 2",
	"KeyL": "ZYNSWITCH 3",
	"Enter": "ZYNSWITCH 3",

	"Period,ctrl": "ZYNPOT 1,1",
	"Comma,ctrl": "ZYNPOT 1,-1",
	"Period": "ZYNPOT 3,1",
	"Comma": "ZYNPOT 3,-1",
	"Period,shift,ctrl": "ZYNPOT 0,1",
	"Comma,shift,ctrl": "ZYNPOT 0,-1",
	"Period,shift": "ZYNPOT 2,1",
	"Comma,shift": "ZYNPOT 2,-1",

	"KeyA": "START_AUDIO_RECORD",
	"KeyA,shift": "STOP_AUDIO_RECORD",
	"KeyA,alt": "TOGGLE_AUDIO_RECORD",
	"KeyA,ctrl": "START_AUDIO_PLAY",
	"KeyA,shift,ctrl": "STOP_AUDIO_PLAY",
	"KeyA,ctrl,alt": "TOGGLE_AUDIO_PLAY",

	"KeyM": "START_MIDI_RECORD",
	"KeyM,shift": "STOP_MIDI_RECORD",
	"KeyM,alt": "TOGGLE_MIDI_RECORD",
	"KeyM,ctrl": "START_MIDI_PLAY",
	"KeyM,shift,ctrl": "STOP_MIDI_PLAY",
	"KeyM,ctrl,alt": "TOGGLE_MIDI_PLAY",

	"ArrowDown": "ARROW_DOWN",
	"ArrowUp": "ARROW_UP",
	"ArrowRight": "ARROW_RIGHT",
	"ArrowLeft": "ARROW_LEFT",

	"Numpad2": "ARROW_DOWN",
	"Numpad8": "ARROW_UP",
	"Numpad6": "ARROW_RIGHT",
	"Numpad4": "ARROW_LEFT",
	"NumpadEnter": "ZYNSWITCH 3",
	"Numpad7": "ZYNSWITCH 0",
	"Numpad1": "ZYNSWITCH 1",
	"Numpad9": "ZYNSWITCH 2",
	"Numpad3": "ZYNSWITCH 3",

	"Digit1": "PROGRAM_CHANGE 1",
	"Digit2": "PROGRAM_CHANGE 2",
	"Digit3": "PROGRAM_CHANGE 3",
	"Digit4": "PROGRAM_CHANGE 4",
	"Digit5": "PROGRAM_CHANGE 5",
	"Digit6": "PROGRAM_CHANGE 6",
	"Digit7": "PROGRAM_CHANGE 7",
	"Digit8": "PROGRAM_CHANGE 8",
	"Digit9": "PROGRAM_CHANGE 9",
	"Digit0": "PROGRAM_CHANGE 0"
}


def get_key_action(keycode, modifier):
	"""Get the name of the function bound to a key combination

	keycode : Keyboard code
	modifier : Bitwise flags of keyboard modifiers [0: none, 1: shift, 2: capslock, 4: ctrl, 8: alt, 16: numlock, 64: super, 128: altgr]
		None to match any modifer (other configurations with modifiers will be captured first)

	Returns : Space separated list of cuia and parameters mapped to the keybinding or None if no match found		
	"""

	logging.debug(f"Get keybinding function name for keycode: {keycode}, modifier: {modifier}")
	try:
		# Check for defined modifier
		if keycode in [63,77,79,80,81,82,83,84,85,86,87,88,89,90,91,104,106]:
			modifier &= 253
		else:
			modifier &= 239
		return binding_map[f"{keycode},{modifier}"]
	except:
		try:
			# Default to no modifier
			return mabinding_mapp[f"{keycode}"]
		except:
			logging.debug("Key not configured")

def load(config="keybinding"):
	"""Load key binding map from file
	config : Name of configuration to load - the file <config>.json will be loaded from the zynthian config directory
		Default: 'keybinding'
	Returns : True on success
	"""

	config_fpath = f"{environ.get('ZYNTHIAN_CONFIG_DIR', '/zynthian/config')}/{config}.json"
	try:
		with open(config_fpath, "r") as fh:
			j = fh.read()
			map =  json.loads(j)
			set_html_map(map)
			return True
	except Exception as e:
		set_html_map(default_map)
		return False


def set_html_map(html_map):
	global binding_map
	binding_map = {}
	for key_mod, value in html_map.items():
		try:
			parts = key_mod.split(",")
			key = parts[0]
			mod = 0
			for txt in parts[1:]:
				if txt in modifiers:
					mod |=modifiers[txt] 
			binding_map[f"{html2tk[key]},{mod}"] = value
		except:
			logging.warning(f"Failed to load keybinding for {key_mod}")

def get_html_map():
	html_map = {}
	for key_mod, cuia in binding_map.items():
		key_code, mod_code = key_mod.split(",", 1)
		html_key = tk2html[int(key_code)]
		for x, y in modifiers.items(): #TODO: Optimise
			if y & int(mod_code):
				html_key += f",{x}"
		html_map[html_key] = cuia
	return html_map

def save(config="keybinding"):
	"""
	Save key binding map to file
	
	config : Name of configuration to save - the file <config>.json will be saved to the Zynthian config directory
		Default: 'keybinding'
	Returns : True on success
	"""
	
	config_fpath = f"{environ.get('ZYNTHIAN_CONFIG_DIR', '/zynthian/config')}/{config}.json"
	try:
		with open(config_fpath, "w") as fh:
			fh.write(json.dumps(get_html_map(), indent=4))
			logging.info("Saving keyboard binding config file {}".format(config_fpath))
			return True

	except Exception as e:
		logging.error("Can't save keyboard binding config file '{}': {}".format(config_fpath,e))
		return False


def reset():
	"""Reset keyboard binding to default values"""

	set_html_map(default_map)


def add_binding(keycode, modifier, cuia):
	"""Bind key/action pair
	
	keycode : Keyboard code
	modifier: Bitwise modifier flags or None to ignore modifiers
	cuia: Callable UI action, including parameters or None to clear binding
	"""

	global binding_map
	remove_binding(keycode, modifier)
	try:
		if not modifier:
			binding_map[f"{keycode}"] = cuia
		else:
			binding_map[f"{keycode},{modifier}"] = cuia
	except:
		pass

def remove_binding(key):
	"""Removes a keybinding

	key : Keyboard code and modifier separated by space
	"""

	global binding_map
	try:
		del binding_map[key]
	except:
		pass

set_html_map(default_map)

#------------------------------------------------------------------------------