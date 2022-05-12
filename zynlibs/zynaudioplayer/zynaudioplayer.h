/*  Audio file player library for Zynthian
    Copyright (C) 2021 Brian Walton <brian@riban.co.uk>
    License: LGPL V3
*/

#include <stdint.h>

#ifdef __cplusplus
extern "C"
{
#endif

/** @brief  Initialise a player instance
*   @retval int Player handle or -1 on failure
*/
int init();

/** @brief  Remove player from library
*   @param  player_handle Handle of player provided by init_player()
*/
void remove_player(int player_handle);

/** @brief Get jack client name
*   @param  player_handle Handle of player provided by init_player()
*   @retval const char* Jack client name
*/
const char* get_jack_client_name(int player_handle);

/** @brief  Open audio file
*   @param  player_handle Handle of player provided by init_player()
*   @param  filename Full path and name of file to load
*   @retval uint8_t True on success
*/
uint8_t open(int player_handle, const char* filename);

/** @brief  Save audio file
*   @param  player_handle Handle of player provided by init_player()
*   @param  filename Full path and name of file to create or overwrite
*   @retval uint8_t True on success
*/
uint8_t save(int player_handle, const char* filename);

/** @brief  Close audio file clearing all data
*   @param  player_handle Handle of player provided by init_player()
*/
void close_file(int player_handle);

/** @brief  Get filename of currently loaded file
*   @param  player_handle Handle of player provided by init_player()
*   @retval const char* Filename or emtpy string if no file loaded
*/
const char* get_filename(int player_handle);

/** @brief  Get duration of audio
*   @param  player_handle Handle of player provided by init_player()
*   @retval float Duration in seconds
*/
float get_duration(int player_handle);

/** @brief  Set playhead position
*   @param  player_handle Handle of player provided by init_player()
*   @param  time Time in seconds since start of audio
*/
void set_position(int player_handle, float time);

/** @brief  Get playhead position
*   @param  player_handle Handle of player provided by init_player()
*   @retval float Time in seconds since start of audio
*/
float get_position(int player_handle);

/** @brief  Set loop mode
*   @param  player_handle Handle of player provided by init_player()
*   @param  bLoop True to loop at end of audio
*/
void enable_loop(int player_handle, uint8_t bLoop);

/*  @brief  Get loop mode
*   @param  player_handle Handle of player provided by init_player()
*   @retval uint8_t 1 if looping, 0 if one-shot
*/
uint8_t is_loop(int player_handle);

/** @brief  Start playback
*   @param  player_handle Handle of player provided by init_player()
*/
void start_playback(int player_handle);

/** @brief  Stop playback
*   @param  player_handle Handle of player provided by init_player()
*/
void stop_playback(int player_handle);

/** @brief  Get play state
*   @param  player_handle Handle of player provided by init_player()
*   @retval uint8_t Play state [STOPPED|STARTING|PLAYING|STOPPING]
*/
uint8_t get_playback_state(int player_handle);

/** @brief  Get samplerate of currently loaded file
*   @param  player_handle Handle of player provided by init_player()
*   @retval int Samplerate in samples per seconds
*/
int get_samplerate(int player_handle);

/** @brief  Get quantity of channels in currently loaded file
*   @param  player_handle Handle of player provided by init_player()
*   @retval int Quantity of channels, e.g. 2 for stereo
*/
int get_channels(int player_handle);

/** @brief  Get quantity of frames (samples) in currently loaded file
*   @param  player_handle Handle of player provided by init_player()
*   @retval int Quantity of frames
*/
int get_frames(int player_handle);

/** @brief  Get format of currently loaded file
*   @param  player_handle Handle of player provided by init_player()
*   @retval int Bitwise OR of major and minor format type and optional endianness value
*   @see    sndfile.h for supported formats
*/
int get_format(int player_handle);

/** @brief  Set samplerate converter quality
*   @param  player_handle Handle of player provided by init_player()
*   @param  quality Samplerate conversion quality [SRC_SINC_BEST_QUALITY | SRC_SINC_MEDIUM_QUALITY | SRC_SINC_FASTEST | SRC_ZERO_ORDER_HOLD | SRC_LINEAR]
*   @retval uint8_t True on success, i.e. the quality parameter is valid
*   @note   Quality will apply to subsequently opened files, not currently open file
*/
uint8_t set_src_quality(int player_handle, unsigned int quality);

/** @brief  Set gain
*   @param  player_handle Handle of player provided by init_player()
*   @param  gain Gain factor (0..2)
*/
void set_gain(int player_handle, float gain);

/** @brief  Get gain (volume)
*   @param  player_handle Handle of player provided by init_player()
*   @retval float Gain
*/
float get_gain(int player_handle);

/** @brief  Set track(s) to playback
*   @param  player_handle Handle of player provided by init_player()
*   @param  track Index of first track to play or -1 for mix of all tracks
*   @note   Alternate tracks are sent to each output as stereo mix
*/
void set_playback_track(int player_handle, int track);

/** @brief  Get track(s) to playback
*   @param  player_handle Handle of player provided by init_player()
*   @retval int Index of first track to play or -1 for mix of all tracks
*/
int get_playback_track(int player_handle);

/**** Global functions ****/

/** @brief  Enable debug output
*   @param  bEnable True to enable, false to disable
*/
void enable_debug(int enable);

/** @brief  Get debug state
*   @retval int 1 if debug enabled
*/
int is_debug();

/** @brief  Get duration of a file without loading it
*   @param  player_handle Handle of player provided by init_player()
*   @param  filename Full path and name of file to load
*   @retval float Duration is seconds. Zero if cannot open file.
*/
float get_file_duration(const char* filename);

/** @brief  Get info from file meta data
*   @param  filename Full path and filename of audio file
*   @param  type Info type to retrieve [SF_STR_TITLE | SF_STR_COPYRIGHT | SF_STR_SOFTWARE | SF_STR_ARTIST | SF_STR_COMMENT | SF_STR_DATE| SF_STR_ALBUM | SF_STR_LICENSE | SF_STR_TRACKNUMBER | SF_STR_GENRE]
*   @retval const char Info value as c-string
*/
const char* get_file_info(const char* filename, int type);

/** @brief  Get quantity of instantiated players
*   @retval unsigned int Quantity of players
*/
unsigned int get_player_count();

#ifdef __cplusplus
}
#endif