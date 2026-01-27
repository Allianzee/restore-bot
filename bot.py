import discord
from discord.ext import commands
from discord.ui import Button, View, Select
from flask import Flask, request, jsonify
from threading import Thread
import asyncio
import os

# ====== CONFIGURATION ======
SETUP_CHANNEL_ID = 1465622142514106464  # <-- YOUR CHANNEL ID HERE!

# ====== WEB SERVER ======
app = Flask('')

pending_requests = {}
completed_requests = {}
tower_lists = {}

@app.route('/')
def home():
    return 'Bot is alive!'

@app.route('/get_request')
def get_request():
    secret = request.args.get('secret')
    if secret != os.environ.get('SECRET_KEY'):
        return jsonify({'error': 'Invalid secret'}), 403
    
    if pending_requests:
        user_id = list(pending_requests.keys())[0]
        data = pending_requests.pop(user_id)
        return jsonify(data)
    
    return jsonify({'status': 'no_requests'})

@app.route('/submit_result', methods=['POST'])
def submit_result():
    data = request.json
    if data.get('secret') != os.environ.get('SECRET_KEY'):
        return jsonify({'error': 'Invalid secret'}), 403
    
    user_id = data.get('user_id')
    
    if data.get('type') == 'tower_list':
        tower_lists[user_id] = data.get('towers', [])
    
    completed_requests[user_id] = data
    return jsonify({'status': 'success'})

def run_web():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run_web).start()

# ====== DISCORD BOT ======
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_selections = {}

