# Discord GIF Bot Setup

## 1. Bot erstellen auf Discord Developer Portal

1. Gehe zu https://discord.com/developers/applications
2. Klicke "New Application" → Name vergeben → "Create"
3. Gehe zu "Bot" auf der linken Seite
4. Klicke "Add Bot"
5. Unter "Privileged Gateway Intents" → **Message Content Intent** einschalten
6. Kopiere das Token (klicke "Reset Token" wenn nötig)

## 2. Bot einladen

1. Gehe zu "OAuth2" → "URL Generator"
2. Bei "Scopes" → **bot** + **applications.commands** auswählen
3. Bei "Bot Permissions" → **Send Messages**, **Read Message History**, **View Channels** auswählen
4. Kopiere die generierte URL und öffne sie im Browser
5. Wähle deinen Server aus und bestätige

## 3. Bot starten

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Token einfügen
# Öffne bot.py und trage dein Token ein (Zeile ganz unten):
# TOKEN = "DEIN_BOT_TOKEN_HIER"

# Bot starten
python bot.py
```

## 4. Bot Commands

| Command | Was es macht |
|---------|--------------|
| `/add [links]` | Fügt Links hinzu (oder ganzen Discord-Chat-Export) |
| `/start` | Startet das Senden (4 GIFs pro Nachricht) |
| `/stop` | Stoppt das Senden |
| `/next` | Sendet die nächsten 4 GIFs manuell |
| `/status` | Zeigt Stand an (gesendet/übrig) |
| `/pos [zahl]` | Setzt Position manuell |
| `/list` | Zeigt erste + letzte 5 Links |
| `/clear` | Löscht die komplette Liste |

## 5. Nutzung

1. `/add` mit deinen Links oder Discord-Chat-Export ausführen
2. `/start` um automatisch 4 GIFs pro Nachricht zu senden
3. Bot wartet 2 Sekunden zwischen jeder Nachricht (gegen Rate-Limits)
4. `/stop` zum Stoppen, `/next` für einzelne Schritte
