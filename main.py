import discord
from discord.ext import commands
from discord_slash import SlashCommand, SlashContext
import os

import logging

logging.basicConfig(level=logging.DEBUG)

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN') or None

bot = commands.Bot(command_prefix="!")
slash = SlashCommand(bot)

@slash.slash(name="test", guild_ids=[775744109359923221])
async def _test(ctx: SlashContext):
    embed = discord.Embed(title="embed test")
    await ctx.send(content="test", embeds=[embed])

bot.run(DISCORD_TOKEN)
