import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord import ui
import json
import re
import os
import asyncio
import tempfile
import time
from datetime import timedelta
import yt_dlp
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
        await interaction.response.send_message("Keine Berechtigung! Nur User mit der 976 Rolle können den Bot nutzen.", ephemeral=True)
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

async def download_tiktok_video(url, mode="clyppy"):
    try:
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
        
        print(f"[TikTok] Starting download: {url} (mode: {mode})")
        
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            print(f"[TikTok] Expected filename: {filename}")
            
            if not os.path.exists(filename):
                base = os.path.splitext(filename)[0]
                for ext in ['.mp4', '.webm', '.mkv', '.mov', '.mp4']:
                    if os.path.exists(base + ext):
                        filename = base + ext
                        break
            
            if not os.path.exists(filename):
                print(f"[TikTok] File not found after download!")
                return None, None
            
            file_size = os.path.getsize(filename)
            print(f"[TikTok] Downloaded: {filename} ({file_size} bytes)")
            
            if file_size < 1000:
                print(f"[TikTok] File too small, likely corrupt")
                os.remove(filename)
                return None, None
            
            final_path = str(TIKTOK_DOWNLOAD_DIR / 'tiktok_final.mp4')
            
            import shutil
            ffmpeg_path = shutil.which('ffmpeg')
            
            if not ffmpeg_path:
                print(f"[TikTok] FFmpeg NOT FOUND at all!")
                return filename, info.get('title', 'TikTok Video')
            
            print(f"[TikTok] FFmpeg found at: {ffmpeg_path}")
            
            convert_cmd = [
                ffmpeg_path, '-y', '-i', filename,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                '-c:a', 'aac', '-b:a', '96k',
                '-movflags', '+faststart',
                '-pix_fmt', 'yuv420p',
                final_path
            ]
            
            print(f"[TikTok] Converting to h264...")
            proc = await asyncio.create_subprocess_exec(
                *convert_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0 and os.path.exists(final_path):
                final_size = os.path.getsize(final_path)
                print(f"[TikTok] Converted OK: {final_path} ({final_size} bytes)")
                
                if filename != final_path and os.path.exists(filename):
                    os.remove(filename)
                return final_path, info.get('title', 'TikTok Video')
            else:
                stderr_text = stderr.decode()[-1000:] if stderr else "no stderr"
                print(f"[TikTok] FFmpeg FAILED (code {proc.returncode})")
                print(f"[TikTok] FFmpeg stderr: {stderr_text}")
                
                print(f"[TikTok] Sending original file anyway")
                return filename, info.get('title', 'TikTok Video')
    except Exception as e:
        import traceback
        print(f"[TikTok] Download EXCEPTION: {e}")
        print(f"[TikTok] Traceback: {traceback.format_exc()}")
        return None, None

@bot.tree.command(name="add", description="Füge GIF/Media-Links hinzu")
@is_admin_or_owner()
@app_commands.describe(links="Links oder Discord-Chat-Export einfügen")
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
        f"**{len(new_links)} neue Links hinzugefügt!**\n"
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
        await interaction.response.send_message("Läuft gerade nicht.", ephemeral=True)

@bot.tree.command(name="next", description="Sendet die nächsten 4 GIFs")
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
    status_text = "Läuft" if running else "Gestoppt"
    embed_mode = "AN" if video_embed_mode.get(interaction.channel_id, False) else "AUS"
    await interaction.response.send_message(
        f"**Status:** {status_text}\n"
        f"**Video-Embed:** {embed_mode}\n"
        f"**Size:** {global_batch_size}\n"
        f"**Gesamt:** {len(links)} Links\n"
        f"**Gesendet:** {idx}\n"
        f"**Uebrig:** {remaining}"
    )

@bot.tree.command(name="clear", description="Löscht die komplette Liste")
@is_admin_or_owner()
async def clear_command(interaction: discord.Interaction):
    path = get_data_file(interaction.channel_id)
    if path.exists():
        path.unlink()
    if interaction.channel_id in channel_status:
        del channel_status[interaction.channel_id]
    await interaction.response.send_message("Liste gelöscht.")

@bot.tree.command(name="embedvideos", description="Toggle: MP4/MOV als Inline-Video-Embed senden (statt Text-Link)")
@is_admin_or_owner()
async def embedvideos_command(interaction: discord.Interaction):
    current = video_embed_mode.get(interaction.channel_id, False)
    video_embed_mode[interaction.channel_id] = not current
    state = "AN" if not current else "AUS"
    icon = "✅" if not current else "❌"
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
@app_commands.describe(position="Die gewünschte Startposition")
async def pos_command(interaction: discord.Interaction, position: int):
    links = load_links(interaction.channel_id)
    if position < 0 or position >= len(links):
        await interaction.response.send_message(f"Ungültige Position. Gültig: 0-{len(links)-1}", ephemeral=True)
        return
    if interaction.channel_id not in channel_status:
        channel_status[interaction.channel_id] = {"index": 0, "running": False}
    channel_status[interaction.channel_id]["index"] = position
    await interaction.response.send_message(f"Position auf {position} gesetzt.")

@bot.tree.command(name="import", description="Lädt bis zu 10 .txt Dateien hoch, erstellt pro Datei einen Channel")
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
            results.append(f"**{file.filename}** - Übersprungen (keine .txt)")
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
                    embed = discord.Embed()
                    embed.set_video(url=url)
                    await new_channel.send(embed=embed)
                else:
                    text_links.append(url)
            if text_links:
                await new_channel.send("\n".join(text_links))
            if i + global_batch_size < len(extracted):
                await asyncio.sleep(2)
        results.append(f"**{new_channel.mention}** - {len(extracted)} Links")
    await interaction.followup.send("\n".join(results))

@bot.tree.command(name="import2", description="Lädt .txt Dateien und sendet die Links direkt in diesen Channel")
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
            results.append(f"**{file.filename}** - Übersprungen (keine .txt)")
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
                    embed = discord.Embed()
                    embed.set_video(url=url)
                    await channel.send(embed=embed)
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
    icon = "✅" if not current else "❌"
    
    if not current:
        desc = (
            f"{icon} **Filter-Modus:** {state}\n\n"
            "Behält nur: GIF, MP4, MOV, AVI, MKV, WebM, PNG, JPG, WEBP, APNG, SVG\n"
            "Entfernt: Alles andere (Text-Links, HTML-Reste, Tracking-Parameter)\n"
            "Gilt für: `/import2`, `/add`, `/load`"
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
    icon = "✅" if not current else "❌"
    
    if not current:
        desc = (
            f"{icon} **NoFilter-Modus:** {state}\n\n"
            "Jede Zeile wird als Link genommen - KEIN Filter!\n"
            "Kein URL-Check, keine Deduplizierung, keine Bereinigung\n"
            "Gilt für: `/import2`, `/add`, `/load`\n\n"
            "**Achtung:** Sendet wirklich ALLES was mit http anfängt!"
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
                description="Empfohlen - Schnell & zuverlässig",
                emoji="⭐"
            ),
            discord.SelectOption(
                label="dlbot",
                value="dlbot",
                description="Hohe Qualität, MP4 Merge",
                emoji="📥"
            ),
            discord.SelectOption(
                label="TikCord",
                value="tikcord",
                description="Alle Formate, flexibel",
                emoji="🎵"
            ),
            discord.SelectOption(
                label="QuickVids",
                value="quickvids",
                description="Schnell & simpel",
                emoji="⚡"
            ),
        ]
        super().__init__(placeholder="Wähle einen TikTok Downloader...", options=options)
    
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
            "clyppy": "Clyppy (⭐ Empfohlen)",
            "dlbot": "dlbot (📥 Hohe Qualität)",
            "tikcord": "TikCord (🎵 Flexibel)",
            "quickvids": "QuickVids (⚡ Schnell)"
        }
        
        await interaction.response.send_message(
            f"✅ **TikTok Auto-Download aktiviert!**\n\n"
            f"**Service:** {mode_names.get(mode, mode)}\n"
            f"**Status:** AN\n\n"
            f"Ab jetzt werden automatisch alle TikTok Links heruntergeladen und als Video gesendet!",
            ephemeral=True
        )

class TiktokModeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TiktokModeSelect())

@bot.tree.command(name="tiktokmode", description="TikTok Auto-Download: Wähle einen Service für automatische Downloads")
@is_admin_or_owner()
async def tiktokmode_command(interaction: discord.Interaction):
    view = TiktokModeView()
    await interaction.response.send_message(
        "**TikTok Auto-Download Konfiguration**\n\n"
        "Wähle einen Service aus:\n\n"
        "⭐ **Clyppy** - Empfohlen, schnell & zuverlässig\n"
        "📥 **dlbot** - Hohe Qualität mit MP4 Merge\n"
        "🎵 **TikCord** - Alle Formate, flexibel\n"
        "⚡ **QuickVids** - Schnell & simpel\n\n"
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
        icon = "✅" if not current else "❌"
        
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
            "Noch nicht konfiguriert! Benutze zuerst `/tiktokmode` um einen Service auszuwählen.",
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
            "clyppy": "Clyppy (⭐ Empfohlen)",
            "dlbot": "dlbot (📥 Hohe Qualität)",
            "tikcord": "TikCord (🎵 Flexibel)",
            "quickvids": "QuickVids (⚡ Schnell)"
        }
        
        status = "✅ AN" if enabled else "❌ AUS"
        
        await interaction.response.send_message(
            f"**TikTok Auto-Download Status**\n\n"
            f"**Status:** {status}\n"
            f"**Service:** {mode_names.get(mode, mode)}\n\n"
            f"{'Alle TikTok Links werden automatisch heruntergeladen!' if enabled else 'TikTok Links werden nicht automatisch verarbeitet.'}"
        )
    else:
        await interaction.response.send_message(
            "Noch nicht konfiguriert! Benutze `/tiktokmode` um einen Service auszuwählen.",
            ephemeral=True
        )

