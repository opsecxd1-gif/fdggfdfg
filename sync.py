import discord
from discord import app_commands
import os

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@tree.command(name="setupadmin", description="Erstellt eine Admin-Rolle und gibt sie dir")
async def setupadmin_command(interaction: discord.Interaction):
    await interaction.response.send_message("Setup...")

@tree.command(name="grantadmin", description="Gibt dir die Admin-Rolle")
async def grantadmin_command(interaction: discord.Interaction):
    await interaction.response.send_message("Granting...")

@tree.command(name="giverole", description="Gibt einem User eine bestimmte Rolle")
async def giverole_command(interaction: discord.Interaction, user: discord.Member, rolename: str):
    await interaction.response.send_message("Giving...")

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    synced = await tree.sync()
    print(f"Synced {len(synced)} commands:")
    for cmd in synced:
        print(f"  - /{cmd.name}")
    await client.close()

client.run(TOKEN)
