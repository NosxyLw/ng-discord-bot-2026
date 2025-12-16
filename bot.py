import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
from datetime import datetime, timedelta
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
list_channel_id = None
alert_channel_id = None
list_message_id = None

# Cache pour les alertes (avec timestamp de dernière alerte)
alert_cache = {}  # Format: {key: {"data": {...}, "last_alert": datetime}}
ALERT_COOLDOWN = timedelta(hours=24)  # Re-alerter après 24h

SERVERS = ["blue", "red", "green", "yellow", "mocha"]


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
            response = requests.get(url, headers=self.headers, timeout=10)
            
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
            response = requests.get(url, headers=self.headers, timeout=10)
            
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
    list_message_id = None
    
    embed = discord.Embed(
        title="✅ Liste configurée",
        description=f"La liste sera mise à jour dans {channel.mention} toutes les **10 minutes**.",
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(embed=embed)
    
    # Lancer une première mise à jour immédiate
    await update_underpower_list()


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
        description=f"Les alertes seront envoyées dans {channel.mention}\nRe-alerte après 24h si toujours en sous-power.",
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
    serveur="Serveur NG",
    pays="Nom du pays à vérifier"
)
@app_commands.choices(serveur=[
    app_commands.Choice(name="Blue", value="blue"),
    app_commands.Choice(name="Red", value="red"),
    app_commands.Choice(name="Green", value="green"),
    app_commands.Choice(name="Yellow", value="yellow"),
    app_commands.Choice(name="Mocha", value="mocha")
])
async def check_power(interaction: discord.Interaction, serveur: str, pays: str):
    """Commande pour vérifier le power d'un pays spécifique"""
    await interaction.response.defer()
    
    country_data = ng_api.get_country_info(serveur, pays)
    
    if not country_data or "error" in country_data:
        await interaction.followup.send(f"❌ Pays `{pays}` introuvable sur le serveur **{serveur.upper()}**!")
        return
    
    name = country_data.get("name", pays)
    power = country_data.get("power", 0)
    claims = country_data.get("count_claims", 0)
    leader = country_data.get("leader", "N/A")
    members = country_data.get("count_members", 0)
    
    is_underpower = power < claims
    difference = power - claims
    
    server_colors = {
        "blue": discord.Color.blue(),
        "red": discord.Color.red(),
        "green": discord.Color.green(),
        "yellow": discord.Color.gold(),
        "mocha": discord.Color.from_rgb(139, 69, 19)
    }
    
    embed_color = discord.Color.red() if is_underpower else server_colors.get(serveur, discord.Color.blue())
    
    embed = discord.Embed(
        title=f"🏴 {name}",
        description=f"Serveur: **{serveur.upper()}**",
        color=embed_color,
        timestamp=datetime.now()
    )
    
    embed.add_field(name="⚡ Power", value=f"`{power:,}`", inline=True)
    embed.add_field(name="🗺️ Claims", value=f"`{claims:,}`", inline=True)
    embed.add_field(name="📈 Différence", value=f"`{difference:,}`", inline=True)
    
    embed.add_field(name="👑 Leader", value=f"`{leader}`", inline=True)
    embed.add_field(name="👥 Membres", value=f"`{members}`", inline=True)
    embed.add_field(name="⚡", value="\u200b", inline=True)
    
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
            claims = country.get("count_claims", 0)
            
            if power < claims:
                deficit = claims - power
                all_underpower.append({
                    "server": server,
                    "name": name,
                    "power": power,
                    "claims": claims,
                    "deficit": deficit
                })
    
    all_underpower.sort(key=lambda x: x["deficit"], reverse=True)
    
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
            "yellow": "🟡",
            "mocha": "🟤"
        }
        
        for server in SERVERS:
            server_countries = [c for c in all_underpower if c["server"] == server]
            
            if server_countries:
                emoji = server_emoji.get(server, "⚪")
                text_list = []
                
                for country in server_countries[:10]:
                    text_list.append(
                        f"**{country['name']}**: `{country['power']:,}` / `{country['claims']:,}` (Déficit: `{country['deficit']:,}`)"
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
    
    try:
        if list_message_id:
            try:
                message = await channel.fetch_message(list_message_id)
                await message.edit(embed=embed)
            except discord.NotFound:
                message = await channel.send(embed=embed)
                list_message_id = message.id
        else:
            message = await channel.send(embed=embed)
            list_message_id = message.id
        print(f"✅ Liste mise à jour ({len(all_underpower)} pays en sous-power)")
    except Exception as e:
        print(f"❌ Erreur mise à jour liste: {e}")


@tasks.loop(minutes=5)
async def check_underpower_alerts():
    """Vérifie les pays en sous-power pour les alertes (re-alerte après 24h)"""
    global alert_channel_id, alert_cache
    
    if not alert_channel_id:
        return
    
    channel = bot.get_channel(alert_channel_id)
    if not channel:
        return
    
    now = datetime.now()
    current_underpower = {}
    
    for server in SERVERS:
        countries = ng_api.get_all_countries_on_server(server)
        
        for country in countries:
            name = country.get("name")
            power = country.get("power", 0)
            claims = country.get("count_claims", 0)
            
            if power < claims:
                key = f"{server}_{name}"
                current_underpower[key] = {
                    "server": server,
                    "name": name,
                    "power": power,
                    "claims": claims,
                    "deficit": claims - power
                }
    
    # Vérifier quels pays doivent être alertés
    for key, data in current_underpower.items():
        should_alert = False
        
        if key not in alert_cache:
            # Nouveau pays en sous-power
            should_alert = True
        else:
            # Pays déjà en sous-power, vérifier si 24h écoulées
            last_alert = alert_cache[key]["last_alert"]
            if now - last_alert >= ALERT_COOLDOWN:
                should_alert = True
        
        if should_alert:
            server_colors = {
                "blue": discord.Color.blue(),
                "red": discord.Color.red(),
                "green": discord.Color.green(),
                "yellow": discord.Color.gold(),
                "mocha": discord.Color.from_rgb(139, 69, 19)
            }
            
            is_new = key not in alert_cache
            title = "🚨 NOUVEAU SOUS-POWER" if is_new else "⚠️ TOUJOURS EN SOUS-POWER"
            
            embed = discord.Embed(
                title=title,
                description=f"**{data['name']}** {'est passé' if is_new else 'est toujours'} en sous-power sur **{data['server'].upper()}**!",
                color=server_colors.get(data['server'], discord.Color.orange()),
                timestamp=now
            )
            
            embed.add_field(name="⚡ Power", value=f"`{data['power']:,}`", inline=True)
            embed.add_field(name="🗺️ Claims", value=f"`{data['claims']:,}`", inline=True)
            embed.add_field(name="📉 Déficit", value=f"`{data['deficit']:,}`", inline=True)
            
            await channel.send(embed=embed)
            print(f"🚨 Alerte envoyée pour {data['name']} ({data['server']})")
            
            # Mettre à jour le cache avec le timestamp actuel
            alert_cache[key] = {
                "data": data,
                "last_alert": now
            }
    
    # Nettoyer le cache des pays qui ne sont plus en sous-power
    keys_to_remove = [k for k in alert_cache.keys() if k not in current_underpower]
    for key in keys_to_remove:
        del alert_cache[key]


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
