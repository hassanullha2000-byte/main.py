main.py

""" Telegram moderation bot + crypto price checker Features:

/ban user_id|@username - ban a user (admin only)

/unban user_id|@username - unban

/mute user_id|@username [minutes] - restrict from sending messages

/unmute user_id|@username - lift restriction

/group_off - set group to read-only for non-admins

/group_on - restore group sending for non-admins

/set_name <new name> - change the bot's name (bot owner only)

Handles join requests (auto-pending) with approve/reject buttons (admin can use inline buttons)

/price <symbol> - fetch crypto price from CoinGecko (e.g. /price btc)


Simple JSON file storage (banned.json, muted.json) Requires: pyrogram, tgcrypto, requests

Deploy: push to GitHub and connect repo to Railway. Set env var BOT_TOKEN (and optionally API_ID, API_HASH) """

import json import time import asyncio from pathlib import Path from typing import Optional

import requests from pyrogram import Client, filters from pyrogram.types import (Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest, ChatPermissions)

---- Configuration ----

SESSION_NAME = "bot_session"

Use environment variables in Railway; placeholder here reads from env when running

import os

>>> SET YOUR CREDENTIALS IN ENVIRONMENT VARIABLES <<<

DO NOT hardcode secrets in code.

BOT_TOKEN = "8501885558:AAF11l5gbCjboPje-FKFtiCVL-PHSVGgL90" API_ID = 37400002 API_HASH = "9735220098debacb2c96cfde6e9ec652" API_ID = os.environ.get("API_ID") API_HASH = os.environ.get("API_HASH")

storage files

DATA_DIR = Path("data") DATA_DIR.mkdir(exist_ok=True) BANNED_FILE = DATA_DIR / "banned.json" MUTED_FILE = DATA_DIR / "muted.json"

ensure files

for f in (BANNED_FILE, MUTED_FILE): if not f.exists(): f.write_text("{}")

helpers to load/save

def load_json(path: Path) -> dict: try: return json.loads(path.read_text()) except Exception: return {}

def save_json(path: Path, data: dict): path.write_text(json.dumps(data, indent=2))

basic storage

banned = load_json(BANNED_FILE)  # {chat_id: [user_id,...]} muted = load_json(MUTED_FILE)    # {chat_id: {user_id: unmute_timestamp}}

---- Utility functions ----

def parse_target(arg: str) -> Optional[int]: """Try to parse a user id or @username to int where possible. For username we return None and let the bot resolve it later via get_users.""" if not arg: return None arg = arg.strip() if arg.startswith("@"): return None try: return int(arg) except ValueError: return None

async def resolve_user(client: Client, chat_id: int, arg: str): # arg may be user_id, @username, or reply if not arg: return None arg = arg.strip() if arg.startswith("@"): try: user = await client.get_users(arg) return user except Exception: return None try: uid = int(arg) return await client.get_users(uid) except Exception: return None

def is_admin(message: Message) -> bool: try: mem = message.chat.get_member(message.from_user.id) return mem.status in ("administrator", "creator") except Exception: # fallback: assume private chat or cannot check return False

---- Pyrogram Client ----

app = Client(SESSION_NAME, bot_token=BOT_TOKEN, api_id=API_ID or None, api_hash=API_HASH or None)

---- Commands ----

@app.on_message(filters.command("start") & filters.private) async def on_start(client, message: Message): await message.reply_text("Hello! I'm a moderation & crypto bot. Use /help to see commands.")

@app.on_message(filters.command("help")) async def on_help(client, message: Message): txt = ("Available commands:\n" "/ban id|@username - ban user (admins)\n" "/unban id|@username - unban\n" "/mute id|@username [minutes] - mute user for minutes\n" "/unmute id|@username - unmute\n" "/group_off - set group to read-only (admins)\n" "/group_on - restore group (admins)\n" "/set_name <new name> - change bot profile name (bot owner)\n" "/price <symbol> - get crypto price (eg. /price btc)\n") await message.reply_text(txt)

@app.on_message(filters.command("ban") & filters.group) async def cmd_ban(client, message: Message): if not message.from_user: return # admin check try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass

target_arg = None
if message.reply_to_message:
    target_user = message.reply_to_message.from_user
else:
    if len(message.command) >= 2:
        target_arg = message.command[1]
        target_user = await resolve_user(client, message.chat.id, target_arg)
    else:
        await message.reply_text("Reply to a user or give user id/username.")
        return

