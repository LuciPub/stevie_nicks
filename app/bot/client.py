import discord
from discord.ext import commands
from utils.config import CMD_PREFIX, FFMPEG_PATH


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=CMD_PREFIX, intents=intents)
    discord.FFmpegOpusAudio.ffmpeg_executable = FFMPEG_PATH

    @bot.event
    async def on_ready():
        try:
            await bot.tree.sync()
        except Exception as e:
            print(f'❌ Error syncing slash commands: {e}')

    from bot.commands import register_commands
    register_commands(bot)

    return bot
