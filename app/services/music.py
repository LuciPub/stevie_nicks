import discord
import asyncio
from utils.config import FFMPEG_OPTIONS, FFMPEG_PATH
from services.youtube import refresh_url
from services.database import log_play


queues = {}
current_tracks = {}
_play_events = {}
_player_tasks = {}
_inactivity_tasks = {}
_seeking = {}
_loop_modes = {}
_history = {}
_skip_history = {}
INACTIVITY_TIMEOUT = 300
HISTORY_LIMIT = 10


def parse_time(time_str):
    if ':' in time_str:
        mins, secs = time_str.split(':')
        return int(mins) * 60 + int(secs)
    return int(time_str)


def _format_duration(seconds):
    if not seconds:
        return None
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def build_now_playing_embed(track):
    embed = discord.Embed(title=track['title'], color=discord.Color.blue())
    duration = _format_duration(track.get('duration'))
    if duration:
        embed.add_field(name="Duration", value=duration, inline=True)
    if track.get('webpage_url'):
        embed.add_field(name="Source", value=f"[YouTube]({track['webpage_url']})", inline=True)
    if track.get('thumbnail'):
        embed.set_thumbnail(url=track['thumbnail'])
    return embed


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

    try:
        while track:
            source = await _create_source(track)
            if not source:
                print(f"Failed to create source for: {track.get('title')}")
                track = _next_track(guild_id)
                continue

            current_tracks[guild_id] = track
            event.clear()

            try:
                log_play(
                    guild_id,
                    track.get('requested_by', 0),
                    track['title'],
                    track.get('webpage_url')
                )
            except Exception:
                pass

            voice_client.play(
                source,
                after=lambda e, gid=guild_id, lp=loop: _on_track_end(e, gid, lp)
            )

            try:
                embed = build_now_playing_embed(track)
                await channel.send(embed=embed)
            except Exception:
                pass

            await event.wait()

            if not voice_client.is_connected():
                break

            mode = _loop_modes.get(guild_id, 'off')
            if mode == 'track':
                pass
            else:
                if not _skip_history.get(guild_id):
                    if guild_id not in _history:
                        _history[guild_id] = []
                    _history[guild_id].append(track)
                    if len(_history[guild_id]) > HISTORY_LIMIT:
                        _history[guild_id].pop(0)
                _skip_history[guild_id] = False
                if mode == 'queue':
                    add_to_queue(guild_id, track)
                track = _next_track(guild_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"Player loop error for guild {guild_id}: {e}")
    finally:
        if guild_id in current_tracks:
            del current_tracks[guild_id]
        if guild_id in _player_tasks:
            del _player_tasks[guild_id]
        if voice_client.is_connected():
            _start_inactivity_timer(voice_client, guild_id)


def _on_track_end(error, guild_id, loop):
    if error:
        print(f"Player error: {error}")
    if _seeking.get(guild_id):
        return
    loop.call_soon_threadsafe(_play_events[guild_id].set)


async def seek_track(voice_client, guild_id, pos_sec):
    track = current_tracks.get(guild_id)
    if not track:
        return False

    url = track['url']
    if 'webpage_url' in track:
        new_url = await refresh_url(track['webpage_url'])
        if new_url:
            track['url'] = new_url
            url = new_url

    try:
        source = discord.FFmpegPCMAudio(
            url,
            before_options=f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {pos_sec}",
            options="-vn",
            executable=FFMPEG_PATH
        )
    except Exception:
        return False

    loop = asyncio.get_running_loop()
    _seeking[guild_id] = True
    voice_client.stop()
    await asyncio.sleep(0.05)
    _seeking[guild_id] = False

    voice_client.play(
        source,
        after=lambda e, gid=guild_id, lp=loop: _on_track_end(e, gid, lp)
    )
    return True


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
    if guild_id in _seeking:
        del _seeking[guild_id]
    if guild_id in _loop_modes:
        del _loop_modes[guild_id]
    if guild_id in _history:
        del _history[guild_id]
    if guild_id in _skip_history:
        del _skip_history[guild_id]
    if guild_id in _player_tasks:
        _player_tasks[guild_id].cancel()
        del _player_tasks[guild_id]
    if guild_id in _play_events:
        _play_events[guild_id].set()
    _cancel_inactivity_timer(guild_id)


def cycle_loop_mode(guild_id):
    current = _loop_modes.get(guild_id, 'off')
    modes = ['off', 'track', 'queue']
    next_mode = modes[(modes.index(current) + 1) % 3]
    _loop_modes[guild_id] = next_mode
    return next_mode


def pop_history(guild_id):
    hist = _history.get(guild_id, [])
    if hist:
        return hist.pop()
    return None


def skip_history_once(guild_id):
    _skip_history[guild_id] = True


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
        if voice_client.is_connected() and not voice_client.is_playing() and not voice_client.is_paused():
            await voice_client.disconnect()
            print(f"⏱️ Disconnected from guild {guild_id} due to inactivity")
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        if guild_id in _inactivity_tasks:
            del _inactivity_tasks[guild_id]
