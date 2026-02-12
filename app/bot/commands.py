import discord
import asyncio
import os

from services.music import add_to_queue, check_queue, clear_queue, play_track, parse_time, queues, current_tracks
from services.youtube import get_youtube_url
from services.spotify import get_spotify_track, get_spotify_playlist, get_spotify_album, process_spotify_tracks
from utils.audio import create_clip, download_audio, cleanup_temp_dir
from utils.config import SPOTIFY_PATTERNS, MAX_QUEUE_DISPLAY, MAX_CLIP_LENGTH, MAX_FILE_SIZE


def _get_loop(voice_client):
    return voice_client.loop if hasattr(voice_client, 'loop') else asyncio.get_event_loop()


def _create_after_callback(voice_client, guild_id, channel):
    def callback(e):
        if e:
            print(f'Player error: {e}')
        try:
            asyncio.run_coroutine_threadsafe(check_queue(guild_id, channel), _get_loop(voice_client))
        except Exception as err:
            print(f"Error scheduling queue check: {err}")
    return callback


async def _get_first_valid_track(tracks):
    for i, track in enumerate(tracks[:2]):
        info = await get_youtube_url(track['search_query'])
        if info:
            return {'url': info['url'], 'title': track['title']}, tracks[i+1:]
    return None, []


async def _handle_spotify_collection(tracks, guild_id, channel):
    if not tracks:
        return None, "❌ Empty or invalid collection"

    song, remaining = await _get_first_valid_track(tracks)
    if not song:
        return None, "❌ Cannot find tracks"

    if remaining:
        asyncio.create_task(process_spotify_tracks(remaining, guild_id, channel))

    return song, f"✅ Found {len(tracks)} tracks"


