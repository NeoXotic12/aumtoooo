import os
import asyncio
import re
import random
import json
from datetime import datetime
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- Configuration (Set in Render Dashboard) ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
STRING_SESSION = os.environ.get("STRING_SESSION")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# --- Bot Control & Persistence ---
is_active = True
OWNER_ID = 'me' 
GAME_BOT_ID = 572621020
GAME_BOT_USERNAME = "HeXamonbot"
TARGETS_FILE = "catch_list.json"
STATS_FILE = "stats.json"

# --- Data Management ---
def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

# Initial Load
custom_catch_list = load_json(TARGETS_FILE, [])
stats = load_json(STATS_FILE, {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "caught": 0, "encountered": 0, "shinies": 0, "last_catches": []
})

# Reset stats if a new day has started
if stats.get("date") != datetime.now().strftime("%Y-%m-%d"):
    stats = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "caught": 0, "encountered": 0, "shinies": 0, "last_catches": []
    }
    save_json(STATS_FILE, stats)

# --- Global States ---
cooldown = random.randint(1, 2)
low_lvl = False
hunt_timer = None 
active_ball = "Poke Balls" 

# --- Timer Functions ---
async def auto_hunt_timer():
    global hunt_timer
    await asyncio.sleep(12)
    if is_active:
        print("No pokemon appeared within 12s. Retrying /hunt...")
        await client.send_message(GAME_BOT_ID, '/hunt')
        reset_hunt_timer()

def reset_hunt_timer():
    global hunt_timer
    if hunt_timer:
        hunt_timer.cancel()
    if is_active:
        hunt_timer = asyncio.create_task(auto_hunt_timer())

def calculate_health_percentage(max_hp, current_hp):
    if max_hp <= 0: return 0
    return round((current_hp / max_hp) * 100)

# --- Commands ---

@client.on(events.NewMessage(pattern=r'/ball_(.*)', from_users=OWNER_ID))
async def set_ball(event):
    global active_ball
    choice = event.pattern_match.group(1).strip().lower()
    active_ball = "Poke Balls" if choice == "regular" else f"{choice.title()} Ball"
    await event.reply(f"🎯 **Ball Mode:** `{active_ball}`")

@client.on(events.NewMessage(pattern='/stats', from_users=OWNER_ID))
async def show_stats(event):
    header = (f"📊 **Daily Stats ({stats['date']})**\n"
              f"Encounters: {stats['encountered']} | Caught: {stats['caught']} | Shinies: {stats['shinies']}\n"
              f"------------------------------------\n")
    
    if not stats["last_catches"]:
        await event.reply(header + "No catches yet today.")
        return

    output = header
    for entry in stats["last_catches"]:
        if len(output) + len(entry) > 3900:
            await event.reply(output)
            output = ""
        output += entry + "\n"
    if output: await event.reply(output)

@client.on(events.NewMessage(pattern='/add (.*)', from_users=OWNER_ID))
async def add_to_list(event):
    global custom_catch_list
    new_names = [n.strip().title() for n in event.pattern_match.group(1).split(',')]
    custom_catch_list = list(set(custom_catch_list + new_names))
    save_json(TARGETS_FILE, custom_catch_list) 
    await event.reply(f"✅ **Added!** Targets: {len(custom_catch_list)}")

# --- Automation Logic ---

