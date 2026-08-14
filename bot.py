import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord import ui
import json
import sys
import re
import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import io
import tempfile
import time
import random
import aiohttp
import yt_dlp
import datetime
from pathlib import Path

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

channel_status = {}
auto_channels = {}
video_embed_mode = {}
global_batch_size = 4
filter_mode = {}
nofilter_mode_default = True
nofilter_mode = {}
REACTION_ROLES_FILE = DATA_DIR / "reaction_roles.json"
TIKTOK_MODE_FILE = DATA_DIR / "tiktok_mode.json"
tiktok_mode = {}
TIKTOK_DOWNLOAD_DIR = Path("tiktok_downloads")
TIKTOK_DOWNLOAD_DIR.mkdir(exist_ok=True)

import traceback

# =====================================
# CRASH-RESILIENCE: Webhook Error Logger
# =====================================

ERROR_WEBHOOK_URL = None

async def send_error_webhook(title, error_info, context=""):
    if not ERROR_WEBHOOK_URL:
        return
    try:
        embed = {
            "title": f"ðŸ”´ {title}",
            "description": f"```{error_info[:1800]}```",
            "color": 0xFF0000,
            "fields": [],
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        if context:
            embed["fields"].append({"name": "Context", "value": context[:1024], "inline": False})
        async with aiohttp.ClientSession() as session:
            await session.post(ERROR_WEBHOOK_URL, json={"embeds": [embed]})
    except:
        pass

def crash_resilient_task(task_func):
    async def wrapper(*args, **kwargs):
        try:
            return await task_func(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[TaskCrash] {task_func.__name__} Fehler: {e}")
            traceback.print_exc()
            critical_tasks = ["auto_save_data", "watchdog_task", "health_monitor", "daily_config_backup"]
            if task_func.__name__ in critical_tasks:
                asyncio.create_task(send_error_webhook(
                    f"Task Crash: {task_func.__name__}",
                    f"{type(e).__name__}: {e}\n\n{tb}"
                ))
            return None
    wrapper.__name__ = task_func.__name__
    return wrapper

# =====================================
# AUTOMOD SYSTEM
# =====================================

AUTOMOD_FILE = DATA_DIR / "automod.json"
automod_config = {}
invite_spam_tracker = {}

def load_automod_config():
    if AUTOMOD_FILE.exists():
        with open(AUTOMOD_FILE, "r") as f:
            return json.load(f)
    return {}

def save_automod_config(data):
    with open(AUTOMOD_FILE, "w") as f:
        json.dump(data, f, indent=2)

# =====================================
# AUTO-MEMES SYSTEM
# =====================================

MEMES_CONFIG_FILE = DATA_DIR / "memes_config.json"
MEMES_VOTES_FILE = DATA_DIR / "memes_votes.json"
MEMES_LIST_DIR = DATA_DIR / "memes_lists"
MEMES_LIST_DIR.mkdir(exist_ok=True)

REDDIT_MEME_SUBREDDITS = [
    "memes", "dankmemes", "me_irl", "MemeEconomy", "ComedyCemetery",
    "funny", "wholesomememes", "shitposting", "okbuddyretard",
    "HistoryMemes", "PrequelMemes", "StarWarsMemes", "animememes"
]

IMGUR_MEME_ALBUMS = [
    "r/memes", "r/dankmemes", "r/funny", "r/me_irl"
]

def load_memes_config():
    if MEMES_CONFIG_FILE.exists():
        with open(MEMES_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memes_config(data):
    with open(MEMES_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_memes_votes():
    if MEMES_VOTES_FILE.exists():
        with open(MEMES_VOTES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memes_votes(data):
    with open(MEMES_VOTES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_memes_list_file(guild_id):
    return MEMES_LIST_DIR / f"{guild_id}_memes.txt"

def load_memes_list(guild_id):
    path = get_memes_list_file(guild_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        return lines
    return []

def save_memes_list(guild_id, urls):
    path = get_memes_list_file(guild_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(urls))

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
_reddit_token = None

async def _get_reddit_token():
    global _reddit_token
    if _reddit_token:
        return _reddit_token
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return None
    try:
        auth = aiohttp.BasicAuth(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=auth,
                headers={"User-Agent": "linux:discord-gif-bot:v1.0 (by /u/discordgifbot)"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _reddit_token = data.get("access_token")
                    return _reddit_token
    except Exception as e:
        print(f"[Memes] Reddit OAuth Fehler: {e}")
    return None

async def fetch_reddit_memes(subreddit="memes", limit=25):
    user_agent = "linux:discord-gif-bot:v1.0 (by /u/discordgifbot)"
    token = await _get_reddit_token()
    base_url = "https://oauth.reddit.com" if token else "https://www.reddit.com"
    url = f"{base_url}/r/{subreddit}/hot.json?limit={limit}"
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    posts = data.get("data", {}).get("children", [])
                    image_urls = []
                    for post in posts:
                        post_data = post.get("data", {})
                        post_url = post_data.get("url", "")
                        is_video = post_data.get("is_video", False)
                        if is_video:
                            continue
                        if any(ext in post_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                            image_urls.append(post_url)
                        elif "imgur.com" in post_url and not post_url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            imgur_url = post_url + ".jpg"
                            image_urls.append(imgur_url)
                        elif "i.redd.it" in post_url:
                            image_urls.append(post_url)
                    return image_urls
                elif resp.status == 429 or resp.status == 403:
                    print(f"[Memes] Reddit blockiert ({resp.status}) - Rate-Limit")
    except Exception as e:
        print(f"[Memes] Reddit API Fehler: {e}")
    return []

async def fetch_imgur_memes(tag="memes", page=1):
    url = f"https://api.imgur.com/3/gallery/t/{tag}/hot/{page}"
    headers = {"Authorization": "Client-ID 546c25a59c58ad7"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", {}).get("items", [])
                    image_urls = []
                    for item in items:
                        if item.get("is_album"):
                            continue
                        link = item.get("link", "")
                        if any(ext in link.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                            image_urls.append(link)
                    return image_urls
    except Exception as e:
        print(f"[Memes] Imgur API Fehler: {e}")
    return []

async def fetch_interpol_videos(limit=50, exclude_ids=None):
    all_videos = []
    cursor = None
    max_pages = 30
    page = 0
    max_size_mb = 8
    try:
        async with aiohttp.ClientSession() as session:
            while page < max_pages:
                try:
                    url = f"https://interpol.cc/api/videos?pageSize=50"
                    if cursor:
                        url += f"&cursor={cursor}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status != 200:
                            print(f"[Interpol] API Status {resp.status} auf Seite {page}")
                            break
                        data = await resp.json()
                        items = data.get("items", [])
                        cursor = data.get("nextCursor")
                        for item in items:
                            if item.get("transcodeStatus") != "Completed":
                                continue
                            video_id = item.get("id")
                            if exclude_ids and video_id in exclude_ids:
                                continue
                            file_size = item.get("fileSizeBytes", 0)
                            if file_size > max_size_mb * 1024 * 1024:
                                continue
                            download_url = item.get("downloadUrl", "")
                            if download_url:
                                if download_url.startswith("/"):
                                    download_url = "https://interpol.cc" + download_url
                                all_videos.append({
                                    "url": download_url,
                                    "title": item.get("title", "Interpol Video"),
                                    "id": video_id,
                                    "size": file_size
                                })
                        page += 1
                        if not cursor:
                            break
                except asyncio.TimeoutError:
                    print(f"[Interpol] Timeout auf Seite {page}, breche ab")
                    break
                except Exception as e:
                    print(f"[Interpol] Fehler auf Seite {page}: {e}")
                    break
            print(f"[Interpol] {len(all_videos)} Videos geladen ({page} Seiten)")
    except Exception as e:
        print(f"[Memes] Interpol API Fehler: {e}")
    return all_videos

async def get_meme_for_guild(guild_id, exclude_ids=None):
    config = load_memes_config()
    guild_str = str(guild_id)
    source = config.get(guild_str, {}).get("source", "reddit")
    
    if source == "reddit":
        sub = config.get(guild_str, {}).get("subreddit", random.choice(REDDIT_MEME_SUBREDDITS))
        memes = await fetch_reddit_memes(sub)
        if memes:
            return random.choice(memes), None
    
    elif source == "imgur":
        tag = config.get(guild_str, {}).get("imgur_tag", "memes")
        memes = await fetch_imgur_memes(tag)
        if memes:
            return random.choice(memes), None
    
    elif source == "liste":
        liste = load_memes_list(guild_id)
        if liste:
            return random.choice(liste), None
    
    elif source == "gemischt":
        all_memes = []
        reddit_memes = await fetch_reddit_memes(random.choice(REDDIT_MEME_SUBREDDITS))
        all_memes.extend(reddit_memes)
        liste = load_memes_list(guild_id)
        all_memes.extend(liste)
        if all_memes:
            return random.choice(all_memes), None
    
    elif source == "interpol":
        videos = await fetch_interpol_videos(exclude_ids=exclude_ids or set())
        if videos:
            chosen = random.choice(videos)
            return chosen["url"], chosen["id"]
    
    return None, None

# =====================================
# FRAGE DES TAGES SYSTEM
# =====================================

FRAGEN_CONFIG_FILE = DATA_DIR / "fragen_config.json"
FRAGEN_CUSTOM_FILE = DATA_DIR / "fragen_custom.json"
FRAGEN_MESSAGES_FILE = DATA_DIR / "fragen_messages.json"
FRAGEN_CACHE_FILE = DATA_DIR / "fragen_cache.json"

DEFAULT_FRAGEN = [
    {"frage": "Würdest du lieber die Fähigkeit zum Teleportieren oder zur Gedankenkontrolle haben?", "emoji": "🧠", "optionen": ["Teleportieren", "Gedankenkontrolle"], "guild_id": "global"},
    {"frage": "Würdest du lieber in einer Welt ohne Internet oder ohne Klimaanlage leben?", "emoji": "🌍", "optionen": ["Ohne Internet", "Ohne Klimaanlage"], "guild_id": "global"},
    {"frage": "Meer oder Berge für den nächsten Urlaub?", "emoji": "🏖️", "optionen": ["Meer", "Berge"], "guild_id": "global"},
    {"frage": "Würdest du lieber unendlich Geld oder unendlich Zeit haben?", "emoji": "💰", "optionen": ["Unendlich Geld", "Unendlich Zeit"], "guild_id": "global"},
    {"frage": "Kaffee oder Tee?", "emoji": "☕", "optionen": ["Kaffee", "Tee"], "guild_id": "global"},
    {"frage": "Würdest du lieber in der Vergangenheit oder in der Zukunft leben?", "emoji": "⏰", "optionen": ["Vergangenheit", "Zukunft"], "guild_id": "global"},
    {"frage": "Hund oder Katze?", "emoji": "🐾", "optionen": ["Hund", "Katze"], "guild_id": "global"},
    {"frage": "Würdest du lieber fliegen oder unsichtbar sein können?", "emoji": "🦅", "optionen": ["Fliegen", "Unsichtbar sein"], "guild_id": "global"},
    {"frage": "Frühaufsteher oder Nachteule?", "emoji": "🌅", "optionen": ["Frühaufsteher", "Nachteule"], "guild_id": "global"},
    {"frage": "Würdest du lieber 1 Millionen Euro gewinnen oder deinen besten Freund für immer behalten?", "emoji": "❤️", "optionen": ["1 Mio Euro", "Besten Freund behalten"], "guild_id": "global"},
    {"frage": "Pizza oder Burger?", "emoji": "🍕", "optionen": ["Pizza", "Burger"], "guild_id": "global"},
    {"frage": "Würdest du lieber in einer großen Stadt oder auf dem Land leben?", "emoji": "🏙️", "optionen": ["Große Stadt", "Land"], "guild_id": "global"},
    {"frage": "Serien schauen oder lesen?", "emoji": "📚", "optionen": ["Serien schauen", "Lesen"], "guild_id": "global"},
    {"frage": "Würdest du lieber super stark oder super intelligent sein?", "emoji": "💪", "optionen": ["Super stark", "Super intelligent"], "guild_id": "global"},
    {"frage": "Zuhause bleiben oder ausgehen?", "emoji": "🏠", "optionen": ["Zuhause bleiben", "Ausgehen"], "guild_id": "global"},
    {"frage": "Würdest du lieber nie wieder lachen oder nie wieder weinen können?", "emoji": "😊", "optionen": ["Nie wieder lachen", "Nie wieder weinen"], "guild_id": "global"},
    {"frage": "Musik hören oder Podcasts?", "emoji": "🎵", "optionen": ["Musik hören", "Podcasts"], "guild_id": "global"},
    {"frage": "Würdest du lieber 1000 oberflächliche Freunde oder 1 richtigen besten Freund haben?", "emoji": "👥", "optionen": ["1000 Freunde", "1 richtiger bester Freund"], "guild_id": "global"},
    {"frage": "Fitnessstudio oder draußen trainieren?", "emoji": "🏋️", "optionen": ["Fitnessstudio", "Draußen trainieren"], "guild_id": "global"},
    {"frage": "Würdest du lieber für immer 20 oder für immer 40 Jahre alt sein?", "emoji": "🎂", "optionen": ["Für immer 20", "Für immer 40"], "guild_id": "global"},
]

def load_fragen_config():
    if FRAGEN_CONFIG_FILE.exists():
        with open(FRAGEN_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_fragen_config(data):
    with open(FRAGEN_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_custom_fragen():
    if FRAGEN_CUSTOM_FILE.exists():
        with open(FRAGEN_CUSTOM_FILE, "r") as f:
            return json.load(f)
    return []

def save_custom_fragen(data):
    with open(FRAGEN_CUSTOM_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_frage_messages():
    if FRAGEN_MESSAGES_FILE.exists():
        with open(FRAGEN_MESSAGES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_frage_messages(data):
    with open(FRAGEN_MESSAGES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_all_fragen(guild_id):
    custom = load_custom_fragen()
    all_fragen = DEFAULT_FRAGEN.copy()
    guild_str = str(guild_id)
    for frag in custom:
        if frag.get("guild_id") == guild_str or frag.get("guild_id") == "global":
            all_fragen.append(frag)
    return all_fragen

def build_results_text(msg_id, display_mode="embed"):
    votes = load_memes_votes()
    vote_data = votes.get(msg_id, {})
    
    emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
    
    if not vote_data:
        return "**Ergebnisse:** Noch keine Stimmen"
    
    vote_counts = {}
    vote_users = {}
    for uid, opt in vote_data.items():
        vote_counts[opt] = vote_counts.get(opt, 0) + 1
        if opt not in vote_users:
            vote_users[opt] = []
        vote_users[opt].append(uid)
    
    total = sum(vote_counts.values())
    lines = [f"**{total} Stimme(n):**"]
    
    for idx in sorted(vote_counts.keys()):
        if idx < len(emojis):
            count = vote_counts[idx]
            if display_mode == "anonym":
                lines.append(f"{emojis[idx]} **{count}**")
            else:
                names = []
                for uid in vote_users[idx]:
                    names.append(f"<@{uid}>")
                names_str = ", ".join(names)
                lines.append(f"{emojis[idx]} **{count}** - {names_str}")
    
    return "\n".join(lines)

# =====================================
# FRAGEN WEB-SCRAPING & CACHE
# =====================================

FRAGEN_CACHE_TTL = 86400

def load_fragen_cache():
    if FRAGEN_CACHE_FILE.exists():
        with open(FRAGEN_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_fragen_cache(data):
    with open(FRAGEN_CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def fetch_url_text(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.text()
    except Exception as e:
        print(f"[FrageScrape] Fehler bei {url}: {e}")
    return None

def parse_numbered_questions(html, pattern=r'(\d+)\.\s*(.+)'):
    fragen = []
    for match in re.finditer(pattern, html, re.MULTILINE):
        text = match.group(2).strip()
        text = re.sub(r'<[^>]+>', '', text)
        text = text.strip('*_`')
        if len(text) > 10 and len(text) < 300:
            fragen.append(text)
    return fragen

def parse_entwederoder(html):
    fragen = []
    pattern = r'(\d+)\.\s*(.+?\s+oder\s+.+?)\?'
    for match in re.finditer(pattern, html, re.MULTILINE | re.IGNORECASE):
        full = match.group(2).strip()
        full = re.sub(r'<[^>]+>', '', full)
        full = full.strip('*_`')
        parts = re.split(r'\s+oder\s+', full, flags=re.IGNORECASE)
        if len(parts) == 2 and len(full) > 10 and len(full) < 200:
            fragen.append({
                "frage": full.rstrip('?') + '?',
                "optionen": [p.strip().rstrip('?') for p in parts]
            })
    return fragen

def parse_wuerdestu(html):
    fragen = []
    pattern = r'(\d+)\.\s*Würdest du lieber\s+(.+?)\s+oder\s+(.+?)\?'
    for match in re.finditer(pattern, html, re.MULTILINE | re.IGNORECASE):
        opt1 = match.group(2).strip()
        opt2 = match.group(3).strip()
        opt1 = re.sub(r'<[^>]+>', '', opt1).strip('*_`')
        opt2 = re.sub(r'<[^>]+>', '', opt2).strip('*_`')
        if len(opt1) > 3 and len(opt2) > 3 and len(opt1) < 150 and len(opt2) < 150:
            fragen.append({
                "frage": f"Würdest du lieber {opt1} oder {opt2}?",
                "optionen": [opt1, opt2]
            })
    return fragen

async def scrape_fragenquelle(quelle):
    cache = load_fragen_cache()
    now = time.time()

    if quelle in cache and (now - cache[quelle].get("timestamp", 0)) < FRAGEN_CACHE_TTL:
        cached = cache[quelle]["fragen"]
        print(f"[FrageScrape] Cache-Treffer fuer {quelle} ({len(cached)} Fragen)")
        return cached

    urls = {
        "eisbrecher": ["https://conversationstartersworld.com/de/eisbrecher-fragen/"],
        "entwederoder": ["https://conversationstartersworld.com/de/entweder-oder-fragen/"],
        "wuerdestu": ["https://conversationstartersworld.com/de/wuerdest-du-lieber-fragen/"]
    }

    fragen = []
    for url in urls.get(quelle, []):
        html = await fetch_url_text(url)
        if not html:
            continue

        if quelle == "eisbrecher":
            texts = parse_numbered_questions(html)
            for t in texts:
                fragen.append({"frage": t, "optionen": [], "emoji": "🧊"})
        elif quelle == "entwederoder":
            parsed = parse_entwederoder(html)
            for p in parsed:
                p["emoji"] = "⚖️"
                fragen.append(p)
        elif quelle == "wuerdestu":
            parsed = parse_wuerdestu(html)
            for p in parsed:
                p["emoji"] = "💭"
                fragen.append(p)

    if fragen:
        cache[quelle] = {"fragen": fragen, "timestamp": now}
        save_fragen_cache(cache)
        print(f"[FrageScrape] {len(fragen)} Fragen gescraped fuer {quelle}")
    else:
        print(f"[FrageScrape] Keine Fragen fuer {quelle} - Cache bleibt")

    return cache.get(quelle, {}).get("fragen", [])

async def get_fragen_from_source(source, guild_id):
    guild_str = str(guild_id)
    if source == "eigene":
        return get_all_fragen(guild_id)

    if source == "gemischt":
        all_fragen = list(get_all_fragen(guild_id))
        for q in ["eisbrecher", "entwederoder", "wuerdestu"]:
            scraped = await scrape_fragenquelle(q)
            for s in scraped:
                item = dict(s)
                item["guild_id"] = guild_str
                all_fragen.append(item)
        return all_fragen

    scraped = await scrape_fragenquelle(source)
    for s in scraped:
        s["guild_id"] = guild_str
    return scraped

EXCLUDED_ROLE_NAMES = ["owner", "head admin", "admin", "moderator", "bot", "muted", "timeout"]

REQUIRED_ROLE_NAME = "976"

WEBHOOK_NAME = "Reaction Roles"
WEBHOOK_URL = "https://discord.com/api/webhooks/1532848727512056039/GRP8vAkYAWpj8UIC_TJclU8a185KFuW5_nreFOdkeY_je6kWhLm-X4C37GPh6DhWJsBK"

MEDIA_EXTENSIONS = {
    'gif': ['gif'],
    'mp4': ['mp4', 'mov', 'avi', 'mkv', 'm4v', 'flv', 'wmv'],
    'webm': ['webm'],
    'images': ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'tif', 'avif', 'ico'],
    'apng': ['apng'],
    'svg': ['svg']
}
ALL_MEDIA_EXTS = [ext for exts in MEDIA_EXTENSIONS.values() for ext in exts]

VIDEO_EXTS = ('.mp4', '.mov', '.webm', '.avi', '.mkv')

def load_reaction_roles():
    if REACTION_ROLES_FILE.exists():
        with open(REACTION_ROLES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_reaction_roles(data):
    with open(REACTION_ROLES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_video_url(url):
    path = url.split("?")[0].lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTS)

def is_admin_or_owner():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild.owner_id == interaction.user.id:
            return True
        required_role = discord.utils.get(interaction.user.roles, name=REQUIRED_ROLE_NAME)
        if required_role:
            return True
        await interaction.response.send_message("Keine Berechtigung! Nur User mit der 976 Rolle kÃ¶nnen den Bot nutzen.", ephemeral=True)
        return False
    return app_commands.check(predicate)

def get_data_file(channel_id):
    return DATA_DIR / f"{channel_id}.json"

def load_links(channel_id):
    path = get_data_file(channel_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_links(channel_id, links):
    path = get_data_file(channel_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2)

def clean_url_advanced(url):
    clean = url.split("?")[0]
    clean = clean.replace("media.discordapp.net", "cdn.discordapp.com")
    if "images-ext-1.discordapp.net/external/" in clean:
        parts = clean.split("/external/")
        if len(parts) > 1:
            rest = parts[1]
            if "/" in rest:
                after_hash = rest.split("/", 1)[1]
                clean = after_hash
    if "giphy.com" in clean:
        clean = clean.split("?")[0]
    clean = re.sub(r'[)\]}>]+$', '', clean)
    return clean

def get_url_extension(url):
    path = url.split("?")[0]
    match = re.search(r'\.([a-z0-9]+)$', path, re.IGNORECASE)
    return match.group(1).lower() if match else ""

def is_media_url(url):
    ext = get_url_extension(url)
    return ext in ALL_MEDIA_EXTS

def extract_links(text):
    url_regex = r'https?://[^\s"\'<>]+\.(gif|webp|png|jpg|jpeg|mp4|webm|mov)(?:\?[^\s"\'<>]*)?'
    full_urls = re.findall(r'https?://[^\s"\'<>]+\.(?:gif|webp|png|jpg|jpeg|mp4|webm|mov)(?:\?[^\s"\'<>]*)?', text, re.IGNORECASE)
    unique = {}
    for url in full_urls:
        clean = clean_url_advanced(url)
        unique[clean] = url
    return list(unique.values())

def extract_links_advanced(text):
    url_pattern = r'https?://[^\s<>"\']+'
    raw_urls = re.findall(url_pattern, text)
    
    seen = set()
    filtered = []
    
    for url in raw_urls:
        clean = clean_url_advanced(url)
        ext = get_url_extension(clean)
        
        if not ext:
            continue
        if ext not in ALL_MEDIA_EXTS:
            continue
        if clean in seen:
            continue
        
        seen.add(clean)
        filtered.append(clean)
    
    return filtered

def extract_links_nofilter(text):
    lines = text.split('\n')
    links = []
    for line in lines:
        line = line.strip()
        if line.startswith('http://') or line.startswith('https://'):
            links.append(line)
    return links

def clean_url(url):
    clean = url.split("?")[0]
    clean = clean.replace("media.discordapp.net", "cdn.discordapp.com")
    if "images-ext-1.discordapp.net/external/" in clean:
        parts = clean.split("/external/")
        if len(parts) > 1:
            rest = parts[1]
            if "/" in rest:
                after_hash = rest.split("/", 1)[1]
                clean = after_hash
    if "giphy.com" in clean:
        clean = clean.split("?")[0]
    return clean

def load_tiktok_mode():
    if TIKTOK_MODE_FILE.exists():
        with open(TIKTOK_MODE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_tiktok_mode(data):
    with open(TIKTOK_MODE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_tiktok_url(url):
    tiktok_patterns = [
        r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
        r'https?://(?:vm|vt)\.tiktok\.com/[\w]+',
        r'https?://(?:www\.)?tiktok\.com/t/[\w]+',
    ]
    for pattern in tiktok_patterns:
        if re.match(pattern, url, re.IGNORECASE):
            return True
    return False

async def _download_via_clipx(url):
    """Clyppy Mode: ClipX API (kein Key noetig)"""
    api_url = f"https://clipx.zamdev.workers.dev/?url={url}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise Exception(f"ClipX returned {resp.status}")
            data = await resp.json()
            if not data.get("success"):
                raise Exception(f"ClipX error: {data.get('error', 'unknown')}")
            download_url = data.get("data", {}).get("url")
            title = data.get("data", {}).get("title", "TikTok Video")
            if not download_url:
                raise Exception("ClipX: no download URL")
            return download_url, title

async def _download_via_tdownv4(url):
    """dlbot Mode: tdownv4 API (kein Key noetig)"""
    api_url = f"https://tdownv4.sl-bjs.workers.dev/?down={url}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise Exception(f"tdownv4 returned {resp.status}")
            text = await resp.text()
            import re as _re
            match = _re.search(r'href="(https?://[^"]*\.mp4[^"]*)"', text)
            if not match:
                match = _re.search(r'(https?://[^"\']*\.mp4[^"\']*)', text)
            if not match:
                raise Exception("tdownv4: no MP4 link found in response")
            download_url = match.group(1)
            return download_url, "TikTok Video"

async def _download_via_curlx(url):
    """tikcord Mode: curl-x API (kein Key noetig)"""
    api_url = "https://www.curl-x.com/api/extract"
    payload = {"url": url}
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise Exception(f"curl-x returned {resp.status}")
            data = await resp.json()
            if data.get("error"):
                raise Exception(f"curl-x error: {data['error']}")
            items = data.get("media", data.get("data", []))
            if isinstance(items, list):
                for item in items:
                    if item.get("type") == "video" or item.get("url", "").endswith(".mp4"):
                        return item["url"], data.get("title", "TikTok Video")
            download_url = data.get("download_url") or data.get("url")
            title = data.get("title", "TikTok Video")
            if not download_url:
                raise Exception("curl-x: no download URL")
            return download_url, title

async def _download_via_quickvids(url):
    """quickvids Mode: dtiktok API (kein Key noetig)"""
    import re as _re
    video_id_match = _re.search(r'/video/(\d+)', url)
    if not video_id_match:
        vm_match = _re.search(r'vm\.tiktok\.com/(\w+)', url)
        if not vm_match:
            raise Exception("quickvids: could not extract video ID")
        short_code = vm_match.group(1)
        resolve_url = f"https://vt.tiktok.com/{short_code}/"
        async with aiohttp.ClientSession() as session:
            async with session.get(resolve_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                final_url = str(resp.url)
                video_id_match = _re.search(r'/video/(\d+)', final_url)
                if not video_id_match:
                    raise Exception("quickvids: could not resolve short URL")
    video_id = video_id_match.group(1)
    api_url = f"https://api.tikliveapi.com/download-video/?url=https://www.tiktok.com/video/{video_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise Exception(f"quickvids returned {resp.status}")
            data = await resp.json()
            download_url = data.get("video_hd") or data.get("video")
            if not download_url:
                raise Exception("quickvids: no download URL")
            return download_url, "TikTok Video"

async def _download_file_from_url(download_url, filename_prefix="tiktok"):
    """Laedt eine Datei von einer direkten URL herunter"""
    TIKTOK_DOWNLOAD_DIR.mkdir(exist_ok=True)
    unique_id = f"{filename_prefix}_{int(asyncio.get_event_loop().time() * 1000)}"
    final_path = str(TIKTOK_DOWNLOAD_DIR / f'{unique_id}.mp4')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Referer': 'https://www.tiktok.com/',
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(download_url, headers=headers, timeout=aiohttp.ClientTimeout(total=60), allow_redirects=True) as resp:
            if resp.status != 200:
                raise Exception(f"Download failed: HTTP {resp.status}")
            with open(final_path, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
    file_size = os.path.getsize(final_path)
    if file_size < 1000:
        os.remove(final_path)
        raise Exception(f"File too small ({file_size} bytes), likely corrupt")
    print(f"[TikTok] Downloaded file: {final_path} ({file_size} bytes)")
    return final_path

async def _convert_to_h264(input_path):
    """Konvertiert Video zu h264 fuer Discord PC-Kompatibilitaet"""
    import shutil
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        print(f"[TikTok] FFmpeg nicht gefunden, Ã¼berspringe Conversion")
        return input_path
    
    probe_cmd = [
        ffmpeg_path, '-i', input_path,
        '-f', 'null', '-t', '0', '-'
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        probe_text = stderr.decode(errors='ignore')
        if 'Video: h264' in probe_text or 'Video: avc1' in probe_text:
            print(f"[TikTok] Already h264, skipping conversion")
            return input_path
        codec_info = ""
        for line in probe_text.split('\n'):
            if 'Video:' in line:
                codec_info = line.strip()
                break
        print(f"[TikTok] Detected codec: {codec_info}")
    except:
        pass
    
    output_path = input_path.replace('.mp4', '_h264.mp4')
    convert_cmd = [
        ffmpeg_path, '-y', '-i', input_path,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-movflags', '+faststart',
        '-pix_fmt', 'yuv420p',
        '-vf', "scale='trunc(iw/2)*2:trunc(ih/2)*2'",
        '-avoid_negative_ts', 'make_zero',
        '-max_muxing_queue_size', '1024',
        output_path
    ]
    print(f"[TikTok] Converting to h264: {input_path} -> {output_path}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *convert_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        print(f"[TikTok] FFmpeg conversion timed out after 120s")
        try:
            proc.kill()
        except:
            pass
        return input_path
    except Exception as e:
        print(f"[TikTok] FFmpeg process error: {e}")
        return input_path
    
    if proc.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        final_size = os.path.getsize(output_path)
        print(f"[TikTok] h264 Conversion OK: {final_size} bytes")
        if input_path != output_path and os.path.exists(input_path):
            os.remove(input_path)
        return output_path
    else:
        stderr_text = stderr.decode(errors='ignore')[-800:] if stderr else "no stderr"
        print(f"[TikTok] h264 Conversion FAILED (code {proc.returncode})")
        print(f"[TikTok] FFmpeg stderr: {stderr_text}")
        return input_path

async def _try_download_with_mode(url, mode):
    """Versucht einen Download mit dem gegebenen Mode"""
    if mode == "clyppy":
        download_url, title = await _download_via_clipx(url)
    elif mode == "dlbot":
        download_url, title = await _download_via_tdownv4(url)
    elif mode == "tikcord":
        download_url, title = await _download_via_curlx(url)
    elif mode == "quickvids":
        download_url, title = await _download_via_quickvids(url)
    else:
        raise Exception(f"Unknown mode: {mode}")
    filename = await _download_file_from_url(download_url)
    filename = await _convert_to_h264(filename)
    return filename, title

async def _try_ytdlp_fallback(url):
    """Letzter Fallback: yt-dlp"""
    base_opts = {
        'outtmpl': str(TIKTOK_DOWNLOAD_DIR / '%(id)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'extract_flat': False,
        'concurrent_fragment_downloads': 4,
        'fragment_retries': 10,
        'retries': 10,
        'socket_timeout': 60,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.tiktok.com/',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'format': 'best[vcodec*=h264]/bestvideo[vcodec*=h264]+bestaudio/best',
        'merge_output_format': 'mp4',
    }
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base = os.path.splitext(filename)[0]
            for ext in ['.mp4', '.webm', '.mkv', '.mov']:
                if os.path.exists(base + ext):
                    filename = base + ext
                    break
        if not os.path.exists(filename):
            raise Exception("File not found after yt-dlp download")
        file_size = os.path.getsize(filename)
        if file_size < 1000:
            os.remove(filename)
            raise Exception(f"yt-dlp file too small ({file_size} bytes)")
        filename = await _convert_to_h264(filename)
        return filename, info.get('title', 'TikTok Video')

async def download_tiktok_video(url, mode="clyppy"):
    """TikTok Download mit API-Fallback-Kette:
    1. Gewaehlter Mode (clyppy/dlbot/tikcord/quickvids)
    2. Naechster Mode als Fallback
    3. yt-dlp als letzter Fallback
    """
    mode_order = ["clyppy", "dlbot", "tikcord", "quickvids"]
    if mode in mode_order:
        mode_order.remove(mode)
        mode_order.insert(0, mode)

    print(f"[TikTok] Starting download: {url} (preferred mode: {mode})")

    for current_mode in mode_order:
        try:
            print(f"[TikTok] Trying mode: {current_mode}")
            filename, title = await _try_download_with_mode(url, current_mode)
            print(f"[TikTok] SUCCESS with mode: {current_mode}")
            return filename, title
        except Exception as e:
            print(f"[TikTok] Mode {current_mode} failed: {e}")
            continue

    print(f"[TikTok] All API modes failed, trying yt-dlp fallback...")
    try:
        filename, title = await _try_ytdlp_fallback(url)
        print(f"[TikTok] SUCCESS with yt-dlp fallback")
        return filename, title
    except Exception as e:
        print(f"[TikTok] yt-dlp also failed: {e}")

    print(f"[TikTok] ALL methods failed for: {url}")
    return None, None

@bot.tree.command(name="add", description="FÃ¼ge GIF/Media-Links hinzu")
@is_admin_or_owner()
@app_commands.describe(links="Links oder Discord-Chat-Export einfÃ¼gen")
async def add_command(interaction: discord.Interaction, links: str):
    await interaction.response.defer()
    use_filter = filter_mode.get(interaction.guild_id, False)
    if use_filter:
        extracted = extract_links_advanced(links)
    else:
        extracted = extract_links(links)
    if not extracted:
        await interaction.followup.send("Keine Media-Links gefunden.", ephemeral=True)
        return
    existing = load_links(interaction.channel_id)
    existing_set = set(clean_url(u) for u in existing)
    new_links = [u for u in extracted if clean_url(u) not in existing_set]
    if not new_links:
        await interaction.followup.send(f"Alle {len(extracted)} Links sind bereits in der Liste.", ephemeral=True)
        return
    combined = existing + new_links
    save_links(interaction.channel_id, combined)
    await interaction.followup.send(
        f"**{len(new_links)} neue Links hinzugefÃ¼gt!**\n"
        f"Gesamt: {len(combined)} Links"
    )

@bot.tree.command(name="load", description="Lade eine .txt Datei mit Links hoch")
@is_admin_or_owner()
@app_commands.describe(datei="Textdatei mit Links (einer pro Zeile)")
async def load_command(interaction: discord.Interaction, datei: discord.Attachment):
    await interaction.response.defer()
    if not datei.filename.endswith('.txt'):
        await interaction.followup.send("Nur .txt Dateien erlaubt!", ephemeral=True)
        return
    content = await datei.read()
    text = content.decode('utf-8', errors='ignore')
    use_filter = filter_mode.get(interaction.guild_id, False)
    if use_filter:
        extracted = extract_links_advanced(text)
    else:
        extracted = extract_links(text)
    if not extracted:
        await interaction.followup.send("Keine Media-Links in der Datei gefunden.", ephemeral=True)
        return
    existing = load_links(interaction.channel_id)
    existing_set = set(clean_url(u) for u in existing)
    new_links = [u for u in extracted if clean_url(u) not in existing_set]
    if not new_links:
        await interaction.followup.send(f"Alle {len(extracted)} Links sind bereits in der Liste.", ephemeral=True)
        return
    combined = existing + new_links
    save_links(interaction.channel_id, combined)
    await interaction.followup.send(
        f"**{len(new_links)} neue Links aus Datei!**\n"
        f"Gesamt: {len(combined)} Links"
    )

@bot.tree.command(name="start", description="Startet das Senden von GIFs pro Nachricht")
@is_admin_or_owner()
async def start_command(interaction: discord.Interaction):
    links = load_links(interaction.channel_id)
    if not links:
        await interaction.response.send_message("Keine Links vorhanden. Benutze zuerst /add", ephemeral=True)
        return
    channel_status[interaction.channel_id] = {"index": 0, "running": True}
    await interaction.response.send_message(f"Gestartet! {len(links)} Links in der Queue.")
    await send_next_batch(interaction.channel_id, interaction.channel)

@bot.tree.command(name="cont", description="Setzt das Senden genau dort fort, wo es aufgehoert hat")
@is_admin_or_owner()
async def cont_command(interaction: discord.Interaction):
    links = load_links(interaction.channel_id)
    if not links:
        await interaction.response.send_message("Keine Links vorhanden.", ephemeral=True)
        return
    if interaction.channel_id not in channel_status:
        channel_status[interaction.channel_id] = {"index": 0, "running": False}
    idx = channel_status[interaction.channel_id]["index"]
    if idx >= len(links):
        await interaction.response.send_message("Bereits fertig! Benutze /start zum Neustart.", ephemeral=True)
        return
    remaining = len(links) - idx
    channel_status[interaction.channel_id]["running"] = True
    await interaction.response.send_message(f"Setze fort ab Position {idx}. Noch {remaining} Links uebrig.")
    await send_next_batch(interaction.channel_id, interaction.channel)

@bot.tree.command(name="stop", description="Stoppt das GIF-Senden")
@is_admin_or_owner()
async def stop_command(interaction: discord.Interaction):
    if interaction.channel_id in channel_status:
        channel_status[interaction.channel_id]["running"] = False
        await interaction.response.send_message("Gestoppt.")
    else:
        await interaction.response.send_message("LÃ¤uft gerade nicht.", ephemeral=True)

@bot.tree.command(name="next", description="Sendet die nÃ¤chsten 4 GIFs")
@is_admin_or_owner()
async def next_command(interaction: discord.Interaction):
    links = load_links(interaction.channel_id)
    if not links:
        await interaction.response.send_message("Keine Links vorhanden.", ephemeral=True)
        return
    if interaction.channel_id not in channel_status:
        channel_status[interaction.channel_id] = {"index": 0, "running": False}
    await send_next_batch(interaction.channel_id, interaction.channel)

@bot.tree.command(name="status", description="Zeigt den aktuellen Stand an")
@is_admin_or_owner()
async def status_command(interaction: discord.Interaction):
    links = load_links(interaction.channel_id)
    if not links:
        await interaction.response.send_message("Keine Links vorhanden.", ephemeral=True)
        return
    idx = 0
    running = False
    if interaction.channel_id in channel_status:
        idx = channel_status[interaction.channel_id]["index"]
        running = channel_status[interaction.channel_id]["running"]
    remaining = len(links) - idx
    status_text = "LÃ¤uft" if running else "Gestoppt"
    embed_mode = "AN" if video_embed_mode.get(interaction.channel_id, False) else "AUS"
    await interaction.response.send_message(
        f"**Status:** {status_text}\n"
        f"**Video-Embed:** {embed_mode}\n"
        f"**Size:** {global_batch_size}\n"
        f"**Gesamt:** {len(links)} Links\n"
        f"**Gesendet:** {idx}\n"
        f"**Uebrig:** {remaining}"
    )

@bot.tree.command(name="clear", description="LÃ¶scht die komplette Liste")
@is_admin_or_owner()
async def clear_command(interaction: discord.Interaction):
    path = get_data_file(interaction.channel_id)
    if path.exists():
        path.unlink()
    if interaction.channel_id in channel_status:
        del channel_status[interaction.channel_id]
    await interaction.response.send_message("Liste gelÃ¶scht.")

@bot.tree.command(name="embedvideos", description="Toggle: MP4/MOV als Inline-Video-Embed senden (statt Text-Link)")
@is_admin_or_owner()
async def embedvideos_command(interaction: discord.Interaction):
    current = video_embed_mode.get(interaction.channel_id, False)
    video_embed_mode[interaction.channel_id] = not current
    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    await interaction.response.send_message(
        f"{icon} **Video-Embed Mode:** {state}\n"
        f"{'MP4/MOV werden jetzt als Inline-Video gesendet.' if not current else 'MP4/MOV werden wieder als Text-Links gesendet.'}"
    )

@bot.tree.command(name="size", description="Setzt wie viele Links pro Nachricht (1-5, gilt fuer alle Commands)")
@is_admin_or_owner()
@app_commands.describe(menge="Anzahl pro Nachricht (Standard: 4)")
async def size_command(interaction: discord.Interaction, menge: int):
    global global_batch_size
    if menge < 1 or menge > 5:
        await interaction.response.send_message("Ungueltig! Erlaubt: 1-5", ephemeral=True)
        return
    global_batch_size = menge
    await interaction.response.send_message(f"**Size gesetzt auf {menge}** pro Nachricht. Gilt fuer /start, /next, /import.")

@bot.tree.command(name="list", description="Zeigt die ersten 5 und letzten 5 Links")
@is_admin_or_owner()
async def list_command(interaction: discord.Interaction):
    links = load_links(interaction.channel_id)
    if not interaction.channel_id in channel_status:
        channel_status[interaction.channel_id] = {"index": 0, "running": False}
    if not links:
        await interaction.response.send_message("Keine Links vorhanden.", ephemeral=True)
        return
    first_5 = "\n".join(links[:5])
    last_5 = "\n".join(links[-5:])
    await interaction.response.send_message(
        f"**Erste 5:**\n{first_5}\n\n"
        f"**Letzte 5:**\n{last_5}\n\n"
        f"**Gesamt:** {len(links)} Links"
    )

@bot.tree.command(name="pos", description="Setzt die Position manuell (z.B. /pos 100)")
@is_admin_or_owner()
@app_commands.describe(position="Die gewÃ¼nschte Startposition")
async def pos_command(interaction: discord.Interaction, position: int):
    links = load_links(interaction.channel_id)
    if position < 0 or position >= len(links):
        await interaction.response.send_message(f"UngÃ¼ltige Position. GÃ¼ltig: 0-{len(links)-1}", ephemeral=True)
        return
    if interaction.channel_id not in channel_status:
        channel_status[interaction.channel_id] = {"index": 0, "running": False}
    channel_status[interaction.channel_id]["index"] = position
    await interaction.response.send_message(f"Position auf {position} gesetzt.")

@bot.tree.command(name="import", description="LÃ¤dt bis zu 10 .txt Dateien hoch, erstellt pro Datei einen Channel")
@is_admin_or_owner()
@app_commands.describe(
    datei1="Datei 1", datei2="Datei 2", datei3="Datei 3", datei4="Datei 4", datei5="Datei 5",
    datei6="Datei 6", datei7="Datei 7", datei8="Datei 8", datei9="Datei 9", datei10="Datei 10"
)
async def import_command(
    interaction: discord.Interaction,
    datei1: discord.Attachment,
    datei2: discord.Attachment = None,
    datei3: discord.Attachment = None,
    datei4: discord.Attachment = None,
    datei5: discord.Attachment = None,
    datei6: discord.Attachment = None,
    datei7: discord.Attachment = None,
    datei8: discord.Attachment = None,
    datei9: discord.Attachment = None,
    datei10: discord.Attachment = None
):
    await interaction.response.defer()
    files = [d for d in [datei1, datei2, datei3, datei4, datei5, datei6, datei7, datei8, datei9, datei10] if d]
    results = []
    for file in files:
        if not file.filename.endswith('.txt'):
            results.append(f"**{file.filename}** - Ãœbersprungen (keine .txt)")
            continue
        content = await file.read()
        text = content.decode('utf-8', errors='ignore')
        extracted = extract_links(text)
        if not extracted:
            results.append(f"**{file.filename}** - Keine Links gefunden")
            continue
        channel_name = file.filename.replace('.txt', '').replace(' ', '-').lower()[:100]
        try:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            new_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=f"Erstellt von {interaction.user} via /import"
            )
            auto_channels.add(new_channel.id)
            video_embed_mode[new_channel.id] = True
        except discord.Forbidden:
            results.append(f"**{file.filename}** - Keine Berechtigung Channel zu erstellen")
            continue
        save_links(new_channel.id, extracted)
        for i in range(0, len(extracted), global_batch_size):
            batch = extracted[i:i+global_batch_size]
            text_links = []
            for url in batch:
                if is_video_url(url):
                    if text_links:
                        await new_channel.send("\n".join(text_links))
                        text_links = []
                    embed = discord.Embed(description=f"[Video anschauen]({url})")
                    embed.set_video(url=url)
                    await new_channel.send(content=url, embed=embed)
                else:
                    text_links.append(url)
            if text_links:
                await new_channel.send("\n".join(text_links))
            if i + global_batch_size < len(extracted):
                await asyncio.sleep(2)
        results.append(f"**{new_channel.mention}** - {len(extracted)} Links")
    await interaction.followup.send("\n".join(results))

@bot.tree.command(name="import2", description="LÃ¤dt .txt Dateien und sendet die Links direkt in diesen Channel")
@is_admin_or_owner()
@app_commands.describe(
    datei1="Datei 1", datei2="Datei 2", datei3="Datei 3", datei4="Datei 4", datei5="Datei 5",
    datei6="Datei 6", datei7="Datei 7", datei8="Datei 8", datei9="Datei 9", datei10="Datei 10"
)
async def import2_command(
    interaction: discord.Interaction,
    datei1: discord.Attachment,
    datei2: discord.Attachment = None,
    datei3: discord.Attachment = None,
    datei4: discord.Attachment = None,
    datei5: discord.Attachment = None,
    datei6: discord.Attachment = None,
    datei7: discord.Attachment = None,
    datei8: discord.Attachment = None,
    datei9: discord.Attachment = None,
    datei10: discord.Attachment = None
):
    await interaction.response.defer()
    files = [d for d in [datei1, datei2, datei3, datei4, datei5, datei6, datei7, datei8, datei9, datei10] if d]
    
    all_links = []
    results = []
    use_nofilter = nofilter_mode.get(interaction.guild_id, nofilter_mode_default)
    use_filter = filter_mode.get(interaction.guild_id, False)
    
    for file in files:
        if not file.filename.endswith('.txt'):
            results.append(f"**{file.filename}** - Ãœbersprungen (keine .txt)")
            continue
        content = await file.read()
        text = content.decode('utf-8', errors='ignore')
        
        if use_nofilter:
            extracted = extract_links_nofilter(text)
        elif use_filter:
            extracted = extract_links_advanced(text)
        else:
            extracted = extract_links(text)
        
        if not extracted:
            results.append(f"**{file.filename}** - Keine Links gefunden")
            continue
        all_links.extend(extracted)
        results.append(f"**{file.filename}** - {len(extracted)} Links")
    
    if not all_links:
        await interaction.followup.send("Keine Links in den Dateien gefunden.", ephemeral=True)
        return
    
    mode_text = ""
    if use_nofilter:
        mode_text = " (NOFILTER - alles durchlassen)"
    elif use_filter:
        mode_text = " (Filter-Modus AN)"
    await interaction.followup.send(f"**{len(all_links)} Links gefunden!**{mode_text} Sende in Batches...", ephemeral=True)
    
    channel = interaction.channel
    existing = load_links(channel.id)
    existing_set = set(clean_url(u) for u in existing)
    new_links = [u for u in all_links if clean_url(u) not in existing_set]
    
    if new_links:
        save_links(channel.id, existing + new_links)
    
    embed_on = video_embed_mode.get(channel.id, False)
    
    for i in range(0, len(all_links), global_batch_size):
        batch = all_links[i:i+global_batch_size]
        text_links = []
        for url in batch:
            if is_video_url(url):
                if text_links:
                    await channel.send("\n".join(text_links))
                    text_links = []
                if embed_on:
                    embed = discord.Embed(description=f"[Video anschauen]({url})")
                    embed.set_video(url=url)
                    await channel.send(content=url, embed=embed)
                else:
                    await channel.send(url)
            else:
                text_links.append(url)
        if text_links:
            await channel.send("\n".join(text_links))
        if i + global_batch_size < len(all_links):
            await asyncio.sleep(2)
    
    await channel.send(f"**Fertig!** {len(all_links)} Links gesendet.")

@bot.tree.command(name="filtermode", description="Toggle: Erweiterter Media-Filter (wie Discord Media Extractor)")
@is_admin_or_owner()
async def filtermode_command(interaction: discord.Interaction):
    current = filter_mode.get(interaction.guild_id, False)
    filter_mode[interaction.guild_id] = not current
    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    
    if not current:
        desc = (
            f"{icon} **Filter-Modus:** {state}\n\n"
            "BehÃ¤lt nur: GIF, MP4, MOV, AVI, MKV, WebM, PNG, JPG, WEBP, APNG, SVG\n"
            "Entfernt: Alles andere (Text-Links, HTML-Reste, Tracking-Parameter)\n"
            "Gilt fÃ¼r: `/import2`, `/add`, `/load`"
        )
    else:
        desc = f"{icon} **Filter-Modus:** {state}\n\nStandard-Filter aktiv."
    
    await interaction.response.send_message(desc)

@bot.tree.command(name="nofiltermode", description="Toggle: Kein Filter - jeder Zeile wird als Link genommen")
@is_admin_or_owner()
async def nofiltermode_command(interaction: discord.Interaction):
    current = nofilter_mode.get(interaction.guild_id, nofilter_mode_default)
    nofilter_mode[interaction.guild_id] = not current
    
    if not current:
        filter_mode[interaction.guild_id] = False
    
    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    
    if not current:
        desc = (
            f"{icon} **NoFilter-Modus:** {state}\n\n"
            "Jede Zeile wird als Link genommen - KEIN Filter!\n"
            "Kein URL-Check, keine Deduplizierung, keine Bereinigung\n"
            "Gilt fÃ¼r: `/import2`, `/add`, `/load`\n\n"
            "**Achtung:** Sendet wirklich ALLES was mit http anfÃ¤ngt!"
        )
    else:
        desc = f"{icon} **NoFilter-Modus:** {state}\n\nStandard-Filter aktiv."
    
    await interaction.response.send_message(desc)

class TiktokModeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Clyppy",
                value="clyppy",
                description="Empfohlen - Schnell & zuverlÃ¤ssig",
                emoji="â­"
            ),
            discord.SelectOption(
                label="dlbot",
                value="dlbot",
                description="Hohe QualitÃ¤t, MP4 Merge",
                emoji="ðŸ“¥"
            ),
            discord.SelectOption(
                label="TikCord",
                value="tikcord",
                description="Alle Formate, flexibel",
                emoji="ðŸŽµ"
            ),
            discord.SelectOption(
                label="QuickVids",
                value="quickvids",
                description="Schnell & simpel",
                emoji="âš¡"
            ),
        ]
        super().__init__(placeholder="WÃ¤hle einen TikTok Downloader...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        mode = self.values[0]
        tiktok_mode_data = load_tiktok_mode()
        tiktok_mode_data[str(interaction.guild_id)] = {
            "enabled": True,
            "mode": mode
        }
        save_tiktok_mode(tiktok_mode_data)
        tiktok_mode[interaction.guild_id] = {"enabled": True, "mode": mode}
        
        mode_names = {
            "clyppy": "Clyppy (â­ Empfohlen)",
            "dlbot": "dlbot (ðŸ“¥ Hohe QualitÃ¤t)",
            "tikcord": "TikCord (ðŸŽµ Flexibel)",
            "quickvids": "QuickVids (âš¡ Schnell)"
        }
        
        await interaction.response.send_message(
            f"âœ… **TikTok Auto-Download aktiviert!**\n\n"
            f"**Service:** {mode_names.get(mode, mode)}\n"
            f"**Status:** AN\n\n"
            f"Ab jetzt werden automatisch alle TikTok Links heruntergeladen und als Video gesendet!",
            ephemeral=True
        )

class TiktokModeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TiktokModeSelect())

@bot.tree.command(name="tiktokmode", description="TikTok Auto-Download: WÃ¤hle einen Service fÃ¼r automatische Downloads")
@is_admin_or_owner()
async def tiktokmode_command(interaction: discord.Interaction):
    view = TiktokModeView()
    await interaction.response.send_message(
        "**TikTok Auto-Download Konfiguration**\n\n"
        "WÃ¤hle einen Service aus:\n\n"
        "â­ **Clyppy** - Empfohlen, schnell & zuverlÃ¤ssig\n"
        "ðŸ“¥ **dlbot** - Hohe QualitÃ¤t mit MP4 Merge\n"
        "ðŸŽµ **TikCord** - Alle Formate, flexibel\n"
        "âš¡ **QuickVids** - Schnell & simpel\n\n"
        "Sobald aktiviert, werden alle TikTok Links automatisch erkannt und heruntergeladen!",
        view=view,
        ephemeral=True
    )

@bot.tree.command(name="tiktoktoggle", description="TikTok Auto-Download ein/ausschalten")
@is_admin_or_owner()
async def tiktoktoggle_command(interaction: discord.Interaction):
    tiktok_mode_data = load_tiktok_mode()
    guild_id_str = str(interaction.guild_id)
    
    if guild_id_str in tiktok_mode_data:
        current = tiktok_mode_data[guild_id_str].get("enabled", False)
        tiktok_mode_data[guild_id_str]["enabled"] = not current
        save_tiktok_mode(tiktok_mode_data)
        tiktok_mode[interaction.guild_id] = tiktok_mode_data[guild_id_str]
        
        state = "AN" if not current else "AUS"
        icon = "âœ…" if not current else "âŒ"
        
        if not current:
            mode = tiktok_mode_data[guild_id_str].get("mode", "clyppy")
            mode_names = {
                "clyppy": "Clyppy",
                "dlbot": "dlbot",
                "tikcord": "TikCord",
                "quickvids": "QuickVids"
            }
            desc = (
                f"{icon} **TikTok Auto-Download:** {state}\n\n"
                f"**Service:** {mode_names.get(mode, mode)}\n"
                f"Alle TikTok Links werden jetzt automatisch heruntergeladen!"
            )
        else:
            desc = f"{icon} **TikTok Auto-Download:** {state}\n\nTikTok Links werden nicht mehr automatisch heruntergeladen."
    else:
        await interaction.response.send_message(
            "Noch nicht konfiguriert! Benutze zuerst `/tiktokmode` um einen Service auszuwÃ¤hlen.",
            ephemeral=True
        )
        return
    
    await interaction.response.send_message(desc)

@bot.tree.command(name="tiktokstatus", description="Zeigt den aktuellen TikTok Auto-Download Status")
@is_admin_or_owner()
async def tiktokstatus_command(interaction: discord.Interaction):
    tiktok_mode_data = load_tiktok_mode()
    guild_id_str = str(interaction.guild_id)
    
    if guild_id_str in tiktok_mode_data:
        data = tiktok_mode_data[guild_id_str]
        enabled = data.get("enabled", False)
        mode = data.get("mode", "clyppy")
        
        mode_names = {
            "clyppy": "Clyppy (â­ Empfohlen)",
            "dlbot": "dlbot (ðŸ“¥ Hohe QualitÃ¤t)",
            "tikcord": "TikCord (ðŸŽµ Flexibel)",
            "quickvids": "QuickVids (âš¡ Schnell)"
        }
        
        status = "âœ… AN" if enabled else "âŒ AUS"
        
        await interaction.response.send_message(
            f"**TikTok Auto-Download Status**\n\n"
            f"**Status:** {status}\n"
            f"**Service:** {mode_names.get(mode, mode)}\n\n"
            f"{'Alle TikTok Links werden automatisch heruntergeladen!' if enabled else 'TikTok Links werden nicht automatisch verarbeitet.'}"
        )
    else:
        await interaction.response.send_message(
            "Noch nicht konfiguriert! Benutze `/tiktokmode` um einen Service auszuwÃ¤hlen.",
            ephemeral=True
        )

@bot.tree.command(name="clearchannels", description="LÃ¶scht alle vom Bot erstellten Channels")
@is_admin_or_owner()
async def clearchannels_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    deleted = 0
    for channel_id in list(auto_channels):
        channel = interaction.guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete(reason=f"GelÃ¶scht via /clearchannels von {interaction.user}")
                deleted += 1
            except discord.Forbidden:
                pass
        auto_channels.discard(channel_id)
    if deleted == 0:
        await interaction.followup.send("Keine Bot-Channels zum LÃ¶schen gefunden.", ephemeral=True)
    else:
        await interaction.followup.send(f"**{deleted} Channel(s) gelÃ¶scht!**")

@bot.tree.command(name="permsync", description="Synchronisiert die Permissions aller Channels einer Kategorie mit der Kategorie")
@is_admin_or_owner()
@app_commands.describe(kategorie="WÃ¤hle eine Kategorie aus")
async def permsync_command(interaction: discord.Interaction, kategorie: str):
    await interaction.response.defer(ephemeral=True)
    
    target_category = None
    for cat in interaction.guild.categories:
        if cat.name.lower() == kategorie.lower():
            target_category = cat
            break
    
    if not target_category:
        await interaction.followup.send(f"Kategorie **{kategorie}** nicht gefunden.", ephemeral=True)
        return
    
    channels = target_category.channels
    if not channels:
        await interaction.followup.send(f"Keine Channels in **{target_category.name}**.", ephemeral=True)
        return
    
    synced = 0
    failed = 0
    for ch in channels:
        try:
            await ch.edit(sync_permissions=True)
            synced += 1
        except discord.Forbidden:
            failed += 1
        except Exception:
            failed += 1
    
    await interaction.followup.send(
        f"**Permissions synchronisiert!**\n"
        f"Kategorie: **{target_category.name}**\n"
        f"Channels: **{synced}** erfolgreich, **{failed}** fehlgeschlagen"
    )

@permsync_command.autocomplete("kategorie")
async def permsync_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=f"{cat.name} ({len(cat.channels)} Channels)", value=cat.name)
        for cat in interaction.guild.categories
        if current.lower() in cat.name.lower()
    ][:25]

@bot.tree.command(name="hoistall", description="Aktiviert 'Rolle getrennt anzeigen' bei allen Rollen")
@is_admin_or_owner()
async def hoistall_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    updated = 0
    skipped = 0
    for role in interaction.guild.roles:
        if role == interaction.guild.default_role:
            skipped += 1
            continue
        if not role.hoist:
            try:
                await role.edit(hoist=True)
                updated += 1
            except discord.Forbidden:
                skipped += 1
        else:
            skipped += 1
    await interaction.followup.send(f"**{updated} Rollen aktualisiert!** ({skipped} Ã¼bersprungen â€“ bereits aktiv oder keine Berechtigung)")

@bot.tree.command(name="setavatar", description="Setzt das Bot-Profilbild (Bild reinziehen)")
@is_admin_or_owner()
@app_commands.describe(bild="Bild als Profilbild (PNG, JPG, GIF, WebP)")
async def setavatar_command(interaction: discord.Interaction, bild: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    allowed_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    if not any(bild.filename.lower().endswith(ext) for ext in allowed_exts):
        await interaction.followup.send("Nur Bilddateien erlaubt (PNG, JPG, GIF, WebP)!", ephemeral=True)
        return
    image_data = await bild.read()
    if len(image_data) > 8 * 1024 * 1024:
        await interaction.followup.send("Bild ist zu groÃŸ (max 8MB)!", ephemeral=True)
        return
    try:
        await bot.user.edit(avatar=image_data)
        await interaction.followup.send("Profilbild erfolgreich geÃ¤ndert!", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Fehler beim Ã„ndern: {e}", ephemeral=True)

@bot.tree.command(name="setbanner", description="Setzt das Bot-Bannerbild (Bild reinziehen)")
@is_admin_or_owner()
@app_commands.describe(bild="Bild als Banner (PNG, JPG, GIF, WebP)")
async def setbanner_command(interaction: discord.Interaction, bild: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    allowed_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    if not any(bild.filename.lower().endswith(ext) for ext in allowed_exts):
        await interaction.followup.send("Nur Bilddateien erlaubt (PNG, JPG, GIF, WebP)!", ephemeral=True)
        return
    image_data = await bild.read()
    if len(image_data) > 10 * 1024 * 1024:
        await interaction.followup.send("Bild ist zu groÃŸ (max 10MB)!", ephemeral=True)
        return
    try:
        await bot.user.edit(banner=image_data)
        await interaction.followup.send("Banner erfolgreich geÃ¤ndert!", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Fehler beim Ã„ndern: {e}\n\n**Hinweis:** Banner-Ã„nderung funktioniert nur bei verifizierten Bots.", ephemeral=True)

@bot.tree.command(name="reactionrole", description="Verwaltet Reaction-Roles (wie Carl-bot)")
@is_admin_or_owner()
@app_commands.describe(
    aktion="add, remove, list oder clear",
    message_id="Die ID der Nachricht",
    emoji="Das Emoji (z.B. ðŸ˜ˆ oder :name:)",
    rolle="Die Rolle (Name oder Mention)"
)
@app_commands.choices(aktion=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove"),
    app_commands.Choice(name="list", value="list"),
    app_commands.Choice(name="clear", value="clear")
])
async def reactionrole_command(
    interaction: discord.Interaction,
    aktion: app_commands.Choice[str],
    message_id: str = "",
    emoji: str = "",
    rolle: str = ""
):
    await interaction.response.defer(ephemeral=True)
    reaction_roles = load_reaction_roles()
    
    if aktion.value == "list":
        if str(interaction.guild_id) not in reaction_roles:
            await interaction.followup.send("Keine Reaction-Roles fÃ¼r diesen Server.", ephemeral=True)
            return
        
        guild_data = reaction_roles[str(interaction.guild_id)]
        if not guild_data:
            await interaction.followup.send("Keine Reaction-Roles fÃ¼r diesen Server.", ephemeral=True)
            return
        
        lines = []
        for msg_id, data in guild_data.items():
            channel = bot.get_channel(data["channel_id"])
            channel_name = f"#{channel.name}" if channel else "unbekannt"
            lines.append(f"**Nachricht {msg_id}** ({channel_name}):")
            for emoji_key, role_id in data["roles"].items():
                role = interaction.guild.get_role(role_id)
                role_name = role.name if role else f"ID: {role_id}"
                lines.append(f"  {emoji_key} â†’ {role_name}")
            lines.append("")
        
        await interaction.followup.send("\n".join(lines)[:2000], ephemeral=True)
        return
    
    if aktion.value == "clear":
        if not message_id:
            await interaction.followup.send("Message-ID angeben!", ephemeral=True)
            return
        
        guild_id_str = str(interaction.guild_id)
        if guild_id_str in reaction_roles and message_id in reaction_roles[guild_id_str]:
            del reaction_roles[guild_id_str][message_id]
            if not reaction_roles[guild_id_str]:
                del reaction_roles[guild_id_str]
            save_reaction_roles(reaction_roles)
            await interaction.followup.send(f"Alle Reaction-Roles fÃ¼r Nachricht {message_id} gelÃ¶scht.", ephemeral=True)
        else:
            await interaction.followup.send("Nachricht nicht gefunden.", ephemeral=True)
        return
    
    if not message_id or not emoji or not rolle:
        await interaction.followup.send("Message-ID, Emoji und Rolle angeben!", ephemeral=True)
        return
    
    try:
        channel = interaction.channel
        msg = await channel.fetch_message(int(message_id))
    except:
        await interaction.followup.send("Nachricht nicht gefunden! ID prÃ¼fen.", ephemeral=True)
        return
    
    role = None
    if rolle.startswith("<@&"):
        role_id = int(rolle.replace("<@&", "").replace(">", ""))
        role = interaction.guild.get_role(role_id)
    else:
        for r in interaction.guild.roles:
            if r.name.lower() == rolle.lower():
                role = r
                break
    
    if not role:
        await interaction.followup.send(f"Rolle **{rolle}** nicht gefunden!", ephemeral=True)
        return
    
    if role.position >= interaction.guild.me.top_role.position:
        await interaction.followup.send(f"Rolle **{role.name}** ist zu hoch fÃ¼r den Bot!", ephemeral=True)
        return
    
    if role.managed:
        await interaction.followup.send(f"Rolle **{role.name}** ist eine Bot-Rolle!", ephemeral=True)
        return
    
    try:
        await msg.add_reaction(emoji)
    except:
        await interaction.followup.send(f"Emoji **{emoji}** ungÃ¼ltig!", ephemeral=True)
        return
    
    guild_id_str = str(interaction.guild_id)
    if guild_id_str not in reaction_roles:
        reaction_roles[guild_id_str] = {}
    if message_id not in reaction_roles[guild_id_str]:
        reaction_roles[guild_id_str][message_id] = {
            "channel_id": interaction.channel_id,
            "roles": {}
        }
    
    reaction_roles[guild_id_str][message_id]["roles"][emoji] = role.id
    save_reaction_roles(reaction_roles)
    
    await interaction.followup.send(f"âœ… {emoji} â†’ **{role.name}** hinzugefÃ¼gt!", ephemeral=True)

async def send_next_batch(channel_id, channel):
    links = load_links(channel_id)
    status = channel_status.get(channel_id, {"index": 0, "running": False})
    idx = status["index"]
    if idx >= len(links):
        await channel.send("**Fertig!** Alle Links durchgesendet.")
        status["running"] = False
        return
    batch = links[idx:idx+global_batch_size]
    embed_on = video_embed_mode.get(channel_id, False)
    if embed_on:
        text_links = []
        for url in batch:
            if is_video_url(url):
                if text_links:
                    await channel.send("\n".join(text_links))
                    text_links = []
                embed = discord.Embed(description=f"[Video anschauen]({url})")
                embed.set_video(url=url)
                await channel.send(content=url, embed=embed)
            else:
                text_links.append(url)
        if text_links:
            await channel.send("\n".join(text_links))
    else:
        message = "\n".join(batch)
        await channel.send(message)
    status["index"] = idx + len(batch)
    channel_status[channel_id] = status
    if status["index"] >= len(links):
        await channel.send("**Fertig!** Alle Links durchgesendet.")
        status["running"] = False
        return
    if status["running"]:
        await asyncio.sleep(2)
        await send_next_batch(channel_id, channel)

@bot.tree.command(name="reactionsetup", description="Sendet eine Webhook-Embed mit Button fÃ¼r Reaction-Roles")
@is_admin_or_owner()
@app_commands.describe(
    rolle="Die Rolle (Name)",
    emoji="Das Emoji fÃ¼r den Button (z.B. ðŸ˜ˆ)",
    farbe="Embed Farbe (hex, z.B. FF0000)",
    channel="Channel (Standard: aktueller Channel)"
)
async def reactionsetup_command(
    interaction: discord.Interaction,
    rolle: str,
    emoji: str,
    farbe: str = "5865F2",
    channel: discord.TextChannel = None
):
    await interaction.response.defer(ephemeral=True)
    
    target_channel = channel or interaction.channel
    
    role = None
    for r in interaction.guild.roles:
        if r.name.lower() == rolle.lower():
            role = r
            break
    
    if not role:
        await interaction.followup.send(f"Rolle **{rolle}** nicht gefunden!", ephemeral=True)
        return
    
    if role == interaction.guild.default_role:
        await interaction.followup.send("Die @everyone Rolle kann nicht verwendet werden!", ephemeral=True)
        return
    
    if role.managed:
        await interaction.followup.send(f"Rolle **{role.name}** ist eine Bot-Rolle!", ephemeral=True)
        return
    
    if role.position >= interaction.guild.me.top_role.position:
        await interaction.followup.send(f"Rolle **{role.name}** ist zu hoch fÃ¼r den Bot!", ephemeral=True)
        return
    
    is_excluded = any(ex in role.name.lower() for ex in EXCLUDED_ROLE_NAMES)
    if is_excluded:
        await interaction.followup.send(
            f"Rolle **{role.name}** ist eine Admin-Rolle!\n"
            f"Exkludiert: {', '.join(EXCLUDED_ROLE_NAMES)}",
            ephemeral=True
        )
        return
    
    try:
        color_int = int(farbe.replace("#", ""), 16)
    except:
        color_int = 0x5865F2
    
    button_custom_id = f"rr_{role.id}"
    
    payload = {
        "content": "",
        "embeds": [{
            "description": f"{emoji}{role.name}",
            "color": color_int,
            "author": {
                "name": emoji
            }
        }],
        "components": [{
            "type": 1,
            "components": [{
                "type": 2,
                "style": 2,
                "label": emoji,
                "custom_id": button_custom_id
            }]
        }]
    }
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(WEBHOOK_URL, json=payload) as resp:
            if resp.status not in (200, 204):
                error = await resp.text()
                await interaction.followup.send(f"Webhook Fehler: {error}", ephemeral=True)
                return
            msg = await resp.json()
    
    reaction_roles = load_reaction_roles()
    guild_id_str = str(interaction.guild_id)
    msg_id_str = str(msg["id"])
    
    if guild_id_str not in reaction_roles:
        reaction_roles[guild_id_str] = {}
    
    reaction_roles[guild_id_str][msg_id_str] = {
        "channel_id": target_channel.id,
        "roles": {emoji: role.id}
    }
    save_reaction_roles(reaction_roles)
    
    await interaction.followup.send(
        f"**Fertig!** Embed in {target_channel.mention}\n\n"
        f"**Message-ID:** `{msg['id']}`\n"
        f"**Rolle:** {role.name}\n"
        f"**Emoji:** {emoji}\n\n"
        f"Button funktioniert sofort - klick = Rolle toggle!",
        ephemeral=True
    )

@reactionsetup_command.autocomplete("rolle")
async def rolle_autocomplete(interaction: discord.Interaction, current: str):
    choices = []
    for role in interaction.guild.roles:
        if role == interaction.guild.default_role:
            continue
        if role.managed:
            continue
        if role.position >= interaction.guild.me.top_role.position:
            continue
        is_excluded = any(ex in role.name.lower() for ex in EXCLUDED_ROLE_NAMES)
        if is_excluded:
            continue
        if current.lower() in role.name.lower():
            choices.append(app_commands.Choice(name=role.name, value=role.name))
    return choices[:25]

USER_ROLE_KEYWORDS = [
    "maske", "tik-toker", "streamer", "ehrenuser", "e-girl", "hello kitty", 
    "seÃ±orita", "marlboro", "sugar mommy", "casanova", "galatasaray", 
    "smile", "gengar", "durstlÃ¶scher", "uchiha", "bunny", "sonic", "kitten", 
    "emo", "rolex", "patrick", "prinzessin", "geistig", "beefer", "queen", 
    "barbie", "baby", "shiggy", "hustler", "saiyajin", "domina", "king", 
    "sadboy", "terrorist", "speedy", "ruffy", "spongebob", "engel", "uwu", 
    "habibi", "geist", "teufel", "cop", "smoker", "stoner", "alien", "senpai", 
    "superman", "tÃ¼rsteher", "demon", "spiderman", "moncler", "godsent", "toxic", 
    "npc", "ehrenmann", "ehrenfrau", "cute", "goofy", "og", "freund", "ðŸ‘‘"
]

EXCLUDED_ROLE_KEYWORDS = [
    "admin", "moderator", "head admin", "teamleitung", "team", "supporter",
    "bot", "muted", "timeout", "booster", "level", "rank", "premium",
    "owner", "security", "role manager", "access", "member", "mitglied",
    "no-xp", "sendmoji", "pic", "platzhalter", "supreme", "stammuser",
    "champion", "ultimativ", "titan", "prestige", "legende", "meister",
    "veteran", "elite", "platin", "silver", "treu", "aktiv", "noob",
    "meme maker", "test", "pb master", "----", "â€”â€”", "ðŸ”Š", "ðŸ”ž+",
    "star", "â˜…", "*"
]

@bot.tree.command(name="masssetup", description="Erstellt Reaction-Role Buttons fÃ¼r ALLE User-Rollen automatisch")
@is_admin_or_owner()
@app_commands.describe(
    channel="Channel wo die Nachricht hinsoll"
)
async def masssetup_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None
):
    await interaction.response.defer(ephemeral=True)
    
    target_channel = channel or interaction.channel
    
    user_roles = []
    for role in interaction.guild.roles:
        if role == interaction.guild.default_role:
            continue
        if role.managed:
            continue
        if role.position >= interaction.guild.me.top_role.position:
            continue
        
        role_name_lower = role.name.lower()
        
        if any(ex in role_name_lower for ex in EXCLUDED_ROLE_KEYWORDS):
            continue
        
        is_user_role = any(kw in role_name_lower for kw in USER_ROLE_KEYWORDS)
        
        if not is_user_role:
            if role.hoist and not any(ex in role_name_lower for ex in ["----", "â€”â€”", "rank", "level"]):
                if role.color.value != 0 and role.name not in ["----", "â€”â€”"]:
                    pass
                else:
                    continue
        
        user_roles.append(role)
    
    if not user_roles:
        await interaction.followup.send("Keine User-Rollen gefunden!", ephemeral=True)
        return
    
    user_roles.sort(key=lambda r: r.name)
    
    reaction_roles = load_reaction_roles()
    guild_id_str = str(interaction.guild_id)
    if guild_id_str not in reaction_roles:
        reaction_roles[guild_id_str] = {}
    
    import aiohttp
    
    webhook = None
    for wh in await target_channel.webhooks():
        if wh.name == WEBHOOK_NAME:
            webhook = wh
            break
    
    if not webhook:
        try:
            webhook = await target_channel.create_webhook(
                name=WEBHOOK_NAME,
                reason="Mass Reaction-Role Setup"
            )
        except discord.Forbidden:
            await interaction.followup.send("Keine Berechtigung um Webhooks zu erstellen!", ephemeral=True)
            return
    
    messages_sent = 0
    total_buttons = 0
    ROLES_PER_PAGE = 20
    
    for chunk_start in range(0, len(user_roles), ROLES_PER_PAGE):
        chunk = user_roles[chunk_start:chunk_start + ROLES_PER_PAGE]
        
        components = []
        for i in range(0, len(chunk), 5):
            row_roles = chunk[i:i + 5]
            row_buttons = []
            for role in row_roles:
                button_custom_id = f"rr_{role.id}"
                row_buttons.append({
                    "type": 2,
                    "style": 2,
                    "label": role.name,
                    "custom_id": button_custom_id
                })
            components.append({"type": 1, "components": row_buttons})
        
        page_num = (chunk_start // ROLES_PER_PAGE) + 1
        total_pages = (len(user_roles) + ROLES_PER_PAGE - 1) // ROLES_PER_PAGE
        
        payload = {
            "content": "",
            "embeds": [{
                "description": f"**WÃ¤hle deine Rollen:**\n\n" + "\n".join([f"â€¢ {r.name}" for r in chunk]),
                "color": 0x5865F2,
                "author": {
                    "name": f"User Rollen ({page_num}/{total_pages})"
                },
                "footer": {
                    "text": f"Seite {page_num} von {total_pages} â€¢ {len(user_roles)} Rollen gesamt"
                }
            }],
            "components": components
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://discord.com/api/v10/webhooks/{webhook.id}/{webhook.token}",
                json=payload,
                params={"wait": "true"}
            ) as resp:
                if resp.status not in (200, 204):
                    error = await resp.text()
                    await interaction.followup.send(f"Webhook Fehler: {error}", ephemeral=True)
                    return
                msg = await resp.json()
        
        msg_id_str = str(msg["id"])
        reaction_roles[guild_id_str][msg_id_str] = {
            "channel_id": target_channel.id,
            "roles": {r.name: r.id for r in chunk}
        }
        
        messages_sent += 1
        total_buttons += len(chunk)
    
    save_reaction_roles(reaction_roles)
    
    await interaction.followup.send(
        f"**Fertig!** {messages_sent} Nachrichten in {target_channel.mention}\n\n"
        f"**{total_buttons} Buttons** fÃ¼r {len(user_roles)} User-Rollen erstellt!\n"
        f"Alle funktionieren sofort - Klick = Rolle toggle!",
        ephemeral=True
    )

# =====================================
# TICKET SYSTEM
# =====================================

TICKET_CONFIG_FILE = DATA_DIR / "ticket_config.json"
TICKET_DATA_FILE = DATA_DIR / "tickets.json"
TICKET_LOG_CHANNEL = None

def load_ticket_config():
    if TICKET_CONFIG_FILE.exists():
        with open(TICKET_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_ticket_config(data):
    with open(TICKET_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_ticket_data():
    if TICKET_DATA_FILE.exists():
        with open(TICKET_DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_ticket_data(data):
    with open(TICKET_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Create Ticket",
        style=discord.ButtonStyle.blurple,
        emoji="",
        custom_id="ticket_create_button"
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        config = load_ticket_config()
        guild_str = str(interaction.guild_id)

        if guild_str not in config:
            await interaction.followup.send("Ticket-System nicht konfiguriert!", ephemeral=True)
            return

        guild_config = config[guild_str]
        category_id = guild_config.get("category_id")
        support_role_id = guild_config.get("support_role_id")
        log_channel_id = guild_config.get("log_channel_id")

        category = interaction.guild.get_channel(category_id) if category_id else None
        support_role = interaction.guild.get_role(support_role_id) if support_role_id else None

        ticket_data = load_ticket_data()
        if guild_str not in ticket_data:
            ticket_data[guild_str] = {"counter": 0, "tickets": {}}

        user_str = str(interaction.user.id)
        for ticket_id, ticket_info in ticket_data[guild_str].get("tickets", {}).items():
            if ticket_info.get("user_id") == user_str and ticket_info.get("status") == "open":
                channel = interaction.guild.get_channel(int(ticket_id))
                if channel:
                    await interaction.followup.send(
                        f"Du hast bereits ein offenes Ticket: {channel.mention}",
                        ephemeral=True
                    )
                    return
                else:
                    ticket_info["status"] = "closed"
                    ticket_info["closed_at"] = discord.utils.utcnow().isoformat()

        save_ticket_data(ticket_data)

        for ch in interaction.guild.text_channels:
            if ch.name.startswith("ticket-") and user_str in ch.name:
                await interaction.followup.send(
                    f"Du hast bereits ein offenes Ticket: {ch.mention}",
                    ephemeral=True
                )
                return

        ticket_data[guild_str]["counter"] = ticket_data[guild_str].get("counter", 0) + 1
        ticket_number = ticket_data[guild_str]["counter"]

        channel_name = f"ticket-{ticket_number:04d}-{interaction.user.name.lower()[:20]}"

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True
            )
        }

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True
            )

        try:
            if category:
                ticket_channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    reason=f"Ticket #{ticket_number:04d} von {interaction.user}"
                )
            else:
                ticket_channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    reason=f"Ticket #{ticket_number:04d} von {interaction.user}"
                )
        except discord.Forbidden:
            await interaction.followup.send("Keine Berechtigung um Channel zu erstellen!", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"Fehler: {e}", ephemeral=True)
            return

        ticket_data[guild_str]["tickets"][str(ticket_channel.id)] = {
            "user_id": user_str,
            "user_name": interaction.user.display_name,
            "status": "open",
            "created_at": discord.utils.utcnow().isoformat(),
            "ticket_number": ticket_number
        }
        save_ticket_data(ticket_data)

        embed = discord.Embed(
            title=f"Ticket #{ticket_number:04d}",
            description=(
                f"Willkommen {interaction.user.mention}!\n\n"
                f"Beschreibe bitte dein Anliegen.\n"
                f"Ein Supporter wird sich bald um dich kuemmern."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Ticket #{ticket_number:04d}")

        if support_role:
            support_mention = support_role.mention
        else:
            support_mention = "@Support"

        await ticket_channel.send(
            content=f"{interaction.user.mention} {support_mention}",
            embed=embed,
            view=TicketManageView()
        )

        await interaction.followup.send(
            f"Ticket erstellt: {ticket_channel.mention}",
            ephemeral=True
        )

        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="Ticket Erstellt",
                    description=(
                        f"**User:** {interaction.user.mention}\n"
                        f"**Channel:** {ticket_channel.mention}\n"
                        f"**Ticket:** #{ticket_number:04d}"
                    ),
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                await log_channel.send(embed=log_embed)

class TicketManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.red,
        emoji="",
        custom_id="ticket_close_button"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Ticket schliessen?",
            description="Bist du sicher? Das Transkript wird gespeichert.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(
            embed=embed,
            view=TicketCloseConfirmView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="Transcript",
        style=discord.ButtonStyle.grey,
        emoji="",
        custom_id="ticket_transcript_button"
    )
    async def transcript_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        transcript = await generate_transcript(interaction.channel)
        if transcript:
            file = discord.File(
                fp=transcript,
                filename=f"transcript-{interaction.channel.name}.txt"
            )
            await interaction.followup.send("Transkript:", file=file, ephemeral=True)
        else:
            await interaction.followup.send("Keine Nachrichten zum Transkribieren.", ephemeral=True)

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(
        label="Ja, schliessen",
        style=discord.ButtonStyle.red,
        custom_id="ticket_close_confirm"
    )
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        config = load_ticket_config()
        guild_str = str(interaction.guild_id)
        log_channel_id = config.get(guild_str, {}).get("log_channel_id")

        transcript_content = await generate_transcript_text(interaction.channel)

        ticket_data = load_ticket_data()
        ticket_info = None
        if guild_str in ticket_data:
            ticket_info = ticket_data[guild_str].get("tickets", {}).get(str(interaction.channel.id))

        if ticket_info:
            ticket_info["status"] = "closed"
            ticket_info["closed_at"] = discord.utils.utcnow().isoformat()
            ticket_info["closed_by"] = str(interaction.user.id)
            save_ticket_data(ticket_data)

        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                user = interaction.guild.get_member(int(ticket_info["user_id"])) if ticket_info else None

                log_embed = discord.Embed(
                    title="Ticket Geschlossen",
                    description=(
                        f"**Ticket:** {interaction.channel.name}\n"
                        f"**User:** {user.mention if user else 'Unbekannt'}\n"
                        f"**Geschlossen von:** {interaction.user.mention}\n"
                        f"**Geschlossen am:** {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')}"
                    ),
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )

                if transcript_content:
                    transcript_file = discord.File(
                        fp=__import__('io').BytesIO(transcript_content.encode('utf-8')),
                        filename=f"transcript-{interaction.channel.name}.txt"
                    )
                    await log_channel.send(embed=log_embed, file=transcript_file)
                else:
                    await log_channel.send(embed=log_embed)

        try:
            await interaction.channel.delete(reason=f"Ticket geschlossen von {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("Keine Berechtigung um Channel zu loeschen!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Fehler: {e}", ephemeral=True)

    @discord.ui.button(
        label="Abbrechen",
        style=discord.ButtonStyle.grey,
        custom_id="ticket_close_cancel"
    )
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Ticket bleibt offen.", embed=None, view=None)

async def generate_transcript(channel, limit=500):
    import io
    messages = []
    async for message in channel.history(limit=limit, oldest_first=True):
        timestamp = message.created_at.strftime("%d.%m.%Y %H:%M")
        content = message.content or ""
        if message.attachments:
            content += " " + " ".join(a.url for a in message.attachments)
        messages.append(f"[{timestamp}] {message.author.display_name}: {content}")

    if not messages:
        return None

    text = f"=== Transcript: {channel.name} ===\n"
    text += f"Erstellt: {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')}\n"
    text += "=" * 40 + "\n\n"
    text += "\n".join(messages)

    return io.BytesIO(text.encode('utf-8'))

async def generate_transcript_text(channel, limit=500):
    messages = []
    async for message in channel.history(limit=limit, oldest_first=True):
        timestamp = message.created_at.strftime("%d.%m.%Y %H:%M")
        content = message.content or ""
        if message.attachments:
            content += " " + " ".join(a.url for a in message.attachments)
        messages.append(f"[{timestamp}] {message.author.display_name}: {content}")

    if not messages:
        return None

    text = f"=== Transcript: {channel.name} ===\n"
    text += f"Erstellt: {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')}\n"
    text += "=" * 40 + "\n\n"
    text += "\n".join(messages)
    return text

@bot.tree.command(name="ticketsetup", description="Ticket-System einrichten")
@is_admin_or_owner()
@app_commands.describe(
    channel="Channel fuer das Ticket-Panel",
    kategorie="Kategorie fuer Ticket-Channels",
    support_rolle="Support-Rolle die Tickets sehen kann",
    log_channel="Channel fuer Ticket-Logs (optional)"
)
async def ticketsetup_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    kategorie: str,
    support_rolle: discord.Role,
    log_channel: discord.TextChannel = None
):
    await interaction.response.defer(ephemeral=True)

    category = None
    for cat in interaction.guild.categories:
        if cat.name.lower() == kategorie.lower():
            category = cat
            break

    if not category:
        try:
            category = await interaction.guild.create_category(
                name=kategorie,
                reason=f"Ticket-System von {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.followup.send("Keine Berechtigung um Kategorie zu erstellen!", ephemeral=True)
            return

    config = load_ticket_config()
    guild_str = str(interaction.guild_id)
    config[guild_str] = {
        "category_id": category.id,
        "support_role_id": support_rolle.id,
        "log_channel_id": log_channel.id if log_channel else None,
        "setup_channel_id": channel.id
    }
    save_ticket_config(config)

    embed = discord.Embed(
        title="Support Tickets",
        description=(
            "Brauchst du Hilfe?\n"
            "Klicke auf den Button um ein Ticket zu erstellen!\n\n"
            "**Wann ein Ticket erstellen?**\n"
            "â€¢ Allgemeine Fragen\n"
            "â€¢ Probleme melden\n"
            "â€¢ Beantragungen\n"
            "â€¢ Beschwerden"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Support Team | Tickets")

    await channel.send(embed=embed, view=TicketCreateView())

    await interaction.followup.send(
        f"Ticket-System eingerichtet!\n\n"
        f"**Panel:** {channel.mention}\n"
        f"**Kategorie:** {category.name}\n"
        f"**Support:** {support_rolle.mention}\n"
        f"**Logs:** {log_channel.mention if log_channel else 'Keine'}",
        ephemeral=True
    )

@bot.tree.command(name="close", description="Ticket schliessen")
async def close_command(interaction: discord.Interaction):
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("Das ist kein Ticket-Channel!", ephemeral=True)
        return

    embed = discord.Embed(
        title="Ticket schliessen?",
        description="Bist du sicher? Das Transkript wird gespeichert.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(
        embed=embed,
        view=TicketCloseConfirmView(),
        ephemeral=True
    )

@bot.tree.command(name="ticketadd", description="User zum Ticket hinzufuegen")
@app_commands.describe(user="Der User der hinzugefuegt werden soll")
async def ticketadd_command(interaction: discord.Interaction, user: discord.Member):
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("Das ist kein Ticket-Channel!", ephemeral=True)
        return

    try:
        await interaction.channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True
        )
        await interaction.response.send_message(f"{user.mention} wurde hinzugefuegt!")
    except discord.Forbidden:
        await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

@bot.tree.command(name="ticketremove", description="User aus dem Ticket entfernen")
@app_commands.describe(user="Der User der entfernt werden soll")
async def ticketremove_command(interaction: discord.Interaction, user: discord.Member):
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("Das ist kein Ticket-Channel!", ephemeral=True)
        return

    try:
        await interaction.channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(f"{user.mention} wurde entfernt!")
    except discord.Forbidden:
        await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

@bot.tree.command(name="transcript", description="Transkript des Tickets generieren")
async def transcript_command(interaction: discord.Interaction):
    if not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("Das ist kein Ticket-Channel!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    transcript = await generate_transcript(interaction.channel)
    if transcript:
        file = discord.File(
            fp=transcript,
            filename=f"transcript-{interaction.channel.name}.txt"
        )
        await interaction.followup.send("Transkript:", file=file, ephemeral=True)
    else:
        await interaction.followup.send("Keine Nachrichten zum Transkribieren.", ephemeral=True)

MAX_ROLES_FOR_MITGLIED = 7
PROTECTED_ROLE_NAMES = ["976", "owner", "head admin", "admin", "moderator", "bot", "muted", "timeout", "booster"]

@bot.event
async def on_member_update(before, after):
    if before.roles == after.roles:
        return
    
    mitglied_role = discord.utils.get(after.roles, name="Mitglied")
    if not mitglied_role:
        return
    
    protected_roles = []
    normal_roles = []
    
    for role in after.roles:
        if role == after.guild.default_role:
            continue
        if role.name.lower() in [r.lower() for r in PROTECTED_ROLE_NAMES]:
            protected_roles.append(role)
        elif role.name.startswith(("â˜…", "*", "â­", "Level")):
            protected_roles.append(role)
        else:
            normal_roles.append(role)
    
    if len(normal_roles) > MAX_ROLES_FOR_MITGLIED:
        to_remove = normal_roles[MAX_ROLES_FOR_MITGLIED:]
        try:
            await after.remove_roles(*to_remove, reason="Max 7 Rollen fÃ¼r Mitglieder")
        except discord.Forbidden:
            pass

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    
    reaction_roles = load_reaction_roles()
    guild_id_str = str(payload.guild_id)
    message_id = str(payload.message_id)
    emoji_str = str(payload.emoji)
    
    frage_messages = load_frage_messages()
    if message_id in frage_messages:
        frage_emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
        if emoji_str in frage_emojis:
            votes = load_memes_votes()
            if message_id not in votes:
                votes[message_id] = {}
            
            user_str = str(payload.user_id)
            option_index = frage_emojis.index(emoji_str)
            old_vote = votes[message_id].get(user_str)
            
            if old_vote is not None and old_vote != option_index:
                old_emoji = frage_emojis[old_vote]
                try:
                    await bot.http.remove_reaction(payload.channel_id, payload.message_id, old_emoji, payload.user_id)
                except:
                    pass
            
            votes[message_id][user_str] = option_index
            save_memes_votes(votes)
            
            config = load_fragen_config()
            results_msg_id = None
            display_mode = "embed"
            for gid, cfg in config.items():
                if cfg.get("last_message_id") == message_id:
                    results_msg_id = cfg.get("last_results_id")
                    display_mode = cfg.get("display_mode", "embed")
                    break
            
            if results_msg_id:
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    try:
                        results_text = build_results_text(message_id, display_mode)
                        results_msg = await channel.fetch_message(int(results_msg_id))
                        await results_msg.edit(content=results_text)
                    except:
                        pass
            return
    
    if guild_id_str not in reaction_roles:
        return
    if message_id not in reaction_roles[guild_id_str]:
        return
    
    role_id = reaction_roles[guild_id_str][message_id]["roles"].get(emoji_str)
    if not role_id:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    if role in member.roles:
        return
    
    try:
        await member.add_roles(role, reason="Reaction Role")
    except discord.Forbidden:
        pass

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.user_id == bot.user.id:
        return
    
    reaction_roles = load_reaction_roles()
    guild_id_str = str(payload.guild_id)
    message_id = str(payload.message_id)
    emoji_str = str(payload.emoji)
    
    frage_messages = load_frage_messages()
    if message_id in frage_messages:
        frage_emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
        if emoji_str in frage_emojis:
            votes = load_memes_votes()
            if message_id in votes:
                user_str = str(payload.user_id)
                if user_str in votes[message_id]:
                    del votes[message_id][user_str]
                    save_memes_votes(votes)
                    
                    channel = bot.get_channel(payload.channel_id)
                    if channel:
                        config = load_fragen_config()
                        results_msg_id = None
                        display_mode = "embed"
                        for gid, cfg in config.items():
                            if cfg.get("last_message_id") == message_id:
                                results_msg_id = cfg.get("last_results_id")
                                display_mode = cfg.get("display_mode", "embed")
                                break
                        
                        if results_msg_id:
                            try:
                                results_text = build_results_text(message_id, display_mode)
                                results_msg = await channel.fetch_message(int(results_msg_id))
                                await results_msg.edit(content=results_text)
                            except:
                                pass
            return
    
    if guild_id_str not in reaction_roles:
        return
    if message_id not in reaction_roles[guild_id_str]:
        return
    
    role_id = reaction_roles[guild_id_str][message_id]["roles"].get(emoji_str)
    if not role_id:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    role = guild.get_role(role_id)
    if not role:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    if role not in member.roles:
        return
    
    try:
        await member.remove_roles(role, reason="Reaction Role")
    except discord.Forbidden:
        pass

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    
    custom_id = interaction.data.get("custom_id", "")
    
    if custom_id.startswith("rr_"):
        role_id = int(custom_id.split("_")[1])
        
        guild = interaction.guild
        if not guild:
            return
        
        role = guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("Rolle nicht gefunden!", ephemeral=True)
            return
        
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)
        
        if role in member.roles:
            try:
                await member.remove_roles(role, reason="Reaction Role Button")
                await interaction.response.send_message(f"**{role.name}** entfernt!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)
        else:
            try:
                await member.add_roles(role, reason="Reaction Role Button")
                await interaction.response.send_message(f"**{role.name}** hinzugefÃ¼gt!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

# =====================================
# MEMBER COUNT AUTO-UPDATE
# =====================================

@bot.event
async def on_member_join(member):
    await update_member_count_channels()

@bot.event
async def on_member_remove(member):
    await update_member_count_channels()

@tasks.loop(minutes=30)
@crash_resilient_task
async def membercount_refresh():
    await update_member_count_channels()

@membercount_refresh.before_loop
async def before_membercount_refresh():
    await bot.wait_until_ready()

# =====================================
# VOICE CHANNEL MANAGEMENT SYSTEM
# =====================================

VOICE_SETUP_FILE = DATA_DIR / "voice_setup.json"
VOICE_OWNERS_FILE = DATA_DIR / "voice_owners.json"
VOICE_SETTINGS_FILE = DATA_DIR / "voice_settings.json"
voice_channel_owners = {}
voice_channel_settings = {}

def load_voice_setup():
    if VOICE_SETUP_FILE.exists():
        with open(VOICE_SETUP_FILE, "r") as f:
            return json.load(f)
    return {}

def save_voice_setup(data):
    with open(VOICE_SETUP_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_voice_owners():
    if VOICE_OWNERS_FILE.exists():
        with open(VOICE_OWNERS_FILE, "r") as f:
            data = json.load(f)
            return {int(k): int(v) for k, v in data.items()}
    return {}

def save_voice_owners(data):
    with open(VOICE_OWNERS_FILE, "w") as f:
        json.dump({str(k): v for k, v in data.items()}, f, indent=2)

def load_voice_settings_file():
    if VOICE_SETTINGS_FILE.exists():
        with open(VOICE_SETTINGS_FILE, "r") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    return {}

def save_voice_settings_file(data):
    with open(VOICE_SETTINGS_FILE, "w") as f:
        json.dump({str(k): v for k, v in data.items()}, f, indent=2)

class VoiceChannelView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.channel_id = channel_id

    @discord.ui.button(label="Private", style=discord.ButtonStyle.danger, emoji="ðŸ”’", custom_id="vc_private")
    async def private_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        settings = voice_channel_settings.get(self.channel_id, {})
        is_private = settings.get("private", False)
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.connect = is_private
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        settings["private"] = not is_private
        voice_channel_settings[self.channel_id] = settings
        save_voice_settings_file(voice_channel_settings)
        
        button.label = "Public" if not is_private else "Private"
        button.emoji = "ðŸŒ" if not is_private else "ðŸ”’"
        
        status = "privat" if not is_private else "Ã¶ffentlich"
        await interaction.response.send_message(f"Channel ist jetzt {status}!", ephemeral=True)

    @discord.ui.button(label="Hide", style=discord.ButtonStyle.secondary, emoji="ðŸ‘ï¸", custom_id="vc_hide")
    async def hide_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        settings = voice_channel_settings.get(self.channel_id, {})
        is_hidden = settings.get("hidden", False)
        
        overwrites = channel.overwrites_for(interaction.guild.default_role)
        overwrites.view_channel = is_hidden
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        settings["hidden"] = not is_hidden
        voice_channel_settings[self.channel_id] = settings
        save_voice_settings_file(voice_channel_settings)
        
        button.label = "Show" if not is_hidden else "Hide"
        
        status = "versteckt" if not is_hidden else "sichtbar"
        await interaction.response.send_message(f"Channel ist jetzt {status}!", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, emoji="âœï¸", custom_id="vc_rename")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        await interaction.response.send_modal(RenameModal(self.channel_id))

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="ðŸ‘¢", custom_id="vc_kick")
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann Leute kicken!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        members_in_channel = [m for m in channel.members if m.id != self.owner_id]
        if not members_in_channel:
            await interaction.response.send_message("Niemand else im Channel!", ephemeral=True)
            return
        
        view = KickSelectView(self.owner_id, self.channel_id, members_in_channel)
        await interaction.response.send_message("WÃ¤hle wen du kicken mÃ¶chtest:", view=view, ephemeral=True)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="ðŸš«", custom_id="vc_ban")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        members_in_channel = [m for m in channel.members if m.id != self.owner_id]
        if not members_in_channel:
            await interaction.response.send_message("Niemand else im Channel!", ephemeral=True)
            return
        
        view = BanSelectView(self.owner_id, self.channel_id, members_in_channel)
        await interaction.response.send_message("Wen bannen:", view=view, ephemeral=True)

    @discord.ui.button(label="Invite", style=discord.ButtonStyle.success, emoji="ðŸ”—", custom_id="vc_invite")
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            "Teile den Server-Invite mit Leuten die joinen sollen!",
            ephemeral=True
        )

    @discord.ui.button(label="Permit", style=discord.ButtonStyle.success, emoji="âœ…", custom_id="vc_permit")
    async def permit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        view = PermitSelectView(self.owner_id, self.channel_id)
        await interaction.response.send_message("Wem Zugriff geben:", view=view, ephemeral=True)

    @discord.ui.button(label="Change Owner", style=discord.ButtonStyle.primary, emoji="ðŸ‘‘", custom_id="vc_changeowner")
    async def change_owner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der aktuelle Besitzer kann das!", ephemeral=True)
            return
        
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        members_in_channel = [m for m in channel.members if m.id != self.owner_id]
        if not members_in_channel:
            await interaction.response.send_message("Niemand else im Channel!", ephemeral=True)
            return
        
        view = OwnerSelectView(self.owner_id, self.channel_id, members_in_channel)
        await interaction.response.send_message("WÃ¤hle den neuen Besitzer:", view=view, ephemeral=True)

class RenameModal(discord.ui.Modal, title="Channel umbenennen"):
    new_name = discord.ui.TextInput(label="Neuer Name", placeholder="Mein Chat", max_length=50)
    
    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id
    
    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        try:
            await channel.edit(name=self.new_name.value)
            await interaction.response.send_message(f"Channel umbenannt in **{self.new_name.value}**!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

class OwnerSelect(discord.ui.Select):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        self.owner_id = owner_id
        self.channel_id = channel_id
        
        options = [
            discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                emoji="ðŸ‘‘"
            ) for m in members[:25]
        ]
        
        super().__init__(placeholder="WÃ¤hle den neuen Besitzer...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        target_id = int(self.values[0])
        channel = interaction.guild.get_channel(self.channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        target_member = interaction.guild.get_member(target_id)
        if not target_member:
            await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
            return
        
        if target_member not in channel.members:
            await interaction.response.send_message("Der User ist nicht im Channel!", ephemeral=True)
            return
        
        voice_channel_owners[self.channel_id] = target_id
        save_voice_owners(voice_channel_owners)
        
        overwrites = channel.overwrites_for(target_member)
        overwrites.update(
            view_channel=True,
            connect=True,
            speak=True,
            move_members=True,
            manage_channels=True,
            manage_permissions=True,
            priority_speaker=True
        )
        await channel.set_permissions(target_member, overwrite=overwrites)
        
        old_overwrites = channel.overwrites_for(interaction.user)
        old_overwrites.update(
            move_members=False,
            manage_channels=False,
            manage_permissions=False,
            priority_speaker=False
        )
        await channel.set_permissions(interaction.user, overwrite=old_overwrites)
        
        embed, view = await create_voice_control_embed(target_member, channel)
        await channel.send(embed=embed, view=view)
        
        await interaction.response.send_message(f"Besitz an {target_member.display_name} Ã¼bertragen!", ephemeral=True)

class OwnerSelectView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        super().__init__(timeout=60)
        self.add_item(OwnerSelect(owner_id, channel_id, members))

class KickSelect(discord.ui.Select):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        self.owner_id = owner_id
        self.channel_id = channel_id
        
        options = [
            discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                emoji="ðŸ‘¢"
            ) for m in members[:25]
        ]
        
        super().__init__(placeholder="WÃ¤hle wen du kicken mÃ¶chtest...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann kicken!", ephemeral=True)
            return
        
        target_id = int(self.values[0])
        channel = interaction.guild.get_channel(self.channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        target_member = interaction.guild.get_member(target_id)
        if not target_member:
            await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
            return
        
        try:
            await target_member.move_to(None, reason=f"Gekickt von {interaction.user.display_name}")
            await interaction.response.send_message(f"{target_member.display_name} wurde gekickt!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

class KickSelectView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        super().__init__(timeout=60)
        self.add_item(KickSelect(owner_id, channel_id, members))

class BanSelect(discord.ui.Select):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        self.owner_id = owner_id
        self.channel_id = channel_id
        
        options = [
            discord.SelectOption(
                label=m.display_name,
                value=str(m.id),
                emoji="ðŸš«"
            ) for m in members[:25]
        ]
        
        super().__init__(placeholder="Wen bannen...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann bannen!", ephemeral=True)
            return
        
        target_id = int(self.values[0])
        channel = interaction.guild.get_channel(self.channel_id)
        
        if not channel:
            await interaction.response.send_message("Channel nicht gefunden!", ephemeral=True)
            return
        
        target_member = interaction.guild.get_member(target_id)
        if not target_member:
            await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
            return
        
        try:
            overwrites = channel.overwrites_for(target_member)
            overwrites.connect = False
            await channel.set_permissions(target_member, overwrite=overwrites)
            await target_member.move_to(None, reason=f"Gebannt von {interaction.user.display_name}")
            await interaction.response.send_message(f"{target_member.display_name} wurde gebannt!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

class BanSelectView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int, members: list):
        super().__init__(timeout=60)
        self.add_item(BanSelect(owner_id, channel_id, members))

class PermitSelect(discord.ui.Select):
    def __init__(self, owner_id: int, channel_id: int):
        self.owner_id = owner_id
        self.channel_id = channel_id
        
        super().__init__(placeholder="User ID eingeben...", min_values=1, max_values=1, options=[
            discord.SelectOption(label="ID eingeben", value="manual", description="Schreib die User ID in Chat")
        ])
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            "Schreib die User ID die du permiten mÃ¶chtest (nur Zahlen):",
            ephemeral=True
        )

class PermitSelectView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=60)
        self.add_item(PermitSelect(owner_id, channel_id))

async def create_voice_control_embed(member, channel):
    embed = discord.Embed(
        title=f"{member.display_name}'s Private Chat",
        description=(
            f"Willkommen {member.mention}!\n"
            f"Der Channel wird gelÃ¶scht wenn alle gehen."
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Nutze die Buttons um deinen Channel zu verwalten.")
    
    view = VoiceChannelView(member.id, channel.id)
    return embed, view

@bot.tree.command(name="voicesetup", description="Voice Channel Management System einrichten")
@is_admin_or_owner()
async def voicesetup(interaction: discord.Interaction):
    guild = interaction.guild
    
    category = await guild.create_category("Private Chats")
    
    lobby_overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            manage_channels=True,
            move_members=True
        )
    }
    
    lobby = await guild.create_voice_channel(
        "âž• Join to Create",
        category=category,
        overwrites=lobby_overwrites
    )
    
    setup_data = load_voice_setup()
    setup_data[str(guild.id)] = {
        "category_id": category.id,
        "lobby_id": lobby.id
    }
    save_voice_setup(setup_data)
    
    embed = discord.Embed(
        title="Voice Channel System",
        description=(
            f"Betritt den {lobby.mention} Channel!\n"
            f"Es wird automatisch ein privater Channel fÃ¼r dich erstellt.\n"
            f"Du bekommst Buttons zum Verwalten deines Channels."
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="vc_kick", description="User aus deinem Voice Channel kicken")
async def vc_kick(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("UngÃ¼ltige User ID!", ephemeral=True)
        return
    
    owner_channel = None
    for channel_id, owner in voice_channel_owners.items():
        if owner == interaction.user.id:
            owner_channel = interaction.guild.get_channel(channel_id)
            break
    
    if not owner_channel:
        await interaction.response.send_message("Du hast keinen eigenen Voice Channel!", ephemeral=True)
        return
    
    target_member = interaction.guild.get_member(target_id)
    if not target_member:
        await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
        return
    
    if target_member not in owner_channel.members:
        await interaction.response.send_message("Dieser User ist nicht in deinem Channel!", ephemeral=True)
        return
    
    try:
        await target_member.move_to(None, reason=f"Gekickt von {interaction.user.display_name}")
        await interaction.response.send_message(f"{target_member.display_name} wurde gekickt!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

@bot.tree.command(name="vc_ban", description="User aus deinem Voice Channel bannen")
async def vc_ban(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("UngÃ¼ltige User ID!", ephemeral=True)
        return
    
    owner_channel = None
    for channel_id, owner in voice_channel_owners.items():
        if owner == interaction.user.id:
            owner_channel = interaction.guild.get_channel(channel_id)
            break
    
    if not owner_channel:
        await interaction.response.send_message("Du hast keinen eigenen Voice Channel!", ephemeral=True)
        return
    
    target_member = interaction.guild.get_member(target_id)
    if not target_member:
        await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
        return
    
    try:
        overwrites = owner_channel.overwrites_for(target_member)
        overwrites.connect = False
        await owner_channel.set_permissions(target_member, overwrite=overwrites)
        await target_member.move_to(None, reason=f"Gebannt von {interaction.user.display_name}")
        await interaction.response.send_message(f"{target_member.display_name} wurde gebannt!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

@bot.tree.command(name="vc_permit", description="User Zugriff auf deinen Channel geben")
async def vc_permit(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("UngÃ¼ltige User ID!", ephemeral=True)
        return
    
    owner_channel = None
    for channel_id, owner in voice_channel_owners.items():
        if owner == interaction.user.id:
            owner_channel = interaction.guild.get_channel(channel_id)
            break
    
    if not owner_channel:
        await interaction.response.send_message("Du hast keinen eigenen Voice Channel!", ephemeral=True)
        return
    
    target_member = interaction.guild.get_member(target_id)
    if not target_member:
        await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
        return
    
    try:
        overwrites = owner_channel.overwrites_for(target_member)
        overwrites.connect = True
        overwrites.view_channel = True
        await owner_channel.set_permissions(target_member, overwrite=overwrites)
        await interaction.response.send_message(f"{target_member.display_name} hat jetzt Zugriff!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

@bot.tree.command(name="vc_changeowner", description="Channel Besitz Ã¼bertragen")
async def vc_changeowner(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("UngÃ¼ltige User ID!", ephemeral=True)
        return
    
    old_owner_channel = None
    old_channel_id = None
    for channel_id, owner in voice_channel_owners.items():
        if owner == interaction.user.id:
            old_owner_channel = interaction.guild.get_channel(channel_id)
            old_channel_id = channel_id
            break
    
    if not old_owner_channel:
        await interaction.response.send_message("Du hast keinen eigenen Voice Channel!", ephemeral=True)
        return
    
    target_member = interaction.guild.get_member(target_id)
    if not target_member:
        await interaction.response.send_message("User nicht gefunden!", ephemeral=True)
        return
    
    if target_member not in old_owner_channel.members:
        await interaction.response.send_message("Der User ist nicht im Channel!", ephemeral=True)
        return
    
    voice_channel_owners[old_channel_id] = target_id
    save_voice_owners(voice_channel_owners)
    
    overwrites = old_owner_channel.overwrites_for(target_member)
    overwrites.update(
        view_channel=True,
        connect=True,
        speak=True,
        move_members=True,
        manage_channels=True,
        manage_permissions=True,
        priority_speaker=True
    )
    await old_owner_channel.set_permissions(target_member, overwrite=overwrites)
    
    old_overwrites = old_owner_channel.overwrites_for(interaction.user)
    old_overwrites.update(
        move_members=False,
        manage_channels=False,
        manage_permissions=False,
        priority_speaker=False
    )
    await old_owner_channel.set_permissions(interaction.user, overwrite=old_overwrites)
    
    embed, view = await create_voice_control_embed(target_member, old_owner_channel)
    await old_owner_channel.send(embed=embed, view=view)
    
    await interaction.response.send_message(f"Besitz an {target_member.display_name} Ã¼bertragen!", ephemeral=True)

# =====================================
# LEVEL SYSTEM
# =====================================

LEVEL_DATA_FILE = DATA_DIR / "levels.json"
LEVEL_CONFIG_FILE = DATA_DIR / "level_config.json"
LEVEL_IMAGES_DIR = DATA_DIR / "level_images"
LEVEL_IMAGES_DIR.mkdir(exist_ok=True)
LEADERBOARD_MSG_FILE = DATA_DIR / "leaderboard_messages.json"

voice_start_times = {}
leaderboard_message_ids = {}

def load_level_data():
    if LEVEL_DATA_FILE.exists():
        with open(LEVEL_DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_level_data(data):
    with open(LEVEL_DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_level_config():
    if LEVEL_CONFIG_FILE.exists():
        with open(LEVEL_CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_level_config(data):
    with open(LEVEL_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_leveling_enabled(guild_id):
    config = load_level_config()
    guild_str = str(guild_id)
    return config.get(guild_str, {}).get("leveling_enabled", False)

def load_leaderboard_messages():
    if LEADERBOARD_MSG_FILE.exists():
        with open(LEADERBOARD_MSG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_leaderboard_messages(data):
    with open(LEADERBOARD_MSG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_xp_for_level(level):
    return 5 * (level ** 2) + 50 * level + 100

def get_user_data(guild_id, user_id):
    data = load_level_data()
    guild_str = str(guild_id)
    user_str = str(user_id)
    if guild_str not in data:
        data[guild_str] = {}
    if user_str not in data[guild_str]:
        data[guild_str][user_str] = {
            "xp": 0,
            "level": 0,
            "messages": {},
            "voice_seconds": 0,
            "voice_daily": {}
        }
    if "messages" not in data[guild_str][user_str]:
        data[guild_str][user_str]["messages"] = {}
    if "voice_daily" not in data[guild_str][user_str]:
        data[guild_str][user_str]["voice_daily"] = {}
    return data[guild_str][user_str]

def today_str():
    return discord.utils.utcnow().strftime("%Y-%m-%d")

def add_xp(guild_id, user_id, amount):
    data = load_level_data()
    guild_str = str(guild_id)
    user_str = str(user_id)
    today = today_str()

    if guild_str not in data:
        data[guild_str] = {}
    if user_str not in data[guild_str]:
        data[guild_str][user_str] = {
            "xp": 0, "level": 0, "messages": {}, "voice_seconds": 0, "voice_daily": {}
        }

    user_data = data[guild_str][user_str]
    if "messages" not in user_data:
        user_data["messages"] = {}
    if "voice_daily" not in user_data:
        user_data["voice_daily"] = {}

    user_data["xp"] += amount
    user_data["messages"][today] = user_data["messages"].get(today, 0) + 1

    old_level = user_data["level"]
    xp_needed = get_xp_for_level(user_data["level"])

    while user_data["xp"] >= xp_needed:
        user_data["xp"] -= xp_needed
        user_data["level"] += 1
        xp_needed = get_xp_for_level(user_data["level"])

    new_level = user_data["level"]
    save_level_data(data)
    return old_level, new_level

def format_time_short(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    else:
        return f"{minutes}m"

def format_time_full(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

@bot.event
async def on_message_level_system(message):
    if message.author.bot:
        return
    if not message.guild:
        return

    if not is_leveling_enabled(message.guild.id):
        return

    config = load_level_config()
    guild_str = str(message.guild.id)

    no_xp_channels = config.get(guild_str, {}).get("no_xp_channels", [])
    if message.channel.id in no_xp_channels:
        return

    old_level, new_level = add_xp(message.guild.id, message.author.id, 15)

    if new_level > old_level:
        level_config = config.get(guild_str, {})
        level_channel_id = level_config.get("level_channel")
        level_images = level_config.get("level_images", {})
        images_enabled = level_config.get("level_images_enabled", True)
        image_path = level_images.get(str(new_level)) if images_enabled else None

        embed = discord.Embed(
            title="Level Up!",
            description=f"{message.author.mention} ist jetzt **Level {new_level}**!",
            color=discord.Color.gold()
        )

        if image_path and os.path.exists(image_path):
            file = discord.File(image_path, filename=f"level_{new_level}.png")
            embed.set_image(url=f"attachment://level_{new_level}.png")

            if level_channel_id:
                channel = bot.get_channel(level_channel_id)
                if channel:
                    await channel.send(content=f"{message.author.mention}", embed=embed, file=file)
            else:
                await message.channel.send(content=f"{message.author.mention}", embed=embed, file=file)
        else:
            if level_channel_id:
                channel = bot.get_channel(level_channel_id)
                if channel:
                    await channel.send(content=f"{message.author.mention}", embed=embed)
            else:
                await message.channel.send(content=f"{message.author.mention}", embed=embed)

@bot.event
async def on_voice_state_update_level(member, before, after):
    if member.bot:
        return

    guild_str = str(member.guild.id)
    user_str = str(member.id)
    today = today_str()

    if before.channel and not after.channel:
        if member.id in voice_start_times:
            start_time = voice_start_times.pop(member.id)
            elapsed = int(time.time() - start_time)

            data = load_level_data()
            if guild_str not in data:
                data[guild_str] = {}
            if user_str not in data[guild_str]:
                data[guild_str][user_str] = {
                    "xp": 0, "level": 0, "messages": {}, "voice_seconds": 0, "voice_daily": {}
                }

            user_data = data[guild_str][user_str]
            if "voice_daily" not in user_data:
                user_data["voice_daily"] = {}

            user_data["voice_seconds"] = user_data.get("voice_seconds", 0) + elapsed
            user_data["voice_daily"][today] = user_data["voice_daily"].get(today, 0) + elapsed
            save_level_data(data)

    elif not before.channel and after.channel:
        if member.id not in voice_start_times:
            voice_start_times[member.id] = time.time()

    elif before.channel and after.channel and before.channel.id != after.channel.id:
        if member.id in voice_start_times:
            start_time = voice_start_times.pop(member.id)
            elapsed = int(time.time() - start_time)

            data = load_level_data()
            if guild_str not in data:
                data[guild_str] = {}
            if user_str not in data[guild_str]:
                data[guild_str][user_str] = {
                    "xp": 0, "level": 0, "messages": {}, "voice_seconds": 0, "voice_daily": {}
                }

            user_data = data[guild_str][user_str]
            if "voice_daily" not in user_data:
                user_data["voice_daily"] = {}

            user_data["voice_seconds"] = user_data.get("voice_seconds", 0) + elapsed
            user_data["voice_daily"][today] = user_data["voice_daily"].get(today, 0) + elapsed
            save_level_data(data)

            voice_start_times[member.id] = time.time()

@bot.tree.command(name="level", description="Zeigt dein aktuelles Level und XP an")
async def level_command(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    user_data = get_user_data(interaction.guild_id, target.id)

    xp_needed = get_xp_for_level(user_data["level"])
    progress = user_data["xp"] / xp_needed * 100 if xp_needed > 0 else 0

    bar_length = 20
    filled = int(bar_length * progress / 100)
    bar = "â–ˆ" * filled + "â–‘" * (bar_length - filled)

    embed = discord.Embed(
        title=f"Level von {target.display_name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Level", value=str(user_data["level"]), inline=True)
    embed.add_field(name="XP", value=f"{user_data['xp']}/{xp_needed}", inline=True)
    embed.add_field(name="Fortschritt", value=f"`{bar}` {progress:.1f}%", inline=False)
    total_msgs = sum(user_data.get("messages", {}).values())
    embed.add_field(name="Nachrichten", value=str(total_msgs), inline=True)
    embed.add_field(name="Voice-Zeit", value=format_time_full(user_data.get("voice_seconds", 0)), inline=True)

    await interaction.response.send_message(embed=embed)

def build_leaderboard_embeds(guild):
    guild_str = str(guild.id)
    data = load_level_data()

    messages_ranking = []
    voice_ranking = []

    if guild_str in data:
        for user_id, user_data in data[guild_str].items():
            member = guild.get_member(int(user_id))
            if not member or member.bot:
                continue

            msgs_total = sum(user_data.get("messages", {}).values())
            voice_total = user_data.get("voice_seconds", 0)

            if msgs_total > 0:
                messages_ranking.append((member, msgs_total))
            if voice_total > 0:
                voice_ranking.append((member, voice_total))

    messages_ranking.sort(key=lambda x: x[1], reverse=True)
    voice_ranking.sort(key=lambda x: x[1], reverse=True)

    medals = ["", "", ""]

    msg_lines = []
    for i, (member, count) in enumerate(messages_ranking[:15]):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        msg_lines.append(f"{medal} {member.mention} â€” **{count:,}** messages")

    voice_lines = []
    for i, (member, seconds) in enumerate(voice_ranking[:15]):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        voice_lines.append(f"{medal} {member.mention} â€” **{format_time_short(seconds)}**")

    top_msg_user = messages_ranking[0][0].mention if messages_ranking else "Keine Daten"
    top_voice_user = voice_ranking[0][0].display_name if voice_ranking else "Keine Daten"

    embed_messages = discord.Embed(
        title=f"{guild.name} Leaderboard",
        description=f" Top Messages (Lifetime) â€” {top_msg_user}",
        color=discord.Color.red()
    )
    embed_messages.description += "\n\n**Rankings**\n"
    if msg_lines:
        embed_messages.description += "\n".join(msg_lines)
    else:
        embed_messages.description += "Noch keine Nachrichten getrackt."

    embed_voice = discord.Embed(
        title=f"{guild.name} Leaderboard",
        description=f" Top Voice Time (Lifetime) â€” {top_voice_user}",
        color=discord.Color.blue()
    )
    embed_voice.description += "\n\n**Rankings**\n"
    if voice_lines:
        embed_voice.description += "\n".join(voice_lines)
    else:
        embed_voice.description += "Noch keine Voice-Zeit getrackt."

    return embed_messages, embed_voice

@bot.tree.command(name="leaderboard", description="Zeigt das Leaderboard an")
async def leaderboard_command(interaction: discord.Interaction):
    embed_msg, embed_voice = build_leaderboard_embeds(interaction.guild)
    await interaction.response.send_message(embeds=[embed_msg, embed_voice])

@bot.tree.command(name="setlevelchannel", description="Setzt den Channel fÃ¼r Level-Up Nachrichten")
@is_admin_or_owner()
@app_commands.describe(channel="Der Channel fÃ¼r Level-Up Nachrichten")
async def setlevelchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}
    config[guild_str]["level_channel"] = channel.id
    save_level_config(config)
    await interaction.response.send_message(f"Level-Up Channel gesetzt auf {channel.mention}!")

@bot.tree.command(name="setleaderboard", description="Richtet das Live-Leaderboard in einem Channel ein")
@is_admin_or_owner()
@app_commands.describe(channel="Der Channel fÃ¼r das Leaderboard")
async def setleaderboard_command(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)

    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}
    config[guild_str]["leaderboard_channel"] = channel.id
    save_level_config(config)

    embed_msg, embed_voice = build_leaderboard_embeds(interaction.guild)

    msg_sent = await channel.send(embed=embed_msg)
    voice_sent = await channel.send(embed=embed_voice)

    lb_msgs = load_leaderboard_messages()
    lb_msgs[guild_str] = {
        "messages_msg_id": msg_sent.id,
        "voice_msg_id": voice_sent.id,
        "channel_id": channel.id
    }
    save_leaderboard_messages(lb_msgs)

    await interaction.followup.send(
        f"Live-Leaderboard eingerichtet in {channel.mention}!\n"
        f"Updatet alle 15 Sekunden automatisch.",
        ephemeral=True
    )

@bot.tree.command(name="leaderboardrefresh", description="Loescht alte Leaderboard-Embeds und sendet neue")
@is_admin_or_owner()
async def leaderboardrefresh_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    lb_msgs = load_leaderboard_messages()
    guild_str = str(interaction.guild_id)

    if guild_str in lb_msgs:
        old = lb_msgs[guild_str]
        channel = bot.get_channel(old.get("channel_id", 0))
        if channel:
            try:
                msg = await channel.fetch_message(old["messages_msg_id"])
                await msg.delete()
            except:
                pass
            try:
                msg = await channel.fetch_message(old["voice_msg_id"])
                await msg.delete()
            except:
                pass
        del lb_msgs[guild_str]
        save_leaderboard_messages(lb_msgs)

    config = load_level_config()
    leaderboard_channel_id = config.get(guild_str, {}).get("leaderboard_channel")
    if not leaderboard_channel_id:
        await interaction.followup.send("Kein Leaderboard-Channel gesetzt! Benutze zuerst /setleaderboard", ephemeral=True)
        return

    channel = bot.get_channel(leaderboard_channel_id)
    if not channel:
        await interaction.followup.send("Channel nicht gefunden!", ephemeral=True)
        return

    embed_msg, embed_voice = build_leaderboard_embeds(interaction.guild)
    msg_sent = await channel.send(embed=embed_msg)
    voice_sent = await channel.send(embed=embed_voice)

    lb_msgs = load_leaderboard_messages()
    lb_msgs[guild_str] = {
        "messages_msg_id": msg_sent.id,
        "voice_msg_id": voice_sent.id,
        "channel_id": channel.id
    }
    save_leaderboard_messages(lb_msgs)

    await interaction.followup.send(f"Leaderboard refreshed in {channel.mention}!", ephemeral=True)

@bot.tree.command(name="levelimage", description="Setzt ein Bild fuer einen bestimmten Levelaufstieg")
@is_admin_or_owner()
@app_commands.describe(level="Das Level (z.B. 5)", bild="Das Bild fÃ¼r diesen Level")
async def levelimage_command(interaction: discord.Interaction, level: int, bild: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    allowed_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    if not any(bild.filename.lower().endswith(ext) for ext in allowed_exts):
        await interaction.followup.send("Nur Bilddateien erlaubt!", ephemeral=True)
        return

    image_data = await bild.read()
    if len(image_data) > 8 * 1024 * 1024:
        await interaction.followup.send("Bild ist zu groÃŸ (max 8MB)!", ephemeral=True)
        return

    filename = f"level_{level}.png"
    filepath = LEVEL_IMAGES_DIR / filename

    with open(filepath, "wb") as f:
        f.write(image_data)

    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}
    if "level_images" not in config[guild_str]:
        config[guild_str]["level_images"] = {}

    config[guild_str]["level_images"][str(level)] = str(filepath)
    save_level_config(config)

    await interaction.followup.send(f"Bild fÃ¼r Level **{level}** gespeichert!", ephemeral=True)

@bot.tree.command(name="noxpchannel", description="Toggle: Kein XP in diesem Channel")
@is_admin_or_owner()
async def noxpchannel_command(interaction: discord.Interaction):
    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}

    no_xp_channels = config[guild_str].get("no_xp_channels", [])

    if interaction.channel_id in no_xp_channels:
        no_xp_channels.remove(interaction.channel_id)
        state = "entfernt"
        icon = "âŒ"
    else:
        no_xp_channels.append(interaction.channel_id)
        state = "hinzugefÃ¼gt"
        icon = "âœ…"

    config[guild_str]["no_xp_channels"] = no_xp_channels
    save_level_config(config)
    await interaction.response.send_message(f"{icon} Dieser Channel wurde {state} (kein XP)")

@bot.tree.command(name="toggleleveling", description="Toggle: Level-System komplett ein/ausschalten")
@is_admin_or_owner()
async def toggleleveling_command(interaction: discord.Interaction):
    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}

    current = config[guild_str].get("leveling_enabled", True)
    config[guild_str]["leveling_enabled"] = not current
    save_level_config(config)

    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    await interaction.response.send_message(f"{icon} Level-System: **{state}**")

@bot.tree.command(name="togglelevelimage", description="Toggle: Bilder bei Level-Up ein/ausschalten")
@is_admin_or_owner()
async def togglelevelimage_command(interaction: discord.Interaction):
    config = load_level_config()
    guild_str = str(interaction.guild_id)
    if guild_str not in config:
        config[guild_str] = {}

    current = config[guild_str].get("level_images_enabled", True)
    config[guild_str]["level_images_enabled"] = not current
    save_level_config(config)

    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    await interaction.response.send_message(f"{icon} Level-Up Bilder: **{state}**")

@bot.tree.command(name="resetlevels", description="Setzt alle Level-Daten zurÃ¼ck")
@is_admin_or_owner()
async def resetlevels_command(interaction: discord.Interaction):
    data = load_level_data()
    guild_str = str(interaction.guild_id)
    if guild_str in data:
        del data[guild_str]
        save_level_data(data)
    await interaction.response.send_message("Alle Level-Daten fÃ¼r diesen Server zurÃ¼ckgesetzt!")

@bot.tree.command(name="setlevel", description="Setzt das Level eines Users manuell")
@is_admin_or_owner()
@app_commands.describe(user="Der User", level="Das neue Level")
async def setlevel_command(interaction: discord.Interaction, user: discord.Member, level: int):
    data = load_level_data()
    guild_str = str(interaction.guild_id)
    user_str = str(user.id)

    if guild_str not in data:
        data[guild_str] = {}

    old = data[guild_str].get(user_str, {})
    data[guild_str][user_str] = {
        "xp": 0,
        "level": level,
        "messages": old.get("messages", {}),
        "voice_seconds": old.get("voice_seconds", 0),
        "voice_daily": old.get("voice_daily", {})
    }
    save_level_data(data)
    await interaction.response.send_message(f"Level von {user.mention} auf **{level}** gesetzt!")

@tasks.loop(seconds=15)
@crash_resilient_task
async def update_live_leaderboard():
    lb_msgs = load_leaderboard_messages()

    for guild in bot.guilds:
        guild_str = str(guild.id)
        if guild_str not in lb_msgs:
            continue

        lb_data = lb_msgs[guild_str]
        channel_id = lb_data.get("channel_id")
        messages_msg_id = lb_data.get("messages_msg_id")
        voice_msg_id = lb_data.get("voice_msg_id")

        if not channel_id:
            continue

        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        embed_msg, embed_voice = build_leaderboard_embeds(guild)

        try:
            msg_msg = await channel.fetch_message(messages_msg_id)
            await msg_msg.edit(embed=embed_msg)
        except:
            try:
                new_msg = await channel.send(embed=embed_msg)
                lb_data["messages_msg_id"] = new_msg.id
            except:
                pass

        try:
            voice_msg = await channel.fetch_message(voice_msg_id)
            await voice_msg.edit(embed=embed_voice)
        except:
            try:
                new_msg = await channel.send(embed=embed_voice)
                lb_data["voice_msg_id"] = new_msg.id
            except:
                pass

    save_leaderboard_messages(lb_msgs)


# =====================================
# LEVEL SYSTEM
@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user}")
    
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} Commands synchronisiert")
    except Exception as e:
        print(f"Sync fehlgeschlagen: {e}")
    
    global tiktok_mode
    try:
        tiktok_mode = load_tiktok_mode()
    except Exception as e:
        print(f"[on_ready] TikTok Mode Fehler: {e}")
    
    global automod_config
    try:
        automod_config = load_automod_config()
    except Exception as e:
        print(f"[on_ready] Automod Config Fehler: {e}")
    
    global voice_channel_owners, voice_channel_settings
    try:
        voice_channel_owners = load_voice_owners()
        voice_channel_settings = load_voice_settings_file()
        print(f"[on_ready] Voice Owners geladen: {len(voice_channel_owners)} Channels")
    except Exception as e:
        print(f"[on_ready] Voice Owners Fehler: {e}")
    
    try:
        if not update_live_leaderboard.is_running():
            update_live_leaderboard.start()
            print("[on_ready] Leaderboard gestartet")
    except Exception as e:
        print(f"[on_ready] Leaderboard Fehler: {e}")
    
    try:
        if not auto_save_data.is_running():
            auto_save_data.start()
            print("[on_ready] AutoSave gestartet")
    except Exception as e:
        print(f"[on_ready] AutoSave Fehler: {e}")
    
    try:
        if not membercount_refresh.is_running():
            membercount_refresh.start()
            print("[on_ready] MemberCount Refresh gestartet")
    except Exception as e:
        print(f"[on_ready] MemberCount Refresh Fehler: {e}")
    
    try:
        if not watchdog_task.is_running():
            watchdog_task.start()
            print("[on_ready] Watchdog gestartet")
    except Exception as e:
        print(f"[on_ready] Watchdog Fehler: {e}")
    
    try:
        if not daily_config_backup.is_running():
            daily_config_backup.start()
            print("[on_ready] Daily Config Backup gestartet")
    except Exception as e:
        print(f"[on_ready] Daily Backup Fehler: {e}")
    
    try:
        if not health_monitor.is_running():
            health_monitor.start()
            print("[on_ready] Health Monitor gestartet")
    except Exception as e:
        print(f"[on_ready] Health Monitor Fehler: {e}")
    
    try:
        memes_config = load_memes_config()
        for guild_str, settings in memes_config.items():
            if settings.get("enabled", False):
                if not auto_memes_task.is_running():
                    interval_minutes = settings.get("interval_minutes", 60)
                    auto_memes_task.change_interval(minutes=interval_minutes)
                    auto_memes_task.start()
                    print(f"[on_ready] Memes Task gestartet ({interval_minutes} Min)")
                    break
    except Exception as e:
        print(f"[on_ready] Memes Task Fehler: {e}")
    
    try:
        fragen_config = load_fragen_config()
        for guild_str, settings in fragen_config.items():
            if settings.get("enabled", False):
                if not auto_frage_task.is_running():
                    interval_minutes = settings.get("interval_minutes", 960)
                    auto_frage_task.change_interval(minutes=interval_minutes)
                    auto_frage_task.start()
                    print(f"[on_ready] Frage Task gestartet ({interval_minutes} Min)")
                    break
    except Exception as e:
        print(f"[on_ready] Frage Task Fehler: {e}")
    
    global recovery
    try:
        recovery = RecoveryManager(bot)
        await recovery.startup_sequence()
    except Exception as e:
        print(f"[Recovery] Fehler: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[on_ready] ALLE SYSTEME AKTIV!")

def save_all_configs_to_disk():
    """Speichert ALLE In-Memory-Configs auf Disk - vor jedem Git-Push"""
    try:
        save_tiktok_mode(tiktok_mode)
    except: pass
    try:
        save_automod_config(automod_config)
    except: pass
    try:
        save_voice_owners(voice_channel_owners)
    except: pass
    try:
        save_voice_settings_file(voice_channel_settings)
    except: pass
    try:
        # Memes Config wird direkt bei Commands gespeichert, aber zur Sicherheit nochmal
        pass
    except: pass
    try:
        # Frag Config wird direkt bei Commands gespeichert
        pass
    except: pass
    try:
        save_reaction_roles(load_reaction_roles())
    except: pass
    try:
        save_level_data(load_level_data())
    except: pass
    try:
        save_level_config(load_level_config())
    except: pass
    try:
        save_membercount_config(load_membercount_config())
    except: pass
    try:
        save_ticket_config(load_ticket_config())
    except: pass
    try:
        save_ticket_data(load_ticket_data())
    except: pass
    try:
        save_frage_messages(load_frage_messages())
    except: pass
    try:
        save_memes_votes(load_memes_votes())
    except: pass
    print("[ConfigSave] Alle In-Memory-Configs auf Disk geschrieben")

@tasks.loop(minutes=5)
@crash_resilient_task
async def auto_save_data():
    save_all_configs_to_disk()
    
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "data/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--cached", "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        
        if proc.returncode != 0:
            proc = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", "auto-save: data backup",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            
            proc = await asyncio.create_subprocess_exec(
                "git", "push",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            print("[AutoSave] Data backup pushed")
    except FileNotFoundError:
        print("[AutoSave] git nicht verfuegbar - Ã¼bersprungen")
    except Exception as e:
        print(f"[AutoSave] Fehler: {e}")

@auto_save_data.before_loop
async def before_auto_save():
    await bot.wait_until_ready()

# =====================================
# DAILY CONFIG BACKUP (zusÃ¤tzlich zu auto_save)
# =====================================

@tasks.loop(hours=24)
@crash_resilient_task
async def daily_config_backup():
    """TÃ¤gliches Config-Backup mit Timestamp"""
    from datetime import datetime as _dt
    timestamp = _dt.now().strftime("%Y-%m-%d_%H-%M")
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    
    config_files = [
        "tiktok_mode.json", "automod.json", "voice_owners.json",
        "voice_settings.json", "voice_setup.json", "memes_config.json",
        "fragen_config.json", "fragen_messages.json", "fragen_custom.json",
        "reaction_roles.json", "memes_votes.json", "levels.json",
        "level_config.json", "membercount_config.json",
        "ticket_config.json", "tickets.json"
    ]
    
    saved = 0
    for fname in config_files:
        src = DATA_DIR / fname
        if src.exists():
            dst = backup_dir / f"{fname.replace('.json', '')}_{timestamp}.json"
            try:
                import shutil
                shutil.copy2(src, dst)
                saved += 1
            except: pass
    
    # Alte Backups lÃ¶schen (nur letzte 7 behalten pro Datei)
    for fname in config_files:
        base = fname.replace('.json', '')
        backups = sorted(backup_dir.glob(f"{base}_*.json"))
        if len(backups) > 7:
            for old in backups[:-7]:
                old.unlink(missing_ok=True)
    
    print(f"[DailyBackup] {saved} Configs gesichert ({timestamp})")

@daily_config_backup.before_loop
async def before_daily_backup():
    await bot.wait_until_ready()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    try:
        if message.guild:
            await check_automod_invite_spam(message)
    except Exception as e:
        print(f"[Automod] Fehler: {e}")
    
    tiktok_mode_data = load_tiktok_mode()
    guild_id_str = str(message.guild.id) if message.guild else None
    
    has_tiktok = False
    if guild_id_str and guild_id_str in tiktok_mode_data:
        guild_mode = tiktok_mode_data[guild_id_str]
        if guild_mode.get("enabled", False):
            urls = re.findall(r'https?://[^\s<>"\']+', message.content)
            tiktok_urls = [url for url in urls if is_tiktok_url(url)]
            if tiktok_urls:
                has_tiktok = True
    
    if has_tiktok:
        print(f"[TikTok] Detected TikTok URL from {message.author}: {tiktok_urls[0]}")
        
        try:
            await message.edit(suppress=True)
        except:
            try:
                await message.delete()
            except:
                pass
        
        mode = tiktok_mode_data[guild_id_str].get("mode", "clyppy")
        
        async with message.channel.typing():
            for url in tiktok_urls[:3]:
                try:
                    await message.add_reaction("â³")
                    
                    filename, title = await download_tiktok_video(url, mode)
                    
                    if filename and os.path.exists(filename):
                        file_size = os.path.getsize(filename)
                        print(f"[TikTok] Sending file: {file_size} bytes")
                        
                        if file_size > 25 * 1024 * 1024:
                            await message.remove_reaction("â³", bot.user)
                            await message.add_reaction("âŒ")
                            await message.reply(
                                f"âŒ Video zu groÃŸ ({file_size / 1024 / 1024:.1f}MB). Discord Limit: 25MB.",
                                mention_author=False
                            )
                            os.remove(filename)
                            continue
                        
                        await message.remove_reaction("â³", bot.user)
                        await message.add_reaction("âœ…")
                        
                        discord_file = discord.File(filename, filename="tiktok.mp4")
                        await message.reply(
                            file=discord_file,
                            mention_author=False
                        )
                        
                        os.remove(filename)
                    else:
                        await message.remove_reaction("â³", bot.user)
                        await message.add_reaction("âŒ")
                        print(f"[TikTok] Download returned None for: {url}")
                except Exception as e:
                    print(f"[TikTok] Exception in loop: {e}")
                    try:
                        await message.remove_reaction("â³", bot.user)
                        await message.add_reaction("âŒ")
                    except:
                        pass
    
    await on_message_level_system(message)
    await bot.process_commands(message)

# Override on_voice_state_update to include level system

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    try:
        setup_data = load_voice_setup()
        guild_setup = setup_data.get(str(member.guild.id))
        
        if guild_setup:
            lobby_id = guild_setup.get("lobby_id")
            category_id = guild_setup.get("category_id")
            
            if after.channel and after.channel.id == lobby_id:
                guild = member.guild
                category = guild.get_channel(category_id)
                
                if not category:
                    print(f"[Voice] Category {category_id} nicht gefunden!")
                    return
                
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        speak=True
                    ),
                    member: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        speak=True,
                        move_members=True,
                        manage_channels=True,
                        manage_permissions=True,
                        priority_speaker=True
                    ),
                    guild.me: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        speak=True,
                        manage_channels=True,
                        move_members=True
                    )
                }
                
                try:
                    new_channel = await guild.create_voice_channel(
                        name=f"{member.display_name}'s Chat",
                        category=category,
                        overwrites=overwrites
                    )
                except discord.HTTPException as e:
                    print(f"[Voice] FEHLER beim Erstellen des Channels: {e}")
                    return
                
                voice_channel_owners[new_channel.id] = member.id
                voice_channel_settings[new_channel.id] = {"private": False, "hidden": False}
                save_voice_owners(voice_channel_owners)
                save_voice_settings_file(voice_channel_settings)
                
                try:
                    await member.move_to(new_channel)
                except Exception as e:
                    print(f"[Voice] Fehler beim Move: {e}")
                
                try:
                    embed, view = await create_voice_control_embed(member, new_channel)
                    await new_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"[Voice] Fehler beim Senden des Embeds: {e}")
            
            if before.channel and before.channel.id in voice_channel_owners:
                channel = before.channel
                
                if len(channel.members) == 0:
                    voice_channel_owners.pop(channel.id, None)
                    voice_channel_settings.pop(channel.id, None)
                    save_voice_owners(voice_channel_owners)
                    save_voice_settings_file(voice_channel_settings)
                    try:
                        await channel.delete(reason="Channel leer")
                    except Exception as e:
                        print(f"[Voice] Fehler beim Loeschen: {e}")
                elif voice_channel_owners.get(channel.id) == member.id:
                    new_owner = channel.members[0]
                    voice_channel_owners[channel.id] = new_owner.id
                    save_voice_owners(voice_channel_owners)
                    
                    try:
                        old_overwrites = channel.overwrites_for(member)
                        old_overwrites.update(move_members=False, manage_channels=False, manage_permissions=False, priority_speaker=False)
                        await channel.set_permissions(member, overwrite=old_overwrites)
                    except:
                        pass
                    
                    try:
                        new_overwrites = channel.overwrites_for(new_owner)
                        new_overwrites.update(
                            view_channel=True,
                            connect=True,
                            speak=True,
                            move_members=True,
                            manage_channels=True,
                            manage_permissions=True,
                            priority_speaker=True
                        )
                        await channel.set_permissions(new_owner, overwrite=new_overwrites)
                    except:
                        pass
                    
                    try:
                        await channel.send(f"Der Besitzer hat den Channel verlassen. {new_owner.mention} ist jetzt der neue Besitzer!")
                    except:
                        pass
    except Exception as e:
        print(f"[Voice] Unerwarteter Fehler in on_voice_state_update: {e}")
    
    try:
        await on_voice_state_update_level(member, before, after)
    except Exception as e:
        print(f"[Level] Fehler in Voice-Level-Tracking: {e}")

# =====================================
# AUTO-MEMES TASK & COMMANDS
# =====================================

async def _compress_video(video_data, target_size_mb=20):
    import shutil
    import tempfile
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        print("[Memes] FFmpeg nicht gefunden - Komprimierung nicht moeglich")
        return None
    try:
        input_path = os.path.join(tempfile.gettempdir(), "interpol_input.mp4")
        output_path = os.path.join(tempfile.gettempdir(), "interpol_output.mp4")
        with open(input_path, "wb") as f:
            f.write(video_data)
        original_size = os.path.getsize(input_path)
        target_bytes = target_size_mb * 1024 * 1024
        duration_probe = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-i", input_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await duration_probe.communicate()
        duration = 60
        for line in stderr.decode(errors="ignore").split("\n"):
            if "Duration:" in line:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                if len(parts) == 3:
                    h, m, s = parts
                    duration = int(h)*3600 + int(m)*60 + float(s)
                break
        target_bitrate = int((target_bytes * 8) / duration * 0.9) if duration > 0 else 500000
        video_bitrate = int(target_bitrate * 0.85)
        audio_bitrate = int(target_bitrate * 0.15)
        convert_cmd = [
            ffmpeg_path, "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            "-b:v", str(video_bitrate),
            "-maxrate", str(int(video_bitrate * 1.5)),
            "-bufsize", str(video_bitrate * 2),
            "-c:a", "aac", "-b:a", f"{audio_bitrate}",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-fs", str(target_bytes),
            output_path
        ]
        print(f"[Memes] Komprimiere Video ({original_size//1024//1024}MB -> ~{target_size_mb}MB)...")
        proc = await asyncio.create_subprocess_exec(
            *convert_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and os.path.exists(output_path):
            final_size = os.path.getsize(output_path)
            with open(output_path, "rb") as f:
                compressed = f.read()
            os.remove(input_path)
            os.remove(output_path)
            print(f"[Memes] Komprimierung OK: {final_size//1024//1024}MB")
            return compressed
        else:
            stderr_text = stderr.decode()[-500:] if stderr else "no stderr"
            print(f"[Memes] FFmpeg fehlgeschlagen (code {proc.returncode}): {stderr_text}")
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)
            return None
    except Exception as e:
        print(f"[Memes] Komprimierungs-Fehler: {e}")
        return None

@tasks.loop(minutes=60)
@crash_resilient_task
async def auto_memes_task():
    try:
        config = load_memes_config()
        for guild in bot.guilds:
            guild_str = str(guild.id)
            if guild_str not in config:
                continue
            
            settings = config[guild_str]
            if not settings.get("enabled", False):
                continue
            
            channel_id = settings.get("channel_id")
            if not channel_id:
                continue
            
            channel = bot.get_channel(channel_id)
            if not channel:
                continue
            
            source = settings.get("source", "reddit")
            exclude_ids = set(settings.get("sent_video_ids", [])) if source == "interpol" else None
            
            if source == "interpol":
                config_changed = False
                MAX_VIDEO_SIZE = 8 * 1024 * 1024
                sent_any = False
                
                try:
                    videos = await fetch_interpol_videos(exclude_ids=exclude_ids)
                except Exception as e:
                    print(f"[Memes] Interpol API Fehler fuer {guild.name}: {e}")
                    videos = []
                
                if not videos and exclude_ids:
                    print(f"[Memes] Alle Videos gesendet - Reset fuer {guild.name}")
                    settings["sent_video_ids"] = []
                    save_memes_config(config)
                    try:
                        videos = await fetch_interpol_videos()
                    except Exception as e:
                        print(f"[Memes] Reset-Fetch Fehler: {e}")
                        videos = []
                
                if videos:
                    random.shuffle(videos)
                    chosen = videos[0]
                    meme_url = chosen["url"]
                    video_id = chosen["id"]
                    video_size = chosen.get("size", 0)
                    
                    if video_size <= MAX_VIDEO_SIZE:
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(meme_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                                    if resp.status == 200:
                                        video_data = await resp.read()
                                        if len(video_data) <= MAX_VIDEO_SIZE + (2 * 1024 * 1024):
                                            video_file = discord.File(
                                                fp=__import__('io').BytesIO(video_data),
                                                filename="interpol_video.mp4"
                                            )
                                            embed = discord.Embed(
                                                title=chosen.get("title", "Interpol Video"),
                                                color=discord.Color.random()
                                            )
                                            embed.set_footer(text="Quelle: INTERPOL.CC")
                                            await channel.send(embed=embed, file=video_file)
                                            print(f"[Memes] #{video_id} gesendet in {channel.name}")
                                            sent_any = True
                        except asyncio.TimeoutError:
                            print(f"[Memes] Timeout #{video_id}")
                        except Exception as e:
                            print(f"[Memes] Fehler #{video_id}: {e}")
                    
                    if video_id:
                        if "sent_video_ids" not in settings:
                            settings["sent_video_ids"] = []
                        settings["sent_video_ids"].append(video_id)
                        config_changed = True
                else:
                    print(f"[Memes] Keine Videos fuer {guild.name}")
                
                if config_changed:
                    save_memes_config(config)
            else:
                sent_urls = set(settings.get("sent_meme_urls", []))
                max_history = 100
                
                meme_url, video_id = await get_meme_for_guild(guild.id)
                if not meme_url:
                    print(f"[Memes] Quelle leer - Fallback auf lokale Liste fuer {guild.name}")
                    liste = load_memes_list(guild.id)
                    if liste:
                        meme_url = random.choice(liste)
                if meme_url:
                    if meme_url in sent_urls:
                        meme_url, video_id = await get_meme_for_guild(guild.id)
                    if meme_url:
                        try:
                            embed = discord.Embed(
                                title="Auto-Meme",
                                color=discord.Color.random()
                            )
                            embed.set_image(url=meme_url)
                            embed.set_footer(text=f"Quelle: {source.upper()}")
                            await channel.send(embed=embed)
                            print(f"[Memes] Gesendet in {channel.name} ({guild.name})")
                            sent_urls.add(meme_url)
                            if len(sent_urls) > max_history:
                                sent_urls = set(list(sent_urls)[-max_history:])
                            settings["sent_meme_urls"] = list(sent_urls)
                            save_memes_config(config)
                        except Exception as e:
                            print(f"[Memes] Fehler beim Senden: {e}")
                    else:
                        print(f"[Memes] Kein neues MemÃ© gefunden fuer {guild.name}")
    except Exception as e:
        print(f"[Memes] CRITICAL Fehler in auto_memes_task: {e}")

@auto_memes_task.error
async def auto_memes_task_error(error):
    print(f"[Memes] Task Error (loop laeuft weiter): {error}")

@auto_memes_task.before_loop
async def before_auto_memes():
    await bot.wait_until_ready()

@tasks.loop(minutes=60)
@crash_resilient_task
async def auto_frage_task():
    try:
        config = load_fragen_config()
        for guild in bot.guilds:
            guild_str = str(guild.id)
            if guild_str not in config:
                continue
            
            settings = config[guild_str]
            if not settings.get("enabled", False):
                continue
            
            channel_id = settings.get("channel_id")
            if not channel_id:
                continue
            
            channel = bot.get_channel(channel_id)
            if not channel:
                continue
            
            source = settings.get("source", "gemischt")
            fragen = await get_fragen_from_source(source, guild.id)
            if not fragen:
                fragen = get_all_fragen(guild.id)
            if not fragen:
                print(f"[Frage] Keine Fragen fuer {guild.name}")
                continue
            
            frage_data = random.choice(fragen)
            
            emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
            options_text = ""
            for i, option in enumerate(frage_data["optionen"][:8]):
                options_text += f"{emojis[i]} {option}\n"
            
            source_emoji = {"eisbrecher": "🧊", "entwederoder": "⚖️", "wuerdestu": "💭", "eigene": "✏️", "gemischt": "🎲"}.get(source, "❓")
            
            embed = discord.Embed(
                title=f"{source_emoji} Frage des Tages",
                description=f"**{frage_data['frage']}**\n\n{options_text}",
                color=discord.Color.gold()
            )
            embed.set_footer(text="Reagiere mit einer Zahl um abzustimmen!")
            
            msg = await channel.send(embed=embed)
            
            for i in range(len(frage_data["optionen"][:8])):
                await msg.add_reaction(emojis[i])
            
            frage_messages = load_frage_messages()
            frage_messages[str(msg.id)] = {
                "guild_id": guild_str,
                "options": frage_data["optionen"][:8]
            }
            save_frage_messages(frage_messages)
            
            display_mode = settings.get("display_mode", "embed")
            results_text = build_results_text(str(msg.id), display_mode)
            results_msg = await channel.send(results_text)
            
            config[guild_str]["last_message_id"] = msg.id
            config[guild_str]["last_channel_id"] = channel.id
            config[guild_str]["last_results_id"] = results_msg.id
            save_fragen_config(config)
            
            print(f"[Frage] Gesendet in {channel.name} ({guild.name})")
    except Exception as e:
        print(f"[Frage] Task Fehler: {e}")

@auto_frage_task.error
async def auto_frage_task_error(error):
    print(f"[Frage] Task Error (loop laeuft weiter): {error}")

@auto_frage_task.before_loop
async def before_auto_frage():
    await bot.wait_until_ready()

@bot.tree.command(name="memessetup", description="Auto-Memes Channel einrichten")
@is_admin_or_owner()
@app_commands.describe(
    channel="Channel fÃ¼r Auto-Memes",
    quelle="reddit, imgur, liste, gemischt oder interpol",
    stunden="Interval in Stunden (1-48)",
    minuten="Zusaetzliche Minuten (0-59)"
)
@app_commands.choices(quelle=[
    app_commands.Choice(name="Reddit (Empfohlen)", value="reddit"),
    app_commands.Choice(name="Imgur", value="imgur"),
    app_commands.Choice(name="Eigene Liste", value="liste"),
    app_commands.Choice(name="Gemischt (Alles)", value="gemischt"),
    app_commands.Choice(name="Interpol.cc (Videos)", value="interpol")
])
async def memessetup_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    quelle: app_commands.Choice[str],
    stunden: int = 0,
    minuten: int = 5
):
    total_minutes = (stunden * 60) + minuten
    if total_minutes < 1 or total_minutes > 2880:
        await interaction.response.send_message("Ungueltig! Min: 1 Minute, Max: 48 Stunden", ephemeral=True)
        return
    
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    config[guild_str] = {
        "enabled": True,
        "channel_id": channel.id,
        "source": quelle.value,
        "interval_minutes": total_minutes,
        "subreddit": "memes",
        "imgur_tag": "memes"
    }
    save_memes_config(config)
    
    if auto_memes_task.is_running():
        auto_memes_task.cancel()
    
    auto_memes_task.change_interval(minutes=total_minutes)
    auto_memes_task.start()
    
    if total_minutes >= 60:
        interval_text = f"{total_minutes // 60}h {total_minutes % 60}m"
    else:
        interval_text = f"{total_minutes} Minuten"
    
    source_names = {
        "reddit": "Reddit",
        "imgur": "Imgur",
        "liste": "Eigene Liste",
        "gemischt": "Gemischt (Reddit + Liste)",
        "interpol": "Interpol.cc (Videos)"
    }
    
    await interaction.response.send_message(
        f"**Auto-Memes eingerichtet!**\n\n"
        f"**Channel:** {channel.mention}\n"
        f"**Quelle:** {source_names.get(quelle.value, quelle.value)}\n"
        f"**Interval:** Alle {interval_text}\n\n"
        f"Der Bot postet jetzt automatisch Memes!"
    )

@bot.tree.command(name="memesinterval", description="Auto-Memes Interval aendern")
@is_admin_or_owner()
@app_commands.describe(
    stunden="Interval in Stunden (0-48)",
    minuten="Zusaetzliche Minuten (0-59)"
)
async def memesinterval_command(interaction: discord.Interaction, stunden: int = 0, minuten: int = 5):
    total_minutes = (stunden * 60) + minuten
    if total_minutes < 1 or total_minutes > 2880:
        await interaction.response.send_message("Ungueltig! Min: 1 Minute, Max: 48 Stunden", ephemeral=True)
        return
    
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    config[guild_str]["interval_minutes"] = total_minutes
    save_memes_config(config)
    
    auto_memes_task.cancel()
    auto_memes_task.change_interval(minutes=total_minutes)
    auto_memes_task.start()
    
    if total_minutes >= 60:
        interval_text = f"{total_minutes // 60}h {total_minutes % 60}m"
    else:
        interval_text = f"{total_minutes} Minuten"
    
    await interaction.response.send_message(f"**Interval geaendert auf alle {interval_text}!**")

@bot.tree.command(name="memestoggle", description="Auto-Memes ein/ausschalten")
@is_admin_or_owner()
async def memestoggle_command(interaction: discord.Interaction):
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    current = config[guild_str].get("enabled", False)
    config[guild_str]["enabled"] = not current
    save_memes_config(config)
    
    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    await interaction.response.send_message(f"{icon} **Auto-Memes:** {state}")

@bot.tree.command(name="memesquelle", description="Memes-Quelle Ã¤ndern")
@is_admin_or_owner()
@app_commands.describe(quelle="reddit, imgur, liste, gemischt oder interpol")
@app_commands.choices(quelle=[
    app_commands.Choice(name="Reddit", value="reddit"),
    app_commands.Choice(name="Imgur", value="imgur"),
    app_commands.Choice(name="Eigene Liste", value="liste"),
    app_commands.Choice(name="Gemischt (Alles)", value="gemischt"),
    app_commands.Choice(name="Interpol.cc (Videos)", value="interpol")
])
async def memesquelle_command(
    interaction: discord.Interaction,
    quelle: app_commands.Choice[str]
):
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    config[guild_str]["source"] = quelle.value
    save_memes_config(config)
    
    source_names = {
        "reddit": "Reddit",
        "imgur": "Imgur",
        "liste": "Eigene Liste",
        "gemischt": "Gemischt (Reddit + Liste)",
        "interpol": "Interpol.cc (Videos)"
    }
    
    await interaction.response.send_message(f"**Quelle geÃ¤ndert auf:** {source_names.get(quelle.value, quelle.value)}")

@bot.tree.command(name="memessubreddit", description="Reddit Subreddit fÃ¼r Memes setzen")
@is_admin_or_owner()
@app_commands.describe(subreddit="Reddit Subreddit (z.B. memes, dankmemes)")
async def memessubreddit_command(interaction: discord.Interaction, subreddit: str):
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    config[guild_str]["subreddit"] = subreddit
    save_memes_config(config)
    
    await interaction.response.send_message(f"**Subreddit gesetzt auf:** r/{subreddit}")

@bot.tree.command(name="memesskip", description="NÃ¤chstes MemÃ© manuell senden")
@is_admin_or_owner()
async def memesskip_command(interaction: discord.Interaction):
    await interaction.response.defer()
    
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.followup.send("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    source = config.get(guild_str, {}).get("source", "reddit")
    exclude_ids = set(config.get(guild_str, {}).get("sent_video_ids", [])) if source == "interpol" else None
    
    meme_url, video_id = await get_meme_for_guild(interaction.guild_id, exclude_ids=exclude_ids)
    if not meme_url and source == "interpol" and exclude_ids:
        config[guild_str]["sent_video_ids"] = []
        save_memes_config(config)
        meme_url, video_id = await get_meme_for_guild(interaction.guild_id)
    if not meme_url:
        await interaction.followup.send("Kein MemÃ© gefunden! Quelle prÃ¼fen.", ephemeral=True)
        return
    
    if source == "interpol" and meme_url:
        MAX_VIDEO_SIZE = 8 * 1024 * 1024
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(meme_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        video_data = await resp.read()
                        if len(video_data) > MAX_VIDEO_SIZE:
                            print(f"[Memes] Skip: Video zu gross ({len(video_data)//1024//1024}MB)")
                            await interaction.followup.send(
                                f"Video zu gross ({len(video_data)//1024//1024}MB). Discord Limit: 8MB.",
                                ephemeral=True
                            )
                            if video_id:
                                config[guild_str]["sent_video_ids"] = config.get(guild_str, {}).get("sent_video_ids", [])
                                config[guild_str]["sent_video_ids"].append(video_id)
                                save_memes_config(config)
                            return
                        if video_data:
                            video_file = discord.File(
                                fp=__import__('io').BytesIO(video_data),
                                filename="interpol_video.mp4"
                            )
                            embed = discord.Embed(
                                title="Interpol.cc Video",
                                color=discord.Color.random()
                            )
                            embed.set_footer(text=f"Gesendet von {interaction.user.display_name}")
                            await interaction.followup.send(embed=embed, file=video_file)
                            if video_id:
                                if "sent_video_ids" not in config[guild_str]:
                                    config[guild_str]["sent_video_ids"] = []
                                config[guild_str]["sent_video_ids"].append(video_id)
                                save_memes_config(config)
                            return
        except Exception as e:
            print(f"[Memes] Skip Fehler: {e}")
        await interaction.followup.send("Video konnte nicht geladen werden.", ephemeral=True)
    else:
        embed = discord.Embed(
            title="Manuelles MemÃ©",
            color=discord.Color.random()
        )
        embed.set_image(url=meme_url)
        embed.set_footer(text=f"Gesendet von {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="memestest", description="Testet die Memes-Quelle")
@is_admin_or_owner()
async def memestest_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    source = config.get(guild_str, {}).get("source", "reddit")
    
    results = []
    
    if source in ("reddit", "gemischt"):
        sub = config.get(guild_str, {}).get("subreddit", "memes")
        memes = await fetch_reddit_memes(sub)
        results.append(f"**Reddit r/{sub}:** {len(memes)} Memes gefunden")
    
    if source in ("imgur", "gemischt"):
        tag = config.get(guild_str, {}).get("imgur_tag", "memes")
        memes = await fetch_imgur_memes(tag)
        results.append(f"**Imgur #{tag}:** {len(memes)} Memes gefunden")
    
    if source in ("liste", "gemischt"):
        liste = load_memes_list(interaction.guild_id)
        results.append(f"**Eigene Liste:** {len(liste)} Memes vorhanden")
    
    if source in ("interpol", "gemischt"):
        videos = await fetch_interpol_videos()
        results.append(f"**Interpol.cc:** {len(videos)} Videos gefunden")
    
    if not results:
        results.append("Keine Quelle konfiguriert!")
    
    await interaction.followup.send("\n".join(results), ephemeral=True)

@bot.tree.command(name="memesstatus", description="Zeigt den Auto-Memes Status")
@is_admin_or_owner()
async def memesstatus_command(interaction: discord.Interaction):
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    settings = config[guild_str]
    channel = bot.get_channel(settings.get("channel_id", 0))
    channel_name = channel.mention if channel else "Nicht gefunden"
    status = "âœ… AN" if settings.get("enabled") else "âŒ AUS"
    
    source_names = {
        "reddit": "Reddit",
        "imgur": "Imgur",
        "liste": "Eigene Liste",
        "gemischt": "Gemischt",
        "interpol": "Interpol.cc"
    }
    
    embed = discord.Embed(
        title="Auto-Memes Status",
        color=discord.Color.blue()
    )
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Channel", value=channel_name, inline=True)
    embed.add_field(name="Quelle", value=source_names.get(settings.get("source"), settings.get("source")), inline=True)
    embed.add_field(name="Interval", value=f"{settings.get('interval_hours', 16)}h", inline=True)
    
    if settings.get("source") == "reddit":
        embed.add_field(name="Subreddit", value=f"r/{settings.get('subreddit', 'memes')}", inline=True)
    elif settings.get("source") == "imgur":
        embed.add_field(name="Imgur Tag", value=settings.get("imgur_tag", "memes"), inline=True)
    elif settings.get("source") == "liste":
        liste = load_memes_list(interaction.guild_id)
        embed.add_field(name="Liste", value=f"{len(liste)} Memes", inline=True)
    elif settings.get("source") == "interpol":
        sent_ids = settings.get("sent_video_ids", [])
        embed.add_field(name="Gesendet (Videos)", value=f"{len(sent_ids)} Videos", inline=True)
    elif settings.get("source") in ("reddit", "imgur", "liste", "gemischt"):
        sent_urls = settings.get("sent_meme_urls", [])
        embed.add_field(name="Gesendet (Memes)", value=f"{len(sent_urls)} Memes", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="memesreset", description="Resetet die gesendete Video-History (Interpol)")
@is_admin_or_owner()
async def memesreset_command(interaction: discord.Interaction):
    config = load_memes_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /memessetup", ephemeral=True)
        return
    
    old_count = len(config[guild_str].get("sent_video_ids", []))
    config[guild_str]["sent_video_ids"] = []
    old_meme_count = len(config[guild_str].get("sent_meme_urls", []))
    config[guild_str]["sent_meme_urls"] = []
    save_memes_config(config)
    
    await interaction.response.send_message(f"**History resetet!** {old_count} gesendete Videos + {old_meme_count} gesendete Memes vergessen. Alles wird jetzt wieder gesendet.")

@bot.tree.command(name="memesadd", description="Memes zur eigenen Liste hinzufÃ¼gen")
@is_admin_or_owner()
@app_commands.describe(
    links="Meme-Links (einer pro Zeile oder kommagetrennt)"
)
async def memesadd_command(interaction: discord.Interaction, links: str):
    existing = load_memes_list(interaction.guild_id)
    
    new_links = []
    for line in links.replace("\r", "").split("\n"):
        for link in line.split(","):
            link = link.strip()
            if link.startswith("http"):
                new_links.append(link)
    
    if not new_links:
        await interaction.response.send_message("Keine Links gefunden!", ephemeral=True)
        return
    
    existing.extend(new_links)
    save_memes_list(interaction.guild_id, existing)
    
    await interaction.response.send_message(
        f"**{len(new_links)} Memes hinzugefÃ¼gt!**\n"
        f"Gesamt in der Liste: {len(existing)}"
    )

@bot.tree.command(name="memesload", description="Memes aus .txt Datei laden")
@is_admin_or_owner()
@app_commands.describe(datei="Textdatei mit Meme-Links")
async def memesload_command(interaction: discord.Interaction, datei: discord.Attachment):
    await interaction.response.defer()
    
    if not datei.filename.endswith('.txt'):
        await interaction.followup.send("Nur .txt Dateien erlaubt!", ephemeral=True)
        return
    
    content = await datei.read()
    text = content.decode('utf-8', errors='ignore')
    
    new_links = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("http"):
            new_links.append(line)
    
    if not new_links:
        await interaction.followup.send("Keine Links in der Datei gefunden!", ephemeral=True)
        return
    
    existing = load_memes_list(interaction.guild_id)
    existing.extend(new_links)
    save_memes_list(interaction.guild_id, existing)
    
    await interaction.followup.send(
        f"**{len(new_links)} Memes aus Datei geladen!**\n"
        f"Gesamt: {len(existing)}"
    )

# =====================================
# FRAGE SYSTEM (MANUELL - KEIN AUTOMATIK-TASK)
# =====================================

@bot.tree.command(name="fragesetup", description="Frage des Tages einrichten")
@is_admin_or_owner()
@app_commands.describe(
    channel="Channel fÃ¼r die tÃ¤gliche Frage",
    quelle="Woher kommen die Fragen?",
    anzeige="Wie werden Stimmen angezeigt",
    stunden="Interval in Stunden (1-48)",
    minuten="Zusaetzliche Minuten (0-59)"
)
@app_commands.choices(
    quelle=[
        app_commands.Choice(name="Eisbrecher-Fragen", value="eisbrecher"),
        app_commands.Choice(name="Entweder-Oder Fragen", value="entwederoder"),
        app_commands.Choice(name="Wuerdest-du-lieber Fragen", value="wuerdestu"),
        app_commands.Choice(name="Nur eigene Fragen", value="eigene"),
        app_commands.Choice(name="Gemischt (Alles)", value="gemischt")
    ],
    anzeige=[
        app_commands.Choice(name="Embed (Empfohlen)", value="embed"),
        app_commands.Choice(name="Text (einfach)", value="text"),
        app_commands.Choice(name="Anonym (keine Names)", value="anonym")
    ]
)
async def fragesetup_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    quelle: app_commands.Choice[str],
    anzeige: app_commands.Choice[str] = None,
    stunden: int = 16,
    minuten: int = 0
):
    total_minutes = (stunden * 60) + minuten
    if total_minutes < 1 or total_minutes > 2880:
        await interaction.response.send_message("Ungueltig! Min: 1 Minute, Max: 48 Stunden", ephemeral=True)
        return
    
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    
    display = anzeige.value if anzeige else "embed"
    
    config[guild_str] = {
        "enabled": True,
        "channel_id": channel.id,
        "interval_hours": stunden,
        "interval_minutes": total_minutes,
        "display_mode": display,
        "source": quelle.value
    }
    save_fragen_config(config)
    
    display_names = {"embed": "Embed", "text": "Text", "anonym": "Anonym"}
    source_names = {
        "eisbrecher": "Eisbrecher-Fragen",
        "entwederoder": "Entweder-Oder Fragen",
        "wuerdestu": "Wuerdest-du-lieber Fragen",
        "eigene": "Nur eigene Fragen",
        "gemischt": "Gemischt (Alles)"
    }
    
    if total_minutes >= 60:
        interval_text = f"{total_minutes // 60}h {total_minutes % 60}m"
    else:
        interval_text = f"{total_minutes} Minuten"
    
    await interaction.response.send_message(
        f"**Frage des Tages eingerichtet!**\n\n"
        f"**Channel:** {channel.mention}\n"
        f"**Quelle:** {source_names.get(quelle.value, quelle.value)}\n"
        f"**Interval:** Alle {interval_text}\n"
        f"**Anzeige:** {display_names.get(display, display)}\n\n"
        f"Der Bot postet jetzt automatisch Fragen!"
    )
    
    if auto_frage_task.is_running():
        auto_frage_task.cancel()
    
    auto_frage_task.change_interval(minutes=total_minutes)
    auto_frage_task.start()

@bot.tree.command(name="fragetoggle", description="Frage des Tages ein/ausschalten")
@is_admin_or_owner()
async def fragetoggle_command(interaction: discord.Interaction):
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /fragesetup", ephemeral=True)
        return
    
    current = config[guild_str].get("enabled", False)
    config[guild_str]["enabled"] = not current
    save_fragen_config(config)
    
    state = "AN" if not current else "AUS"
    icon = "âœ…" if not current else "âŒ"
    await interaction.response.send_message(f"{icon} **Frage des Tages:** {state}")

@bot.tree.command(name="fragestatus", description="Zeigt den Frage-des-Tages Status")
@is_admin_or_owner()
async def fragestatus_command(interaction: discord.Interaction):
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.response.send_message("Noch nicht eingerichtet! Benutze /fragesetup", ephemeral=True)
        return
    
    settings = config[guild_str]
    channel = bot.get_channel(settings.get("channel_id", 0))
    channel_name = channel.mention if channel else "Nicht gefunden"
    status = "âœ… AN" if settings.get("enabled") else "âŒ AUS"
    display = settings.get("display_mode", "embed")
    display_names = {"embed": "Embed", "text": "Text", "anonym": "Anonym"}
    source = settings.get("source", "gemischt")
    source_names = {
        "eisbrecher": "Eisbrecher-Fragen",
        "entwederoder": "Entweder-Oder Fragen",
        "wuerdestu": "Wuerdest-du-lieber Fragen",
        "eigene": "Nur eigene Fragen",
        "gemischt": "Gemischt (Alles)"
    }
    
    fragen = get_all_fragen(interaction.guild_id)
    interval_min = settings.get("interval_minutes", 960)
    if interval_min >= 60:
        interval_text = f"{interval_min // 60}h {interval_min % 60}m"
    else:
        interval_text = f"{interval_min} Min"
    
    embed = discord.Embed(
        title="Frage des Tages Status",
        color=discord.Color.gold()
    )
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Channel", value=channel_name, inline=True)
    embed.add_field(name="Interval", value=interval_text, inline=True)
    embed.add_field(name="Quelle", value=source_names.get(source, source), inline=True)
    embed.add_field(name="Anzeige", value=display_names.get(display, display), inline=True)
    embed.add_field(name="Eigene Fragen", value=str(len(fragen)), inline=True)
    
    auto_status = "âœ… LÃ„UFT" if auto_frage_task.is_running() else "âŒ STOPP"
    embed.add_field(name="Auto-Send", value=auto_status, inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="frageadd", description="Eigene Frage hinzufÃ¼gen")
@is_admin_or_owner()
@app_commands.describe(
    frage="Die Frage",
    option1="Option 1",
    option2="Option 2",
    option3="Option 3 (optional)",
    option4="Option 4 (optional)"
)
async def frageadd_command(
    interaction: discord.Interaction,
    frage: str,
    option1: str,
    option2: str,
    option3: str = "",
    option4: str = ""
):
    custom = load_custom_fragen()
    
    optionen = [option1, option2]
    if option3:
        optionen.append(option3)
    if option4:
        optionen.append(option4)
    
    new_frage = {
        "frage": frage,
        "emoji": "â“",
        "optionen": optionen,
        "guild_id": str(interaction.guild_id)
    }
    
    custom.append(new_frage)
    save_custom_fragen(custom)
    
    await interaction.response.send_message(
        f"**Frage hinzugefÃ¼gt!**\n\n"
        f"**{frage}**\n"
        f"Optionen: {', '.join(optionen)}"
    )

@bot.tree.command(name="fragetest", description="Testet eine Frage manuell")
@is_admin_or_owner()
async def fragetest_command(interaction: discord.Interaction):
    await interaction.response.defer()
    
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    source = config.get(guild_str, {}).get("source", "gemischt")
    
    fragen = await get_fragen_from_source(source, interaction.guild_id)
    if not fragen:
        fragen = get_all_fragen(interaction.guild_id)
    if not fragen:
        await interaction.followup.send("Keine Fragen vorhanden!", ephemeral=True)
        return
    
    frage_data = random.choice(fragen)
    
    emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
    options_text = ""
    for i, option in enumerate(frage_data["optionen"][:8]):
        options_text += f"{emojis[i]} {option}\n"
    
    embed = discord.Embed(
        title=f"{frage_data.get('emoji', '\u2753')} Frage des Tages (Test)",
        description=f"**{frage_data['frage']}**\n\n{options_text}",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Reagiere mit einer Zahl um abzustimmen!")
    
    msg = await interaction.followup.send(embed=embed)
    
    for i in range(len(frage_data["optionen"][:8])):
        await msg.add_reaction(emojis[i])
    
    frage_messages = load_frage_messages()
    frage_messages[str(msg.id)] = {
        "guild_id": str(interaction.guild_id),
        "options": frage_data["optionen"][:8]
    }
    save_frage_messages(frage_messages)

@bot.tree.command(name="frageresults", description="Zeigt die Ergebnisse einer Frage mit Users")
@is_admin_or_owner()
@app_commands.describe(message_id="Die ID der Frage-Nachricht (leer = letzte Frage)")
async def frageresults_command(interaction: discord.Interaction, message_id: str = ""):
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    
    if not message_id:
        message_id = config.get(guild_str, {}).get("last_message_id", "")
        if not message_id:
            await interaction.response.send_message("Keine aktuelle Frage gefunden! Message-ID angeben.", ephemeral=True)
            return
    
    display_mode = config.get(guild_str, {}).get("display_mode", "embed")
    results_text = build_results_text(message_id, display_mode)
    
    embed = discord.Embed(
        title="Frage-Ergebnisse",
        description=results_text,
        color=discord.Color.gold()
    )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="frageskip", description="Aktuelle Frage ueberspringen und neue senden")
@is_admin_or_owner()
async def frageskip_command(interaction: discord.Interaction):
    await interaction.response.defer()
    
    config = load_fragen_config()
    guild_str = str(interaction.guild_id)
    
    if guild_str not in config:
        await interaction.followup.send("Noch nicht eingerichtet! Benutze /fragesetup", ephemeral=True)
        return
    
    settings = config[guild_str]
    last_msg_id = settings.get("last_message_id")
    last_channel_id = settings.get("last_channel_id")
    
    if last_msg_id and last_channel_id:
        channel = bot.get_channel(last_channel_id)
        if channel:
            try:
                old_msg = await channel.fetch_message(int(last_msg_id))
                await old_msg.delete()
            except:
                pass
    
    channel_id = settings.get("channel_id")
    channel = bot.get_channel(channel_id)
    if not channel:
        await interaction.followup.send("Channel nicht gefunden!", ephemeral=True)
        return
    
    source = settings.get("source", "gemischt")
    fragen = await get_fragen_from_source(source, interaction.guild_id)
    if not fragen:
        fragen = get_all_fragen(interaction.guild_id)
    if not fragen:
        await interaction.followup.send("Keine Fragen vorhanden!", ephemeral=True)
        return
    
    frage_data = random.choice(fragen)
    
    emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
    options_text = ""
    for i, option in enumerate(frage_data["optionen"][:8]):
        options_text += f"{emojis[i]} {option}\n"
    
    embed = discord.Embed(
        title=f"{frage_data.get('emoji', '\u2753')} Frage des Tages",
        description=f"**{frage_data['frage']}**\n\n{options_text}",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Reagiere mit einer Zahl um abzustimmen!")
    
    msg = await channel.send(embed=embed)
    
    reaction_emojis = ["1\uFE0F\u20E3", "2\uFE0F\u20E3", "3\uFE0F\u20E3", "4\uFE0F\u20E3", "5\uFE0F\u20E3", "6\uFE0F\u20E3", "7\uFE0F\u20E3", "8\uFE0F\u20E3"]
    for i in range(len(frage_data["optionen"][:8])):
        await msg.add_reaction(reaction_emojis[i])
    
    frage_messages = load_frage_messages()
    frage_messages[str(msg.id)] = {
        "guild_id": guild_str,
        "options": frage_data["optionen"][:8]
    }
    save_frage_messages(frage_messages)
    
    display_mode = config[guild_str].get("display_mode", "embed")
    results_text = build_results_text(str(msg.id), display_mode)
    results_msg = await channel.send(results_text)
    
    config[guild_str]["last_message_id"] = msg.id
    config[guild_str]["last_channel_id"] = channel.id
    config[guild_str]["last_results_id"] = results_msg.id
    save_fragen_config(config)
    
    await interaction.followup.send(
        f"**Frage uebersprungen!** Neue Frage gesendet in {channel.mention}"
    )

@bot.tree.command(name="fixvoice", description="Aktiviert Sprechen fuer alle in allen Voice-Channels (kein Push-to-Talk noetig)")
@is_admin_or_owner()
async def fixvoice_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    fixed = 0
    failed = 0
    for channel in interaction.guild.voice_channels:
        try:
            overwrites = channel.overwrites_for(interaction.guild.default_role)
            overwrites.speak = True
            overwrites.connect = True
            overwrites.use_voice_activation = True
            await channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
            fixed += 1
        except discord.Forbidden:
            failed += 1
        except Exception:
            failed += 1
    await interaction.followup.send(
        f"**Voice-Permissions gefixt!**\n"
        f"**{fixed}** Channels aktualisiert\n"
        f"**{failed}** fehlgeschlagen\n\n"
        f"Alle koennen jetzt frei sprechen (kein Push-to-Talk noetig)."
    )

# =====================================
# AUTOMOD - INVITE SPAM PROTECTION
# =====================================

INVITE_PATTERN = re.compile(r'(discord\.gg|discordapp\.com/invite|discord\.com/invite)/[\w\-]+', re.IGNORECASE)
AUTOMOD_TIMEOUT_MINUTES = 10080
AUTOMOD_THRESHOLD = 4
AUTOMOD_WINDOW = 300

async def check_automod_invite_spam(message):
    global automod_config
    if not automod_config:
        automod_config = load_automod_config()
    
    guild_str = str(message.guild.id)
    if guild_str not in automod_config:
        return
    if not automod_config[guild_str].get("enabled", False):
        return
    
    if not INVITE_PATTERN.search(message.content):
        return
    
    user_id = str(message.author.id)
    now = time.time()
    key = f"{guild_str}:{user_id}"
    
    if key not in invite_spam_tracker:
        invite_spam_tracker[key] = []
    
    invite_spam_tracker[key] = [t for t in invite_spam_tracker[key] if now - t < AUTOMOD_WINDOW]
    invite_spam_tracker[key].append(now)
    
    count = len(invite_spam_tracker[key])
    
    if count >= AUTOMOD_THRESHOLD:
        invite_spam_tracker[key] = []
        
        try:
            timeout_duration = datetime.timedelta(minutes=AUTOMOD_TIMEOUT_MINUTES)
            await message.author.timeout(timeout_duration, reason=f"Automod: {count}x Invite-Spam in {AUTOMOD_WINDOW}s")
            
            await message.delete()
            
            embed = discord.Embed(
                title="Automod - Timeout",
                description=(
                    f"{message.author.mention} hat einen **1-Woche Timeout** bekommen.\n\n"
                    f"**Grund:** {count}x Discord-Invite gespamt\n"
                    f"**Nachricht:** {message.content[:200]}"
                ),
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed, delete_after=10)
            
            print(f"[Automod] {message.author} ({message.author.id}) getimeoutet fuer 1 Woche ({count}x Invite-Spam)")
        except discord.Forbidden:
            print(f"[Automod] Keine Berechtigung fuer Timeout von {message.author}")
        except Exception as e:
            print(f"[Automod] Timeout Fehler: {e}")

@bot.tree.command(name="automod", description="Invite-Spam Schutz ein/ausschalten")
@is_admin_or_owner()
@app_commands.describe(aktion="ein oder aus")
@app_commands.choices(aktion=[
    app_commands.Choice(name="Aktivieren", value="ein"),
    app_commands.Choice(name="Deaktivieren", value="aus"),
    app_commands.Choice(name="Status", value="status")
])
async def automod_command(interaction: discord.Interaction, aktion: app_commands.Choice[str]):
    global automod_config
    if not automod_config:
        automod_config = load_automod_config()
    
    guild_str = str(interaction.guild_id)
    
    if aktion.value == "status":
        settings = automod_config.get(guild_str, {})
        enabled = settings.get("enabled", False)
        status = "âœ… AN" if enabled else "âŒ AUS"
        embed = discord.Embed(
            title="Automod Status",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Schwellenwert", value=f"{AUTOMOD_THRESHOLD}x", inline=True)
        embed.add_field(name="Timeout", value="1 Woche", inline=True)
        embed.add_field(name="Fenster", value=f"{AUTOMOD_WINDOW}s", inline=True)
        embed.add_field(name="Pattern", value="discord.gg/ Links", inline=True)
        await interaction.response.send_message(embed=embed)
        return
    
    if guild_str not in automod_config:
        automod_config[guild_str] = {}
    
    enabled = aktion.value == "ein"
    automod_config[guild_str]["enabled"] = enabled
    save_automod_config(automod_config)
    
    if enabled:
        desc = (
            f"âœ… **Automod aktiviert!**\n\n"
            f"**Schutz:** Discord-Invite-Spam\n"
            f"**Schwellenwert:** {AUTOMOD_THRESHOLD}x in {AUTOMOD_WINDOW}s\n"
            f"**Strafe:** 1-Woche Timeout + Nachricht gelÃ¶scht\n\n"
            f"Wenn jemand {AUTOMOD_THRESHOLD}x oder Ã¶fter discord.gg/ Links posted, "
            f"bekommt er automatisch Timeout."
        )
    else:
        desc = "âŒ **Automod deaktiviert!**"
    
    await interaction.response.send_message(desc)

# =====================================
# MEMBER COUNT CHANNEL SYSTEM
# =====================================

MEMBERCOUNT_CONFIG_FILE = DATA_DIR / "membercount_config.json"
MEMBERCOUNT_MIN_RENAME_INTERVAL = 300

_last_membercount_rename = {}

def load_membercount_config():
    try:
        if MEMBERCOUNT_CONFIG_FILE.exists():
            with open(MEMBERCOUNT_CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[MemberCount] Config lesen fehlgeschlagen: {e}")
    return {}

def save_membercount_config(data):
    try:
        with open(MEMBERCOUNT_CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[MemberCount] Config speichern fehlgeschlagen: {e}")

async def update_member_count_channels(force=False):
    config = load_membercount_config()
    now = time.time()
    for guild_str, settings in config.items():
        channel_id = settings.get("channel_id")
        if not channel_id:
            continue
        channel = bot.get_channel(channel_id)
        if not channel:
            guild = bot.get_guild(int(guild_str))
            if guild:
                channel = guild.get_channel(channel_id)
        if not channel:
            continue
        guild = channel.guild
        if not guild:
            continue
        member_count = guild.member_count or 0
        prefix = settings.get("prefix", "Members")
        new_name = f"{prefix}: {member_count}"
        if channel.name == new_name:
            continue
        if not force:
            last = _last_membercount_rename.get(channel_id, 0)
            if now - last < MEMBERCOUNT_MIN_RENAME_INTERVAL:
                print(f"[MemberCount] Throttle - letztes Rename vor {int(now - last)}s, Skipped")
                continue
        _last_membercount_rename[channel_id] = now
        try:
            await channel.edit(name=new_name)
            print(f"[MemberCount] {channel.name} -> {new_name}")
        except discord.HTTPException as e:
            if e.status == 429:
                print(f"[MemberCount] Rate-Limit (429) - Skipped, naechster Versuch in {MEMBERCOUNT_MIN_RENAME_INTERVAL}s")
            else:
                print(f"[MemberCount] HTTP-Fehler: {e}")
        except discord.Forbidden:
            print(f"[MemberCount] Keine Berechtigung fuer {channel.name}")
        except Exception as e:
            print(f"[MemberCount] Fehler: {e}")

@bot.tree.command(name="membercountsetup", description="Channel fuer Member-Anzahl einrichten (Voice oder Text)")
@is_admin_or_owner()
@app_commands.describe(
    channel="Channel der die Anzahl anzeigen soll",
    prefix="Text vor der Zahl (z.B. Members, Mitglieder, Users)"
)
async def membercountsetup_command(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel,
    prefix: str = "Members"
):
    config = load_membercount_config()
    config[str(interaction.guild_id)] = {
        "channel_id": channel.id,
        "prefix": prefix
    }
    save_membercount_config(config)
    
    member_count = interaction.guild.member_count
    if member_count is None:
        member_count = len(interaction.guild.members)
    new_name = f"{prefix}: {member_count}"
    try:
        await channel.edit(name=new_name, reason="Member-Count Setup")
        success = True
    except discord.Forbidden:
        success = False
        new_name = f"{prefix}: ???"
    except Exception as e:
        success = False
        new_name = f"{prefix}: ???"
    
    status = f"Channel Name: **{new_name}**" if success else "âš ï¸ **Keine Berechtigung** - Bot braucht `Channel verwalten` Permission!"
    
    await interaction.response.send_message(
        f"**Member-Count eingerichtet!**\n\n"
        f"**Channel:** {channel.mention}\n"
        f"{status}\n\n"
        f"Updated sich automatisch bei Join/Leave!"
    )

@bot.tree.command(name="membercount", description="Member-Anzahl Channel sofort updaten")
@is_admin_or_owner()
async def membercount_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await update_member_count_channels(force=True)
    config = load_membercount_config()
    guild_str = str(interaction.guild_id)
    if guild_str in config:
        channel = bot.get_channel(config[guild_str].get("channel_id", 0))
        member_count = interaction.guild.member_count
        prefix = config[guild_str].get("prefix", "Members")
        await interaction.followup.send(
            f"**Updated!** {channel.mention if channel else 'Channel'}: {prefix}: {member_count}",
            ephemeral=True
        )
    else:
        await interaction.followup.send("Noch nicht eingerichtet! Benutze `/membercountsetup`", ephemeral=True)

@bot.tree.command(name="membercountremove", description="Member-Count Channel entfernen")
@is_admin_or_owner()
async def membercountremove_command(interaction: discord.Interaction):
    config = load_membercount_config()
    guild_str = str(interaction.guild_id)
    if guild_str in config:
        del config[guild_str]
        save_membercount_config(config)
        await interaction.response.send_message("Member-Count Channel entfernt!")
    else:
        await interaction.response.send_message("Kein Member-Count Channel eingerichtet.", ephemeral=True)

# =====================================
# SERVER LIST CHECKER & SENDER
# =====================================

import re as _re

async def check_invite_valid(invite_code):
    """Prueft ob ein Discord Invite gueltig ist"""
    url = f"https://discord.com/api/v10/invites/{invite_code}?with_counts=true"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                guild = data.get("guild", {})
                return {
                    "valid": True,
                    "code": invite_code,
                    "guild_name": guild.get("name", "Unbekannt"),
                    "guild_id": guild.get("id"),
                    "member_count": data.get("approximate_member_count", 0),
                    "online_count": data.get("approximate_presence_count", 0),
                    "splash": guild.get("splash"),
                    "icon": guild.get("icon"),
                    "description": guild.get("description", ""),
                    "vanity_url": guild.get("vanity_url_code"),
                }
            elif resp.status == 404:
                return {"valid": False, "code": invite_code, "reason": "Inviteä¸å­˜åœ¨æˆ–å·²è¿‡æœŸ"}
            elif resp.status == 429:
                retry_after = (await resp.json()).get("retry_after", 5)
                await asyncio.sleep(retry_after)
                return await check_invite_valid(invite_code)
            else:
                return {"valid": False, "code": invite_code, "reason": f"HTTP {resp.status}"}

def extract_invite_codes(text):
    """Extrahiert Discord Invite Codes aus Text"""
    codes = set()
    patterns = [
        r'discord\.gg/([a-zA-Z0-9_-]+)',
        r'discord\.com/invite/([a-zA-Z0-9_-]+)',
        r'discordapp\.com/invite/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        for match in _re.finditer(pattern, text):
            codes.add(match.group(1))
    return list(codes)

@bot.tree.command(name="serverlist", description="Sendet Discord Server Links als Text (11 pro Nachricht), loescht kaputte automatisch")
@is_admin_or_owner()
@app_commands.describe(
    datei="Textdatei mit Discord Server Links (einer pro Zeile)",
    pro_nachricht="Links pro Nachricht (Standard: 11)",
    delay="Sekunden zwischen jeder Nachricht (Standard: 0.5)"
)
async def serverlist_command(
    interaction: discord.Interaction,
    datei: discord.Attachment,
    pro_nachricht: int = 11,
    delay: float = 0.5
):
    await interaction.response.defer(ephemeral=True)

    if not datei.filename.endswith('.txt'):
        await interaction.followup.send("Nur .txt Dateien erlaubt!", ephemeral=True)
        return

    content = await datei.read()
    text = content.decode('utf-8', errors='ignore')

    lines = [l.strip() for l in text.split('\n') if l.strip()]
    codes = extract_invite_codes(text)

    if not codes:
        await interaction.followup.send(
            f"Keine Discord Invite Links in der Datei gefunden.\n"
            f"Gelesen: {len(lines)} Zeilen\n"
            f"Erwartetes Format: discord.gg/xxxx pro Zeile",
            ephemeral=True
        )
        return

    if pro_nachricht < 1:
        pro_nachricht = 1
    if pro_nachricht > 20:
        pro_nachricht = 20

    await interaction.followup.send(
        f"**{len(codes)} Invite(s) gefunden.** Sende je {pro_nachricht} als Text, pruefe danach parallel und loesche kaputte...",
        ephemeral=True
    )

    batch_size = pro_nachricht
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]

    sent_batches = []
    failed = 0
    for batch in batches:
        try:
            content_text = "\n".join(f"discord.gg/{code}" for code in batch)
            msg = await interaction.channel.send(content_text)
            sent_batches.append((msg, batch))
        except Exception as e:
            failed += len(batch)
            print(f"[ServerList] Fehler beim Senden einer Batch: {e}")

        await asyncio.sleep(delay)

    if not sent_batches:
        await interaction.followup.send(
            f"**Fehlgeschlagen!** Keine Nachricht konnte gesendet werden ({failed} Fehler).",
            ephemeral=True
        )
        return

    all_sent_codes = [code for _, batch in sent_batches for code in batch]
    await interaction.followup.send(
        f"**{len(all_sent_codes)} Links gesendet.** Pruefe jetzt parallel (10 gleichzeitig)...",
        ephemeral=True
    )

    sem = asyncio.Semaphore(10)

    async def check_with_limit(code):
        async with sem:
            return await check_invite_valid(code)

    valid = []
    invalid = []

    for i in range(0, len(all_sent_codes), 10):
        batch_codes = all_sent_codes[i:i + 10]
        results = await asyncio.gather(*[check_with_limit(c) for c in batch_codes])

        for code, result in zip(batch_codes, results):
            if result["valid"]:
                valid.append(result)
            else:
                invalid.append(result)

    valid_codes = [v["code"] for v in valid]

    if invalid:
        for msg, batch in sent_batches:
            batch_invalid = [c for c in batch if c in [iv["code"] for iv in invalid]]
            if batch_invalid:
                try:
                    await msg.delete()
                    valid_in_batch = [c for c in batch if c in valid_codes]
                    if valid_in_batch:
                        content_text = "\n".join(f"discord.gg/{c}" for c in valid_in_batch)
                        await interaction.channel.send(content_text)
                except Exception as e:
                    print(f"[ServerList] Batch-Korrektur fehlgeschlagen: {e}")

    result_data = {
        "last_check": datetime.datetime.utcnow().isoformat(),
        "total": len(codes),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "valid": valid,
        "invalid": [r["code"] for r in invalid[:50]],
    }

    SERVERLIST_RESULT_FILE = DATA_DIR / "serverlist_results.json"
    try:
        with open(SERVERLIST_RESULT_FILE, "w") as f:
            json.dump(result_data, f, indent=2)
        saved = True
    except Exception as e:
        saved = False
        print(f"[ServerList] Speichern fehlgeschlagen: {e}")

    report = (
        f"**Ergebnis:**\n"
        f" Gesendet: **{len(all_sent_codes)}**\n"
        f" Gueltig (bleiben): **{len(valid)}**\n"
        f" Ungueltig (geloescht): **{len(invalid)}**\n"
        f" Sendefehler: {failed}"
    )

    if saved:
        report += f"\n Gueltige Links gespeichert in `data/serverlist_results.json`"

    await interaction.followup.send(report, ephemeral=True)

# =====================================
# ROLLEN RECHTE ENTZIEHEN (GIF/BILDER/STICKER)
# =====================================

@bot.tree.command(name="striproles", description="Entzieht ALLEN Rollen die Rechte fuer GIFs, Bilder und externe Sticker")
@is_admin_or_owner()
async def striproles_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    bot_top_role = interaction.guild.me.top_role
    print(f"[STRIPROLES] Bot Top: {bot_top_role.name} (Pos {bot_top_role.position})")

    updated = []
    skipped = []

    roles_to_edit = []
    for role in interaction.guild.roles:
        if role.position >= bot_top_role.position and role != interaction.guild.default_role:
            skipped.append(f"{role.name} (Bot zu niedrig)")
            continue
        if role.managed:
            skipped.append(f"{role.name} (Bot-Rolle)")
            continue

        old_perms = role.permissions
        new_perms = old_perms.copy()
        new_perms.attach_files = False
        new_perms.use_external_stickers = False
        new_perms.use_external_emojis = False

        if old_perms == new_perms:
            skipped.append(f"{role.name} (bereits gesetzt)")
            continue
        roles_to_edit.append((role, new_perms))

    print(f"[STRIPROLES] Zu bearbeiten: {len(roles_to_edit)}, Uebersprungen: {len(skipped)}")
    await interaction.followup.send(f"Starte... {len(roles_to_edit)} Rollen zu bearbeiten, {len(skipped)} uebersprungen", ephemeral=True)

    total = len(roles_to_edit)
    for i, (role, new_perms) in enumerate(roles_to_edit, 1):
        try:
            print(f"[STRIPROLES] Bearbeite {i}/{total}: {role.name}")
            await role.edit(permissions=new_perms, reason=f"striproles von {interaction.user}")
            updated.append(role.name)
            print(f"[STRIPROLES] OK: {role.name}")
            if i < total:
                await asyncio.sleep(1.0)
        except discord.Forbidden:
            print(f"[STRIPROLES] Forbidden: {role.name}")
            skipped.append(f"{role.name} (keine Berechtigung)")
        except Exception as e:
            print(f"[STRIPROLES] Error: {role.name} - {e}")
            skipped.append(f"{role.name} ({e})")

    print(f"[STRIPROLES] Fertig! Updated: {len(updated)}, Skipped: {len(skipped)}")

    embed = discord.Embed(
        title="Rechte entzogen",
        color=discord.Color.green() if updated else discord.Color.red()
    )
    if updated:
        embed.add_field(
            name=f"Aktualisiert ({len(updated)})",
            value=", ".join(updated),
            inline=False
        )
    if skipped:
        embed.add_field(
            name=f"Uebersprungen ({len(skipped)})",
            value=", ".join(skipped),
            inline=False
        )
    embed.set_footer(text="ALLE Rollen - Bilder, GIFs, externe Sticker/Emojis deaktiviert")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="unstriproles", description="Gibt ALLEN Rollen die GIF/Bilder/Sticker Rechte zurueck")
@is_admin_or_owner()
async def unstriproles_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    bot_top_role = interaction.guild.me.top_role

    updated = []
    skipped = []

    roles_to_edit = []
    for role in interaction.guild.roles:
        if role.position >= bot_top_role.position and role != interaction.guild.default_role:
            skipped.append(f"{role.name} (Bot zu niedrig)")
            continue
        if role.managed:
            skipped.append(f"{role.name} (Bot-Rolle)")
            continue

        old_perms = role.permissions
        new_perms = old_perms.copy()
        new_perms.attach_files = True
        new_perms.use_external_stickers = True
        new_perms.use_external_emojis = True

        if old_perms == new_perms:
            skipped.append(f"{role.name} (bereits gesetzt)")
            continue
        roles_to_edit.append((role, new_perms))

    total = len(roles_to_edit)
    for i, (role, new_perms) in enumerate(roles_to_edit, 1):
        try:
            await role.edit(permissions=new_perms, reason=f"unstriproles von {interaction.user}")
            updated.append(role.name)
            if i < total:
                await asyncio.sleep(1.0)
        except discord.Forbidden:
            skipped.append(f"{role.name} (keine Berechtigung)")
        except Exception as e:
            skipped.append(f"{role.name} ({e})")

    embed = discord.Embed(
        title="Rechte wiederhergestellt",
        color=discord.Color.green() if updated else discord.Color.red()
    )
    if updated:
        embed.add_field(
            name=f"Aktualisiert ({len(updated)})",
            value=", ".join(updated),
            inline=False
        )

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Zeigt alle Commands nach Kategorie")
async def help_command(interaction: discord.Interaction):
    categories = {
        "GIF-Sender": {
            "add": "GIF/Media-Links zur Liste hinzufuegen",
            "load": "TXT-Datei mit Links hochladen",
            "start": "Startet das Senden von GIFs pro Nachricht",
            "cont": "Setzt das Senden dort fort, wo es aufgehoert hat",
            "stop": "Stoppt das GIF-Senden",
            "next": "Sendet die naechsten 4 GIFs",
            "status": "Zeigt den aktuellen Stand",
            "clear": "Loescht die komplette Liste",
            "embedvideos": "MP4/MOV als Inline-Video statt Text-Link",
            "size": "Links pro Nachricht setzen (1-5)",
            "list": "Zeigt erste/letzte 5 Links",
            "pos": "Position manuell setzen",
            "import": "Bis zu 10 TXT-Dateien, pro Datei ein Channel",
            "import2": "TXT-Dateien direkt in diesen Channel senden",
        },
        "TikTok / Filter": {
            "filtermode": "Erweiterter Media-Filter",
            "nofiltermode": "Kein Filter - jede Zeile als Link",
            "tiktokmode": "TikTok Auto-Download Service waehlen",
            "tiktoktoggle": "TikTok Auto-Download ein/aus",
            "tiktokstatus": "TikTok Auto-Download Status",
        },
        "Server-Verwaltung": {
            "clearchannels": "Loescht alle Bot-erstellten Channels",
            "permsync": "Permissions eines Channels mit Kategorie syncen",
            "hoistall": "Rolle getrennt anzeigen bei allen Rollen",
            "setavatar": "Bot-Profilbild setzen",
            "setbanner": "Bot-Bannerbild setzen",
            "serverlist": "Server-Links aus TXT pruefen und senden",
        },
        "Reaction-Roles": {
            "reactionrole": "Reaction-Roles verwalten (wie Carl-bot)",
            "reactionsetup": "Embed mit Buttons fuer Reaction-Roles senden",
            "masssetup": "Reaction-Role Buttons fuer ALLE User-Rollen",
        },
        "Ticket-System": {
            "ticketsetup": "Ticket-System einrichten",
            "close": "Ticket schliessen",
            "ticketadd": "User zum Ticket hinzufuegen",
            "ticketremove": "User aus Ticket entfernen",
            "transcript": "Ticket-Transkript generieren",
        },
        "Voice-Channel": {
            "voicesetup": "Voice System einrichten (Lobby + Category)",
            "vc_kick": "User aus deinem VC kicken",
            "vc_ban": "User aus deinem VC bannen",
            "vc_permit": "User Zugriff auf deinen Channel geben",
            "vc_changeowner": "Channel-Besitz uebertragen",
        },
        "Level-System": {
            "level": "Dein Level und XP",
            "leaderboard": "Leaderboard anzeigen",
            "setlevelchannel": "Channel fuer Level-Up-Nachrichten",
            "setleaderboard": "Live-Leaderboard einrichten",
            "leaderboardrefresh": "Alte Leaderboard-Embeds neu senden",
            "levelimage": "Bild fuer Levelaufstieg setzen",
            "noxpchannel": "Kein XP in diesem Channel",
            "toggleleveling": "Level-System komplett an/aus",
            "togglelevelimage": "Bilder bei Level-Up an/aus",
            "resetlevels": "Alle Level-Daten zuruecksetzen",
            "setlevel": "Level eines Users manuell setzen",
        },
        "Auto-Memes": {
            "memessetup": "Meme-Channel einrichten",
            "memesinterval": "Intervall aendern",
            "memestoggle": "Memes an/aus",
            "memesquelle": "Quelle aendern (reddit/imgur/liste/gemischt/interpol)",
            "memessubreddit": "Subreddit setzen",
            "memesskip": "Naechstes Meme manuell senden",
            "memestest": "Quelle testen",
            "memesstatus": "Status anzeigen",
            "memesreset": "Video-History resetten",
            "memesadd": "Meme zur eigenen Liste hinzufuegen",
            "memesload": "Memes aus TXT laden",
        },
        "Frage des Tages": {
            "fragesetup": "Frage des Tages einrichten",
            "fragetoggle": "An/aus",
            "fragestatus": "Status anzeigen",
            "frageadd": "Eigene Frage hinzufuegen",
            "fragetest": "Frage manuell testen",
            "frageresults": "Ergebnisse mit Users anzeigen",
            "frageskip": "Frage ueberspringen",
        },
        "Sonstige": {
            "fixvoice": "Sprechen fuer alle aktivieren (kein Push-to-Talk)",
            "automod": "Invite-Spam Schutz an/aus",
            "membercountsetup": "Member-Anzahl Channel einrichten",
            "membercount": "Member-Anzahl sofort updaten",
            "membercountremove": "Member-Count Channel entfernen",
            "striproles": "Entzieht Rollen unter 'Maske' GIF/Bilder/Sticker-Rechte",
            "unstriproles": "Gibt diese Rechte zurueck",
            "botstatus": "Status aller Bot-Systeme",
        },
    }

    cat_names = list(categories.keys())

    def build_embed(cat):
        cmds = categories[cat]
        lines = "\n".join(f"`/{name}` - {desc}" for name, desc in cmds.items())
        total = sum(len(v) for v in categories.values())
        embed = discord.Embed(
            title=f"Hilfe - {cat}",
            description=lines,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"{cat} {len(cmds)}/{total} Commands | Kategorie unten auswaehlen")
        return embed

    select = discord.ui.Select(
        placeholder="Kategorie waehlen...",
        options=[discord.SelectOption(label=cat, value=cat, description=f"{len(categories[cat])} Commands") for cat in cat_names]
    )

    async def on_select(select_interaction: discord.Interaction):
        await select_interaction.response.edit_message(embed=build_embed(select.values[0]))

    select.callback = on_select

    view = discord.ui.View()
    view.add_item(select)

    await interaction.response.send_message(embed=build_embed(cat_names[0]), view=view)

MIMO_API_URL = "https://opencode.ai/zen/v1/chat/completions"

AI_MODELS = [
    {"id": "mimo-v2.5-free", "name": "MiMo V2.5"},
    {"id": "deepseek-v4-flash-free", "name": "DeepSeek V4"},
    {"id": "nemotron-3-ultra-free", "name": "Nemotron 3 Ultra"},
]

ai_cooldowns = {}

@bot.tree.command(name="ai", description="Frage die KI (MiMo / DeepSeek / Nemotron)")
@app_commands.describe(
    frage="Deine Frage an die KI",
    system="System-Prompt (z.B. 'Antworte wie ein Pirat')"
)
async def ai_command(
    interaction: discord.Interaction,
    frage: str,
    system: str = ""
):
    user_id = interaction.user.id
    now = time.time()
    
    if user_id in ai_cooldowns and (now - ai_cooldowns[user_id]) < 30:
        rest = int(30 - (now - ai_cooldowns[user_id]))
        await interaction.response.send_message(f"⏳ Noch {rest} Sekunden warten...", ephemeral=True)
        return
    
    ai_cooldowns[user_id] = now
    
    await interaction.response.defer()
    
    api_key = os.getenv("MIMO_API_KEY")
    if not api_key:
        await interaction.followup.send("❌ MIMO_API_KEY nicht gesetzt!\nRailway → Variables → MIMO_API_KEY eintragen", ephemeral=True)
        return
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    else:
        messages.append({"role": "system", "content": "Du bist ein hilfreicher Discord-Bot Assistent. Antworte kurz und präzise auf Deutsch. Verwende Emojis sparsam."})
    messages.append({"role": "user", "content": frage})
    
    for model in AI_MODELS:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    MIMO_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model["id"],
                        "messages": messages,
                        "max_tokens": 1024,
                        "temperature": 0.7
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 429:
                        print(f"[AI] {model['name']} rate-limited, naechstes Model...")
                        continue
                    
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"[AI] {model['name']} Fehler {resp.status}: {error_text[:100]}")
                        continue
                    
                    data = await resp.json()
                    
                    antwort = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {})
                    
                    embed = discord.Embed(
                        title=f"🤖 {model['name']}",
                        description=antwort[:4000],
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="📋 Frage", value=frage[:256], inline=False)
                    embed.set_footer(text=f"Tokens: {tokens.get('total_tokens', '?')} | Model: {model['id']}")
                    
                    await interaction.followup.send(embed=embed)
                    return
        
        except asyncio.TimeoutError:
            print(f"[AI] {model['name']} Timeout, naechstes Model...")
            continue
        except Exception as e:
            print(f"[AI] {model['name']} Exception: {e}")
            continue
    
    await interaction.followup.send("❌ Alle KI-Models sind gerade nicht verfuegbar - bitte spaeter nochmal versuchen!", ephemeral=True)

@bot.tree.command(name="botstatus", description="Zeigt den Status aller Bot-Systeme")
@is_admin_or_owner()
async def botstatus_command(interaction: discord.Interaction):
    global recovery
    
    embed = discord.Embed(
        title="Bot System Status",
        color=discord.Color.green()
    )
    
    uptime = recovery.get_uptime() if recovery else "unbekannt"
    embed.add_field(name="Uptime", value=uptime, inline=True)
    
    tasks_status = []
    try:
        tasks_status.append(f"Auto-Memes: {'LAEUFT' if auto_memes_task.is_running() else 'STOPP'}")
    except:
        tasks_status.append("Auto-Memes: FEHLER")
    try:
        tasks_status.append(f"AutoSave: {'LAEUFT' if auto_save_data.is_running() else 'STOPP'}")
    except:
        tasks_status.append("AutoSave: FEHLER")
    try:
        tasks_status.append(f"MemberCount: {'LAEUFT' if membercount_refresh.is_running() else 'STOPP'}")
    except:
        tasks_status.append("MemberCount: FEHLER")
    try:
        tasks_status.append(f"Watchdog: {'LAEUFT' if watchdog_task.is_running() else 'STOPP'}")
    except:
        tasks_status.append("Watchdog: FEHLER")
    try:
        tasks_status.append(f"Leaderboard: {'LAEUFT' if update_live_leaderboard.is_running() else 'STOPP'}")
    except:
        tasks_status.append("Leaderboard: FEHLER")
    embed.add_field(name="Tasks", value="\n".join(tasks_status), inline=False)
    
    memes_config = load_memes_config()
    active_memes = sum(1 for s in memes_config.values() if s.get("enabled"))
    embed.add_field(name="Memes Channels", value=f"{active_memes} aktiv", inline=True)
    
    fragen_config = load_fragen_config()
    active_fragen = sum(1 for s in fragen_config.values() if s.get("enabled"))
    embed.add_field(name="Frage Channels", value=f"{active_fragen} aktiv", inline=True)
    
    embed.add_field(name="Voice Owners", value=f"{len(voice_channel_owners)} Channels", inline=True)
    
    mc_config = load_membercount_config()
    embed.add_field(name="MemberCount", value=f"{len(mc_config)} Channel(s)", inline=True)
    
    embed.set_footer(text=f"Bot: {bot.user.name} | Server: {interaction.guild.name}")
    
    await interaction.response.send_message(embed=embed)

# =====================================
# WATCHDOG + RECOVERY SYSTEM
# =====================================

recovery = None

@tasks.loop(seconds=60)
@crash_resilient_task
async def watchdog_task():
    global recovery
    if not recovery:
        return
    recovery.heartbeat()
    
    # Vor jedem Watchdog-Check Configs sichern
    save_all_configs_to_disk()
    
    config = load_memes_config()
    for guild_str, settings in config.items():
        if settings.get("enabled"):
            ch_id = settings.get("channel_id")
            if ch_id:
                channel = bot.get_channel(ch_id)
                if not channel:
                    guild = bot.get_guild(int(guild_str))
                    if guild:
                        channel = guild.get_channel(ch_id)
                if not channel:
                    misses = settings.get("_cache_misses", 0) + 1
                    settings["_cache_misses"] = misses
                    save_memes_config(config)
                    if misses >= 10:
                        config[guild_str]["enabled"] = False
                        settings.pop("_cache_misses", None)
                        save_memes_config(config)
                        print(f"[Watchdog] Memes Channel {ch_id} 10x nicht gefunden - deaktiviert")
                    else:
                        print(f"[Watchdog] Memes Channel {ch_id} Cache-Miss ({misses}/10)")
                else:
                    settings.pop("_cache_misses", None)
    
    mc_config = load_membercount_config()
    for guild_str, settings in mc_config.items():
        ch_id = settings.get("channel_id")
        if ch_id:
            channel = bot.get_channel(ch_id)
            if not channel:
                print(f"[Watchdog] MemberCount Channel {ch_id} verschwunden!")
    
    voice_channels = list(voice_channel_owners.keys())
    for ch_id in voice_channels:
        channel = bot.get_channel(ch_id)
        if not channel:
            for guild in bot.guilds:
                channel = guild.get_channel(ch_id)
                if channel:
                    break
        if not channel:
            voice_channel_owners.pop(ch_id, None)
            voice_channel_settings.pop(ch_id, None)
    
    print(f"[Watchdog] Health Check OK - Uptime: {recovery.get_uptime()}")

@watchdog_task.before_loop
async def before_watchdog():
    await bot.wait_until_ready()

async def safe_api_call(coro_func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = e.retry_after if hasattr(e, 'retry_after') else (2 ** attempt)
                print(f"[RateLimit] Warte {retry_after}s (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(retry_after)
            else:
                raise
        except asyncio.TimeoutError:
            print(f"[Timeout] Attempt {attempt+1}/{max_retries}")
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    return None

def setup_exception_handlers():
    loop = asyncio.get_event_loop()
    
    # ==========================================
    # 1. GLOBAL UNHANDLED EXCEPTION HANDLER
    #    (fÃ¤ngt ALLE unerwarteten Fehler ab)
    # ==========================================
    def global_exception_handler(loop, context):
        exception = context.get("exception")
        msg = context.get("message", "Unbekannter Fehler")
        
        error_detail = f"{msg}"
        if exception:
            error_detail = f"{type(exception).__name__}: {exception}"
        
        print(f"\n{'='*60}")
        print(f"[UNHANDLED] {msg}")
        if exception:
            print(f"[UNHANDLED] Typ: {error_detail}")
            traceback.print_exception(type(exception), exception, exception.__traceback__)
        print(f"{'='*60}")
        
        # Webhook senden
        try:
            tb = traceback.format_exc() if exception else msg
            asyncio.ensure_future(send_error_webhook(
                "AsyncIO Unhandled Exception",
                f"{error_detail}\n\n{tb}",
                "global_exception_handler"
            ))
        except: pass
        
        # Configs sofort sichern
        try:
            save_all_configs_to_disk()
            print("[UNHANDLED] Configs gespeichert")
        except Exception as save_err:
            print(f"[UNHANDLED] Config-Save fehlgeschlagen: {save_err}")
        
        # Versuch Git-Push
        try:
            import subprocess
            subprocess.run(["git", "add", "data/"], capture_output=True, timeout=10)
            result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True, timeout=10)
            if result.returncode != 0:
                subprocess.run(["git", "commit", "-m", "crash: unhandled exception backup"], 
                             capture_output=True, timeout=15)
                subprocess.run(["git", "push"], capture_output=True, timeout=30)
                print("[UNHANDLED] Git-Push nach Crash erfolgreich")
        except Exception as git_err:
            print(f"[UNHANDLED] Git-Push fehlgeschlagen: {git_err}")
    
    loop.set_exception_handler(global_exception_handler)
    
    # ==========================================
    # 2. SYS.EXCEPTHOOK (Python-Level Errors)
    #    FÃ¤ngt Fehler ab die aus dem Loop fallen
    # ==========================================
    import sys
    
    _original_excepthook = sys.excepthook
    
    def enhanced_excepthook(exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            _original_excepthook(exc_type, exc_value, exc_tb)
            return
        
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        
        print(f"\n{'='*60}")
        print(f"[SYS_EXCEPTHOOK] Unhandled Python Exception")
        print(f"[SYS_EXCEPTHOOK] Typ: {exc_type.__name__}: {exc_value}")
        if exc_tb:
            traceback.print_exception(exc_type, exc_value, exc_tb)
        print(f"{'='*60}")
        
        # Webhook senden
        try:
            asyncio.ensure_future(send_error_webhook(
                "Python Unhandled Exception",
                f"{exc_type.__name__}: {exc_value}\n\n{tb_str}",
                "sys.excepthook"
            ))
        except: pass
        
        # Configs sichern
        try:
            save_all_configs_to_disk()
        except: pass
        
        # Git-Push
        try:
            import subprocess
            subprocess.run(["git", "add", "data/"], capture_output=True, timeout=10)
            result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True, timeout=10)
            if result.returncode != 0:
                subprocess.run(["git", "commit", "-m", "crash: excepthook backup"], 
                             capture_output=True, timeout=15)
                subprocess.run(["git", "push"], capture_output=True, timeout=30)
        except: pass
        
        # Original Handler aufrufen
        _original_excepthook(exc_type, exc_value, exc_tb)
    
    sys.excepthook = enhanced_excepthook
    
    # ==========================================
    # 3. ASYNCIO TASKS: Unguarded Exceptions
    #    Tasks die unerwartete Exceptions werfen
    # ==========================================
    original_create_task = loop.create_task
    
    def tracked_create_task(coro, *, name=None, **kwargs):
        task = original_create_task(coro, name=name, **kwargs)
        
        def task_exception_handler(t):
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                task_name = name or getattr(coro, '__name__', str(coro))
                tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                
                print(f"\n{'='*60}")
                print(f"[TASK_CRASH] Task '{task_name}' abgestÃ¼rzt!")
                print(f"[TASK_CRASH] {type(exc).__name__}: {exc}")
                traceback.print_exception(type(exc), exc, exc.__traceback__)
                print(f"{'='*60}")
                
                # Webhook senden
                try:
                    asyncio.ensure_future(send_error_webhook(
                        f"Task Crash: {task_name}",
                        f"{type(exc).__name__}: {exc}\n\n{tb_str}"
                    ))
                except: pass
                
                # Configs sichern
                try:
                    save_all_configs_to_disk()
                except: pass
        
        task.add_done_callback(task_exception_handler)
        return task
    
    loop.create_task = tracked_create_task
    
    # ==========================================
    # 4. SAFE RUN WRAPPER
    # ==========================================
    original_run = bot.run
    def safe_run(token):
        try:
            original_run(token)
        except Exception as e:
            print(f"[SafeRun] Bot-Fehler: {e}")
            traceback.print_exc()
    
    bot.run = safe_run

# =====================================
# CRASH-RESILIENCE: Graceful Shutdown
# =====================================

import signal

_shutdown_requested = False

async def graceful_shutdown(sig_name):
    """Sauberes Herunterfahren bei SIGTERM/SIGINT"""
    global _shutdown_requested
    if _shutdown_requested:
        return
    _shutdown_requested = True
    
    print(f"\n[Shutdown] {sig_name} empfangen - fahre sauber herunter...")
    
    # 1. Tasks stoppen
    try:
        tasks_to_stop = []
        for task_name in ["auto_save_data", "update_live_leaderboard", 
                          "auto_memes_task",
                          "membercount_refresh", "watchdog_task", "daily_config_backup"]:
            try:
                task_obj = globals().get(task_name)
                if task_obj and hasattr(task_obj, 'is_running') and task_obj.is_running():
                    tasks_to_stop.append((task_name, task_obj))
            except: pass
        
        for name, task in tasks_to_stop:
            try:
                task.cancel()
                print(f"[Shutdown] Task {name} gestoppt")
            except: pass
        
        # Warte kurz damit Tasks aufrÃ¤umen kÃ¶nnen
        if tasks_to_stop:
            await asyncio.sleep(2)
    except: pass
    
    # 2. Alle Configs sofort speichern
    try:
        save_all_configs_to_disk()
        print("[Shutdown] Alle Configs gespeichert")
    except: pass
    
    # 3. Git-Push wenn mÃ¶glich
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "add", "data/",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--cached", "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        
        if proc.returncode != 0:
            proc = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", "shutdown: auto-save before exit",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            
            proc = await asyncio.create_subprocess_exec(
                "git", "push",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            print("[Shutdown] Git-Push erfolgreich")
    except: pass
    
    # 4. Bot schlieÃŸen
    try:
        await bot.close()
        print("[Shutdown] Bot geschlossen")
    except: pass

def handle_signal(sig_name):
    """Signal-Handler (wird in thread aufgerufen)"""
    print(f"\n[Signal] {sig_name} empfangen")
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(graceful_shutdown(sig_name))

# =====================================
# CRASH-RESILIENCE: Health-Check
# =====================================

import psutil

@tasks.loop(minutes=2)
@crash_resilient_task
async def health_monitor():
    """Ãœberwacht Speicher und Performance"""
    try:
        process = psutil.Process()
        mem_mb = process.memory_info().rss / 1024 / 1024
        cpu_pct = process.cpu_percent(interval=1)
        
        # Warnung bei hohem Speicher
        if mem_mb > 400:
            print(f"[Health] WARN: Speicher hoch: {mem_mb:.0f}MB")
        
        # Bei kritischem Speicher: Configs sofort sichern
        if mem_mb > 500:
            print(f"[Health] KRITISCH: {mem_mb:.0f}MB - sichere Configs!")
            try:
                save_all_configs_to_disk()
            except: pass
        
        # Status alle 10 Minuten loggen
        if health_monitor.current_loop % 5 == 0:
            print(f"[Health] OK - Memory: {mem_mb:.0f}MB, CPU: {cpu_pct:.1f}%")
    except:
        pass

@health_monitor.before_loop
async def before_health_monitor():
    await bot.wait_until_ready()

# =====================================
# MAIN / ON_READY (Tasks starten)
# =====================================

import traceback
from recovery import RecoveryManager

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("FEHLER: DISCORD_TOKEN nicht gesetzt!")
        exit(1)
    
    setup_exception_handlers()
    
    # Signal-Handler registrieren (funktioniert nur im Hauptthread)
    try:
        signal.signal(signal.SIGTERM, lambda s, f: handle_signal("SIGTERM"))
        signal.signal(signal.SIGINT, lambda s, f: handle_signal("SIGINT"))
        print("[BOT] Signal-Handler registriert (SIGTERM/SIGINT)")
    except Exception as e:
        print(f"[BOT] Signal-Handler Fehler: {e}")
    
    while True:
        try:
            print("[BOT] Starte Bot...")
            bot.run(TOKEN)
        except KeyboardInterrupt:
            print("[BOT] Manueller Abbruch")
            break
        except Exception as e:
            print(f"[BOT] CRASH: {e}")
            traceback.print_exc()
            print("[BOT] Neustart in 10 Sekunden...")
            time.sleep(10)