@bot.tree.command(name="clearchannels", description="Löscht alle vom Bot erstellten Channels")
@is_admin_or_owner()
async def clearchannels_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    deleted = 0
    for channel_id in list(auto_channels):
        channel = interaction.guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete(reason=f"Gelöscht via /clearchannels von {interaction.user}")
                deleted += 1
            except discord.Forbidden:
                pass
        auto_channels.discard(channel_id)
    if deleted == 0:
        await interaction.followup.send("Keine Bot-Channels zum Löschen gefunden.", ephemeral=True)
    else:
        await interaction.followup.send(f"**{deleted} Channel(s) gelöscht!**")

@bot.tree.command(name="permsync", description="Synchronisiert die Permissions aller Channels einer Kategorie mit der Kategorie")
@is_admin_or_owner()
@app_commands.describe(kategorie="Wähle eine Kategorie aus")
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
    await interaction.followup.send(f"**{updated} Rollen aktualisiert!** ({skipped} übersprungen – bereits aktiv oder keine Berechtigung)")

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
        await interaction.followup.send("Bild ist zu groß (max 8MB)!", ephemeral=True)
        return
    try:
        await bot.user.edit(avatar=image_data)
        await interaction.followup.send("Profilbild erfolgreich geändert!", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Fehler beim Ändern: {e}", ephemeral=True)

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
        await interaction.followup.send("Bild ist zu groß (max 10MB)!", ephemeral=True)
        return
    try:
        await bot.user.edit(banner=image_data)
        await interaction.followup.send("Banner erfolgreich geändert!", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"Fehler beim Ändern: {e}\n\n**Hinweis:** Banner-Änderung funktioniert nur bei verifizierten Bots.", ephemeral=True)

@bot.tree.command(name="reactionrole", description="Verwaltet Reaction-Roles (wie Carl-bot)")
@is_admin_or_owner()
@app_commands.describe(
    aktion="add, remove, list oder clear",
    message_id="Die ID der Nachricht",
    emoji="Das Emoji (z.B. 😈 oder :name:)",
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
            await interaction.followup.send("Keine Reaction-Roles für diesen Server.", ephemeral=True)
            return
        
        guild_data = reaction_roles[str(interaction.guild_id)]
        if not guild_data:
            await interaction.followup.send("Keine Reaction-Roles für diesen Server.", ephemeral=True)
            return
        
        lines = []
        for msg_id, data in guild_data.items():
            channel = bot.get_channel(data["channel_id"])
            channel_name = f"#{channel.name}" if channel else "unbekannt"
            lines.append(f"**Nachricht {msg_id}** ({channel_name}):")
            for emoji_key, role_id in data["roles"].items():
                role = interaction.guild.get_role(role_id)
                role_name = role.name if role else f"ID: {role_id}"
                lines.append(f"  {emoji_key} → {role_name}")
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
            await interaction.followup.send(f"Alle Reaction-Roles für Nachricht {message_id} gelöscht.", ephemeral=True)
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
        await interaction.followup.send("Nachricht nicht gefunden! ID prüfen.", ephemeral=True)
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
        await interaction.followup.send(f"Rolle **{role.name}** ist zu hoch für den Bot!", ephemeral=True)
        return
    
    if role.managed:
        await interaction.followup.send(f"Rolle **{role.name}** ist eine Bot-Rolle!", ephemeral=True)
        return
    
    try:
        await msg.add_reaction(emoji)
    except:
        await interaction.followup.send(f"Emoji **{emoji}** ungültig!", ephemeral=True)
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
    
    await interaction.followup.send(f"✅ {emoji} → **{role.name}** hinzugefügt!", ephemeral=True)

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
                embed = discord.Embed()
                embed.set_video(url=url)
                await channel.send(embed=embed)
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

@bot.tree.command(name="reactionsetup", description="Sendet eine Webhook-Embed mit Button für Reaction-Roles")
@is_admin_or_owner()
@app_commands.describe(
    rolle="Die Rolle (Name)",
    emoji="Das Emoji für den Button (z.B. 😈)",
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
        await interaction.followup.send(f"Rolle **{role.name}** ist zu hoch für den Bot!", ephemeral=True)
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
    "señorita", "marlboro", "sugar mommy", "casanova", "galatasaray", 
    "smile", "gengar", "durstlöscher", "uchiha", "bunny", "sonic", "kitten", 
    "emo", "rolex", "patrick", "prinzessin", "geistig", "beefer", "queen", 
    "barbie", "baby", "shiggy", "hustler", "saiyajin", "domina", "king", 
    "sadboy", "terrorist", "speedy", "ruffy", "spongebob", "engel", "uwu", 
    "habibi", "geist", "teufel", "cop", "smoker", "stoner", "alien", "senpai", 
    "superman", "türsteher", "demon", "spiderman", "moncler", "godsent", "toxic", 
    "npc", "ehrenmann", "ehrenfrau", "cute", "goofy", "og", "freund", "👑"
]

EXCLUDED_ROLE_KEYWORDS = [
    "admin", "moderator", "head admin", "teamleitung", "team", "supporter",
    "bot", "muted", "timeout", "booster", "level", "rank", "premium",
    "owner", "security", "role manager", "access", "member", "mitglied",
    "no-xp", "sendmoji", "pic", "platzhalter", "supreme", "stammuser",
    "champion", "ultimativ", "titan", "prestige", "legende", "meister",
    "veteran", "elite", "platin", "silver", "treu", "aktiv", "noob",
    "meme maker", "test", "pb master", "----", "——", "🔊", "🔞+",
    "star", "★", "*"
]

@bot.tree.command(name="masssetup", description="Erstellt Reaction-Role Buttons für ALLE User-Rollen automatisch")
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
            if role.hoist and not any(ex in role_name_lower for ex in ["----", "——", "rank", "level"]):
                if role.color.value != 0 and role.name not in ["----", "——"]:
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
                "description": f"**Wähle deine Rollen:**\n\n" + "\n".join([f"• {r.name}" for r in chunk]),
                "color": 0x5865F2,
                "author": {
                    "name": f"User Rollen ({page_num}/{total_pages})"
                },
                "footer": {
                    "text": f"Seite {page_num} von {total_pages} • {len(user_roles)} Rollen gesamt"
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
        f"**{total_buttons} Buttons** für {len(user_roles)} User-Rollen erstellt!\n"
        f"Alle funktionieren sofort - Klick = Rolle toggle!",
        ephemeral=True
    )

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
        elif role.name.startswith(("★", "*", "⭐", "Level")):
            protected_roles.append(role)
        else:
            normal_roles.append(role)
    
    if len(normal_roles) > MAX_ROLES_FOR_MITGLIED:
        to_remove = normal_roles[MAX_ROLES_FOR_MITGLIED:]
        try:
            await after.remove_roles(*to_remove, reason="Max 7 Rollen für Mitglieder")
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
                await interaction.response.send_message(f"**{role.name}** hinzugefügt!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("Keine Berechtigung!", ephemeral=True)

# =====================================
# VOICE CHANNEL MANAGEMENT SYSTEM
# =====================================

VOICE_SETUP_FILE = DATA_DIR / "voice_setup.json"
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

class VoiceChannelView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.channel_id = channel_id

    @discord.ui.button(label="Private", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="vc_private")
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
        
        button.label = "Public" if not is_private else "Private"
        button.emoji = "🌍" if not is_private else "🔒"
        
        status = "privat" if not is_private else "öffentlich"
        await interaction.response.send_message(f"Channel ist jetzt {status}!", ephemeral=True)

    @discord.ui.button(label="Hide", style=discord.ButtonStyle.secondary, emoji="👁️", custom_id="vc_hide")
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
        
        button.label = "Show" if not is_hidden else "Hide"
        
        status = "versteckt" if not is_hidden else "sichtbar"
        await interaction.response.send_message(f"Channel ist jetzt {status}!", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="vc_rename")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        await interaction.response.send_modal(RenameModal(self.channel_id))

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", custom_id="vc_kick")
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
        await interaction.response.send_message("Wähle wen du kicken möchtest:", view=view, ephemeral=True)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🚫", custom_id="vc_ban")
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

    @discord.ui.button(label="Invite", style=discord.ButtonStyle.success, emoji="🔗", custom_id="vc_invite")
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Nur der Channel-Besitzer kann das!", ephemeral=True)
            return
        
        await interaction.response.send_message(
            "Teile den Server-Invite mit Leuten die joinen sollen!",
            ephemeral=True
        )

    @discord.ui.button(label="Permit", style=discord.ButtonStyle.success, emoji="✅", custom_id="vc_permit")
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

    @discord.ui.button(label="Change Owner", style=discord.ButtonStyle.primary, emoji="👑", custom_id="vc_changeowner")
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
        await interaction.response.send_message("Wähle den neuen Besitzer:", view=view, ephemeral=True)

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
                emoji="👑"
            ) for m in members[:25]
        ]
        
        super().__init__(placeholder="Wähle den neuen Besitzer...", options=options)
    
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
        
        await interaction.response.send_message(f"Besitz an {target_member.display_name} übertragen!", ephemeral=True)

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
                emoji="👢"
            ) for m in members[:25]
        ]
        
        super().__init__(placeholder="Wähle wen du kicken möchtest...", options=options)
    
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
                emoji="🚫"
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
            "Schreib die User ID die du permiten möchtest (nur Zahlen):",
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
            f"Der Channel wird gelöscht wenn alle gehen."
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
        "➕ Join to Create",
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
            f"Es wird automatisch ein privater Channel für dich erstellt.\n"
            f"Du bekommst Buttons zum Verwalten deines Channels."
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    setup_data = load_voice_setup()
    guild_setup = setup_data.get(str(member.guild.id))
    
    if not guild_setup:
        return
    
    lobby_id = guild_setup.get("lobby_id")
    category_id = guild_setup.get("category_id")
    
    if after.channel and after.channel.id == lobby_id:
        guild = member.guild
        category = guild.get_channel(category_id)
        
        if not category:
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
        
        new_channel = await guild.create_voice_channel(
            name=f"{member.display_name}'s Chat",
            category=category,
            overwrites=overwrites
        )
        
        voice_channel_owners[new_channel.id] = member.id
        voice_channel_settings[new_channel.id] = {"private": False, "hidden": False}
        
        try:
            await member.move_to(new_channel)
        except:
            pass
        
        embed, view = await create_voice_control_embed(member, new_channel)
        try:
            await new_channel.send(embed=embed, view=view)
        except:
            pass
    
    if before.channel and before.channel.id in voice_channel_owners:
        channel = before.channel
        
        if len(channel.members) == 0:
            voice_channel_owners.pop(channel.id, None)
            voice_channel_settings.pop(channel.id, None)
            try:
                await channel.delete(reason="Channel leer")
            except:
                pass
        elif voice_channel_owners.get(channel.id) == member.id:
            new_owner = channel.members[0]
            voice_channel_owners[channel.id] = new_owner.id
            
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

