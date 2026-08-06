import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord import ui
import json
import re
import os
import asyncio
from pathlib import Path

intents = discord.Intents.default()
intents.message_content = True

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

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)} Commands synchronisiert")
    except Exception as e:
        print(f"Sync fehlgeschlagen: {e}")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("FEHLER: DISCORD_TOKEN nicht gesetzt!")
        exit(1)
    bot.run(TOKEN)
