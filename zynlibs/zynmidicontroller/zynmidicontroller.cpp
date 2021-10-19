/*
 * ******************************************************************
 * ZYNTHIAN PROJECT: Zynmidicontroller Library
 *
 * Library providing interface to MIDI pad controllers
 *
 * Copyright (C) 2021 Brian Walton <brian@riban.co.uk>
 *
 * ******************************************************************
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation; either version 2 of
 * the License, or any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 * For a full copy of the GNU General Public License see the LICENSE.txt file.
 *
 * ******************************************************************
 */

#include <stdio.h> //provides printf
#include <stdlib.h> //provides exit
#include <thread> //provides thread for timer
#include <jack/jack.h> //provides JACK interface
#include <jack/midiport.h> //provides JACK MIDI interface
#include "zynmidicontroller.h" //exposes library methods as c functions
#include "constants.h"
#include <cstring> //provides strstr
#include <lo/lo.h> //provides OSC interface
#include <lo/lo_cpp.h> //provides C++ OSC interface

#define DPRINTF(fmt, args...) if(g_bDebug) printf(fmt, ## args)

jack_port_t * g_pInputPortDevice; // Pointer to the JACK input port connected to controller
jack_port_t * g_pOutputPortDevice; // Pointer to the JACK output port connected to controller
jack_port_t * g_pOutputPort; // Pointer to the JACK output port connected to zynmidirouter
jack_client_t *g_pJackClient = NULL; // Pointer to the JACK client
unsigned int g_nInputProtocol = -1; // Value of the protocol used by controller connected to MIDI
unsigned int g_nOutputProtocol = -1; // Value of the protocol used by controller connected to MIDI
unsigned int g_nProtocol = -1; // Index of the protocol to use for device control
bool g_bShift = false; // True if shift button is pressed

const char* g_sSupported[] = {"Launchkey-Mini-MK3-MIDI-2","Launchpad-Mini-MK3-MIDI-2"}; // List of jack aliases supported by library
size_t g_nSupportedQuant = sizeof(g_sSupported) / sizeof(const char*);
//!@todo How does Launchpad Mini implement drum pads?
uint8_t g_nDrumPads[] = {40,41,42,43,44,45,46,47,48,49,50,51,36,37,38,39,40,41,42,43,44,45,46,47}; // MIDI note for each drum pad
uint8_t g_nLKM3SessionPads[] = {96,97,98,99,100,101,102,103,112,113,114,115,116,117,118,119}; // MIDI note for each session pad
uint8_t g_nLPM3SessionPads[] = {81,82,83,84,85,86,87,88,
                            71,72,73,74,75,76,77,78,
                            61,62,63,64,65,66,67,68,
                            51,52,53,54,55,56,57,58,
                            41,42,43,44,45,46,47,48,
                            31,32,33,34,35,36,37,38,
                            21,22,23,24,25,26,27,28,
                            11,12,13,14,15,16,17,18}; // MIDI note for each session pad
uint8_t g_nPadColours[] = {67,35,9,47,105,63,94,126,40,81,8,45,28,95,104,44}; //Novation Mk3 colours closely matching zynpad group colours
uint8_t g_nPadColour[64]; // Current colour of each pad
uint8_t g_nDrumColour = 79; // Colour of drum pads
uint8_t g_nDrumOnColour = 90; // Colour of drum pads when pressed
uint8_t g_nStartingColour = 123; // Colour to flash pad when sequence starting
uint8_t g_nStoppingColour = 120; // Colour to flash pad when sequence stopping
int g_nCCoffset = 0; // Offset to add to CC controllers (base is 21 for controller 1)
uint8_t g_nMidiChannel = 0; // MIDI channel to send CC messages
uint8_t g_nPlayState = 0; // Bitwise play state: b0:MIDI Player, b1: MIDI Recorder, b2: Audio Player, b3: Audio Recorder

std::vector<MIDI_MESSAGE*> g_vSendQueue; // Queue of MIDI events to send
bool g_bDebug = false; // True to output debug info
bool g_bMutex = false; // Mutex lock for access to g_vSendQueue

// Start OSC API client and server
//!@todo Temporary implementation until proper API implemented
lo::Address g_oscClient("localhost", "1370");
lo::ServerThread g_oscServer(2001);

// ** Internal (non-public) functions  (not delcared in header so need to be in correct order in source file) **

