# DISCORD BOT - NOTFALL KONTEXT

## WICHTIG: Wenn Server/Deploy neu aufgesetzt werden muss

### Datenstruktur
Alle Bot-Daten liegen in `data/` als JSON-Dateien:

| Datei | Inhalt |
|-------|--------|
| `*.json` (Channel-IDs) | Gespeicherte GIF/Video-Links pro Channel |
| `memes_config.json` | Auto-Memes Config (Quelle, Interval, Channel) |
| `memes_votes.json` | Stimmen fuer Fragen des Tages |
| `fragen_config.json` | Frage-des-Tages Config |
| `fragen_custom.json` | Eigene Fragen |
| `fragen_messages.json` | Message-IDs der aktuellen Fragen |
| `reaction_roles.json` | Reaction-Roles (Button -> Rolle) |
| `tiktok_mode.json` | TikTok Auto-Download Config |
| `level_data.json` | User-Level und XP |
| `level_config.json` | Level-System Config |
| `leaderboard_messages.json` | Live-Leaderboard Message-IDs |
| `voice_setup.json` | Voice-Channel-Lobby Config |
| `ticket_config.json` | Ticket-System Config |
| `tickets.json` | Ticket-Daten |

### Auto-Save
Der Bot speichert alle 30 Minuten automatisch die `data/` nach GitHub.
Bei jedem Deploy laedt Railway die neuesten Daten von GitHub.

### Falls neu deployed werden muss:
1. GitHub Repo klonen
2. `.env` mit DISCORD_TOKEN anlegen
3. Railway mit GitHub Repo verbinden
4. Fertig - alle Daten sind da

### Commands Quick-Reference

**GIF-System:**
- `/add` - Links hinzufuegen
- `/start` - Senden starten
- `/size 4` - 4 pro Nachricht
- `/embedvideos` - Video-Embed AN/AUS

**Auto-Memes:**
- `/memessetup channel:#channel quelle:interpol`
- `/memesinterval stunden:5`
- `/memesskip`

**Frage des Tages:**
- `/fragesetup channel:#channel anzeige:embed`
- `/frageskip`
- `/frageresults`

**TikTok:**
- `/tiktokmode` - Service waehlen
- `/tiktoktoggle` - AN/AUS

**Level:**
- `/setlevelchannel` - Channel setzen
- `/setleaderboard` - Live-Leaderboard Channel

**Tickets:**
- `/ticketsetup` - Ticket-System einrichten

### Tech Stack
- Python 3.12 + discord.py
- Railway Hosting (24/7)
- GitHub fuer Code + Daten-Backup
- Interpol.cc API fuer Videos
- Reddit/Imgur API fuer Memes
