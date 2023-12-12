#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian GUI
# 
# Zynthian GUI MIDI config Class
# 
# Copyright (C) 2015-2023 Fernando Moyano <jofemodo@zynthian.org>
#                         Brian Walton <brian@riban.co.uk>
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
from collections import OrderedDict
from threading import Timer
from subprocess import check_output, Popen, PIPE
from time import sleep

# Zynthian specific modules
import zynautoconnect
from zyncoder.zyncore import lib_zyncore
from zyngui.zynthian_gui_selector import zynthian_gui_selector
from zyngui import zynthian_gui_config

# ------------------------------------------------------------------------------
# Zynthian MIDI config GUI Class
# ------------------------------------------------------------------------------

ZMIP_MODE_CONTROLLER = "⌨" #\u2328
ZMIP_MODE_ACTIVE = "⇥" #\u21e5
ZMIP_MODE_OMNI = "∈" #\u2208
ZMIP_MODE_MULTI = "⇶" #\u21f6

class zynthian_gui_midi_config(zynthian_gui_selector):


    def __init__(self):
        self.chain = None      # Chain object
        self.chain_zmop = None
        self.ble_devices = {}  # Map of BLE MIDI device configs indexed by BLE address. Config: [name, paired, trusted, connected]
        self.input = True      # True to process MIDI inputs, False for MIDI outputs
        self.fingerprint = []  # Used to detect changes in port list
        self.ble_scan_proc = None
        super().__init__('MIDI Devices', True)

    def build_view(self):
        if self.input:
            self.fingerprint = zynautoconnect.get_hw_src_ports()
        else:
            self.fingerprint = zynautoconnect.get_hw_dst_ports()
        if self.chain is None:
            # Start scanning and processing bluetooth
            self.ble_scan_proc = Popen('bluetoothctl', stdin=PIPE, stdout=PIPE, encoding='utf-8')
            self.ble_scan_proc.stdin.write('menu scan\nuuids 03B80E5A-EDE8-4B33-A751-6CE34EC4C700\nback\nscan on\n')
            self.ble_scan_proc.stdin.flush()
            Timer(0.1, self.process_dynamic_ports).start()
        super().build_view()

    def hide(self):
        if self.ble_scan_proc:
            # Stop bluetooth scanning
            self.ble_scan_proc.stdin.write('scan off\nexit\n')
            self.ble_scan_proc.stdin.flush()
            self.ble_scan_proc.terminate()
            self.ble_scan_proc = None
        super().hide()

    def set_chain(self, chain):
        self.chain = chain
        if self.chain:
            self.chain_zmop = self.chain.midi_chan    # This could change in the future, when multi-channel chains are implemented
        else:
            self.chain_zmop = None
        self.set_select_path()

    def fill_list(self):
        """Populate data list used for display and configuration.
        Different display mode for admin view (no chain) and chain view (i/o routing)
        List of lists, each consisting of elements based on the display mode and entry type.
        
        Elements in jack port:
        0: Port UID (or service name if service disabled)
        0: For services this is the name of function to start/stop service
        1: ZMIP/ZMOP index on None if not connected
        2: Display text
        """

        self.list_data = []

        def get_mode(i):
            """Get input mode prefix"""
            mode = ""
            if self.input:
                if lib_zyncore.zmip_get_flag_active_chan(i):
                    mode += ZMIP_MODE_ACTIVE
                elif lib_zyncore.zmip_get_flag_omni_chan(i):
                    mode += ZMIP_MODE_OMNI
                else:
                    mode += ZMIP_MODE_MULTI
                if i in self.zyngui.state_manager.ctrldev_manager.drivers:
                    mode += f" {ZMIP_MODE_CONTROLLER}"
            if mode:
                mode += " "
            return mode

        def append_port(dev_i):
            """Add a port to list"""
            if self.input:
                port = zynautoconnect.devices_in[dev_i]
                mode = get_mode(dev_i)
                if self.chain is None:
                    self.list_data.append((port.aliases[0], dev_i, f"{mode}{port.aliases[1]}"))
                elif dev_i in self.zyngui.state_manager.ctrldev_manager.drivers:
                    self.list_data.append((port.aliases[0], dev_i, f"    {mode}{port.aliases[1]}"))
                else:
                    if lib_zyncore.zmop_get_route_from(self.chain_zmop, dev_i):
                        self.list_data.append((port.aliases[0], dev_i, f"\u2612 {mode}{port.aliases[1]}"))
                    else:
                        self.list_data.append((port.aliases[0], dev_i, f"\u2610 {mode}{port.aliases[1]}"))
            else:
                port = zynautoconnect.devices_out[dev_i]
                if self.chain is None:
                    self.list_data.append((port.aliases[0], dev_i, f"{port.aliases[1]}"))
                elif port.name in self.chain.midi_out:
                    #TODO: Why use port.name here?
                    self.list_data.append((port.name, dev_i, f"\u2612 {port.aliases[1]}"))
                else:
                    self.list_data.append((port.name, dev_i, f"\u2610 {port.aliases[1]}"))

        def append_service_device(dev_name, obj):
            """Add service (that is also a port) to list"""
            if isinstance(obj, int):
                if self.input:
                    port = zynautoconnect.devices_in[obj]
                else:
                    port = zynautoconnect.devices_out[obj]
                if port:
                    mode = get_mode(obj)
                    self.list_data.append((f"stop_{dev_name}", obj, f"\u2612 {mode}{port.aliases[1]}"))
            else:
                self.list_data.append((f"start_{dev_name}", None, f"\u2610 {obj}"))

        # Lists of zmop/zmip indicies
        int_devices = []    # Internal MIDI ports
        usb_devices = []    # USB MIDI ports
        ble_devices = {}    # BLE MIDI ports, indexed by BLE address
        aubio_devices = []  # Aubio MIDI ports
        net_devices = {}    # Network MIDI ports, indexed by jack port name
        for i in range(zynautoconnect.max_num_devs):
            if self.input:
                dev = zynautoconnect.devices_in[i]
            else:
                dev = zynautoconnect.devices_out[i]
            if dev and dev.aliases:
                if dev.aliases[0].startswith("USB:"):
                    usb_devices.append(i)
                elif dev.aliases[0].startswith("BLE:"):
                    if self.input:
                        key = dev.aliases[0][4:-3]
                    else:
                        key = dev.aliases[0][4:-4]
                    ble_devices[key] = i
                elif dev.aliases[0].startswith("AUBIO:"):
                    aubio_devices.append(i)
                elif dev.aliases[0].startswith("NET:"):
                    net_devices[dev.name] = i
                else:
                    int_devices.append(i)
        if int_devices:
            self.list_data.append((None, None, "Internal Devices"))
            for i in int_devices:
                append_port(i)

        if usb_devices:
            self.list_data.append((None, None, "USB Devices"))
            for i in usb_devices:
                append_port(i)

        if not self.chain or zynthian_gui_config.bluetooth_enabled and ble_devices:
            self.list_data.append((None, None, "Bluetooth Devices"))
            if zynthian_gui_config.bluetooth_enabled:
                if self.chain:
                    for i in ble_devices.values():
                        append_port(i)
                else:
                    self.list_data.append(("stop_bluetooth", None, "\u2612 BLE MIDI"))
                    for addr, data in self.ble_devices.items():
                        #[name, paired, trusted, connected]
                        if data[2]:
                            title = "\u2612 "
                        else:
                            title = "\u2610 "
                        if addr in ble_devices:
                            dev_i = ble_devices[addr]
                            title += get_mode(dev_i)
                        else:
                            dev_i = None
                        if data[3]:
                            title += "\uf293 "
                        if dev_i is None:
                            title += data[0]
                        elif self.input:
                            title += zynautoconnect.devices_in[dev_i].aliases[1]
                        else:
                            title += zynautoconnect.devices_out[dev_i].aliases[1]
                        self.list_data.append((f"BLE:{addr}", dev_i, title))
            elif not self.chain:
                self.list_data.append(("start_bluetooth", None, "\u2610 BLE MIDI"))

        if not self.chain or net_devices:
            self.list_data.append((None, None, "Network Devices"))
            if self.chain:
                for i in net_devices.values():
                    append_port(i)
            else:
                if "jackrtpmidid:rtpmidi_in" in net_devices:
                    append_service_device("jackrtpmidid", net_devices["jackrtpmidid:rtpmidi_in"])
                elif "jackrtpmidid:rtpmidi_out" in net_devices:
                    append_service_device("jackrtpmidid", net_devices["jackrtpmidid:rtpmidi_out"])
                else:
                    append_service_device("jackrtpmidid", "RTP-MIDI")

                if "QmidiNet:in_1" in net_devices:
                    append_service_device("QmidiNet", net_devices["QmidiNet:in_1"])
                elif "QmidiNet:out_1" in net_devices:
                    append_service_device("QmidiNet", net_devices["QmidiNet:out_1"])
                else:
                    append_service_device("QmidiNet", "QmidiNet")

                if "RtMidiIn Client:TouchOSC Bridge" in net_devices:
                    append_service_device("touchosc", net_devices["RtMidiIn Client:TouchOSC Bridge"])
                elif "RtMidiOut Client:TouchOSC Bridge" in net_devices:
                    append_service_device("touchosc", net_devices["RtMidiOut Client:TouchOSC Bridge"])
                else:
                    append_service_device("touchosc", "TouchOSC Bridge")

        if self.input:
            if not self.chain or zynthian_gui_config.midi_aubionotes_enabled:
                self.list_data.append((None, None, "Aubionotes Audio\u2794MIDI"))
                if self.chain:
                    for i in aubio_devices:
                        append_port(i)
                else:
                    if aubio_devices:
                        append_service_device("aubionotes", aubio_devices[0])
                    else:
                        append_service_device("aubionotes", "Aubionotes")

        if not self.input and self.chain:
            self.list_data.append((None, None, "Chain inputs"))
            for chain_id, chain in self.zyngui.chain_manager.chains.items():
                if chain.is_midi() and chain != self.chain:
                    if self.zyngui.chain_manager.will_route_howl(self.zyngui.chain_manager.active_chain_id, chain_id):
                        prefix = "∞"
                    else:
                        prefix = ""
                    if chain_id in self.chain.midi_out:
                        self.list_data.append((chain_id, None, f"\u2612 {prefix}Chain {chain_id}"))
                    else:
                        self.list_data.append((chain_id, None, f"\u2610 {prefix}Chain {chain_id}"))

        super().fill_list()


    def select_action(self, i, t='S'):
        action = self.list_data[i][0]
        if t == 'S':
            action = self.list_data[i][0]
            wait = 2 # Delay after starting service to allow jack ports to update
            if action == "stop_jackrtpmidid":
                self.zyngui.state_manager.stop_rtpmidi(wait=wait)
            elif action == "start_jackrtpmidid":
                self.zyngui.state_manager.start_rtpmidi(wait=wait)
            elif action == "stop_QmidiNet":
                self.zyngui.state_manager.stop_qmidinet(wait=wait)
            elif action == "start_QmidiNet":
                self.zyngui.state_manager.start_qmidinet(wait=wait)
            elif action == "stop_touchosc":
                self.zyngui.state_manager.stop_touchosc2midi(wait=wait)
            elif action == "start_touchosc":
                self.zyngui.state_manager.start_touchosc2midi(wait=wait)
            elif action == "stop_aubionotes":
                self.zyngui.state_manager.stop_aubionotes(wait=wait)
            elif action == "start_aubionotes":
                self.zyngui.state_manager.start_aubionotes(wait=wait)
            elif action == "stop_bluetooth":
                self.zyngui.state_manager.stop_bluetooth(wait=wait)
            elif action == "start_bluetooth":
                self.zyngui.state_manager.start_bluetooth(wait=wait)
            # Route/Unroute
            elif self.chain:
                if self.input:
                    dev_i = self.list_data[i][1]
                    if dev_i in self.zyngui.state_manager.ctrldev_manager.drivers:
                        return
                    lib_zyncore.zmop_set_route_from(self.chain_zmop, dev_i, not lib_zyncore.zmop_get_route_from(self.chain_zmop, dev_i))
                else:
                    try:
                        self.zyngui.chain_manager.get_active_chain().toggle_midi_out(self.list_data[i][0])
                    except Exception as e:
                        logging.error(e)
                self.fill_list()
            elif self.list_data[i][0].startswith("BLE:"):
                self.toggle_ble_trust(self.list_data[i][0][4:])

        # Change mode
        elif t == 'B':
            if self.list_data[i][1] is None:
                if self.list_data[i][0].startswith("BLE:"):
                    # BLE MIDI device not connected
                    addr = self.list_data[i][0][4:]
                    if addr not in self.ble_devices or not self.ble_devices[addr][2]:
                        # Not trusted so offer to remove
                        self.zyngui.show_confirm(f"Remove BLE MIDI device?\n{self.list_data[i][0]}", self.remove_ble, self.list_data[i][0][4:])
                return
            dev_i = self.list_data[i][1]
            if dev_i is None:
                return
            try:
                options = OrderedDict()
                if self.input:
                    # Check mode (Acti/Omni/Multi)
                    if lib_zyncore.zmip_get_flag_active_chan(dev_i):
                        mode = 0
                    elif lib_zyncore.zmip_get_flag_omni_chan(dev_i):
                        mode = 1
                    else:
                        mode = 2
                    options["MIDI Input Mode"] = None
                    
                    if mode == 0:
                        options[f'\u25C9 {ZMIP_MODE_ACTIVE} Active channel'] = "ACTI"
                    else:
                        options[f'\u25CE {ZMIP_MODE_ACTIVE} Active channel'] = "ACTI"
                    if mode == 2:
                        options[f'\u25C9 {ZMIP_MODE_MULTI} Multitimbral mode '] = "MULTI"
                    else:
                        options[f'\u25CE {ZMIP_MODE_MULTI} Multitimbral mode'] = "MULTI"
                    if mode == 1:
                        options[f'\u25C9 {ZMIP_MODE_OMNI} Omni mode'] = "OMNI"
                    else:
                        options[f'\u25CE {ZMIP_MODE_OMNI} Omni mode'] = "OMNI"

                    options["Configuration"] = None
                    dev_id = zynautoconnect.get_midi_in_devid(dev_i)
                    if dev_id in self.zyngui.state_manager.ctrldev_manager.available_drivers:
                        #TODO: Offer list of profiles
                        if dev_i in self.zyngui.state_manager.ctrldev_manager.drivers:
                            options[f"\u2612 {ZMIP_MODE_CONTROLLER} Controller driver"] = "UNLOAD_DRIVER"
                        else:
                            options[f"\u2610 {ZMIP_MODE_CONTROLLER} Controller driver"] = "LOAD_DRIVER"
                    port = zynautoconnect.devices_in[dev_i]
                else:
                    port = zynautoconnect.devices_out[dev_i]
                options[f"Rename port '{port.aliases[0]}'"] = port
                options[f"Reset name to '{zynautoconnect.build_midi_port_name(port)[1]}'"] = port
                self.zyngui.screens['option'].config("MIDI Input Device", options, self.menu_cb)
                self.zyngui.show_screen('option')
            except:
                pass # Port may have disappeared whilst building menu


    def menu_cb(self, option, params):
        try:
            if option.startswith("Rename port"):
                self.zyngui.show_keyboard(self.rename_device, params.aliases[1])
                return
            elif option.startswith("Reset name"):
                zynautoconnect.set_port_friendly_name(params)
            elif params == "LOAD_DRIVER":
                self.zyngui.state_manager.ctrldev_manager.load_driver(self.list_data[self.index][1])
            elif params == "UNLOAD_DRIVER":
                self.zyngui.state_manager.ctrldev_manager.unload_driver(self.list_data[self.index][1])
            elif self.input:
                dev_i = self.list_data[self.index][1]
                flags_acti = params == "ACTI"
                flags_omni = params == "OMNI"
                lib_zyncore.zmip_set_flag_active_chan(dev_i, flags_acti)
                lib_zyncore.zmip_set_flag_omni_chan(dev_i, flags_omni)

            self.fill_list()
        except:
            pass # Ports may have changed since menu opened

    def process_dynamic_ports(self):
        """Process dynamically added/removed MIDI devices
        
        Calls itself every 2s
        """

        if not self.shown or not zynthian_gui_config.bluetooth_enabled:
            return

        update = False
        try:
            # Get list of available BLE Devices
            devices = check_output(['bluetoothctl', 'devices'], encoding='utf-8', timeout=0.1).split('\n')
            for device in devices:
                if not device:
                    continue
                addr = device.split()[1]
                name = device[25:]
                info = check_output(['bluetoothctl', 'info', addr], encoding='utf-8', timeout=0.1).split('\n')
                for line in info:
                    if line.startswith('\tName:'):
                        name = line[7:]
                    if line.startswith('\tPaired:'):
                        paired = line[9:] == "yes"
                    if line.startswith('\tTrusted:'):
                        trusted = line[10:] == "yes"
                    if line.startswith('\tConnected:'):
                        connected = line[12:] == "yes"
                if addr not in self.ble_devices or self.ble_devices[addr] != [name, paired, trusted, connected]:
                    self.ble_devices[addr] = [name, paired, trusted, connected]
                    update = True
                if connected and not trusted:
                    # Do not let an untrusted device remain connected
                    check_output(['bluetoothctl', 'disconnect', addr], encoding='utf-8', timeout=5)
        except:
            pass

        if self.input:
            if self.fingerprint != zynautoconnect.get_hw_src_ports():
                self.fingerprint = zynautoconnect.get_hw_src_ports()
                update = True
        else:
            if self.fingerprint != zynautoconnect.get_hw_dst_ports():
                self.fingerprint = zynautoconnect.get_hw_dst_ports()
                update = True

        if update:
            self.fill_list()
        
        if self.shown:
            # Repeat every 2s
            Timer(2, self.process_dynamic_ports).start()

    def toggle_ble_trust(self, addr):
        """Toggle trust of BLE device
        
        addr - BLE address
        """

        try:
            if self.ble_devices[addr][2]:
                self.zyngui.state_manager.start_busy("trust_ble", f"Untrusting BLE MIDI device\n{addr}")
                check_output(['bluetoothctl', 'untrust', addr], encoding='utf-8', timeout=1)
                check_output(['bluetoothctl', 'disconnect', addr], encoding='utf-8', timeout=5)
                self.ble_devices[addr][3] = False
                self.ble_devices[addr][2] = False
            else:
                self.zyngui.state_manager.start_busy("trust_ble", f"Trusting BLE MIDI device\n{addr}")
                check_output(['bluetoothctl', 'trust', addr], encoding='utf-8', timeout=1)
                check_output(['bluetoothctl', 'connect', addr], encoding='utf-8', timeout=5)
                self.ble_devices[addr][2] = True
        except Exception as e:
            logging.warning(f"Failed to complete toggle BLE device action: {e}")

        self.zyngui.state_manager.end_busy("trust_ble")

    def remove_ble(self, addr):
        """Remove the BLE MIDI device
        
        addr : BLE address
        """
        
        self.zyngui.state_manager.start_busy("remove_ble", f"Removing BLE MIDI device\n{addr}")
        try:
            self.ble_devices.pop(addr)
            check_output(['bluetoothctl', 'remove', addr], encoding='utf-8', timeout=1)
        except:
            pass
        self.zyngui.state_manager.end_busy("remove_ble")

    def rename_device(self, name):
        """Set the friendly name of selected
        
        name : New friendly name
        """

        if self.input:
            port = zynautoconnect.devices_in[self.list_data[self.index][1]]
        else:
            port = zynautoconnect.devices_out[self.list_data[self.index][1]]
        zynautoconnect.set_port_friendly_name(port, name)
        self.fill_list()

    def set_select_path(self):
        if self.chain:
            if self.input:
                self.select_path.set(f"Chain {self.chain.chain_id} MIDI Input")
            else:
                self.select_path.set(f"Chain {self.chain.chain_id} MIDI Output")
        else:
            if self.input:
                self.select_path.set(f"MIDI Input Devices")
            else:
                self.select_path.set(f"MIDI Output Devices")

# ------------------------------------------------------------------------------