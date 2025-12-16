import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
from datetime import datetime
import os

# =========================================================
# CONFIGURATION GLOBALE
# =========================================================
SERVER = "mocha"
UPDATE_INTERVAL = 5  # minutes
NG_API_BASE = "https://publicapi.nationsglory.fr"

NG_API_KEY = os.getenv("NG_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Channels
list_channel_id = None
alert_channel_id = None
list_message_id = None

# Cache des pays déjà en sous-power
underpower_cache = set()


# =========================================================
# CLASSE API NATIONSGLOBAL
# =========================================================
class NationsGloryAPI:
    def __init__(self, api_key: str):
        self.headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    def get_all_countries(self):
        try:
            url = f"{NG_API_BASE}/countries/{SERVER}"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print("❌ Erreur API NG:", e)
            return []


ng_api = NationsGloryAPI(NG_API_KEY)


# =========================================================
# BOT READY
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user}")
    await bot.tree.sync()

    if not underpower_loop.is_running():
        underpower_loop.start()
        print("🔄 Loop sous-power démarrée")


# =========================================================
# COMMANDES DE CONFIG
# =========================================================
@bot.tree.command(name="setup_souspower", description="Définit le channel de la liste sous-power")
async def setup_souspower(interaction: discord.Interaction, channel: discord.TextChannel):
    global list_channel_id, list_message_id
    list_channel_id = channel.id
    list_message_id = None

    await interaction.response.send_message(
        f"✅ Liste sous-power configurée dans {channel.mention}",
        ephemeral=True
    )


@bot.tree.command(name="setup_alerts", description="Définit le channel des alertes sous-power")
async def setup_alerts(interaction: discord.Interaction, channel: discord.TextChannel):
    global alert_channel_id
    alert_channel_id = channel.id

    await interaction.response.send_message(
        f"🚨 Alertes configurées dans {channel.mention}",
        ephemeral=True
    )


# =========================================================
# LOOP PRINCIPALE SOUS-POWER
# =========================================================
@tasks.loop(minutes=UPDATE_INTERVAL)
async def underpower_loop():
    global list_message_id, underpower_cache

    if not list_channel_id:
        return

    channel = bot.get_channel(list_channel_id)
    if not channel:
        return

    countries = ng_api.get_all_countries()

    underpower_list = []
    current_underpower = set()

    for country in countries:
        power = country.get("power", 0)
        claims = country.get("count_claims", 0)

        if power < claims:
            diff = power - claims
            name = country["name"]

            underpower_list.append({
                "name": name,
                "power": power,
                "claims": claims,
                "diff": diff
            })

            current_underpower.add(name)

            # 🚨 ALERTE si nouveau pays en sous-power
            if name not in underpower_cache:
                await send_underpower_alert(country)

    # Mise à jour du cache
    underpower_cache = current_underpower

    # Tri par déficit
    underpower_list.sort(key=lambda x: x["diff"])

    # =====================================================
    # EMBED LISTE CONSTANTE
    # =====================================================
    embed = discord.Embed(
        title="📉 Pays en sous-power — MOCHA",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )

    if not underpower_list:
        embed.description = "✅ Aucun pays en sous-power"
        embed.color = discord.Color.green()
    else:
        for c in underpower_list:
            embed.add_field(
                name=c["name"],
                value=(
                    f"Claims : `{c['claims']:,}`\n"
                    f"Power  : `{c['power']:,}`\n"
                    f"Diff   : `{c['diff']:,}`"
                ),
                inline=False
            )

    embed.set_footer(text=f"Mise à jour toutes les {UPDATE_INTERVAL} minutes")

    # Envoi ou édition du message unique
    try:
        if list_message_id:
            message = await channel.fetch_message(list_message_id)
            await message.edit(embed=embed)
        else:
            message = await channel.send(embed=embed)
            list_message_id = message.id
    except discord.NotFound:
        message = await channel.send(embed=embed)
        list_message_id = message.id


# =========================================================
# ALERTES
# =========================================================
async def send_underpower_alert(country: dict):
    if not alert_channel_id:
        return

    channel = bot.get_channel(alert_channel_id)
    if not channel:
        return

    power = country["power"]
    claims = country["count_claims"]
    diff = power - claims

    embed = discord.Embed(
        title="🚨 SOUS-POWER DÉTECTÉ — MOCHA",
        description=f"**{country['name']}** vient de passer en sous-power !",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )

    embed.add_field(name="Claims", value=f"`{claims:,}`", inline=True)
    embed.add_field(name="Power", value=f"`{power:,}`", inline=True)
    embed.add_field(name="Diff", value=f"`{diff:,}`", inline=True)

    await channel.send(embed=embed)


# =========================================================
# AVANT LA LOOP
# =========================================================
@underpower_loop.before_loop
async def before_underpower_loop():
    await bot.wait_until_ready()


# =========================================================
# LANCEMENT
# =========================================================
if __name__ == "__main__":
    if not NG_API_KEY or not DISCORD_TOKEN:
        print("❌ NG_API_KEY ou DISCORD_TOKEN manquant")
    else:
        bot.run(DISCORD_TOKEN)