@client.on(events.NewMessage(from_users=GAME_BOT_ID))
async def game_handler(event):
    global hunt_timer, is_active, stats, low_lvl
    if not is_active: return
    
    raw = event.raw_text.lower()

    if "daily hunt limit reached" in raw:
        is_active = False
        if hunt_timer: hunt_timer.cancel()
        await event.reply("🛑 **Daily limit reached!**")
        return

    # 1. Shiny Detection & Automated Battle Entry
    elif "✨" in event.raw_text or "shiny" in raw:  
        stats["shinies"] += 1
        save_json(STATS_FILE, stats)
        await asyncio.sleep(1)
        try:
            await event.click(0, 0) # Click Battle
        except: pass
        await event.client.send_message(-4254868305, f"@Newbiw_ot ✨ **SHINY ENCOUNTERED!** ✨\nCatching with: `{active_ball}`") 
        return

    # 2. Hunt or Pass
    elif "a wild" in raw:
        stats["encountered"] += 1
        save_json(STATS_FILE, stats)
        reset_hunt_timer() 
        pok_name = event.raw_text.split("wild ")[1].split(" (")[0]
        
        delay = random.uniform(1.2, 2.5)
        if pok_name in custom_catch_list:
            await asyncio.sleep(delay)
            await event.click(0, 0) # Start Battle
        else:
            await asyncio.sleep(delay)
            await client.send_message(GAME_BOT_ID, '/hunt')

    elif "battle begins!" in raw:
        if hunt_timer: hunt_timer.cancel() 
        match = re.search(r"Lv\. \d+  •  HP (\d+)/(\d+)", event.raw_text)
        if match:
            if int(match.group(2)) <= 55:
                low_lvl = True
                await asyncio.sleep(1)
                await event.click(text="Poke Balls")
            else:
                low_lvl = False
                await asyncio.sleep(1.5)
                await event.click(0, 0)

@client.on(events.MessageEdited(from_users=GAME_BOT_ID))
async def battle_manager(event):
    global stats, is_active, low_lvl, active_ball
    if not is_active: return

    # 3. Catch Extraction (Nature, IV, ID)
    if "You caught" in event.raw_text:
        stats["caught"] += 1
        
        name_m = re.search(r"You caught ([\w\s]+)!", event.raw_text)
        id_m = re.search(r"ID: #?(\d+)", event.raw_text)
        nat_m = re.search(r"Nature: (\w+)", event.raw_text)
        iv_m = re.search(r"IV: (\d+\.?\d*%)", event.raw_text)

        p_name = name_m.group(1) if name_m else "Unknown"
        p_id = id_m.group(1) if id_m else "0"
        p_nat = (nat_m.group(1)[:3]) if nat_m else "?"
        p_iv = iv_m.group(1) if iv_m else "?"

        entry = f"`#{p_id}` **{p_name}** ({p_nat}|{p_iv})"
        stats["last_catches"].append(entry)
        if len(stats["last_catches"]) > 300: stats["last_catches"].pop(0)
        save_json(STATS_FILE, stats)

        low_lvl = False
        await asyncio.sleep(2)
        await client.send_message(GAME_BOT_ID, '/hunt')
        reset_hunt_timer()
        return

    if any(s in event.raw_text for s in ["fled", "💵"]):
        low_lvl = False
        await asyncio.sleep(2)
        await client.send_message(GAME_BOT_ID, '/hunt')
        reset_hunt_timer()
        return

    if "Wild" in event.raw_text:
        hp_match = re.search(r"HP (\d+)/(\d+)", event.raw_text)
        if hp_match:
            percent = calculate_health_percentage(int(hp_match.group(2)), int(hp_match.group(1)))
            if low_lvl or percent <= 50:
                await asyncio.sleep(1)
                await event.click(text="Poke Balls")
                await asyncio.sleep(1)
                try:
                    if active_ball != "Poke Balls":
                        await event.click(text=active_ball)
                    else: await event.click(0, 0)
                except: await event.click(0, 0) 
                await asyncio.sleep(1)
                await event.click(text="Repeat")
            else:
                await asyncio.sleep(1.2)
                await event.click(0, 0)

# --- Render Web Server ---
async def handle(request): return web.Response(text="Bot Active")

async def main():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000))).start()
    await client.connect()
    if not await client.is_user_authorized(): return 
    await client.get_input_entity(GAME_BOT_ID)
    await client.send_message(GAME_BOT_ID, '/hunt')
    reset_hunt_timer()
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())