import discord
from discord.ext import commands
from discord.ui import Button, View, Select
from flask import Flask, request, jsonify
from threading import Thread
import asyncio
import os

# ====== CONFIGURATION ======
SETUP_CHANNEL_ID = 1465622142514106464  # Your channel ID
ADMIN_IDS = [958738600491638896]  # Add your Discord user ID (as integer)

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
        if data.get('error'):
            completed_requests[user_id] = {'type': 'tower_list', 'towers': [], 'error': data.get('error')}
        else:
            completed_requests[user_id] = data
    elif data.get('type') == 'reset_result':
        completed_requests[user_id + "_reset"] = data
    else:
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
                label = "Shiny " + label
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
        
        # Clear previous selections and add new ones
        user_selections[self.roblox_user_id] = []
        
        for tower_id in selected_ids:
            for tower in self.all_towers:
                if tower['id'] == tower_id:
                    user_selections[self.roblox_user_id].append(tower)
                    break
        
        selected_names = []
        for t in user_selections[self.roblox_user_id]:
            name = t['name']
            if t.get('shiny'):
                name = "Shiny " + name
            if t.get('trait') and t['trait'] != 'None':
                name += f" | {t['trait']}"
            selected_names.append(name)
        
        await interaction.response.send_message(
            f"**Selected {len(user_selections[self.roblox_user_id])} towers:**\n" +
            "\n".join([f"• {name}" for name in selected_names]) +
            f"\n\nClick **Confirm Restore** when ready!",
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
        
        # Add page buttons
        self.add_page_buttons()
    
    def add_page_buttons(self):
        prev_btn = Button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == 0))
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)
        
        page_label = Button(label=f"Page {self.page + 1}/{self.max_pages}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
        self.add_item(page_label)
        
        next_btn = Button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page >= self.max_pages - 1))
        next_btn.callback = self.next_page
        self.add_item(next_btn)
        
        confirm_btn = Button(label="✅ Confirm Restore", style=discord.ButtonStyle.success, row=2)
        confirm_btn.callback = self.confirm_restore
        self.add_item(confirm_btn)
        
        cancel_btn = Button(label="❌ Cancel", style=discord.ButtonStyle.danger, row=2)
        cancel_btn.callback = self.cancel_restore
        self.add_item(cancel_btn)
    
    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.clear_items()
            self.add_item(TowerSelect(self.towers, self.roblox_user_id, self.page))
            self.add_page_buttons()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.clear_items()
            self.add_item(TowerSelect(self.towers, self.roblox_user_id, self.page))
            self.add_page_buttons()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    async def confirm_restore(self, interaction: discord.Interaction):
        if self.roblox_user_id not in user_selections or len(user_selections[self.roblox_user_id]) == 0:
            await interaction.response.send_message("❌ Select at least 1 tower first!", ephemeral=True)
            return
        
        selected = user_selections[self.roblox_user_id][:5]
        
        # Show what's being restored
        selected_names = []
        for t in selected:
            name = t['name']
            if t.get('shiny'):
                name = "Shiny " + name
            if t.get('trait') and t['trait'] != 'None':
                name += f" | {t['trait']}"
            selected_names.append(name)
        
        await interaction.response.send_message(
            f"⏳ **Restoring {len(selected)} towers...**\n" + 
            "\n".join([f"• {name}" for name in selected_names]),
            ephemeral=True
        )
        
        # Send restore request to Roblox
        pending_requests[self.roblox_user_id + "_restore"] = {
            'user_id': self.roblox_user_id,
            'discord_id': str(self.discord_user_id),
            'action': 'restore',
            'towers': selected
        }
        
        # Wait for result
        for i in range(60):
            await asyncio.sleep(1)
            result_key = self.roblox_user_id + "_restore_result"
            if result_key in completed_requests:
                result = completed_requests.pop(result_key)
                
                if result.get('success'):
                    restored_list = result.get('restored', [])
                    
                    embed = discord.Embed(
                        title='✅ Towers Restored Successfully!',
                        description=f"You received **{len(restored_list)}** towers!",
                        color=discord.Color.green()
                    )
                    
                    if restored_list:
                        embed.add_field(
                            name='Restored Towers',
                            value="```\n" + "\n".join([f"• {name}" for name in restored_list[:10]]) + "\n```",
                            inline=False
                        )
                    
                    embed.add_field(
                        name='📝 Note',
                        value='If you were online, **rejoin the game** to see your towers!',
                        inline=False
                    )
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    error_msg = result.get('error', 'Unknown error')
                    await interaction.followup.send(
                        f"❌ **Restore Failed**\n\nReason: {error_msg}",
                        ephemeral=True
                    )
                
                user_selections.pop(self.roblox_user_id, None)
                return
        
        await interaction.followup.send(
            "⏰ **Timeout** - The game server didn't respond in time.\n\n" +
            "Please try again or check if you're in the game.",
            ephemeral=True
        )
    
    async def cancel_restore(self, interaction: discord.Interaction):
        user_selections.pop(self.roblox_user_id, None)
        await interaction.response.send_message("❌ Restore cancelled.", ephemeral=True)