if not target_user:
    await message.reply_text("Couldn't find that user.")
    return

# ban (kick until forever)
try:
    await client.ban_chat_member(message.chat.id, target_user.id)
except Exception as e:
    await message.reply_text(f"Failed to ban: {e}")
    return

chat_rec = banned.get(str(message.chat.id), [])
if target_user.id not in chat_rec:
    chat_rec.append(target_user.id)
banned[str(message.chat.id)] = chat_rec
save_json(BANNED_FILE, banned)
await message.reply_text(f"Banned {target_user.first_name} ({target_user.id}).")

@app.on_message(filters.command("unban") & filters.group) async def cmd_unban(client, message: Message): try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass

if message.reply_to_message:
    target_user = message.reply_to_message.from_user
else:
    if len(message.command) >= 2:
        target_user = await resolve_user(client, message.chat.id, message.command[1])
    else:
        await message.reply_text("Reply to a user or give user id/username.")
        return

if not target_user:
    await message.reply_text("Couldn't find that user.")
    return

try:
    await client.unban_chat_member(message.chat.id, target_user.id)
except Exception as e:
    await message.reply_text(f"Failed to unban: {e}")
    return

chat_rec = banned.get(str(message.chat.id), [])
if target_user.id in chat_rec:
    chat_rec.remove(target_user.id)
banned[str(message.chat.id)] = chat_rec
save_json(BANNED_FILE, banned)
await message.reply_text(f"Unbanned {target_user.first_name} ({target_user.id}).")

@app.on_message(filters.command("mute") & filters.group) async def cmd_mute(client, message: Message): # only admins try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass

# target
if message.reply_to_message:
    target_user = message.reply_to_message.from_user
    args = message.command[1:]
else:
    if len(message.command) >= 2:
        target_user = await resolve_user(client, message.chat.id, message.command[1])
        args = message.command[2:]
    else:
        await message.reply_text("Reply to a user or give user id/username.")
        return

if not target_user:
    await message.reply_text("Couldn't find that user.")
    return

minutes = 30
if args:
    try:
        minutes = int(args[0])
    except Exception:
        minutes = 30

until_ts = int(time.time()) + minutes * 60
# restrict the user from sending messages
try:
    await client.restrict_chat_member(
        message.chat.id,
        target_user.id,
        permissions=ChatPermissions(can_send_messages=False,
                                    can_send_media_messages=False,
                                    can_send_other_messages=False,
                                    can_add_web_page_previews=False),
        until_date=until_ts
    )
except Exception as e:
    await message.reply_text(f"Failed to mute: {e}")
    return

chat_muted = muted.get(str(message.chat.id), {})
chat_muted[str(target_user.id)] = until_ts
muted[str(message.chat.id)] = chat_muted
save_json(MUTED_FILE, muted)
await message.reply_text(f"Muted {target_user.first_name} for {minutes} minutes.")

@app.on_message(filters.command("unmute") & filters.group) async def cmd_unmute(client, message: Message): try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass

if message.reply_to_message:
    target_user = message.reply_to_message.from_user
else:
    if len(message.command) >= 2:
        target_user = await resolve_user(client, message.chat.id, message.command[1])
    else:
        await message.reply_text("Reply to a user or give user id/username.")
        return

if not target_user:
    await message.reply_text("Couldn't find that user.")
    return

try:
    await client.restrict_chat_member(
        message.chat.id,
        target_user.id,
        permissions=ChatPermissions(can_send_messages=True,
                                    can_send_media_messages=True,
                                    can_send_other_messages=True,
                                    can_add_web_page_previews=True),
        until_date=0
    )
except Exception as e:
    await message.reply_text(f"Failed to unmute: {e}")
    return

chat_muted = muted.get(str(message.chat.id), {})
if str(target_user.id) in chat_muted:
    chat_muted.pop(str(target_user.id), None)
muted[str(message.chat.id)] = chat_muted
save_json(MUTED_FILE, muted)
await message.reply_text(f"Unmuted {target_user.first_name}.")

@app.on_message(filters.command("group_off") & filters.group) async def cmd_group_off(client, message: Message): # set group read-only for non-admins try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass try: await client.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False)) await message.reply_text("Group set to read-only for non-admins.") except Exception as e: await message.reply_text(f"Failed: {e}")