class TowerSelect(Select):
    def __init__(self, towers, user_id, page=0):
        self.all_towers = towers
        self.roblox_user_id = user_id
        self.page = page
        
        start = page * 25
        end = start + 25
        page_towers = towers[start:end]
        
        options = []
        for tower in page_towers:
    label = tower['name'][:100]
    if tower.get('shiny'):
        label = "Shiny " + label  # <-- NOW SAYS "Shiny"
            if tower.get('trait') and tower['trait'] != 'None':
                label += f" | {tower['trait']}"
            
            options.append(discord.SelectOption(
                label=label[:100],
                value=tower['id'],
                description=f"Amount: {tower.get('amount', 1)}"
            ))
        
        if not options:
            options.append(discord.SelectOption(label="No towers", value="none"))
        
        super().__init__(
            placeholder=f"Select towers to restore (Page {page + 1})...",
            min_values=1,
            max_values=min(5, len(options)),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_ids = self.values
        
        if self.roblox_user_id not in user_selections:
            user_selections[self.roblox_user_id] = []
        
        for tower_id in selected_ids:
            for tower in self.all_towers:
                if tower['id'] == tower_id and tower not in user_selections[self.roblox_user_id]:
                    user_selections[self.roblox_user_id].append(tower)
                    break
        
        selected_names = [t['name'] for t in user_selections[self.roblox_user_id]]
        
        await interaction.response.send_message(
            f"**Selected {len(user_selections[self.roblox_user_id])} towers:**\n" +
            "\n".join([f"• {name}" for name in selected_names[:5]]) +
            f"\n\n{'✅ Click **Confirm Restore** when ready!' if len(user_selections[self.roblox_user_id]) >= 1 else ''}",
            ephemeral=True
        )

class TowerSelectView(View):
    def __init__(self, towers, user_id, discord_user_id):
        super().__init__(timeout=300)
        self.towers = towers
        self.roblox_user_id = user_id
        self.discord_user_id = discord_user_id
        self.page = 0
        self.max_pages = max(1, (len(towers) - 1) // 25 + 1)
        
        if towers:
            self.add_item(TowerSelect(towers, user_id, self.page))
    
    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: Button):
        if self.page > 0:
            self.page -= 1
            self.clear_items()
            self.add_item(TowerSelect(self.towers, self.roblox_user_id, self.page))
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.clear_items()
            self.add_item(TowerSelect(self.towers, self.roblox_user_id, self.page))
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    @discord.ui.button(label="✅ Confirm Restore", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, button: Button):
        if self.roblox_user_id not in user_selections or len(user_selections[self.roblox_user_id]) == 0:
            await interaction.response.send_message("❌ Select at least 1 tower first!", ephemeral=True)
            return
        
        selected = user_selections[self.roblox_user_id][:5]
        
        await interaction.response.send_message("⏳ Restoring your towers...", ephemeral=True)
        
        pending_requests[self.roblox_user_id + "_restore"] = {
            'user_id': self.roblox_user_id,
            'discord_id': str(self.discord_user_id),
            'action': 'restore',
            'towers': selected
        }
        
        for i in range(60):
            await asyncio.sleep(1)
            result_key = self.roblox_user_id + "_restore_result"
            if result_key in completed_requests:
                result = completed_requests.pop(result_key)
                
                if result.get('success'):
                    embed = discord.Embed(
                        title='✅ Towers Restored!',
                        color=discord.Color.green()
                    )
                    restored_list = "\n".join([f"• {t['name']}" for t in selected])
                    embed.add_field(name='📦 Restored', value=f"```{restored_list}```")
                    embed.add_field(name='🎮 Join', value=result.get('ps_link', 'Join any server!'))
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Failed: {result.get('error')}", ephemeral=True)
                
                user_selections.pop(self.roblox_user_id, None)
                return
        
        await interaction.followup.send("⚠️ Timeout - check in-game!", ephemeral=True)

class RestoreView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🔄 Restore My Items', style=discord.ButtonStyle.green, custom_id='restore')
    async def restore(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message('📩 Check your DMs!', ephemeral=True)
        
        try:
            dm = await interaction.user.create_dm()
            await dm.send('**Send your Roblox User ID:**')
            
            def check(m):
                return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
            
            msg = await bot.wait_for('message', check=check, timeout=120)
            user_id = msg.content.strip()
            
            if not user_id.isdigit():
                await dm.send('❌ Invalid! Numbers only.')
                return
            
            await dm.send('⏳ Fetching towers...')
            
            pending_requests[user_id] = {
                'user_id': user_id,
                'discord_id': str(interaction.user.id),
                'action': 'get_towers'
            }
            
            for i in range(30):
                await asyncio.sleep(1)
                if user_id in completed_requests:
                    result = completed_requests.pop(user_id)
                    
                    if result.get('type') == 'tower_list':
                        towers = result.get('towers', [])
                        
                        if not towers:
                            await dm.send('❌ No restorable towers found!')
                            return
                        
                        user_selections.pop(user_id, None)
                        
                        embed = discord.Embed(
                            title='📦 Your Towers',
                            description=f'Found **{len(towers)}** towers!\nSelect up to **5** to restore.',
                            color=discord.Color.blue()
                        )
                        
                        await dm.send(embed=embed, view=TowerSelectView(towers, user_id, interaction.user.id))
                        return
            
            await dm.send('⚠️ Timeout!')
            
        except Exception as e:
            print(f'Error: {e}')

@bot.event
async def on_ready():
    print(f'✅ Bot online: {bot.user}')
    bot.add_view(RestoreView())
    
    # Auto-send setup message
    try:
        channel = bot.get_channel(SETUP_CHANNEL_ID)
        
        if channel:
            # Check if already exists
            async for message in channel.history(limit=10):
                if message.author == bot.user and message.embeds:
                    for embed in message.embeds:
                        if embed.title and "Restoration" in embed.title:
                            print("✅ Setup already exists!")
                            return
            
            # Send setup
            embed = discord.Embed(
                title='🔄 Tower Restoration System',
                description=(
                    'Lost towers due to a bug?\n'
                    'Click below to restore them!\n\n'
                    '**How it works:**\n'
                    '1️⃣ Click the button\n'
                    '2️⃣ Send your Roblox User ID\n'
                    '3️⃣ Select up to 5 towers\n'
                    '4️⃣ Confirm and receive!'
                ),
                color=discord.Color.blue()
            )
            
            await channel.send(embed=embed, view=RestoreView())
            print(f"✅ Setup sent to #{channel.name}!")
        else:
            print("❌ Channel not found!")
            
    except Exception as e:
        print(f"❌ Error: {e}")

bot.run(os.environ.get('DISCORD_TOKEN'))