// Enable / disable debug output
void enableDebug(bool bEnable)
{
    printf("libmidicontroller setting debug mode %s\n", bEnable?"on":"off");
    g_bDebug = bEnable;
}

// Check if both device input and output are connected
bool isDeviceConnected() {
    if(g_nInputProtocol == g_nOutputProtocol)
        g_nProtocol = g_nInputProtocol;
    return g_nProtocol != -1;
}

// Add arbriatary length MIDI message to queue to be sent to device on next jack cycle
void sendDeviceMidi(const unsigned char data[], size_t size) {
    if(size < 1 || data[0] < 128)
        return;
    MIDI_MESSAGE* pMsg = new MIDI_MESSAGE(data, size);
    while(g_bMutex)
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    g_bMutex = true;
    g_vSendQueue.push_back(pMsg);
    g_bMutex = false;
}

// Add 3 byte MIDI command to queue to be sent to device on next jack cycle
void sendDeviceMidi3(uint8_t status, uint8_t value1, uint8_t value2)
{
    if(status < 128 || value1 > 127 && value2 > 127)
        return;
    MIDI_MESSAGE* pMsg = new MIDI_MESSAGE(3);
    pMsg->data[0]= status;
    pMsg->data[1] = value1;
    pMsg->data[2] = value2;
    while(g_bMutex)
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    g_bMutex = true;
    g_vSendQueue.push_back(pMsg);
    g_bMutex = false;
}

void sendPadStatusToDevice(uint8_t sequence, uint16_t state) {
    int pad;
    if(g_nProtocol == DEVICE_LAUNCHKEY_MINI_MK3 && sequence < 16)
        pad = g_nLKM3SessionPads[sequence];
    else if(g_nProtocol == DEVICE_LAUNCHPAD_MINI_MK3 && sequence < 64)
        pad = g_nLPM3SessionPads[sequence];
    else
        return;
    //printf("sendPadStatus seq:%d state:%d pad:%d\n", sequence, state, pad);
    switch(state)
    {
        case STOPPED:
            sendDeviceMidi3(0x90, pad, g_nPadColour[sequence]);
            break;
        case STARTING:
        case RESTARTING:
            sendDeviceMidi3(0x90, pad, g_nPadColour[sequence]);
            sendDeviceMidi3(0x91, pad, g_nStartingColour);
            break;
        case PLAYING:
            sendDeviceMidi3(0x92, pad, g_nPadColour[sequence]);
            break;
        case STOPPING:
            sendDeviceMidi3(0x90, pad, g_nPadColour[sequence]);
            sendDeviceMidi3(0x91, pad, g_nStoppingColour);
            break;
        case DISABLED:
            sendDeviceMidi3(0x90, pad, 0);
            break;
    }
}

void selectMode(int mode) {
    switch(g_nProtocol) {
        case DEVICE_LAUNCHKEY_MINI_MK3:
            sendDeviceMidi3(0xbf, 3, mode);
            break;
        case DEVICE_LAUNCHPAD_MINI_MK3:
            // Switch to Progammer mode
            const unsigned char data[] = {0xf0,0x00,0x20,0x29,0x02,0x0d,0x0e,0x01,0xf7};
            sendDeviceMidi(data, sizeof(data));
            break;
    }
}

void onOscStatus(lo_arg **pArgs, int nArgs)
{
    if(nArgs < 4)
        return;
    uint8_t nBank = pArgs[0]->i;
    uint8_t nSequence = pArgs[1]->i;
    uint8_t nState = pArgs[2]->i;
    uint8_t nGroup = pArgs[3]->i;
    //printf("OSC Bank %d Sequence %d State %d Group %c\n", nBank, nSequence, nState, 'A'+nGroup);
    if(nSequence > 63)
        return;
    g_nPadColour[nSequence] = g_nPadColours[nGroup % 16];
    sendPadStatusToDevice(nSequence, nState);
}

