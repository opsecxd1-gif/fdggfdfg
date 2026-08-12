import json
import os
import time
import asyncio
import tempfile
import traceback
from pathlib import Path
from datetime import datetime

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

class AtomicJSON:
    @staticmethod
    def load(filepath):
        path = Path(filepath)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            backup = path.with_suffix(".json.bak")
            if backup.exists():
                try:
                    with open(backup, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    print(f"[AtomicJSON] Backup von {path.name} wiederhergestellt")
                    return data
                except:
                    pass
            print(f"[AtomicJSON] KORRUPT: {path.name} - {e}")
            return {}

    @staticmethod
    def save(filepath, data):
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = path.with_suffix(".json.bak")
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    old_data = f.read()
                with open(backup, "w", encoding="utf-8") as f:
                    f.write(old_data)
        except:
            pass
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".tmp",
                dir=str(path.parent),
                delete=False, encoding="utf-8"
            )
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, str(path))
        except Exception as e:
            print(f"[AtomicJSON] FEHLER beim Schreiben von {path.name}: {e}")
            try:
                os.remove(tmp.name)
            except:
                pass
            raise

class RecoveryManager:
    def __init__(self, bot):
        self.bot = bot
        self.start_time = None
        self.last_heartbeat = None
        self.health_status = {}
        self._recovery_log = []

    def log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] [{level}] {msg}"
        self._recovery_log.append(entry)
        if len(self._recovery_log) > 200:
            self._recovery_log = self._recovery_log[-200:]
        if level == "ERROR":
            print(f"[Recovery] {entry}")
        else:
            print(f"[Recovery] {entry}")

    async def startup_sequence(self):
        self.start_time = time.time()
        self.log("=== STARTUP SEQUENZ GESTARTET ===")
        
        await self._load_all_configs()
        await self._validate_channels()
        await self._reconcile_voice_state()
        
        self.log("=== STARTUP SEQUENZ ABGESCHLOSSEN ===")

    async def _load_all_configs(self):
        self.log("Lade alle Configs...")
        
        try:
            self.bot.tiktok_mode = AtomicJSON.load(DATA_DIR / "tiktok_mode.json")
            self.log("TikTok Mode geladen", "OK")
        except Exception as e:
            self.log(f"TikTok Mode Fehler: {e}", "ERROR")
        
        try:
            self.bot.automod_config = AtomicJSON.load(DATA_DIR / "automod.json")
            self.log("Automod Config geladen", "OK")
        except Exception as e:
            self.log(f"Automod Config Fehler: {e}", "ERROR")
        
        try:
            raw_owners = AtomicJSON.load(DATA_DIR / "voice_owners.json")
            self.bot.voice_channel_owners = {int(k): int(v) for k, v in raw_owners.items()}
            raw_settings = AtomicJSON.load(DATA_DIR / "voice_settings.json")
            self.bot.voice_channel_settings = {int(k): v for k, v in raw_settings.items()}
            self.log(f"Voice Owners geladen: {len(self.bot.voice_channel_owners)} Channels", "OK")
        except Exception as e:
            self.log(f"Voice Owners Fehler: {e}", "ERROR")
        
        self.health_status["configs"] = "loaded"

    async def _validate_channels(self):
        self.log("Validiere konfigurierte Channels...")
        
        try:
            memes_config = AtomicJSON.load(DATA_DIR / "memes_config.json")
            for guild_str, settings in memes_config.items():
                if settings.get("enabled"):
                    ch_id = settings.get("channel_id")
                    if ch_id:
                        channel = self.bot.get_channel(ch_id)
                        if not channel:
                            self.log(f"Memes Channel {ch_id} NICHT GEFUNDEN fuer Guild {guild_str}", "ERROR")
                            memes_config[guild_str]["enabled"] = False
                            AtomicJSON.save(DATA_DIR / "memes_config.json", memes_config)
                        else:
                            self.log(f"Memes Channel {channel.name} OK", "OK")
        except Exception as e:
            self.log(f"Memes Validation Fehler: {e}", "ERROR")
        
        try:
            fragen_config = AtomicJSON.load(DATA_DIR / "fragen_config.json")
            for guild_str, settings in fragen_config.items():
                if settings.get("enabled"):
                    ch_id = settings.get("channel_id")
                    if ch_id:
                        channel = self.bot.get_channel(ch_id)
                        if not channel:
                            self.log(f"Frage Channel {ch_id} NICHT GEFUNDEN", "ERROR")
                            fragen_config[guild_str]["enabled"] = False
                            AtomicJSON.save(DATA_DIR / "fragen_config.json", fragen_config)
                        else:
                            self.log(f"Frage Channel {channel.name} OK", "OK")
        except Exception as e:
            self.log(f"Frage Validation Fehler: {e}", "ERROR")
        
        try:
            mc_config = AtomicJSON.load(DATA_DIR / "membercount_config.json")
            for guild_str, settings in mc_config.items():
                ch_id = settings.get("channel_id")
                if ch_id:
                    channel = self.bot.get_channel(ch_id)
                    if not channel:
                        self.log(f"MemberCount Channel {ch_id} NICHT GEFUNDEN", "ERROR")
                    else:
                        self.log(f"MemberCount Channel {channel.name} OK", "OK")
        except Exception as e:
            self.log(f"MemberCount Validation Fehler: {e}", "ERROR")
        
        self.health_status["channels"] = "validated"

    async def _reconcile_voice_state(self):
        self.log("Reconcile Voice State...")
        
        owners = self.bot.voice_channel_owners
        if not owners:
            self.log("Keine Voice Owners gespeichert", "OK")
            return
        
        cleaned = 0
        for channel_id in list(owners.keys()):
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.bot.voice_channel_owners.pop(channel_id, None)
                self.bot.voice_channel_settings.pop(channel_id, None)
                cleaned += 1
                continue
            
            if len(channel.members) == 0:
                try:
                    await channel.delete(reason="Recovery: Channel leer")
                    self.bot.voice_channel_owners.pop(channel_id, None)
                    self.bot.voice_channel_settings.pop(channel_id, None)
                    cleaned += 1
                except:
                    pass
            else:
                owner_id = owners.get(channel_id)
                owner_in_channel = any(m.id == owner_id for m in channel.members)
                if not owner_in_channel and channel.members:
                    new_owner = channel.members[0]
                    self.bot.voice_channel_owners[channel_id] = new_owner.id
                    try:
                        old_overwrites = channel.overwrites_for(self.bot.get_guild(channel.guild.id).get_member(owner_id) or self.bot.user)
                        old_overwrites.update(move_members=False, manage_channels=False, manage_permissions=False, priority_speaker=False)
                        new_overwrites = channel.overwrites_for(new_owner)
                        new_overwrites.update(
                            view_channel=True, connect=True, speak=True,
                            move_members=True, manage_channels=True,
                            manage_permissions=True, priority_speaker=True
                        )
                        await channel.set_permissions(new_owner, overwrite=new_overwrites)
                    except:
                        pass
        
        if cleaned > 0:
            AtomicJSON.save(DATA_DIR / "voice_owners.json", 
                {str(k): v for k, v in self.bot.voice_channel_owners.items()})
            AtomicJSON.save(DATA_DIR / "voice_settings.json",
                {str(k): v for k, v in self.bot.voice_channel_settings.items()})
        
        self.log(f"Voice Reconcile: {cleaned} Channels bereinigt", "OK")
        self.health_status["voice"] = "reconciled"

    async def _start_all_tasks(self):
        self.log("Tasks werden von on_ready gestartet - übersprungen", "OK")
        self.health_status["tasks"] = "managed by on_ready"

    async def _start_watchdog(self):
        self.log("Watchdog wird von on_ready gestartet - übersprungen", "OK")

    def heartbeat(self):
        self.last_heartbeat = time.time()

    def get_uptime(self):
        if not self.start_time:
            return "unbekannt"
        seconds = int(time.time() - self.start_time)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s"
