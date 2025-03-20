import os
from os import getenv
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
from dotenv import load_dotenv

load_dotenv()

discord.FFmpegOpusAudio.ffmpeg_executable = '/usr/bin/ffmpeg'

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '192',
    }],
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!!', intents=intents)

queues = {}

interactions_cache = {}


@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')
    print(f'FFmpeg path: {discord.FFmpegOpusAudio.ffmpeg_executable}')

    try:
        print("Tentando sincronizar comandos...")
        await bot.tree.sync()
        print("Comandos sincronizados globalmente!")
    except Exception as e:
        print(f'❌ Erro ao sincronizar comandos slash: {e}')


async def store_interaction(interaction):

    guild_id = interaction.guild_id
    interactions_cache[guild_id] = interaction


async def check_queue(guild_id, channel):
    if guild_id in queues and queues[guild_id]:
        next_song = queues[guild_id].pop(0)
        voice_client = None

        for vc in bot.voice_clients:
            if vc.guild.id == guild_id:
                voice_client = vc
                break

        if not voice_client:
            await channel.send("❌ Não estou mais conectado ao canal de voz!")
            return

        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                next_song['url'],
                **ffmpeg_options,
                executable=discord.FFmpegOpusAudio.ffmpeg_executable
            )

            def after_callback(e):
                if e:
                    print(f'Player error: {e}')
                asyncio.run_coroutine_threadsafe(
                    check_queue(guild_id, channel), bot.loop)

            voice_client.play(source, after=after_callback)
            await channel.send(f"🎵 Tocando agora: **{next_song['title']}**")
        except Exception as e:
            await channel.send(f"❌ Erro ao tocar a próxima música: {str(e)}")
            print(f"Erro detalhado: {e}")


@bot.tree.command(name="play", description="Toca música do YouTube/Spotify ou adiciona à fila")
@app_commands.describe(query="Link ou nome da música para tocar")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer(ephemeral=False)
    if not interaction.user.voice:
        await interaction.followup.send("❌ Você precisa estar em um canal de voz!")
        return

    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if not voice_client:
        try:
            voice_client = await voice_channel.connect()
        except discord.errors.ClientException as e:
            await interaction.followup.send(f"❌ Erro ao conectar: {str(e)}")
            return
    elif voice_client.channel != voice_channel:
        try:
            await voice_client.move_to(voice_channel)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao mover para seu canal: {str(e)}")
            return

    await interaction.followup.send(f"🔍 Buscando: `{query}`")

    
    if not query.startswith(('http://', 'https://')):
        query = f'ytsearch:{query}'

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            print(f"Extraindo informações para: {query}")
            info = ydl.extract_info(query, download=False)
            
            if 'entries' in info:
                
                if "spotify.com" in query and info.get('_type') == 'playlist':
                    songs = info['entries']
                    guild_id = interaction.guild_id
                    
                    if voice_client.is_playing() or voice_client.is_paused():
                        if guild_id not in queues:
                            queues[guild_id] = []
                        queues[guild_id].extend(
                            {'url': s['url'], 'title': s['title']} for s in songs)
                        await interaction.followup.send(f"✅ Playlist adicionada com {len(songs)} músicas à fila!")
                        return
                    else:
                        
                        first_song = songs[0]
                        rest = songs[1:]
                        if guild_id not in queues:
                            queues[guild_id] = []
                        queues[guild_id].extend(
                            {'url': s['url'], 'title': s['title']} for s in rest)
                        song = {'url': first_song['url'],
                                'title': first_song['title']}
                else:
                    info = info['entries'][0]
                    song = {'url': info['url'], 'title': info['title']}
            else:
                song = {'url': info['url'], 'title': info['title']}
            print(f"Informações extraídas com sucesso: {song['title']}")
    except Exception as e:
        await interaction.followup.send(f"❌ Não foi possível encontrar a música: {str(e)}")
        print(f"Erro ao extrair informações: {e}")
        return

    guild_id = interaction.guild_id

    if voice_client.is_playing() or voice_client.is_paused():
        if guild_id not in queues:
            queues[guild_id] = []
        queues[guild_id].append(song)
        await interaction.followup.send(f"✅ **{song['title']}** adicionado à fila!")
    else:
        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                song['url'],
                **ffmpeg_options,
                executable=discord.FFmpegOpusAudio.ffmpeg_executable
            )

            def after_callback(e):
                if e:
                    print(f'Player error: {e}')
                asyncio.run_coroutine_threadsafe(check_queue(
                    guild_id, interaction.channel), bot.loop)
            voice_client.play(source, after=after_callback)
            await interaction.followup.send(f"🎵 Tocando agora: **{song['title']}**")
        except Exception as e:
            error_msg = f"❌ Erro ao tocar música: {str(e)}"
            await interaction.followup.send(error_msg)
            print(error_msg)