void onOscSmf(lo_arg **pArgs, int nArgs)
{
    /*  Single 8-bit integer argument is bitwise flag:
        b0: MIDI player
        b1: MIDI Recorder
    */
    if(nArgs != 1)
        return;

    g_nPlayState = pArgs[0]->i;
    printf("zynmidicontroller received SMF status: %u\n", nStatus);
    switch(nStatus) {
        case 0:
            // All stopped
            sendDeviceMidi3(0xb0, 115, 0);
            sendDeviceMidi3(0xb0, 117, 0);
            break;
        case 1:
            // MIDI playing
            sendDeviceMidi3(0xb1, 115, 127);
            sendDeviceMidi3(0xb1, 117, 0);
            break;
        case 2:
            // MIDI recording
            sendDeviceMidi3(0xb0, 115, 0);
            sendDeviceMidi3(0xb0, 117, 127);
            break;
        case 3:
            // MIDI playing and recording
            sendDeviceMidi3(0xb2, 115, 127);
            sendDeviceMidi3(0xb2, 117, 127);
            break;
        //!@todo Calculate state of audio/midi play/rec and send appropriate solid/pulse/flash
    }
}


void enableDevice(bool enable) {
    if(!isDeviceConnected())
        return;
    if(enable) {
        g_oscServer.add_method("/sequence/status", "iiii", onOscStatus);
        g_oscServer.add_method("smf", "i", onOscSmf);
        g_oscServer.start();
        g_oscClient.send("/cuia/register", "sis", "localhost", 2001, "/SEQUENCER/STATE");
        g_oscClient.send("/cuia/register", "sis", "localhost", 2001, "SMF");
    } else {
        g_oscServer.del_method("/sequence/status", "iiii");
        g_oscServer.del_method("smf", "i");
        g_oscServer.stop();
        g_oscClient.send("/cuia/unregister", "sis", "localhost", 2001, "/SEQUENCER/STATE");
        g_oscClient.send("/cuia/unregister", "sis", "localhost", 2001, "SMF");
    }

    switch(g_nProtocol) {
        case DEVICE_LAUNCHKEY_MINI_MK3:
            // Novation Launchkey Mini
            sendDeviceMidi3(0x9f, 12, enable?127:0);
            DPRINTF("\tSession mode %s\n", enable?"enabled":"disabled");
            if(!enable)
                return;
            for(uint8_t pad = 0; pad < 16; ++pad)
                sendDeviceMidi3(0x99, g_nDrumPads[pad], g_nDrumColour);
            for(uint8_t pad = 0; pad < 16; ++pad)
                sendPadStatusToDevice(pad, STOPPED);
            selectKnobs(1); // Select "Volume" for CC knobs (to avoid undefined state)
            break;
        case DEVICE_LAUNCHPAD_MINI_MK3:
        {
            // Select programmer layout
            const unsigned char data[] = {0xf0,0x00,0x20,0x29,0x02,0x0d,0x00,0x7f,0xf7};
            sendDeviceMidi(data, sizeof(data));
            break;
        }
        default:
            break;
    }
}

// Initialise LaunchKey device
void initLaunchkey(size_t protocol) {
    if(protocol >= g_nSupportedQuant)
        return;
    g_nProtocol = -1;
    if(!isDeviceConnected())
        return;
    g_nProtocol = protocol;
    printf("Initialising controller interface with protocol %s\n", g_sSupported[protocol]);
    enableDevice(true);
}

// Send MIDI command to normal output (not to control device)
inline void sendMidi(void* pOutputBuffer, int command, int value1, int value2) {
    unsigned char* pBuffer = jack_midi_event_reserve(pOutputBuffer, 0, 3); //!@todo Check if offset 0 is valid
    if(pBuffer == NULL)
        return; // Exceeded buffer size (or other issue)
    pBuffer[0] = command;
    pBuffer[1] = value1;
    pBuffer[2] = value2;
    //DPRINTF("Sending MIDI event 0x%2X,%d,%d to zynmidirouter\n", pBuffer[0],pBuffer[1],pBuffer[2]);
}

