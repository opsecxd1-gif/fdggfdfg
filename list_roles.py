import requests
import json
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = "1532797083554156806"

headers = {"Authorization": f"Bot {TOKEN}"}

r = requests.get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/roles", headers=headers)
roles = r.json()

# Sort by position (highest first)
roles.sort(key=lambda x: x["position"], reverse=True)

print("=== ALLE ROLLEN (von oben nach unten) ===\n")
for i, role in enumerate(roles):
    if role["name"] == "@everyone":
        continue
    
    managed = "BOT" if role["managed"] else ""
    hoist = "HOIST" if role["hoist"] else ""
    color = f"#{role['color']:06x}" if role["color"] else "keine Farbe"
    
    flags = []
    if managed:
        flags.append("BOT-ROLLE")
    if hoist:
        flags.append("HOIST")
    if role["permissions"] != "0":
        flags.append(f"PERMS: {role['permissions']}")
    
    flag_str = f" [{', '.join(flags)}]" if flags else ""
    
    print(f"{i}. {role['name']} (ID: {role['id']}) - {color}{flag_str}")

print(f"\nGesamt: {len([r for r in roles if r['name'] != '@everyone'])} Rollen")
