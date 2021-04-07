import discord
from discord.ext import commands
from discord_slash import SlashCommand, SlashContext
from discord_slash.utils.manage_commands import create_option
import mcstatus
import peewee as pw
import aioredis

import os
import asyncio
import logging
import time
import re
import base64
import io
import hashlib

logging.basicConfig(level=logging.INFO)

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN') or None
URL_PREFIX = os.getenv('URL_PREFIX') or None
if URL_PREFIX is None:
    logging.error("URL_PREFIX is unset! Server favicons will not be sent!")

bot = commands.Bot(command_prefix="!")
slash = SlashCommand(bot, sync_commands=True)

db = pw.SqliteDatabase('/config.db')

def file_hash(data):
    return hashlib.sha256(data).hexdigest()

class MyModel(pw.Model):
    class Meta:
        database = db

class Server(MyModel):
    ip = pw.CharField()
    port = pw.IntegerField()
    note = pw.CharField()
    guild = pw.BigIntegerField()
    command = pw.CharField()
    description = pw.CharField()

    class Meta:
        indexes = [
                   (('ip', 'port',), False),
                   (('guild', 'command',), True),
                  ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def markdown(self):
        return '`'+self.ip+'`:`'+str(self.port)+'`'

    @property
    def mcstatus(self):
        return mcstatus.MinecraftServer(self.ip, self.port)

class PlayerID(MyModel):
    discord_id = pw.BigIntegerField(unique=True)
    minecraft_username = pw.CharField(unique=True)

    @classmethod
    def contains(cls, other):
        # this will probably be used in conjunction with resolve(), but because the expected data volume is low, we can rely on the database to cache the result.
        try:
            item = cls.resolve(other)
            return True
        except cls.DoesNotExist:
            return False

    @classmethod
    def resolve(cls, other):
        if isinstance(other, int):
            return cls.get(cls.discord_id==other).minecraft_username
        else:
            return cls.get(cls.minecraft_username==other).discord_id

db.create_tables([Server, PlayerID])

def get_pending_embed(server):
    return discord.Embed(description='Querying server at ' + server.markdown + ' for information...', colour=discord.Colour.blue())                                   

def get_ping_pending_query_embed(server, ping, query=None):
    emb = discord.Embed(title='Server status:', colour=discord.Colour.from_rgb(255, 255, 0))
    emb.add_field(name='Server IP', value=server.markdown)
    emb.add_field(name='Ping latency', value=str(round(ping.latency, 2))+' ms', inline=True)
    emb.add_field(name='Slots', value=str(ping.players.online)+' / '+str(ping.players.max), inline=True)
    emb.add_field(name='Information limited', value='Waiting for query result from server...' if query is None else 'Server did not respond to query request.')
    return emb

def get_error_embed(server):
    emb = discord.Embed(colour=discord.Colour.from_rgb(255, 0, 0))
    emb.description = 'Server did not respond to ping or query request. Is it offline or overloaded?'
    return emb

def get_query_result_embed(server, query=None, ping=None):
    data = {}
    qfailed = False
    if query == False:
        qfailed = True
    
    if query:
        q = {'latency': query.latency}
        q.update(query.raw)
        qplayers = query.players.names
        query = q
    else:
        query = {}
        qplayers = []
    
    if ping:
        p = {'latency': ping.latency}
        p.update(ping.raw)
        ping = p
    else: ping = {}
    data['latency'] = max(query.get('latency') or 0, ping.get('latency') or 0)
    data['version'] = ping.get('version', {}).get('name') or query.get('software', {}).get('version')
    data['plugins'] = query.get('software', {}).get('plugins', [])
    data['favicon'] = ping.get('favicon')
    data['motd'] = ping.get('description') or query.get('hostname')
    data['modinfo'] = ping.get('modinfo') or ping.get('forgeData')
    data['slots-online'] = query.get('players', {}).get('online') or ping.get('players', {}).get('online')
    data['slots-max'] = query.get('players', {}).get('max') or ping.get('players', {}).get('max')
    data['players'] = qplayers or [x.get('name') for x in ping.get('players', {}).get('sample', [])]

    to_del = []
    for key in data:
        if not bool(data[key]): to_del.append(key)

    for key in to_del:
        if key == 'slots-online': continue
        del data[key]


    emb = discord.Embed(description='Server stats:', colour=discord.Colour.green()).add_field(name="Server IP", value=server.markdown, inline=False)
    
    if 'latency' in data:
        emb.add_field(name='Request latency', value=str(round(data['latency'], 2))+' ms')

    if 'version' in data:
        emb.add_field(name='Server version', value=data['version'])

    if 'motd' in data:
        motd = data['motd']
        if isinstance(motd, dict) and list(motd) == ['text']: motd = motd['text']
        motd = str(motd)
        motd = re.sub('§.', '', motd)  # remove all formatting characters
        emb.add_field(name='MOTD', value=motd)

    if 'slots-online' in data or 'slots-max' in data:
        emb.add_field(name='Slots', value=str(data.get('slots-online', '?'))+'/'+str(data.get('slots-max', '?')))\

    if 'plugins' in data:
        emb.add_field(name='Plugins', value=data['plugins'], inline=False)

    if 'players' in data:
        player_list = ''
        for nick in data['players']:
            player_list += nick
            if PlayerID.contains(nick):
                player_list += ' (aka <@'+str(PlayerID.resolve(nick))+'>)'
            player_list += '\n'
        emb.add_field(name='Players', value=player_list)

    if not query or not ping:
        if qfailed: desc = 'Querying the server failed, is the query interface not enabled?'
        elif query == dict(): desc = 'Waiting for result of query...'
        elif ping == dict(): desc = 'Waiting for result of ping...'
        else: desc = 'Pinging the server failed. This should not happen. '+str({'query': query, 'ping': len(ping)})
        emb.add_field(name='Incomplete data', value=desc)
        emb.colour = discord.Colour.gold()

    if data.get('favicon'):
        res = re.match('data:image\/(.*);base64,(.*)', data['favicon'])
        ext = res.group(1)
        data = base64.b64decode(bytes(res.group(2), 'utf-8'))
        if URL_PREFIX:
            emb.set_thumbnail(url=URL_PREFIX+file_hash(data)+'.'+ext)

    return emb, data.get('favicon')
    

def get_msg_embed(server, query=None, ping=None):
    favicon = None
    if query is None and ping is None:
        emb = get_pending_embed(server)
    elif ping is False and not query:
        emb = get_error_embed(server)
    else:
        emb, favicon = get_query_result_embed(server, query=query, ping=ping)

    if server.note:
        emb = emb.add_field(name="Note", value=server.note)
    return emb, favicon

def measure_latency(func):
    start = time.time()
    result = func()
    elapsed = time.time() - start
    result.latency = elapsed * 1000
    return result

@slash.slash(name="status",
             description="Fetch a Minecraft server's status.",
             options=[
                 create_option(name="ip", description="The server's connection IP.", option_type=3, required=True),
                 create_option(name="port", description="The server's connection port. Defaults to 25565.", option_type=4, required=False)
             ])
async def send_status(ctx, ip, port=25565):
    if ':' in ip:
        ip, port_line = ip.split(':')
    else: port_line = None
    port = int(port_line or port or 25565)
    server = Server(ip=ip, port=port)
    sr = server.mcstatus
    
    await ctx.defer()
    
    ping = bot.loop.run_in_executor(None, sr.status)
    query = bot.loop.run_in_executor(None, measure_latency, sr.query)


    # favicons are returned by ping requests, so when one is completed we delete our message and resend it with attachment

    done, pending = await asyncio.wait([ping, query], return_when=asyncio.FIRST_COMPLETED)

    done, pending = await asyncio.wait([ping, query], return_when=asyncio.ALL_COMPLETED)

    try:
        ping_res = await ping
    except:
        ping_res = False

    try:
        query_res = await query
    except:
        query_res = False
        
    e,f = get_msg_embed(server, query=query_res, ping=ping_res)
    if f:
        res = re.match('data:image\/(.*);base64,(.*)', f)
        ext = res.group(1)
        data = res.group(2)
        data = base64.b64decode(bytes(data, 'utf-8'))
        redis = await aioredis.create_redis('redis://redis')
        await redis.set(file_hash(data)+'.'+ext, data)
 
    msg = await ctx.send(embed=e)


def sync_guild_commands():
    for serv in Server.select().iterator():
        @slash.slash(name=serv.command, guild_ids=[serv.guild], description=serv.description)
        async def guild_command(ctx):
            await send_status.invoke(ctx, serv.ip, serv.port)


@slash.slash(name="mcwho",
             description="Identify a Discord user's Minecraft username.",
             options=[
                 create_option(name="user", description="The user to lookup.", option_type=6, required=True),
             ])
async def mcwho(ctx, user: discord.User):
    try:
        username = PlayerID.resolve(user.id)
        await ctx.send('User ' + user.mention + ' is associated with this Minecraft username: `'+username+'`.', allowed_mentions=discord.AllowedMentions.none())
    except PlayerID.DoesNotExist:
        await ctx.send('User ' + user.mention + ' is not associated with any Minecraft username.', allowed_mentions=discord.AllowedMentions.none())

@slash.slash(name="discordwho",
             description="Identify a Minecraft player's Discord account.",
             options=[
                 create_option(name="username", description="The username to lookup.", option_type=3, required=True),
             ])
async def discordwho(ctx, username):
    try:
        uid = PlayerID.resolve(username)
        await ctx.send('Minecraft username `'+username+'` is associated with this Discord user: <@'+str(uid)+'>.', allowed_mentions=discord.AllowedMentions.none())
    except PlayerID.DoesNotExist:
        await ctx.send('Minecraft username `'+username+'` is not associated with a Discord user.', allowed_mentions=discord.AllowedMentions.none())


sync_guild_commands()
bot.run(DISCORD_TOKEN)