class RestoreView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🔄 Restore My Items', style=discord.ButtonStyle.green, custom_id='restore')
    async def restore(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message('📬 Check your DMs!', ephemeral=True)
        
        try:
            dm = await interaction.user.create_dm()
            await dm.send('**📝 Send your Roblox User ID:**\n*(You can find this in your Roblox profile URL)*')
            
            def check(m):
                return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
            
            msg = await bot.wait_for('message', check=check, timeout=120)
            user_id = msg.content.strip()
            
            if not user_id.isdigit():
                await dm.send('❌ Invalid User ID! Please send only numbers.')
                return
            
            status_msg = await dm.send('⏳ Fetching your towers from the database...')
            
            # Request towers from Roblox
            pending_requests[user_id] = {
                'user_id': user_id,
                'discord_id': str(interaction.user.id),
                'action': 'get_towers'
            }
            
            # Wait for response
            for i in range(30):
                await asyncio.sleep(1)
                if user_id in completed_requests:
                    result = completed_requests.pop(user_id)
                    
                    # Check for error
                    if result.get('error'):
                        await status_msg.edit(content=f"❌ **Error:** {result.get('error')}")
                        return
                    
                    if result.get('type') == 'tower_list':
                        towers = result.get('towers', [])
                        
                        if not towers:
                            await status_msg.edit(content='❌ No restorable towers found in your account!')
                            return
                        
                        # Clear previous selections
                        user_selections.pop(user_id, None)
                        
                        await status_msg.delete()
                        
                        embed = discord.Embed(
                            title='🗼 Your Restorable Towers',
                            description=f'Found **{len(towers)}** unique towers!\n\nSelect up to **5** towers to restore.',
                            color=discord.Color.blue()
                        )
                        
                        # Show first few towers as preview
                        preview = []
                        for t in towers[:5]:
                            name = t['name']
                            if t.get('shiny'):
                                name = "✨ " + name
                            if t.get('trait') and t['trait'] != 'None':
                                name += f" ({t['trait']})"
                            preview.append(f"• {name}")
                        
                        if len(towers) > 5:
                            preview.append(f"...and {len(towers) - 5} more")
                        
                        embed.add_field(name="Preview", value="\n".join(preview), inline=False)
                        
                        await dm.send(embed=embed, view=TowerSelectView(towers, user_id, interaction.user.id))
                        return
            
            await status_msg.edit(content='⏰ Timeout! The game server is not responding. Please try again later.')
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I can't DM you! Please enable DMs from server members.", ephemeral=True)
        except asyncio.TimeoutError:
            await dm.send("⏰ You took too long! Please try again.")
        except Exception as e:
            print(f'Error: {e}')
            await interaction.followup.send(f"❌ An error occurred. Please try again.", ephemeral=True)

# ====== ADMIN COMMANDS ======
@bot.command()
async def reset(ctx, user_id: str):
    """Reset a user's claim status (Admin only)"""
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    if not user_id.isdigit():
        await ctx.send("❌ Invalid User ID!")
        return
    
    status_msg = await ctx.send(f"⏳ Resetting claim status for `{user_id}`...")
    
    # Send reset request
    pending_requests[user_id + "_reset_cmd"] = {
        'user_id': user_id,
        'action': 'reset_claim',
        'admin_id': str(ctx.author.id)
    }
    
    # Wait for response
    for i in range(15):
        await asyncio.sleep(1)
        if user_id + "_reset" in completed_requests:
            result = completed_requests.pop(user_id + "_reset")
            if result.get('success'):
                await status_msg.edit(content=f"✅ Reset claim status for `{user_id}`! They can now restore again.")
            else:
                await status_msg.edit(content=f"❌ Failed to reset for `{user_id}`")
            return
    
    await status_msg.edit(content="⏰ Timeout - game server not responding")

@bot.command()
async def forcerestore(ctx, user_id: str):
    """Force fetch towers for a user (Admin only, bypasses claim check)"""
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    if not user_id.isdigit():
        await ctx.send("❌ Invalid User ID!")
        return
    
    status_msg = await ctx.send(f"⏳ Fetching towers for `{user_id}` (bypassing claim check)...")
    
    pending_requests[user_id] = {
        'user_id': user_id,
        'discord_id': str(ctx.author.id),
        'action': 'get_towers',
        'skip_claim_check': True
    }
    
    for i in range(30):
        await asyncio.sleep(1)
        if user_id in completed_requests:
            result = completed_requests.pop(user_id)
            
            if result.get('error'):
                await status_msg.edit(content=f"❌ Error: {result.get('error')}")
                return
            
            towers = result.get('towers', [])
            if not towers:
                await status_msg.edit(content=f"❌ No towers found for `{user_id}`")
                return
            
            tower_list = "\n".join([f"• {t['name']}" + (" ✨" if t.get('shiny') else "") for t in towers[:20]])
            if len(towers) > 20:
                tower_list += f"\n...and {len(towers) - 20} more"
            
            await status_msg.edit(content=f"✅ Found **{len(towers)}** towers for `{user_id}`:\n```{tower_list}```")
            return
    
    await status_msg.edit(content="⏰ Timeout")

@bot.command()
async def status(ctx):
    """Check bot status (Admin only)"""
    if ctx.author.id not in ADMIN_IDS:
        return
    
    embed = discord.Embed(title="Bot Status", color=discord.Color.blue())
    embed.add_field(name="Pending Requests", value=str(len(pending_requests)), inline=True)
    embed.add_field(name="Completed Requests", value=str(len(completed_requests)), inline=True)
    embed.add_field(name="Active Selections", value=str(len(user_selections)), inline=True)
    
    if pending_requests:
        embed.add_field(name="Pending Keys", value="\n".join(list(pending_requests.keys())[:5]), inline=False)
    
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Bot online: {bot.user}')
    bot.add_view(RestoreView())
    
    try:
        channel = bot.get_channel(SETUP_CHANNEL_ID)
        
        if channel:
            async for message in channel.history(limit=10):
                if message.author == bot.user and message.embeds:
                    for embed in message.embeds:
                        if embed.title and "Restoration" in embed.title:
                            print("Setup already exists!")
                            return
            
            embed = discord.Embed(
                title='🔄 Tower Restoration System',
                description=(
                    '**Lost towers due to a bug?**\n'
                    'Click below to restore them!\n\n'
                    '**How it works:**\n'
                    '1️⃣ Click the button below\n'
                    '2️⃣ Send your Roblox User ID in DMs\n'
                    '3️⃣ Select up to 5 towers to restore\n'
                    '4️⃣ Confirm and receive your towers!\n\n'
                    '⚠️ *You can only restore once!*'
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text="Contact staff if you have issues")
            
            await channel.send(embed=embed, view=RestoreView())
            print(f"Setup sent to #{channel.name}!")
        else:
            print("Channel not found!")
            
    except Exception as e:
        print(f"Error: {e}")

bot.run(os.environ.get('DISCORD_TOKEN'))