@app.on_message(filters.command("group_on") & filters.group) async def cmd_group_on(client, message: Message): try: m = await client.get_chat_member(message.chat.id, message.from_user.id) if m.status not in ("administrator", "creator"): await message.reply_text("Only admins can use this.") return except Exception: pass try: await client.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)) await message.reply_text("Group permissions restored.") except Exception as e: await message.reply_text(f"Failed: {e}")

@app.on_message(filters.command("set_name") & filters.private) async def cmd_set_name(client, message: Message): # Only bot owner (the user who started the bot) should be able. We'll check against BOT_OWNER env var BOT_OWNER = os.environ.get("BOT_OWNER") if BOT_OWNER and str(message.from_user.id) != str(BOT_OWNER): await message.reply_text("Only the bot owner can change the name. Set BOT_OWNER env var to your user id.") return if len(message.command) < 2: await message.reply_text("Usage: /set_name New Name") return new_name = " ".join(message.command[1:]) try: await client.set_my_name(new_name) await message.reply_text(f"Name changed to: {new_name}") except Exception as e: await message.reply_text(f"Failed to change name: {e}")

---- Join request handling ----

@app.on_chat_join_request() async def on_join_request(client: Client, q: ChatJoinRequest): # Auto-pend and notify admins with inline approve/reject chat = q.chat user = q.from_user text = f"Join request: {user.mention} ({user.id}) wants to join {chat.title or chat.id}." kb = InlineKeyboardMarkup( [[InlineKeyboardButton("Approve", callback_data=f"approve:{chat.id}:{user.id}"), InlineKeyboardButton("Reject", callback_data=f"reject:{chat.id}:{user.id}")]] ) # send to chat (admins will see) — also send to chat if bot can try: await client.send_message(chat.id, text, reply_markup=kb) except Exception: # fallback: try owner bot_owner = os.environ.get("BOT_OWNER") if bot_owner: await client.send_message(int(bot_owner), text, reply_markup=kb)

@app.on_callback_query(filters.regex(r"^(approve|reject):")) async def on_approve_reject(client, callback_query): data = callback_query.data action, chat_id_str, user_id_str = data.split(":") chat_id = int(chat_id_str) user_id = int(user_id_str) try: # ensure clicker is admin clicker = callback_query.from_user mem = await client.get_chat_member(chat_id, clicker.id) if mem.status not in ("administrator", "creator"): await callback_query.answer("Only admins can approve/reject.", show_alert=True) return except Exception: pass

if action == "approve":
    try:
        await client.approve_chat_join_request(chat_id, user_id)
        await callback_query.edit_message_text(f"Approved join of {user_id}.")
    except Exception as e:
        await callback_query.answer(f"Failed: {e}")
else:
    try:
        await client.decline_chat_join_request(chat_id, user_id)
        await callback_query.edit_message_text(f"Rejected join of {user_id}.")
    except Exception as e:
        await callback_query.answer(f"Failed: {e}")

---- Crypto price ----

@app.on_message(filters.command("price") & (filters.private | filters.group)) async def cmd_price(client, message: Message): if len(message.command) < 2: await message.reply_text("Usage: /price <symbol> (eg. /price btc)") return symbol = message.command[1].lower() # use coingecko simple price try: r = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": symbol, "vs_currencies": "usd"}, timeout=10) # The API expects coin ids (e.g. 'bitcoin'), but users will type 'btc' often. # Try mapping some common tickers quickly if direct lookup failed. if r.status_code != 200 or not r.json(): # quick ticker -> id map quick = {"btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin", "ada": "cardano"} coin = quick.get(symbol, symbol) r = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": coin, "vs_currencies": "usd"}, timeout=10) data = r.json() # choose first key if not data: await message.reply_text("Coin not found.") return key = list(data.keys())[0] price = data[key].get("usd") await message.reply_text(f"{key.title()} price: ${price}") except Exception as e: await message.reply_text(f"Failed to fetch price: {e}")

---- Simple scheduled task: cleanup expired mutes ----

async def cleanup_mutes(): while True: try: now = int(time.time()) changed = False for chat_id, users in list(muted.items()): for uid_str, until_ts in list(users.items()): if now >= int(until_ts): try: await app.restrict_chat_member(int(chat_id), int(uid_str), permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)) except Exception: pass users.pop(uid_str, None) changed = True if not users: muted.pop(chat_id, None) if changed: save_json(MUTED_FILE, muted) except Exception: pass await asyncio.sleep(30)

---- Run ----

if name == "main": print("Starting bot...") with app: # start background task app.loop.create_task(cleanup_mutes()) app.run()