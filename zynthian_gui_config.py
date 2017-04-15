#!/usr/bin/python3
# -*- coding: utf-8 -*-
#******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
# 
# Zynthian GUI configuration
# 
# Copyright (C) 2015-2016 Fernando Moyano <jofemodo@zynthian.org>
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

import os
import sys
import logging

#******************************************************************************

#------------------------------------------------------------------------------
# Log level and debuging
#------------------------------------------------------------------------------

if os.environ.get('ZYNTHIAN_LOG_LEVEL'):
	log_level=int(os.environ.get('ZYNTHIAN_LOG_LEVEL'))
else:
	log_level=logging.WARNING
	#log_level=logging.DEBUG

if os.environ.get('ZYNTHIAN_RAISE_EXCEPTIONS'):
	raise_exceptions=int(os.environ.get('ZYNTHIAN_RAISE_EXCEPTIONS'))
else:
	raise_exceptions=False

# Set root logging level
logging.basicConfig(stream=sys.stderr, level=log_level)

#------------------------------------------------------------------------------
# Wiring layout
#------------------------------------------------------------------------------

if os.environ.get('ZYNTHIAN_WIRING_LAYOUT'):
	wiring_layout=os.environ.get('ZYNTHIAN_WIRING_LAYOUT')
	logging.info("Wiring Layout %s" % wiring_layout)
else:
	wiring_layout="DUMMIES"
	logging.info("No Wiring Layout configured. Only touch interface is available.")

if os.environ.get('ZYNTHIAN_WIRING_ENCODER_A'):
	wiring_encoder_a=os.environ.get('ZYNTHIAN_WIRING_ENCODER_A').split(',')
else:
	wiring_encoder_a=[26,25,0,4]

if os.environ.get('ZYNTHIAN_WIRING_ENCODER_B'):
	wiring_encoder_b=os.environ.get('ZYNTHIAN_WIRING_ENCODER_B').split(',')
else:
	wiring_encoder_b=[21,27,7,3]

if os.environ.get('ZYNTHIAN_WIRING_SWITCHES'):
	wiring_encoder_switches=os.environ.get('ZYNTHIAN_WIRING_SWITCHES').split(',')
else:
	wiring_encoder_switches=[107,23,106,2]

#------------------------------------------------------------------------------
# Zyncoder GPIO pin assignment (wiringPi numbering)
#------------------------------------------------------------------------------

# First Prototype => Generic Plastic Case
if wiring_layout=="PROTOTYPE-1":
	zyncoder_pin_a=[27,21,3,7]
	zyncoder_pin_b=[25,26,4,0]
	zynswitch_pin=[23,None,2,None]
	select_ctrl=2
# Controller RBPi connector downside, controller 1 reversed
elif wiring_layout=="PROTOTYPE-2":
	zyncoder_pin_a=[27,21,4,0]
	zyncoder_pin_b=[25,26,3,7]
	zynswitch_pin=[23,107,2,106]
	select_ctrl=3
# Controller RBPi connector upside
elif wiring_layout=="PROTOTYPE-3":
	zyncoder_pin_a=[27,21,3,7]
	zyncoder_pin_b=[25,26,4,0]
	zynswitch_pin=[107,23,106,2]
	select_ctrl=3
# Controller RBPi connector downside (Holger's way)
elif wiring_layout=="PROTOTYPE-3H":
	zyncoder_pin_a=[21,27,7,3]
	zyncoder_pin_b=[26,25,0,4]
	zynswitch_pin=[107,23,106,2]
	select_ctrl=3
# Controller RBPi connector upside / Controller Singles
elif wiring_layout=="PROTOTYPE-4":
	zyncoder_pin_a=[26,25,0,4]
	zyncoder_pin_b=[21,27,7,3]
	zynswitch_pin=[107,23,106,2]
	select_ctrl=3
# Controller RBPi connector downside / Controller Singles Inverted
elif wiring_layout=="PROTOTYPE-4B":
	zyncoder_pin_a=[25,26,4,0]
	zyncoder_pin_b=[27,21,3,7]
	zynswitch_pin=[23,107,2,106]
	select_ctrl=3
# Kees layout, for display Waveshare 3.2
elif wiring_layout=="PROTOTYPE-KEES":
	zyncoder_pin_a=[27,21,4,5]
	zyncoder_pin_b=[25,26,31,7]
	zynswitch_pin=[23,107,6,106]
	select_ctrl=3
# Controller RBPi connector upside / Controller Singles / Switches throw GPIO expander
elif wiring_layout=="PROTOTYPE-5":
	zyncoder_pin_a=[26,25,0,4]
	zyncoder_pin_b=[21,27,7,3]
	zynswitch_pin=[107,105,106,104]
	select_ctrl=3
