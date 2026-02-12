import discord
import asyncio
from utils.config import FFMPEG_OPTIONS, FFMPEG_PATH


queues = {}
current_tracks = {}


def parse_time(time_str):
    if ':' in time_str:
        mins, secs = time_str.split(':')
        return int(mins) * 60 + int(secs)
    return int(time_str)


async def play_track(voice_client, track, guild_id):
    """Play a track in the voice channel"""
    try:
        source = await discord.FFmpegOpusAudio.from_probe(
            track['url'],
            **FFMPEG_OPTIONS,
            executable=FFMPEG_PATH
        )
        current_tracks[guild_id] = track
        return source
    except Exception as e:
        print(f"Error playing track: {e}")
        return None


async def check_queue(guild_id, channel):
    """Check and play the next song in queue"""
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].pop(0)
        voice_client = discord.utils.get(
            channel.guild.voice_clients, guild=channel.guild)

        if not voice_client or not voice_client.is_connected():
            clear_queue(guild_id)
            return False

        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                next_song['url'],
                **FFMPEG_OPTIONS,
                executable=FFMPEG_PATH
            )
            current_tracks[guild_id] = next_song

            def after_callback(e):
                if e:
                    print(f'Player error: {e}')

                # Get the current event loop from the bot
                try:
                    loop = voice_client.loop if hasattr(voice_client, 'loop') else asyncio.new_event_loop()
                    asyncio.run_coroutine_threadsafe(
                        check_queue(guild_id, channel), loop)
                except Exception as loop_error:
                    print(f"Error scheduling next track: {loop_error}")

            voice_client.play(source, after=after_callback)
            await channel.send(f"🎵 Now playing: **{next_song['title']}**")
            return True
        except Exception as e:
            print(f"Error playing next track: {e}")
            # Try to play next song in queue if current failed
            try:
                loop = voice_client.loop if hasattr(voice_client, 'loop') else asyncio.new_event_loop()
                asyncio.run_coroutine_threadsafe(
                    check_queue(guild_id, channel), loop)
            except:
                pass
            return False
    else:
        # Queue is empty, cleanup
        if guild_id in current_tracks:
            del current_tracks[guild_id]
    return False


def add_to_queue(guild_id, track):
    """Add a track to the queue"""
    if guild_id not in queues:
        queues[guild_id] = []
    queues[guild_id].append(track)


def clear_queue(guild_id):
    """Clear the queue for a guild"""
    if guild_id in queues:
        del queues[guild_id]
    if guild_id in current_tracks:
        del current_tracks[guild_id]