def register_commands(bot):
    @bot.tree.command(name="play", description="Play audio from URL or search")
    @discord.app_commands.describe(query="URL or search term")
    async def play(interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            return await interaction.followup.send("❌ Join a voice channel first")

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if not voice_client:
            try:
                voice_client = await voice_channel.connect()
            except Exception:
                return await interaction.followup.send("❌ Connection error")
        elif voice_client.channel != voice_channel:
            try:
                await voice_client.move_to(voice_channel)
            except Exception:
                return await interaction.followup.send("❌ Cannot move to your channel")

        guild_id = interaction.guild_id
        await interaction.followup.send("🔍 Searching...")

        song = None
        for pattern_type, pattern in SPOTIFY_PATTERNS.items():
            match = pattern.match(query)
            if match:
                item_id = match.group(1)

                if pattern_type == 'track':
                    track_info = await get_spotify_track(item_id)
                    if not track_info:
                        return await interaction.followup.send("❌ Failed to fetch track")

                    youtube_info = await get_youtube_url(track_info['search_query'])
                    if not youtube_info:
                        return await interaction.followup.send("❌ Couldn't find track")

                    song = {'url': youtube_info['url'], 'title': track_info['title']}

                elif pattern_type == 'playlist':
                    tracks = await get_spotify_playlist(item_id)
                    song, msg = await _handle_spotify_collection(tracks, guild_id, interaction.channel)
                    if not song:
                        return await interaction.followup.send(msg)
                    await interaction.followup.send(msg)

                elif pattern_type == 'album':
                    tracks = await get_spotify_album(item_id)
                    song, msg = await _handle_spotify_collection(tracks, guild_id, interaction.channel)
                    if not song:
                        return await interaction.followup.send(msg)
                    await interaction.followup.send(msg)

                break

        if not song:
            youtube_info = await get_youtube_url(query)
            if not youtube_info:
                return await interaction.followup.send("❌ Nothing found")
            song = youtube_info

        if voice_client.is_playing() or voice_client.is_paused():
            add_to_queue(guild_id, song)
            await interaction.followup.send(f"✅ Added to queue: **{song['title']}**")
        else:
            source = await play_track(voice_client, song, guild_id)
            if source:
                voice_client.play(source, after=_create_after_callback(voice_client, guild_id, interaction.channel))
                await interaction.followup.send(f"🎵 Now playing: **{song['title']}**")
            else:
                await interaction.followup.send("❌ Error playing track")

    @bot.tree.command(name="stop", description="Stop playback and clear queue")
    async def stop(interaction: discord.Interaction):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client

        if voice_client:
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
            await voice_client.disconnect()
            clear_queue(interaction.guild_id)
            await interaction.followup.send("⏹️ Stopped and cleared queue")
        else:
            await interaction.followup.send("❌ Not in a voice channel")

    @bot.tree.command(name="skip", description="Skip to next song")
    async def skip(interaction: discord.Interaction):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            voice_client.stop()
            await interaction.followup.send("⏭️ Skipped")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="queue", description="Show current queue")
    async def queue_cmd(interaction: discord.Interaction):
        await interaction.response.defer()
        guild_id = interaction.guild_id

        if guild_id in queues and queues[guild_id]:
            embed = discord.Embed(title="🎵 Queue", color=discord.Color.blue())

            for i, song in enumerate(queues[guild_id][:MAX_QUEUE_DISPLAY], 1):
                name = "Next:" if i == 1 else f"{i}."
                value = f"**{song['title']}**" if i == 1 else song['title']
                embed.add_field(name=name, value=value, inline=False)

            remaining = len(queues[guild_id]) - MAX_QUEUE_DISPLAY
            if remaining > 0:
                embed.add_field(name="", value=f"*And {remaining} more...*", inline=False)

            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("📋 Queue is empty")

    @bot.tree.command(name="pause", description="Pause playback")
    async def pause(interaction: discord.Interaction):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.followup.send("⏸️ Paused")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="resume", description="Resume playback")
    async def resume(interaction: discord.Interaction):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.followup.send("▶️ Resumed")
        else:
            await interaction.followup.send("❌ Nothing paused")

    @bot.tree.command(name="seek", description="Jump to position in song")
    @discord.app_commands.describe(position="Time position (seconds or mm:ss)")
    async def seek(interaction: discord.Interaction, position: str):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if voice_client and voice_client.is_playing() and guild_id in current_tracks:
            pos_sec = parse_time(position)
            song = current_tracks[guild_id]

            try:
                source = await discord.FFmpegOpusAudio.from_probe(
                    song['url'],
                    before_options=f"-reconnect 1 -ss {pos_sec}",
                    options="-vn",
                )
                voice_client.stop()
                voice_client.play(source)
                await interaction.followup.send(f"▶️ Jumped to {position}")
            except Exception:
                await interaction.followup.send("❌ Seek failed")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="ping", description="Check bot latency")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms")

    @bot.tree.command(name="cut", description="Cut a section of current song")
    @discord.app_commands.describe(start="Start time (seconds or mm:ss)", end="End time (seconds or mm:ss)")
    async def cut(interaction: discord.Interaction, start: str, end: str):
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if not voice_client or not voice_client.is_playing():
            return await interaction.followup.send("❌ Nothing playing")

        try:
            start_sec = parse_time(start)
            end_sec = parse_time(end)

            if end_sec <= start_sec:
                return await interaction.followup.send("❌ End time must be after start time")

            if end_sec - start_sec > MAX_CLIP_LENGTH:
                return await interaction.followup.send(f"❌ Max clip length is {MAX_CLIP_LENGTH}s")

            if guild_id not in current_tracks:
                return await interaction.followup.send("❌ Cannot determine current song")

            playing_url = current_tracks[guild_id]['url']
            await interaction.followup.send("✂️ Processing clip...")

            output_path, temp_dir = await create_clip(playing_url, start_sec, end_sec)

            if not output_path:
                return await interaction.followup.send(f"❌ Failed to create clip: {temp_dir}")

            clip_duration = end_sec - start_sec
            file = discord.File(output_path, filename=f"clip_{clip_duration}s.mp3")
            await interaction.followup.send("✅ Here's your clip!", file=file)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
        finally:
            if 'temp_dir' in locals():
                cleanup_temp_dir(temp_dir)

    @bot.tree.command(name="download", description="Download audio")
    @discord.app_commands.describe(query="URL or search term")
    async def download_cmd(interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        spotify_track_match = SPOTIFY_PATTERNS['track'].match(query)

        if spotify_track_match:
            track_id = spotify_track_match.group(1)
            track_info = await get_spotify_track(track_id)

            if not track_info:
                return await interaction.followup.send("❌ Failed to fetch track")

            youtube_info = await get_youtube_url(track_info['search_query'])

            if not youtube_info:
                return await interaction.followup.send("❌ Couldn't find track")

            url = youtube_info['url']
            title = track_info['title']
        else:
            youtube_info = await get_youtube_url(query)

            if not youtube_info:
                return await interaction.followup.send("❌ Nothing found")

            url = youtube_info['url']
            title = youtube_info['title']

        await interaction.followup.send("⏳ Downloading...")

        output_path, temp_dir = await download_audio(url, title)

        if not output_path:
            return await interaction.followup.send(f"❌ Failed: {temp_dir}")

        file_size = os.path.getsize(output_path)
        if file_size > MAX_FILE_SIZE:
            cleanup_temp_dir(temp_dir)
            return await interaction.followup.send("❌ File too large (>8MB)")

        filename = f"{title.replace(' ', '_')[:40]}.mp3"
        file = discord.File(output_path, filename=filename)

        await interaction.followup.send(f"✅ Download complete ({file_size/1024/1024:.1f}MB)", file=file)
        cleanup_temp_dir(temp_dir)

    class TextInteraction:
        def __init__(self, ctx):
            self.guild_id = ctx.guild.id if ctx.guild else None
            self.guild = ctx.guild
            self.channel = ctx.channel
            self.user = ctx.author
            self.response = self
            self.voice_client = ctx.guild.voice_client if ctx.guild else None

        async def defer(self, **kwargs):
            pass

        class Followup:
            def __init__(self, channel):
                self.channel = channel

            async def send(self, content=None, file=None, embed=None):
                if file:
                    await self.channel.send(content, file=file)
                elif embed:
                    await self.channel.send(embed=embed)
                else:
                    await self.channel.send(content)

        @property
        def followup(self):
            return self.Followup(self.channel)

    @bot.command(name="play")
    async def play_text(ctx, *, query: str):
        await play(TextInteraction(ctx), query)

    @bot.command(name="stop")
    async def stop_text(ctx):
        await stop(TextInteraction(ctx))

    @bot.command(name="skip")
    async def skip_text(ctx):
        await skip(TextInteraction(ctx))

    @bot.command(name="queue")
    async def queue_text(ctx):
        await queue_cmd(TextInteraction(ctx))

    @bot.command(name="pause")
    async def pause_text(ctx):
        await pause(TextInteraction(ctx))

    @bot.command(name="resume")
    async def resume_text(ctx):
        await resume(TextInteraction(ctx))

    @bot.command(name="ping")
    async def ping_text(ctx):
        await ping(TextInteraction(ctx))

    @bot.command(name="cut")
    async def cut_text(ctx, start: str, end: str):
        await cut(TextInteraction(ctx), start, end)

    @bot.command(name="download")
    async def download_text(ctx, *, query: str):
        await download_cmd(TextInteraction(ctx), query)
