import discord
import asyncio
import os
import random

from services.music import (
    add_to_queue, start_player, clear_queue, parse_time, seek_track,
    queues, current_tracks, cycle_loop_mode, pop_history,
    skip_history_once, build_now_playing_embed, _format_duration
)
from services.database import get_recent, get_top_tracks, get_most_active, log_event, get_user_status
from services.youtube import get_youtube_url, search_youtube, resolve_youtube_entry
from services.spotify import get_spotify_track, get_spotify_playlist, get_spotify_album, process_spotify_tracks
from utils.audio import create_clip, download_audio, cleanup_temp_dir
from utils.config import SPOTIFY_PATTERNS, MAX_QUEUE_DISPLAY, MAX_CLIP_LENGTH, MAX_FILE_SIZE


async def _get_first_valid_track(tracks):
    for i, track in enumerate(tracks[:2]):
        info = await get_youtube_url(track['search_query'])
        if info:
            return {
                'url': info['url'],
                'title': track['title'],
                'webpage_url': info.get('webpage_url'),
                'duration': track.get('duration') or info.get('duration'),
                'thumbnail': track.get('thumbnail') or info.get('thumbnail'),
            }, tracks[i+1:]
    return None, []


async def _handle_spotify_collection(tracks, guild_id, channel, user_id=0):
    if not tracks:
        return None, "❌ Empty or invalid collection"

    song, remaining = await _get_first_valid_track(tracks)
    if not song:
        return None, "❌ Cannot find tracks"

    song['requested_by'] = user_id

    if remaining:
        asyncio.create_task(process_spotify_tracks(
            remaining, guild_id, channel, user_id))

    return song, f"✅ Found {len(tracks)} tracks"


