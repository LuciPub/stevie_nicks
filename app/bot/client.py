import discord
from discord.ext import commands
from utils.config import CMD_PREFIX, FFMPEG_PATH


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix=CMD_PREFIX, intents=intents)
    discord.FFmpegOpusAudio.ffmpeg_executable = FFMPEG_PATH

    @bot.event
    async def on_ready():
        try:
            await bot.tree.sync()
            print(f'✅ Bot ready as {bot.user}')
        except Exception as e:
            print(f'❌ Error syncing slash commands: {e}')

    @bot.event
    async def on_voice_state_update(member, before, after):
        """Cleanup when bot leaves voice channel"""
        if member == bot.user and before.channel is not None and after.channel is None:
            # Bot was disconnected from voice
            from services.music import clear_queue
            if before.channel.guild:
                clear_queue(before.channel.guild.id)
                print(
                    f"🧹 Cleaned up queue for guild {before.channel.guild.id}")

    from bot.commands import register_commands
    register_commands(bot)

    return bot
