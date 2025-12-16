import discord
from discord.ext import commands
from discord import app_commands
import requests
import os
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================
SERVER = "mocha"
NG_API_BASE = "https://publicapi.nationsglory.fr"

NG_API_KEY = os.getenv("NG_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# =====================================================
# API NATIONSGLOBAL
# =====================================================
class NationsGloryAPI:
    def __init__(self, api_key: str):
        self.headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    def get_countries(self):
        try:
            url = f"{NG_API_BASE}/countries/{SERVER}"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print("❌ Erreur API NG :", e)
            return []


ng_api = NationsGloryAPI(NG_API_KEY)


# =====================================================
# READY
# =====================================================
@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    await bot.tree.sync()


# =====================================================
# COMMANDE MANUELLE /souspower
# =====================================================
@bot.tree.command(
    name="souspower",
    description="Affiche les pays en sous-power sur MOCHA (claims > power)"
)
async def souspower(interaction: discord.Interaction):
    await interaction.response.defer()

    countries = ng_api.get_countries()
    underpower = []

    for country in countries:
        power = int(country.get("power") or 0)
        claims = int(country.get("count_claims") or 0)

        # 🔴 LOGIQUE OFFICIELLE
        if claims > power:
            underpower.append({
                "name": country["name"],
                "power": power,
                "claims": claims,
                "diff": power - claims
            })

    # Tri par déficit (le plus négatif en premier)
    underpower.sort(key=lambda x: x["diff"])

    embed = discord.Embed(
        title="📉 Pays en sous-power — MOCHA",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )

    if not underpower:
        embed.description = "⚠️ Aucun pays en sous-power selon l’API"
    else:
        for c in underpower:
            embed.add_field(
                name=c["name"],
                value=(
                    f"Claims : `{c['claims']:,}`\n"
                    f"Power  : `{c['power']:,}`\n"
                    f"Diff   : `{c['diff']:,}`"
                ),
                inline=False
            )

    await interaction.followup.send(embed=embed)


# =====================================================
# LANCEMENT DU BOT
# =====================================================
if __name__ == "__main__":
    if not NG_API_KEY or not DISCORD_TOKEN:
        print("❌ NG_API_KEY ou DISCORD_TOKEN manquant")
    else:
        bot.run(DISCORD_TOKEN)