def register_commands(bot):
    @bot.tree.command(name="play", description="Play audio from URL or search")
    @discord.app_commands.describe(query="URL or search term")
    async def play(interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)

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

                    song = {
                        'url': youtube_info['url'],
                        'title': track_info['title'],
                        'webpage_url': youtube_info.get('webpage_url'),
                        'duration': track_info.get('duration') or youtube_info.get('duration'),
                        'thumbnail': track_info.get('thumbnail') or youtube_info.get('thumbnail'),
                    }

                elif pattern_type == 'playlist':
                    tracks = await get_spotify_playlist(item_id)
                    if not tracks:
                        return await interaction.followup.send("❌ Failed to load playlist")
                    song, msg = await _handle_spotify_collection(tracks, guild_id, interaction.channel, interaction.user.id)
                    if not song:
                        return await interaction.followup.send(msg)
                    await interaction.followup.send(msg)

                elif pattern_type == 'album':
                    tracks = await get_spotify_album(item_id)
                    if not tracks:
                        return await interaction.followup.send("❌ Failed to load album")
                    song, msg = await _handle_spotify_collection(tracks, guild_id, interaction.channel, interaction.user.id)
                    if not song:
                        return await interaction.followup.send(msg)
                    await interaction.followup.send(msg)

                break

        if not song:
            is_url = query.startswith(('http://', 'https://'))

            if is_url:
                youtube_info = await get_youtube_url(query)
                if not youtube_info:
                    return await interaction.followup.send("❌ Nothing found")
                song = youtube_info
            else:
                results = await search_youtube(query)
                if not results:
                    return await interaction.followup.send("❌ Nothing found")

                number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
                lines = []
                for i, r in enumerate(results):
                    dur = _format_duration(r.get('duration')) or '?:??'
                    channel = r.get('channel', '')
                    line = f"{number_emojis[i]} **{r['title']}**\n{channel} — `{dur}`"
                    lines.append(line)

                embed = discord.Embed(
                    title=f"🔍 Results for: {query[:50]}",
                    description='\n\n'.join(lines),
                    color=discord.Color.blue()
                )
                embed.set_footer(text="React to choose a track (30s timeout)")

                msg = await interaction.channel.send(embed=embed)
                for i in range(len(results)):
                    await msg.add_reaction(number_emojis[i])

                def check(reaction, user):
                    return (
                        user == interaction.user
                        and reaction.message.id == msg.id
                        and str(reaction.emoji) in number_emojis[:len(results)]
                    )

                try:
                    reaction, _ = await bot.wait_for('reaction_add', timeout=30.0, check=check)
                    choice = number_emojis.index(str(reaction.emoji))
                except asyncio.TimeoutError:
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    return await interaction.followup.send("⏱️ Selection timed out")

                try:
                    await msg.delete()
                except Exception:
                    pass

                chosen = results[choice]
                await interaction.followup.send(f"🔍 Loading **{chosen['title']}**...")

                youtube_info = await resolve_youtube_entry(chosen['webpage_url'])
                if not youtube_info:
                    return await interaction.followup.send("❌ Failed to load track")
                song = youtube_info

        song['requested_by'] = interaction.user.id

        if voice_client.is_playing() or voice_client.is_paused():
            add_to_queue(guild_id, song)
            await interaction.followup.send(f"✅ Added to queue: **{song['title']}**")
        else:
            await start_player(voice_client, song, guild_id, interaction.channel)

    @bot.tree.command(name="stop", description="Stop playback and clear queue")
    async def stop(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client

        if voice_client:
            clear_queue(interaction.guild_id)
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
            await voice_client.disconnect()
            await interaction.followup.send("⏹️ Stopped and cleared queue")
        else:
            await interaction.followup.send("❌ Not in a voice channel")

    @bot.tree.command(name="skip", description="Skip to next song")
    async def skip(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            track = current_tracks.get(guild_id)
            voice_client.stop()
            try:
                log_event(guild_id, interaction.user.id, 'skip', track['title'] if track else None)
            except Exception:
                pass
            await interaction.followup.send("⏭️ Skipped")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="queue", description="Show current queue")
    async def queue_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        if guild_id in queues and queues[guild_id]:
            embed = discord.Embed(title="🎵 Queue", color=discord.Color.blue())

            for i, song in enumerate(queues[guild_id][:MAX_QUEUE_DISPLAY], 1):
                name = "Next:" if i == 1 else f"{i}."
                value = f"**{song['title']}**" if i == 1 else song['title']
                embed.add_field(name=name, value=value, inline=False)

            remaining = len(queues[guild_id]) - MAX_QUEUE_DISPLAY
            if remaining > 0:
                embed.add_field(
                    name="", value=f"*And {remaining} more...*", inline=False)

            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("📋 Queue is empty")

    @bot.tree.command(name="pause", description="Pause playback")
    async def pause(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.followup.send("⏸️ Paused")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="resume", description="Resume playback")
    async def resume(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.followup.send("▶️ Resumed")
        else:
            await interaction.followup.send("❌ Nothing paused")

    @bot.tree.command(name="seek", description="Jump to position in song")
    @discord.app_commands.describe(position="Time position (seconds or mm:ss)")
    async def seek(interaction: discord.Interaction, position: str):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()) and guild_id in current_tracks:
            pos_sec = parse_time(position)
            success = await seek_track(voice_client, guild_id, pos_sec)
            if success:
                await interaction.followup.send(f"▶️ Jumped to {position}")
            else:
                await interaction.followup.send("❌ Seek failed")
        else:
            await interaction.followup.send("❌ Nothing playing")

    @bot.tree.command(name="loop", description="Cycle loop mode: off / track / queue")
    async def loop(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        mode = cycle_loop_mode(interaction.guild_id)
        labels = {'off': '➡️ Loop off', 'track': '🔂 Looping track', 'queue': '🔁 Looping queue'}
        await interaction.followup.send(labels[mode])

    @bot.tree.command(name="previous", description="Go back to the previous track")
    async def previous(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if not voice_client or (not voice_client.is_playing() and not voice_client.is_paused()):
            return await interaction.followup.send("❌ Nothing playing")

        prev = pop_history(guild_id)
        if not prev:
            return await interaction.followup.send("❌ No previous track")

        if guild_id not in queues:
            queues[guild_id] = []
        queues[guild_id].insert(0, prev)
        skip_history_once(guild_id)
        voice_client.stop()
        await interaction.followup.send(f"⏮️ Going back to: **{prev['title']}**")

    @bot.tree.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        if guild_id in queues and queues[guild_id]:
            random.shuffle(queues[guild_id])
            await interaction.followup.send(f"🔀 Shuffled {len(queues[guild_id])} tracks")
        else:
            await interaction.followup.send("📋 Queue is empty")

    @bot.tree.command(name="nowplaying", description="Show current track info")
    async def nowplaying(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        track = current_tracks.get(interaction.guild_id)
        if not track:
            return await interaction.followup.send("❌ Nothing playing")
        embed = build_now_playing_embed(track)
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="recent", description="Show recently played tracks")
    async def recent(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = get_recent(interaction.guild_id)
        if not rows:
            return await interaction.followup.send("📋 No play history yet")

        embed = discord.Embed(title="🕐 Recently Played", color=discord.Color.blue())
        for row in rows:
            user_tag = f"<@{row['user_id']}>" if row['user_id'] else "Unknown"
            played = row['played_at'][:16].replace('T', ' ')
            embed.add_field(
                name=row['track_title'][:100],
                value=f"{user_tag} — {played}",
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="toptracks", description="Show most played tracks")
    async def toptracks(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = get_top_tracks(interaction.guild_id)
        if not rows:
            return await interaction.followup.send("📋 No play history yet")

        embed = discord.Embed(title="🏆 Top Tracks", color=discord.Color.gold())
        for i, row in enumerate(rows, 1):
            embed.add_field(
                name=f"{i}. {row['track_title'][:100]}",
                value=f"**{row['plays']}** plays",
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="mostplayed", description="Show users who played the most")
    async def mostplayed(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = get_most_active(interaction.guild_id)
        if not rows:
            return await interaction.followup.send("📋 No play history yet")

        embed = discord.Embed(title="🎧 Most Active DJs", color=discord.Color.purple())
        for i, row in enumerate(rows, 1):
            user_tag = f"<@{row['user_id']}>" if row['user_id'] else "Unknown"
            embed.add_field(
                name=f"{i}. {user_tag}",
                value=f"**{row['plays']}** tracks played",
                inline=False
            )
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="like", description="Like the current track")
    async def like(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        track = current_tracks.get(guild_id)
        if not track:
            return await interaction.followup.send("❌ Nothing playing")
        try:
            log_event(guild_id, interaction.user.id, 'like', track['title'])
        except Exception:
            pass
        await interaction.followup.send(f"❤️ Liked **{track['title']}**")

    @bot.tree.command(name="status", description="Your listening stats (last 30 days)")
    @discord.app_commands.describe(user="User to check (default: yourself)")
    async def status(interaction: discord.Interaction, user: discord.User = None):
        await interaction.response.defer(ephemeral=True)
        target = user or interaction.user
        data = get_user_status(interaction.guild_id, target.id)

        if not data:
            return await interaction.followup.send(f"📋 No listening data for <@{target.id}> in the last 30 days")

        embed = discord.Embed(
            title=f"📊 Music Status — {target.display_name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="Overview",
            value=(
                f"**{data['total_plays']}** plays · "
                f"**{data['total_skips']}** skips · "
                f"**{data['total_likes']}** likes"
            ),
            inline=False
        )

        embed.add_field(name="Skip Rate", value=f"{data['skip_rate']:.1f}%", inline=True)
        embed.add_field(name="Like Rate", value=f"{data['like_rate']:.1f}%", inline=True)
        embed.add_field(name="Repeat Rate", value=f"{data['repeat_rate']:.1f}%", inline=True)

        if data['top_tracks']:
            tracks_text = '\n'.join(
                f"`{i}.` {row['track_title'][:45]} ({row['plays']}x)"
                for i, row in enumerate(data['top_tracks'], 1)
            )
            embed.add_field(name="Top Tracks", value=tracks_text, inline=False)

        if data['top_artists']:
            artists_text = '\n'.join(
                f"`{i}.` {row['artist'][:40]} ({row['plays']}x)"
                for i, row in enumerate(data['top_artists'], 1)
            )
            embed.add_field(name="Top Artists", value=artists_text, inline=False)

        labels = ['🌙 00-06', '🌅 06-12', '☀️ 12-18', '🌆 18-24']
        blocks = data['hour_blocks']
        total_h = sum(blocks) or 1
        dist_lines = []
        for label, count in zip(labels, blocks):
            pct = count / total_h * 100
            bar_len = round(pct / 10)
            bar = '█' * bar_len + '░' * (10 - bar_len)
            dist_lines.append(f"{label} {bar} {pct:.0f}%")
        embed.add_field(name="Listening Hours", value='\n'.join(dist_lines), inline=False)

        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="ping", description="Check bot latency")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)}ms", ephemeral=True)

    @bot.tree.command(name="cut", description="Cut a section of current song")
    @discord.app_commands.describe(start="Start time (seconds or mm:ss)", end="End time (seconds or mm:ss)")
    async def cut(interaction: discord.Interaction, start: str, end: str):
        await interaction.response.defer(ephemeral=True)
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
            file = discord.File(
                output_path, filename=f"clip_{clip_duration}s.mp3")
            await interaction.followup.send("✅ Here's your clip!", file=file)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")
        finally:
            if 'temp_dir' in locals():
                cleanup_temp_dir(temp_dir)

    @bot.tree.command(name="download", description="Download current song or from URL/search")
    @discord.app_commands.describe(query="URL or search term (leave empty to download current song)")
    async def download_cmd(interaction: discord.Interaction, query: str = None):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild_id

        if not query:
            voice_client = interaction.guild.voice_client
            if not voice_client or not voice_client.is_connected():
                return await interaction.followup.send("❌ Not connected to a voice channel")

            if guild_id not in current_tracks:
                return await interaction.followup.send("❌ Nothing playing")

            track = current_tracks[guild_id]
            url = track['url']
            title = track['title']
        else:
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
    async def download_text(ctx, *, query: str = None):
        await download_cmd(TextInteraction(ctx), query)

    @bot.command(name="loop")
    async def loop_text(ctx):
        await loop(TextInteraction(ctx))

    @bot.command(name="previous")
    async def previous_text(ctx):
        await previous(TextInteraction(ctx))

    @bot.command(name="shuffle")
    async def shuffle_text(ctx):
        await shuffle(TextInteraction(ctx))

    @bot.command(name="nowplaying")
    async def nowplaying_text(ctx):
        await nowplaying(TextInteraction(ctx))

    @bot.command(name="recent")
    async def recent_text(ctx):
        await recent(TextInteraction(ctx))

    @bot.command(name="toptracks")
    async def toptracks_text(ctx):
        await toptracks(TextInteraction(ctx))

    @bot.command(name="mostplayed")
    async def mostplayed_text(ctx):
        await mostplayed(TextInteraction(ctx))

    @bot.command(name="like")
    async def like_text(ctx):
        await like(TextInteraction(ctx))

    @bot.command(name="status")
    async def status_text(ctx, user: discord.User = None):
        await status(TextInteraction(ctx), user)
