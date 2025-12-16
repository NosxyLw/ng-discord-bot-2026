import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
from datetime import datetime
import os

# Configuration
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Variables globales
NG_API_KEY = os.getenv("NG_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NG_API_BASE = "https://publicapi.nationsglory.fr"

# Channels configurés
list_channel_id = None  # Channel pour la liste (mise à jour toutes les 10 min)
alert_channel_id = None  # Channel pour les alertes
list_message_id = None  # ID du message de liste à éditer

underpower_cache = {}
SERVERS = ["blue", "red", "green", "yellow"]


class NGApi:
    """Classe pour gérer les appels à l'API NationsGlory"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    
    def get_country_info(self, server: str, country_name: str):
        """Récupère les infos d'un pays sur un serveur"""
        try:
            url = f"{NG_API_BASE}/country/{server}/{country_name}"
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Erreur API pour {country_name} sur {server}: {e}")
            return None
    
    def get_all_countries_on_server(self, server: str):
        """Récupère tous les pays d'un serveur"""
        try:
            url = f"{NG_API_BASE}/countries/{server}"
            response = requests.get(url, headers=self.headers)
            
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Erreur API pour le serveur {server}: {e}")
            return []


ng_api = NGApi(NG_API_KEY)


@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}")
    print(f"📊 Serveurs Discord: {len(bot.guilds)}")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées")
    except Exception as e:
        print(f"❌ Erreur sync: {e}")
    
    if not update_underpower_list.is_running():
        update_underpower_list.start()
        print("✅ Monitoring liste démarré (toutes les 10 min)")
    
    if not check_underpower_alerts.is_running():
        check_underpower_alerts.start()
        print("✅ Monitoring alertes démarré (toutes les 5 min)")