@bot.tree.command(name="vc_kick", description="User aus deinem Voice Channel kicken")
async def vc_kick(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("Ungültige User ID!", ephemeral=True)
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
        await interaction.response.send_message("Ungültige User ID!", ephemeral=True)
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
        await interaction.response.send_message("Ungültige User ID!", ephemeral=True)
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

@bot.tree.command(name="vc_changeowner", description="Channel Besitz übertragen")
async def vc_changeowner(interaction: discord.Interaction, user_id: str):
    try:
        target_id = int(user_id)
    except:
        await interaction.response.send_message("Ungültige User ID!", ephemeral=True)
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
    
    await interaction.response.send_message(f"Besitz an {target_member.display_name} übertragen!", ephemeral=True)

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

def days_ago_str(days):
    from datetime import datetime, timedelta
    return (discord.utils.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

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

def get_messages_last_7_days(user_data):
    messages = user_data.get("messages", {})
    total = 0
    cutoff = days_ago_str(7)
    for date_key, count in messages.items():
        if date_key >= cutoff:
            total += count
    return total

def get_voice_last_7_days(user_data):
    voice_daily = user_data.get("voice_daily", {})
    total = 0
    cutoff = days_ago_str(7)
    for date_key, seconds in voice_daily.items():
        if date_key >= cutoff:
            total += seconds
    return total

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

def cleanup_old_dates(user_data):
    cutoff = days_ago_str(14)
    if "messages" in user_data:
        user_data["messages"] = {k: v for k, v in user_data["messages"].items() if k >= cutoff}
    if "voice_daily" in user_data:
        user_data["voice_daily"] = {k: v for k, v in user_data["voice_daily"].items() if k >= cutoff}

@bot.event
async def on_message_level_system(message):
    if message.author.bot:
        return
    if not message.guild:
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
        image_path = level_images.get(str(new_level))

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
            cleanup_old_dates(user_data)
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
            cleanup_old_dates(user_data)
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
    bar = "█" * filled + "░" * (bar_length - filled)

    msgs_7d = get_messages_last_7_days(user_data)
    voice_7d = get_voice_last_7_days(user_data)

    embed = discord.Embed(
        title=f"Level von {target.display_name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="Level", value=str(user_data["level"]), inline=True)
    embed.add_field(name="XP", value=f"{user_data['xp']}/{xp_needed}", inline=True)
    embed.add_field(name="Fortschritt", value=f"`{bar}` {progress:.1f}%", inline=False)
    embed.add_field(name="Nachrichten (7 Tage)", value=str(msgs_7d), inline=True)
    embed.add_field(name="Voice-Zeit (7 Tage)", value=format_time_full(voice_7d), inline=True)

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

            msgs_7d = get_messages_last_7_days(user_data)
            voice_7d = get_voice_last_7_days(user_data)

            if msgs_7d > 0:
                messages_ranking.append((member, msgs_7d))
            if voice_7d > 0:
                voice_ranking.append((member, voice_7d))

    messages_ranking.sort(key=lambda x: x[1], reverse=True)
    voice_ranking.sort(key=lambda x: x[1], reverse=True)

    medals = ["", "", ""]
    end_date = discord.utils.utcnow() + timedelta(days=7 - discord.utils.utcnow().weekday())

    msg_lines = []
    for i, (member, count) in enumerate(messages_ranking[:15]):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        msg_lines.append(f"{medal} {member.mention} — **{count:,}** messages")

    voice_lines = []
    for i, (member, seconds) in enumerate(voice_ranking[:15]):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        voice_lines.append(f"{medal} {member.mention} — **{format_time_short(seconds)}**")

    top_msg_user = messages_ranking[0][0].mention if messages_ranking else "Keine Daten"
    top_voice_user = voice_ranking[0][0].display_name if voice_ranking else "Keine Daten"

    embed_messages = discord.Embed(
        title=f"{guild.name} Leaderboard",
        description=f" Top Messages (Last 7 Days) — {top_msg_user}",
        color=discord.Color.red()
    )
    embed_messages.description += "\n\n**Rankings**\n"
    if msg_lines:
        embed_messages.description += "\n".join(msg_lines)
    else:
        embed_messages.description += "Noch keine Nachrichten getrackt."
    embed_messages.set_footer(text=f"Ends in {7 - discord.utils.utcnow().weekday()} days · {end_date.strftime('%m/%d/%Y 11:59 PM')}")

    embed_voice = discord.Embed(
        title=f"{guild.name} Leaderboard",
        description=f" Top Voice Time (Last 7 Days) — {top_voice_user}",
        color=discord.Color.blue()
    )
    embed_voice.description += "\n\n**Rankings**\n"
    if voice_lines:
        embed_voice.description += "\n".join(voice_lines)
    else:
        embed_voice.description += "Noch keine Voice-Zeit getrackt."
    embed_voice.set_footer(text=f"Ends in {7 - discord.utils.utcnow().weekday()} days · {end_date.strftime('%m/%d/%Y 11:59 PM')}")

    return embed_messages, embed_voice

@bot.tree.command(name="leaderboard", description="Zeigt das Leaderboard an")
async def leaderboard_command(interaction: discord.Interaction):
    embed_msg, embed_voice = build_leaderboard_embeds(interaction.guild)
    await interaction.response.send_message(embeds=[embed_msg, embed_voice])

@bot.tree.command(name="setlevelchannel", description="Setzt den Channel für Level-Up Nachrichten")
@is_admin_or_owner()
@app_commands.describe(channel="Der Channel für Level-Up Nachrichten")
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
@app_commands.describe(channel="Der Channel für das Leaderboard")
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
        f"Updatet alle 5 Minuten automatisch.",
        ephemeral=True
    )

@bot.tree.command(name="levelimage", description="Setzt ein Bild für einen bestimmten Levelaufstieg")
@is_admin_or_owner()
@app_commands.describe(level="Das Level (z.B. 5)", bild="Das Bild für diesen Level")
async def levelimage_command(interaction: discord.Interaction, level: int, bild: discord.Attachment):
    await interaction.response.defer(ephemeral=True)

    allowed_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
    if not any(bild.filename.lower().endswith(ext) for ext in allowed_exts):
        await interaction.followup.send("Nur Bilddateien erlaubt!", ephemeral=True)
        return

    image_data = await bild.read()
    if len(image_data) > 8 * 1024 * 1024:
        await interaction.followup.send("Bild ist zu groß (max 8MB)!", ephemeral=True)
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

    await interaction.followup.send(f"Bild für Level **{level}** gespeichert!", ephemeral=True)

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
        icon = "❌"
    else:
        no_xp_channels.append(interaction.channel_id)
        state = "hinzugefügt"
        icon = "✅"

    config[guild_str]["no_xp_channels"] = no_xp_channels
    save_level_config(config)
    await interaction.response.send_message(f"{icon} Dieser Channel wurde {state} (kein XP)")

@bot.tree.command(name="resetlevels", description="Setzt alle Level-Daten zurück")
@is_admin_or_owner()
async def resetlevels_command(interaction: discord.Interaction):
    data = load_level_data()
    guild_str = str(interaction.guild_id)
    if guild_str in data:
        del data[guild_str]
        save_level_data(data)
    await interaction.response.send_message("Alle Level-Daten für diesen Server zurückgesetzt!")

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

@tasks.loop(minutes=5)
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
    tiktok_mode = load_tiktok_mode()
    
    if not update_live_leaderboard.is_running():
        update_live_leaderboard.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
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
            pass
        
        mode = tiktok_mode_data[guild_id_str].get("mode", "clyppy")
        
        async with message.channel.typing():
            for url in tiktok_urls[:3]:
                try:
                    await message.add_reaction("⏳")
                    
                    filename, title = await download_tiktok_video(url, mode)
                    
                    if filename and os.path.exists(filename):
                        file_size = os.path.getsize(filename)
                        print(f"[TikTok] Sending file: {file_size} bytes")
                        
                        if file_size > 8 * 1024 * 1024:
                            await message.remove_reaction("⏳", bot.user)
                            await message.add_reaction("❌")
                            await message.reply(
                                f"❌ Video zu groß ({file_size / 1024 / 1024:.1f}MB). Discord Limit: 8MB.",
                                mention_author=False
                            )
                            os.remove(filename)
                            continue
                        
                        await message.remove_reaction("⏳", bot.user)
                        await message.add_reaction("✅")
                        
                        discord_file = discord.File(filename, filename="tiktok.mp4")
                        await message.reply(
                            file=discord_file,
                            mention_author=False
                        )
                        
                        os.remove(filename)
                    else:
                        await message.remove_reaction("⏳", bot.user)
                        await message.add_reaction("❌")
                        print(f"[TikTok] Download returned None for: {url}")
                except Exception as e:
                    print(f"[TikTok] Exception in loop: {e}")
                    try:
                        await message.remove_reaction("⏳", bot.user)
                        await message.add_reaction("❌")
                    except:
                        pass
    
    await on_message_level_system(message)
    await bot.process_commands(message)

# Override on_voice_state_update to include level system

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    setup_data = load_voice_setup()
    guild_setup = setup_data.get(str(member.guild.id))
    
    if guild_setup:
        lobby_id = guild_setup.get("lobby_id")
        category_id = guild_setup.get("category_id")
        
        if after.channel and after.channel.id == lobby_id:
            guild = member.guild
            category = guild.get_channel(category_id)
            
            if category:
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
                
                new_channel = await guild.create_voice_channel(
                    name=f"{member.display_name}'s Chat",
                    category=category,
                    overwrites=overwrites
                )
                
                voice_channel_owners[new_channel.id] = member.id
                voice_channel_settings[new_channel.id] = {"private": False, "hidden": False}
                
                try:
                    await member.move_to(new_channel)
                except:
                    pass
                
                embed, view = await create_voice_control_embed(member, new_channel)
                try:
                    await new_channel.send(embed=embed, view=view)
                except:
                    pass
        
        if before.channel and before.channel.id in voice_channel_owners:
            channel = before.channel
            
            if len(channel.members) == 0:
                voice_channel_owners.pop(channel.id, None)
                voice_channel_settings.pop(channel.id, None)
                try:
                    await channel.delete(reason="Channel leer")
                except:
                    pass
            elif voice_channel_owners.get(channel.id) == member.id:
                new_owner = channel.members[0]
                voice_channel_owners[channel.id] = new_owner.id
                
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
    
    await on_voice_state_update_level(member, before, after)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("FEHLER: DISCORD_TOKEN nicht gesetzt!")
        exit(1)
    bot.run(TOKEN)
