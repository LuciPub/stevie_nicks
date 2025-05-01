from os import getenv
from bot.client import create_bot

if __name__ == "__main__":
    token = getenv("DISCORD__TOKEN")
    if not token:
        print("❌ ERROR: Discord token not found")
        exit(1)

    bot = create_bot()
    print("Starting bot...")
    bot.run(token)
