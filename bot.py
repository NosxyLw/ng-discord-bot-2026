import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
from datetime import datetime
import os

# Configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Variables globales
NG_API_KEY = os.getenv("NG_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NG_API_BASE = "https://publicapi.nationsglory.fr"

alert_channel_id = None
underpower_cache = {}

# Liste des serveurs NG
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
    
    if not check_underpower.is_running():
        check_underpower.start()
        print("✅ Monitoring automatique démarré")


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
    
    # Extraction des données
    name = country_data.get("name", pays)
    power = country_data.get("power", 0)
    claim = country_data.get("claim", 0)
    capital = country_data.get("capital", "N/A")
    leader = country_data.get("leader", "N/A")
    
    is_underpower = power < claim
    difference = power - claim
    
    # Couleur selon le serveur
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


@bot.tree.command(name="list_underpower", description="Liste tous les pays en sous-power")
@app_commands.describe(serveur="Serveur NG (optionnel, tous par défaut)")
@app_commands.choices(serveur=[
    app_commands.Choice(name="Tous les serveurs", value="all"),
    app_commands.Choice(name="Blue", value="blue"),
    app_commands.Choice(name="Red", value="red"),
    app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Yellow", value="yellow")
])
async def list_underpower(interaction: discord.Interaction, serveur: str = "all"):
    """Liste tous les pays actuellement en sous-power"""
    await interaction.response.defer()
    
    servers_to_check = SERVERS if serveur == "all" else [serveur]
    all_underpower = []
    
    for server in servers_to_check:
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
    
    if not all_underpower:
        embed = discord.Embed(
            title="✅ Aucun pays en sous-power",
            description="Tous les pays ont suffisamment de power!",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed)
        return
    
    # Trier par déficit (du plus grave au moins grave)
    all_underpower.sort(key=lambda x: x["deficit"], reverse=True)
    
    # Créer la liste formatée
    underpower_text = []
    for country in all_underpower[:25]:  # Limite à 25 pour Discord
        server_emoji = {
            "blue": "🔵",
            "red": "🔴",
            "green": "🟢",
            "yellow": "🟡"
        }
        emoji = server_emoji.get(country["server"], "⚪")
        underpower_text.append(
            f"{emoji} **{country['name']}** ({country['server'].upper()})\n"
            f"   Power: `{country['power']:,}` / Claim: `{country['claim']:,}` | Déficit: `{country['deficit']:,}`"
        )
    
    embed = discord.Embed(
        title=f"⚠️ Pays en sous-power ({len(all_underpower)})",
        description="\n".join(underpower_text),
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    
    if len(all_underpower) > 25:
        embed.set_footer(text=f"+ {len(all_underpower) - 25} autres pays...")
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="setup_alerts", description="Configure le canal pour les alertes")
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
        description=f"Les alertes seront envoyées dans {channel.mention}\n"
                   f"Vérification automatique toutes les 5 minutes.",
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stop_alerts", description="Désactive les alertes automatiques")
async def stop_alerts(interaction: discord.Interaction):
    """Désactive les alertes automatiques"""
    global alert_channel_id
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu dois être administrateur!", ephemeral=True)
        return
    
    alert_channel_id = None
    await interaction.response.send_message("✅ Alertes désactivées")


@tasks.loop(minutes=5)
async def check_underpower():
    """Tâche automatique qui vérifie les pays en sous-power"""
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
            title="⚠️ ALERTE SOUS-POWER",
            description=f"**{data['name']}** est passé en sous-power sur **{data['server'].upper()}**!",
            color=server_colors.get(data['server'], discord.Color.orange()),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="⚡ Power", value=f"`{data['power']:,}`", inline=True)
        embed.add_field(name="🗺️ Claim", value=f"`{data['claim']:,}`", inline=True)
        embed.add_field(name="📉 Déficit", value=f"`{data['deficit']:,}`", inline=True)
        
        await channel.send(embed=embed)
    
    underpower_cache = current_underpower


@check_underpower.before_loop
async def before_check():
    """Attend que le bot soit prêt avant de démarrer la boucle"""
    await bot.wait_until_ready()


if __name__ == "__main__":
    if not NG_API_KEY or not DISCORD_TOKEN:
        print("❌ Erreur: Variables d'environnement manquantes!")
        print("Configure NG_API_KEY et DISCORD_TOKEN dans ton fichier .env")
    else:
        bot.run(DISCORD_TOKEN)