# Desktop Development & Emulation
elif wiring_layout=="EMULATOR":
	zyncoder_pin_a=[4,5,6,7]
	zyncoder_pin_b=[8,9,10,11]
	zynswitch_pin=[0,1,2,3]
	select_ctrl=3
# No HW Controllers => Dummy Controllers
elif wiring_layout=="DUMMIES":
	zyncoder_pin_a=[0,0,0,0]
	zyncoder_pin_b=[0,0,0,0]
	zynswitch_pin=[0,0,0,0]
	select_ctrl=3
elif wiring_layout=="CUSTOM":
	zyncoder_pin_a=wiring_encoder_a
	zyncoder_pin_b=wiring_encoder_b
	zynswitch_pin=wiring_switches
	select_ctrl=3
# Default to DUMMIES
else:
	zyncoder_pin_a=[0,0,0,0]
	zyncoder_pin_b=[0,0,0,0]
	zynswitch_pin=[0,0,0,0]
	select_ctrl=3

#------------------------------------------------------------------------------
# UI Geometric Parameters
#------------------------------------------------------------------------------

# Screen Size => Autodetect if None
if os.environ.get('DISPLAY_WIDTH'):
	display_width=int(os.environ.get('DISPLAY_WIDTH'))
	ctrl_width=int(display_width/4)
else:
	display_width=None

if os.environ.get('DISPLAY_HEIGHT'):
	display_height=int(os.environ.get('DISPLAY_HEIGHT'))
	topbar_height=int(display_height/10)
	ctrl_height=int((display_height-topbar_height)/2)
else:
	display_height=None

# Controller Positions
ctrl_pos=[
	(1,0,"nw"),
	(2,0,"sw"),
	(1,2,"ne"),
	(2,2,"se")
]

#------------------------------------------------------------------------------
# UI Color Parameters
#------------------------------------------------------------------------------

if os.environ.get('ZYNTHIAN_UI_COLOR_BG'):
	color_bg=os.environ.get('ZYNTHIAN_UI_COLOR_BG')
else:
	color_bg="#000000"

if os.environ.get('ZYNTHIAN_UI_COLOR_TX'):
	color_tx=os.environ.get('ZYNTHIAN_UI_COLOR_TX')
else:
	color_tx="#ffffff"

if os.environ.get('ZYNTHIAN_UI_COLOR_ON'):
	color_on=os.environ.get('ZYNTHIAN_UI_COLOR_ON')
else:
	color_on="#ff0000"

if os.environ.get('ZYNTHIAN_UI_COLOR_PANEL_BG'):
	color_panel_bg=os.environ.get('ZYNTHIAN_UI_COLOR_PANEL_BG')
else:
	color_panel_bg="#3a424d"

# Color Scheme
color_panel_bd=color_bg
color_panel_tx=color_tx
color_header_bg=color_bg
color_header_tx=color_tx
color_ctrl_bg_off="#5a626d"
color_ctrl_bg_on=color_on
color_ctrl_tx=color_tx
color_ctrl_tx_off="#e0e0e0"

#------------------------------------------------------------------------------
# UI Font Parameters
#------------------------------------------------------------------------------

if os.environ.get('ZYNTHIAN_UI_FONT_FAMILY'):
	font_family=os.environ.get('ZYNTHIAN_UI_FONT_FAMILY')
else:
	font_family="Audiowide"
	#font_family="Helvetica" #=> the original ;-)
	#font_family="Economica" #=> small
	#font_family="Orbitron" #=> Nice, but too strange
	#font_family="Abel" #=> Quite interesting, also "Strait"

if os.environ.get('ZYNTHIAN_UI_FONT_TOPBAR_SIZE'):
	font_topbar=(font_family,int(os.environ.get('ZYNTHIAN_UI_FONT_TOPBAR_SIZE')))
else:
	font_topbar=(font_family,11)

if os.environ.get('ZYNTHIAN_UI_FONT_LISTBOX_SIZE'):
	font_listbox=(font_family,int(os.environ.get('ZYNTHIAN_UI_FONT_LISTBOX_SIZE')))
else:
	font_listbox=(font_family,10)

if os.environ.get('ZYNTHIAN_UI_FONT_CTRL_TITLE_MAXSIZE'):
	font_ctrl_title_maxsize=int(os.environ.get('ZYNTHIAN_UI_FONT_CTRL_TITLE_MAXSIZE'))
else:
	font_ctrl_title_maxsize=11

#------------------------------------------------------------------------------