@bot.tree.command(name="setup_list", description="Configure le channel pour la liste sous-power")
@app_commands.describe(channel="Canal où afficher la liste")
async def setup_list(interaction: discord.Interaction, channel: discord.TextChannel):
    """Configure le canal pour la liste mise à jour automatiquement"""
    global list_channel_id, list_message_id
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu dois être administrateur!", ephemeral=True)
        return
    
    list_channel_id = channel.id
    list_message_id = None  # Reset le message
    
    embed = discord.Embed(
        title="✅ Liste configurée",
        description=f"La liste sera mise à jour dans {channel.mention} toutes les **10 minutes**.",
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup_alerts", description="Configure le channel pour les alertes")
@app_commands.describe(channel="Canal où envoyer les alertes")
async def setup_alerts(interaction: discord.Interaction, channel: discord.TextChannel):
    """Configure le canal pour recevoir les alertes automatiques"""
    global alert_channel_id
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu dois être administrateur!", ephemeral=True)
        return
    
    alert_channel_id = channel.id
    
    embed = discord.Embed(
        title="✅ Alertes configurées",
        description=f"Les alertes seront envoyées dans {channel.mention} quand un pays passe en sous-power.",
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="force_update", description="Force la mise à jour immédiate de la liste")
async def force_update(interaction: discord.Interaction):
    """Force une mise à jour immédiate de la liste"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu dois être administrateur!", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    if not list_channel_id:
        await interaction.followup.send("❌ Configure d'abord le channel avec `/setup_list`!")
        return
    
    await update_underpower_list()
    await interaction.followup.send("✅ Liste mise à jour!")


@bot.tree.command(name="check_power", description="Vérifie le power d'un pays")
@app_commands.describe(
    serveur="Serveur NG (blue/red/green/yellow)",
    pays="Nom du pays à vérifier"
)
@app_commands.choices(serveur=[
    app_commands.Choice(name="Blue", value="blue"),
    app_commands.Choice(name="Red", value="red"),
    app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Yellow", value="yellow")
])
async def check_power(interaction: discord.Interaction, serveur: str, pays: str):
    """Commande pour vérifier le power d'un pays spécifique"""
    await interaction.response.defer()
    
    country_data = ng_api.get_country_info(serveur, pays.lower())
    
    if not country_data or "error" in country_data:
        await interaction.followup.send(f"❌ Pays `{pays}` introuvable sur le serveur **{serveur.upper()}**!")
        return
    
    name = country_data.get("name", pays)
    power = country_data.get("power", 0)
    claim = country_data.get("claim", 0)
    capital = country_data.get("capital", "N/A")
    leader = country_data.get("leader", "N/A")
    
    is_underpower = power < claim
    difference = power - claim
    
    server_colors = {
        "blue": discord.Color.blue(),
        "red": discord.Color.red(),
        "green": discord.Color.green(),
        "yellow": discord.Color.gold()
    }
    
    embed_color = discord.Color.red() if is_underpower else server_colors.get(serveur, discord.Color.blue())
    
    embed = discord.Embed(
        title=f"🏴 {name}",
        description=f"Serveur: **{serveur.upper()}**",
        color=embed_color,
        timestamp=datetime.now()
    )
    
    embed.add_field(name="⚡ Power", value=f"`{power:,}`", inline=True)
    embed.add_field(name="🗺️ Claim", value=f"`{claim:,}`", inline=True)
    embed.add_field(name="📈 Différence", value=f"`{difference:,}`", inline=True)
    
    embed.add_field(name="🏛️ Capitale", value=f"`{capital}`", inline=True)
    embed.add_field(name="👑 Leader", value=f"`{leader}`", inline=True)
    
    if is_underpower:
        embed.add_field(
            name="⚠️ Statut",
            value=f"**SOUS-POWER** (déficit: {abs(difference):,})",
            inline=False
        )
    else:
        embed.add_field(
            name="✅ Statut",
            value="Power suffisant",
            inline=False
        )
    
    await interaction.followup.send(embed=embed)


@tasks.loop(minutes=10)
async def update_underpower_list():
    """Met à jour la liste des pays en sous-power toutes les 10 minutes"""
    global list_channel_id, list_message_id
    
    if not list_channel_id:
        return
    
    channel = bot.get_channel(list_channel_id)
    if not channel:
        return
    
    print(f"🔄 Mise à jour de la liste à {datetime.now().strftime('%H:%M:%S')}")
    
    all_underpower = []
    
    for server in SERVERS:
        countries = ng_api.get_all_countries_on_server(server)
        
        for country in countries:
            name = country.get("name", "Inconnu")
            power = country.get("power", 0)
            claim = country.get("claim", 0)
            
            if power < claim:
                deficit = claim - power
                all_underpower.append({
                    "server": server,
                    "name": name,
                    "power": power,
                    "claim": claim,
                    "deficit": deficit
                })
    
    # Trier par déficit
    all_underpower.sort(key=lambda x: x["deficit"], reverse=True)
    
    # Créer l'embed
    embed = discord.Embed(
        title="⚠️ Pays en Sous-Power",
        description=f"**{len(all_underpower)} pays** actuellement en sous-power",
        color=discord.Color.orange(),
        timestamp=datetime.now()
    )
    
    if not all_underpower:
        embed.description = "✅ **Aucun pays en sous-power**"
        embed.color = discord.Color.green()
    else:
        server_emoji = {
            "blue": "🔵",
            "red": "🔴",
            "green": "🟢",
            "yellow": "🟡"
        }
        
        # Grouper par serveur
        for server in SERVERS:
            server_countries = [c for c in all_underpower if c["server"] == server]
            
            if server_countries:
                emoji = server_emoji.get(server, "⚪")
                text_list = []
                
                for country in server_countries[:10]:  # Max 10 par serveur
                    text_list.append(
                        f"**{country['name']}**: `{country['power']:,}` / `{country['claim']:,}` (Déficit: `{country['deficit']:,}`)"
                    )
                
                field_text = "\n".join(text_list)
                if len(server_countries) > 10:
                    field_text += f"\n*+ {len(server_countries) - 10} autres...*"
                
                embed.add_field(
                    name=f"{emoji} {server.upper()} ({len(server_countries)})",
                    value=field_text,
                    inline=False
                )
    
    embed.set_footer(text="Prochaine mise à jour dans 10 minutes")
    
    # Éditer ou créer le message
    try:
        if list_message_id:
            try:
                message = await channel.fetch_message(list_message_id)
                await message.edit(embed=embed)
            except discord.NotFound:
                # Message supprimé, en créer un nouveau
                message = await channel.send(embed=embed)
                list_message_id = message.id
        else:
            message = await channel.send(embed=embed)
            list_message_id = message.id
    except Exception as e:
        print(f"❌ Erreur mise à jour liste: {e}")


@tasks.loop(minutes=5)
async def check_underpower_alerts():
    """Vérifie les nouveaux pays en sous-power pour les alertes"""
    global alert_channel_id, underpower_cache
    
    if not alert_channel_id:
        return
    
    channel = bot.get_channel(alert_channel_id)
    if not channel:
        return
    
    current_underpower = {}
    
    for server in SERVERS:
        countries = ng_api.get_all_countries_on_server(server)
        
        for country in countries:
            name = country.get("name")
            power = country.get("power", 0)
            claim = country.get("claim", 0)
            
            if power < claim:
                key = f"{server}_{name}"
                current_underpower[key] = {
                    "server": server,
                    "name": name,
                    "power": power,
                    "claim": claim,
                    "deficit": claim - power
                }
    
    # Nouveaux pays en sous-power
    new_underpower = set(current_underpower.keys()) - set(underpower_cache.keys())
    
    for key in new_underpower:
        data = current_underpower[key]
        
        server_colors = {
            "blue": discord.Color.blue(),
            "red": discord.Color.red(),
            "green": discord.Color.green(),
            "yellow": discord.Color.gold()
        }
        
        embed = discord.Embed(
            title="🚨 ALERTE SOUS-POWER",
            description=f"**{data['name']}** est passé en sous-power sur **{data['server'].upper()}**!",
            color=server_colors.get(data['server'], discord.Color.orange()),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="⚡ Power", value=f"`{data['power']:,}`", inline=True)
        embed.add_field(name="🗺️ Claim", value=f"`{data['claim']:,}`", inline=True)
        embed.add_field(name="📉 Déficit", value=f"`{data['deficit']:,}`", inline=True)
        
        await channel.send(embed=embed)
        print(f"🚨 Alerte envoyée pour {data['name']} ({data['server']})")
    
    underpower_cache = current_underpower


@update_underpower_list.before_loop
async def before_update_list():
    await bot.wait_until_ready()


@check_underpower_alerts.before_loop
async def before_check_alerts():
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not NG_API_KEY or not DISCORD_TOKEN:
        print("❌ Erreur: Variables d'environnement manquantes!")
        print("Configure NG_API_KEY et DISCORD_TOKEN")
    else:
        bot.run(DISCORD_TOKEN)