@bot.tree.command(name="stop", description="Para a música e limpa a fila")
async def stop(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    voice_client = interaction.guild.voice_client

    if voice_client:
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        await voice_client.disconnect()

        guild_id = interaction.guild_id
        if guild_id in queues:
            del queues[guild_id]

        await interaction.followup.send("⏹️ Música parada e fila limpa!")
    else:
        await interaction.followup.send("❌ Não estou conectado a nenhum canal de voz!")


@bot.tree.command(name="skip", description="Pula para a próxima música da fila")
async def skip(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    voice_client = interaction.guild.voice_client

    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await interaction.followup.send("⏭️ Música pulada!")
    else:
        await interaction.followup.send("❌ Não estou tocando nenhuma música no momento!")


@bot.tree.command(name="queue", description="Mostra a fila de músicas")
async def queue_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    guild_id = interaction.guild_id

    if guild_id in queues and queues[guild_id]:
        embed = discord.Embed(title="🎵 Fila de Músicas",
                              color=discord.Color.blue())

        for i, song in enumerate(queues[guild_id], 1):
            if i == 1:
                embed.add_field(name=f"Próxima música:",
                                value=f"**{song['title']}**", inline=False)
            else:
                embed.add_field(
                    name=f"{i}.", value=f"{song['title']}", inline=False)

            if i >= 10:
                remaining = len(queues[guild_id]) - 10
                if remaining > 0:
                    embed.add_field(
                        name="", value=f"*E mais {remaining} músicas na fila...*", inline=False)
                break

        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send("📋 A fila está vazia!")


@bot.tree.command(name="pause", description="Pausa a música atual")
async def pause(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    voice_client = interaction.guild.voice_client

    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await interaction.followup.send("⏸️ Música pausada!")
    else:
        await interaction.followup.send("❌ Não estou tocando nenhuma música no momento!")


@bot.tree.command(name="resume", description="Retoma a música pausada")
async def resume(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    voice_client = interaction.guild.voice_client

    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await interaction.followup.send("▶️ Música retomada!")
    else:
        await interaction.followup.send("❌ Não há música pausada no momento!")


@bot.tree.command(name="ping", description="Verifica se o bot está funcionando")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latência: {round(bot.latency * 1000)}ms")


@bot.command(name="play")
async def play_prefix(ctx, *, query: str):

    if not ctx.author.voice:
        await ctx.send("❌ Você precisa estar em um canal de voz!")
        return

    voice_channel = ctx.author.voice.channel
    voice_client = ctx.voice_client

    if not voice_client:
        try:
            voice_client = await voice_channel.connect()
        except discord.errors.ClientException as e:
            await ctx.send(f"❌ Erro ao conectar: {str(e)}")
            return
    elif voice_client.channel != voice_channel:
        try:
            await voice_client.move_to(voice_channel)
        except Exception as e:
            await ctx.send(f"❌ Erro ao mover para seu canal: {str(e)}")
            return

    await ctx.send(f"🔍 Buscando: `{query}`")

    if not query.startswith(('http://', 'https://')):
        query = f'ytsearch:{query}'

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            print(f"Extraindo informações para: {query}")
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                info = info['entries'][0]

            song = {
                'url': info['url'],
                'title': info['title']
            }
            print(f"Informações extraídas com sucesso: {song['title']}")
    except Exception as e:
        await ctx.send(f"❌ Não foi possível encontrar a música: {str(e)}")
        print(f"Erro ao extrair informações: {e}")
        return

    guild_id = ctx.guild.id

    if voice_client.is_playing() or voice_client.is_paused():
        if guild_id not in queues:
            queues[guild_id] = []
        queues[guild_id].append(song)
        await ctx.send(f"✅ **{song['title']}** adicionado à fila!")
    else:
        try:
            print(f"Preparando para tocar: {song['title']}")
            print(f"URL: {song['url']}")
            print(f"FFmpeg path: {discord.FFmpegOpusAudio.ffmpeg_executable}")

            source = await discord.FFmpegOpusAudio.from_probe(
                song['url'],
                **ffmpeg_options,
                executable=discord.FFmpegOpusAudio.ffmpeg_executable
            )

            print("Áudio preparado com sucesso")

            def after_callback(e):
                if e:
                    print(f'Player error: {e}')
                asyncio.run_coroutine_threadsafe(
                    check_queue(guild_id, ctx.channel), bot.loop)

            voice_client.play(source, after=after_callback)
            await ctx.send(f"🎵 Tocando agora: **{song['title']}**")
        except Exception as e:
            error_msg = f"❌ Erro ao tocar música: {str(e)}"
            await ctx.send(error_msg)
            print(error_msg)
            if hasattr(e, '__traceback__'):
                import traceback
                print(''.join(traceback.format_exception(None, e, e.__traceback__)))


@bot.command(name="skip")
async def skip_prefix(ctx):
    voice_client = ctx.voice_client

    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        await ctx.send("⏭️ Música pulada!")
    else:
        await ctx.send("❌ Não estou tocando nenhuma música no momento!")


@bot.command(name="stop")
async def stop_prefix(ctx):
    voice_client = ctx.voice_client

    if voice_client:
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        await voice_client.disconnect()

        guild_id = ctx.guild.id
        if guild_id in queues:
            del queues[guild_id]

        await ctx.send("⏹️ Música parada e fila limpa!")
    else:
        await ctx.send("❌ Não estou conectado a nenhum canal de voz!")


@bot.command(name="queue")
async def queue_prefix(ctx):
    guild_id = ctx.guild.id

    if guild_id in queues and queues[guild_id]:
        embed = discord.Embed(title="🎵 Fila de Músicas",
                              color=discord.Color.blue())

        for i, song in enumerate(queues[guild_id], 1):
            if i == 1:
                embed.add_field(name=f"Próxima música:",
                                value=f"**{song['title']}**", inline=False)
            else:
                embed.add_field(
                    name=f"{i}.", value=f"{song['title']}", inline=False)

            if i >= 10:
                remaining = len(queues[guild_id]) - 10
                if remaining > 0:
                    embed.add_field(
                        name="", value=f"*E mais {remaining} músicas na fila...*", inline=False)
                break

        await ctx.send(embed=embed)
    else:
        await ctx.send("📋 A fila está vazia!")


@bot.command(name="pause")
async def pause_prefix(ctx):
    voice_client = ctx.voice_client

    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("⏸️ Música pausada!")
    else:
        await ctx.send("❌ Não estou tocando nenhuma música no momento!")


@bot.command(name="resume")
async def resume_prefix(ctx):
    voice_client = ctx.voice_client

    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("▶️ Música retomada!")
    else:
        await ctx.send("❌ Não há música pausada no momento!")


@bot.command(name="ping")
async def ping_prefix(ctx):
    await ctx.send(f"🏓 Pong! Latência: {round(bot.latency * 1000)}ms")


if __name__ == "__main__":
    token = getenv("DISCORD__TOKEN")
    if not token:
        print("❌ ERRO: Token do Discord não encontrado. Configure a variável de ambiente DISCORD__TOKEN.")
        exit(1)

    print("Iniciando o bot...")
    bot.run(token)