// Handle received MIDI events based on selected protocol
inline void protocolHandler(jack_midi_event_t* pEvent, void* pOutputBuffer) {
    //!@todo Move API notification outside jack process thread
    if(!pEvent || pEvent->size != 3)
        return;
    jack_midi_data_t* pBuffer = pEvent->buffer;
    int channel = pBuffer[0] & 0x0F + 1;
    switch(g_nProtocol) {
        case 0:
            // Novation Launchkey Mini
            switch(pBuffer[0] & 0xF0) {
                case 0x90:
                    //DPRINTF("NOTE ON: Channel %d Note %d Velocity %d\n", channel, pBuffer[1], pBuffer[2]);
                    if(pBuffer[1] > 35 && pBuffer[1] < 52) {
                        // Drum pads
                        sendDeviceMidi3(0x99, pBuffer[1], g_nDrumOnColour);
                        sendMidi(pOutputBuffer, 0x99, pBuffer[1], pBuffer[2]);
                    } else if(pBuffer[1] > 95 && pBuffer[1] < 104) {
                        // Launch buttons 1-8
                        g_oscClient.send("/cuia/TOGGLE_SEQUENCE", "i", pBuffer[1] - 96);
                    } else if(pBuffer[1] > 111 && pBuffer[1] < 120) {
                        // Launch buttons 9-16
                        g_oscClient.send("/cuia/TOGGLE_SEQUENCE", "i", pBuffer[1] - 104);
                    }
                    break;
                case 0x80:
                    //DPRINTF("NOTE OFF: Channel %d Note %d Velocity %d\n", channel, pBuffer[1], pBuffer[2]);
                    if(pBuffer[1] > 35 && pBuffer[1] < 52) {
                        // Drum pads
                        sendDeviceMidi3(0x99, pBuffer[1], g_nDrumColour);
                        sendMidi(pOutputBuffer, 0x89, pBuffer[1], pBuffer[2]);
                    }
                    break;
                case 0xb0:
                    //DPRINTF("CC: Channel %d CC %d Value %d\n", channel, pBuffer[1], pBuffer[2]);
                    if(pBuffer[1] == 9) {
                        // Switch CC offset
                        g_nCCoffset = 8 * (pBuffer[2] - 1);
                        DPRINTF("Changing CC knob bank to %d (%d-%d)\n", pBuffer[2], 21 + g_nCCoffset, 21 + g_nCCoffset + 7);
                    } else if(pBuffer[1] == 108) {
                        // Shift button
                        g_bShift = pBuffer[2];
                        DPRINTF("Shift button %s\n", g_bShift?"pressed":"released");
                    }
                    if(g_bShift) {
                        // Shift held
                        if(pBuffer[1] == 104) {
                            // Up button
                            DPRINTF("Up button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/BACK_UP");
                        } else if(pBuffer[1] == 105) {
                            // Down button
                            DPRINTF("Down button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/BACK_DOWN");
                        } else if(pBuffer[1] == 103) {
                            // Left button
                            DPRINTF("Left button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/SELECT_UP");
                        } else if(pBuffer[1] == 102) {
                            // Right button
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/SELECT_DOWN");
                            DPRINTF("Right button %s\n", pBuffer[2]?"pressed":"released");
                        } else if(pBuffer[1] > 20 && pBuffer[1] < 29) {
                            // CC knobs
                            sendMidi(pOutputBuffer, 0xb0 | g_nMidiChannel, pBuffer[1] + g_nCCoffset + 40, pBuffer[2]);
                        } else if(pBuffer[1] == 115) {
                            // Play button
                            DPRINTF("Shift+Play button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                               g_oscClient.send("/cuia/TOGGLE_AUDIO_PLAY");
                        } else if(pBuffer[1] == 117) {
                            // Record button
                            DPRINTF("Shift+Record button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/TOGGLE_AUDIO_RECORD");
                        }
                    } else {
                        // Shift not held
                        if(pBuffer[1] == 104) {
                            // Launch button
                            DPRINTF("Launch button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/SWITCH_SELECT_SHORT");
                        } else if(pBuffer[1] == 105) {
                            // Stop/Solo/Mute button
                            DPRINTF("Stop/Solo/Mute button %s\n", pBuffer[2]?"pressed":"released");
                            if(pBuffer[2])
                                g_oscClient.send("/cuia/SWITCH_BACK_SHORT");
                        } else if(pBuffer[1] > 20 && pBuffer[1] < 29) {
                            // CC knobs
                            sendMidi(pOutputBuffer, 0xb0 | g_nMidiChannel, pBuffer[1] + g_nCCoffset, pBuffer[2]);
                        } else if(pBuffer[1] == 115) {
                            // Play button
                            DPRINTF("Play button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/TOGGLE_MIDI_PLAY");
                        } else if(pBuffer[1] == 117) {
                            // Record button
                            DPRINTF("Record button %s\n", pBuffer[2]?"pressed":"released");
                           if(pBuffer[2])
                                g_oscClient.send("/cuia/TOGGLE_MIDI_RECORD");
                        }
                    }
                    break;
                default:
                    // MIDI command not handled
                    break;
            }
        default:
            // Protocol not defined
            break;
    }
}

/*  Process jack cycle - must complete within single jack period
    nFrames: Quantity of frames in this period
    pArgs: Parameters passed to function by main thread (not used here)

    [For info]
    jack_last_frame_time() returns the quantity of samples since JACK started until start of this period
    jack_midi_event_write sends MIDI message at sample time sequence within this period

    [Process]
    Process incoming MIDI events
    Send pending MIDI events
    Remove events from queue
*/
int onJackProcess(jack_nframes_t nFrames, void *pArgs)
{
    if(!g_pJackClient)
        return 0;
    // Get output buffers that will be processed in this process cycle
    void* pOutputBuffer = jack_port_get_buffer(g_pOutputPort, nFrames);
    void* pDeviceOutputBuffer = jack_port_get_buffer(g_pOutputPortDevice, nFrames);
    unsigned char* pBuffer;
    jack_midi_clear_buffer(pOutputBuffer);
    jack_midi_clear_buffer(pDeviceOutputBuffer);

    // Process MIDI input
    void* pInputBuffer = jack_port_get_buffer(g_pInputPortDevice, nFrames);
    jack_midi_event_t midiEvent;
    jack_nframes_t nCount = jack_midi_get_event_count(pInputBuffer);
    for(jack_nframes_t i = 0; i < nCount; i++)
    {
        jack_midi_event_get(&midiEvent, pInputBuffer, i);
        protocolHandler(&midiEvent, pOutputBuffer);
    }

    // Send MIDI output aligned with first sample of frame resulting in similar latency to audio
    while(g_bMutex)
        std::this_thread::sleep_for(std::chrono::microseconds(10));
    g_bMutex = true;

    // Process events scheduled to be sent to device MIDI output
    for(auto it = g_vSendQueue.begin(); it != g_vSendQueue.end();) {
        pBuffer = jack_midi_event_reserve(pDeviceOutputBuffer, 0, (*it)->size); //!@todo Check if offset 0 is valid
        if(pBuffer == NULL)
            break; // Exceeded buffer size (or other issue)
        memcpy(pBuffer, (*it)->data, (*it)->size);
        //DPRINTF("Sending MIDI event 0x%2X,%d,%d to device\n", pBuffer[0],pBuffer[1],pBuffer[2]);
        delete(*it);
        it = g_vSendQueue.erase(it);
    }
    g_bMutex = false;
    return 0;
}

void onJackConnect(jack_port_id_t port_a, jack_port_id_t port_b, int connect, void *arg) {
    // Need to monitor supported controllers - do we support multiple simultaneous controllers?
    /*
        Check if it is one of our ports
        Check if remote port is supported device
        Check if it is connect or disconnect
        For now just accept one supported device and drop all others - may add ports for multiple devices in future
    */
    if(!g_pJackClient)
        return;
    DPRINTF("connection: %d %s %d\n", port_a, connect?"connected to":"disconnected from", port_b);
    jack_port_t* pSrcPort = jack_port_by_id(g_pJackClient, port_a);
    jack_port_t* pDstPort = jack_port_by_id(g_pJackClient, port_b);
    if(pDstPort == g_pInputPortDevice) {
        char * aliases[2];
        aliases[0] = (char *) malloc (jack_port_name_size());
        aliases[1] = (char *) malloc (jack_port_name_size());
        int nAliases = jack_port_get_aliases(pSrcPort, aliases);
        for(int i = 0; i < nAliases; ++i) {
            for(int j = 0; j < g_nSupportedQuant; ++j) {
                if(strstr(aliases[i], g_sSupported[j])) {
                    g_nInputProtocol = connect?j:-1;
                    DPRINTF("%s %s zynmidicontroller input\n", aliases[i], connect?"connected to":"disconnected from");
                    initLaunchkey(j);
                }
            }
        }
        free(aliases[0]);
        free(aliases[1]);
    }
    else if(pSrcPort == g_pOutputPortDevice) {
        char * aliases[2];
        aliases[0] = (char *) malloc (jack_port_name_size());
        aliases[1] = (char *) malloc (jack_port_name_size());
        int nAliases = jack_port_get_aliases(pDstPort, aliases);
        for(int i = 0; i < nAliases; ++i) {
            for(int j = 0; j < g_nSupportedQuant; ++j) {
                if(strstr(aliases[i], g_sSupported[j])) {
                    g_nOutputProtocol = connect?j:-1;
                    DPRINTF("zynmidicontroller output %s %s\n", connect?"connected to":"disconnected from", aliases[i]);
                    initLaunchkey(j);
                }
            }
        }
        free(aliases[0]);
        free(aliases[1]);
    }
}

// ** Library management functions **

void init() {
    // Register with Jack server
    printf("**zynmidicontroller initialising**\n");

    if(g_pJackClient)
    {
        fprintf(stderr, "libzynmidicontroller already initialised\n");
        return; // Already initialised
    }

    if((g_pJackClient = jack_client_open("zynmidicontroller", JackNoStartServer, NULL)) == 0)
    {
        fprintf(stderr, "libzynmidicontroller failed to start jack client\n");
        return;
    }
    // Create input port
    if(!(g_pInputPortDevice = jack_port_register(g_pJackClient, "controller input", JACK_DEFAULT_MIDI_TYPE, JackPortIsInput, 0)))
    {
        fprintf(stderr, "libzynmidicontroller cannot register device input port\n");
        return;
    }
    // Create output port
    if(!(g_pOutputPortDevice = jack_port_register(g_pJackClient, "controller output", JACK_DEFAULT_MIDI_TYPE, JackPortIsOutput, 0)))
    {
        fprintf(stderr, "libzynmidicontroller cannot register device output port\n");
        return;
    }

    // Create output port
    if(!(g_pOutputPort = jack_port_register(g_pJackClient, "output", JACK_DEFAULT_MIDI_TYPE, JackPortIsOutput, 0)))
    {
        fprintf(stderr, "libzynmidicontroller cannot register output port\n");
        return;
    }

    // Register JACK callbacks
    jack_set_process_callback(g_pJackClient, onJackProcess, 0);
    jack_set_port_connect_callback(g_pJackClient, onJackConnect, 0);

    if(jack_activate(g_pJackClient)) {
        fprintf(stderr, "libzynmidicontroller cannot activate client\n");
        return;
    }

    // Register the cleanup function to be called when program exits
    printf("zynmidicontroller initialisation complete\n");
}

__attribute__((constructor)) void zynmidicontroller(void) {
    printf("New instance of zynmidicontroller\n");
    init();
}

__attribute__((destructor)) void zynmidicontrollerend(void) {
    printf("Destroy instance of zynmidicontroller\n");
    g_bMutex = true;
    for(auto it = g_vSendQueue.begin(); it != g_vSendQueue.end(); ++it)
        delete *it;
    g_vSendQueue.clear();
    g_bMutex = false;
//    jack_client_close(g_pJackClient);
//    std::this_thread::sleep_for(std::chrono::milliseconds(5000));
}

void activate(bool activate) {
    if(!g_pJackClient)
        return;
    if(activate)
        jack_activate(g_pJackClient);
    else
        jack_deactivate(g_pJackClient);
}

// Public functions

void setMidiChannel(unsigned int channel) {
    if(channel < 16)
        g_nMidiChannel = channel;
}

void selectKnobs(unsigned int bank) {
    switch(g_nProtocol) {
        case 0:
            // Novation Launchkey Mini
            if(isDeviceConnected() && bank < 7) {
                g_nCCoffset = bank;
                sendDeviceMidi3(0xbf, 9, bank);
                DPRINTF("\tKnob bank %d selected\n", bank);
            }
    }
}

void selectPads(unsigned int mode) {
    switch(g_nProtocol) {
        case 0:
            // Novation Launchkey Mini
            if(isDeviceConnected()) {
                sendDeviceMidi3(0xbf, 3, mode);
                DPRINTF("\tPad mode %d selected\n", mode);
            }
    }
}

const char* getSupported(bool reset) {
    static size_t nIndex = 0;
    if(reset) {
        if(g_nProtocol == -1)
            nIndex = 0;
        else
            nIndex = g_nProtocol;
    } else {
        if(g_nProtocol != -1) {
            if(nIndex < g_nProtocol)
                nIndex = g_nProtocol;
            else
                nIndex = g_nSupportedQuant;
        }
    }
    if(nIndex >= g_nSupportedQuant)
        return NULL;
    return(g_sSupported[nIndex++]);
}