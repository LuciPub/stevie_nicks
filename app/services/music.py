import discord
import asyncio
from utils.config import FFMPEG_OPTIONS, FFMPEG_PATH
from services.youtube import refresh_url


queues = {}
current_tracks = {}
_play_events = {}
_player_tasks = {}
_inactivity_tasks = {}
INACTIVITY_TIMEOUT = 300


def parse_time(time_str):
    if ':' in time_str:
        mins, secs = time_str.split(':')
        return int(mins) * 60 + int(secs)
    return int(time_str)


async def _create_source(track):
    url = track['url']
    for attempt in range(2):
        try:
            return discord.FFmpegPCMAudio(
                url, **FFMPEG_OPTIONS, executable=FFMPEG_PATH
            )
        except Exception as e:
            print(f"FFmpegPCMAudio attempt {attempt + 1} failed: {e}")
            if attempt == 0 and 'webpage_url' in track:
                new_url = await refresh_url(track['webpage_url'])
                if new_url:
                    track['url'] = new_url
                    url = new_url
                    continue
    return None


def _get_event(guild_id):
    if guild_id not in _play_events:
        _play_events[guild_id] = asyncio.Event()
    return _play_events[guild_id]


def signal_next(guild_id):
    if guild_id in _play_events:
        _play_events[guild_id].set()


async def start_player(voice_client, track, guild_id, channel):
    if guild_id in _player_tasks:
        task = _player_tasks[guild_id]
        if not task.done():
            add_to_queue(guild_id, track)
            return

    _cancel_inactivity_timer(guild_id)
    _player_tasks[guild_id] = asyncio.create_task(
        _player_loop(voice_client, track, guild_id, channel)
    )


async def _player_loop(voice_client, first_track, guild_id, channel):
    event = _get_event(guild_id)
    loop = asyncio.get_running_loop()
    track = first_track

    while track:
        source = await _create_source(track)
        if not source:
            print(f"Failed to create source for: {track.get('title')}")
            track = _next_track(guild_id)
            continue

        current_tracks[guild_id] = track
        event.clear()

        voice_client.play(
            source,
            after=lambda e, gid=guild_id, lp=loop: _on_track_end(e, gid, lp)
        )
        await channel.send(f"🎵 Now playing: **{track['title']}**")

        await event.wait()

        if not voice_client.is_connected():
            break

        track = _next_track(guild_id)

    if guild_id in current_tracks:
        del current_tracks[guild_id]
    if guild_id in _player_tasks:
        del _player_tasks[guild_id]

    _start_inactivity_timer(voice_client, guild_id)


def _on_track_end(error, guild_id, loop):
    if error:
        print(f"Player error: {error}")
    loop.call_soon_threadsafe(_play_events[guild_id].set)


def _next_track(guild_id):
    if guild_id in queues and queues[guild_id]:
        return queues[guild_id].pop(0)
    return None


def add_to_queue(guild_id, track):
    if guild_id not in queues:
        queues[guild_id] = []
    queues[guild_id].append(track)


def clear_queue(guild_id):
    if guild_id in queues:
        del queues[guild_id]
    if guild_id in current_tracks:
        del current_tracks[guild_id]
    if guild_id in _player_tasks:
        _player_tasks[guild_id].cancel()
        del _player_tasks[guild_id]
    if guild_id in _play_events:
        _play_events[guild_id].set()
    _cancel_inactivity_timer(guild_id)


def _cancel_inactivity_timer(guild_id):
    if guild_id in _inactivity_tasks:
        _inactivity_tasks[guild_id].cancel()
        del _inactivity_tasks[guild_id]


def _start_inactivity_timer(voice_client, guild_id):
    _cancel_inactivity_timer(guild_id)
    _inactivity_tasks[guild_id] = asyncio.create_task(
        _inactivity_disconnect(voice_client, guild_id)
    )


async def _inactivity_disconnect(voice_client, guild_id):
    try:
        await asyncio.sleep(INACTIVITY_TIMEOUT)
        if voice_client.is_connected():
            await voice_client.disconnect()
            print(f"⏱️ Disconnected from guild {guild_id} due to inactivity")
    except asyncio.CancelledError:
        pass
    finally:
        if guild_id in _inactivity_tasks:
            del _inactivity_tasks[guild_id]
