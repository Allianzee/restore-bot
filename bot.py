import discord
from discord.ext import commands
from discord.ui import Button, View, Select
from flask import Flask, request, jsonify
from threading import Thread
import asyncio
import os
import time

# ====== CONFIGURATION ======
SETUP_CHANNEL_ID = 1465622142514106464  # Your channel ID
ADMIN_IDS = [958738600491638896]  # Replace with your Discord user ID

# ====== WEB SERVER ======
app = Flask(__name__)

pending_requests = {}
completed_requests = {}

@app.route('/')
def home():
    return 'Restore Bot is alive!'

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/get_request')
def get_request():
    secret = request.args.get('secret')
    expected_secret = os.environ.get('SECRET_KEY', 'RealSecretKey')
    
    if secret != expected_secret:
        return jsonify({'error': 'Invalid secret'}), 403
    
    if pending_requests:
        key = list(pending_requests.keys())[0]
        data = pending_requests.pop(key)
        print(f"[Web] Sending request to Roblox: {data.get('action')} for {data.get('user_id')}")
        return jsonify(data)
    
    return jsonify({'status': 'no_requests'})

@app.route('/submit_result', methods=['POST'])
def submit_result():
    data = request.json
    expected_secret = os.environ.get('SECRET_KEY', 'RealSecretKey')
    
    if data.get('secret') != expected_secret:
        return jsonify({'error': 'Invalid secret'}), 403
    
    user_id = data.get('user_id')
    result_type = data.get('type', 'unknown')
    
    print(f"[Web] Received result: {result_type} for {user_id}")
    
    if data.get('error'):
        print(f"[Web] Error in result: {data.get('error')}")
    
    completed_requests[user_id] = data
    return jsonify({'status': 'success'})

@app.route('/status')
def status():
    return jsonify({
        'pending': len(pending_requests),
        'completed': len(completed_requests),
        'pending_keys': list(pending_requests.keys()),
        'completed_keys': list(completed_requests.keys())
    })

def run_web():
    port = int(os.environ.get('PORT', 10000))
    print(f"[Web] Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)

# Start web server FIRST
print("[Web] Initializing web server...")
web_thread = Thread(target=run_web, daemon=True)
web_thread.start()
time.sleep(2)  # Give Flask time to start

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
            label = tower['name'][:90]
            if tower.get('shiny'):
                label = "✨ " + label
            if tower.get('trait') and tower['trait'] != 'None':
                label += f" [{tower['trait']}]"
            
            desc = f"Amount: {tower.get('amount', 1)}"
            
            options.append(discord.SelectOption(
                label=label[:100],
                value=tower['id'][:100],
                description=desc[:100]
            ))
        
        if not options:
            options.append(discord.SelectOption(label="No towers available", value="none"))
        
        super().__init__(
            placeholder=f"Select towers (Page {page + 1})...",
            min_values=1,
            max_values=min(5, len(options)),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        if "none" in self.values:
            await interaction.response.send_message("No towers to select!", ephemeral=True)
            return
        
        user_selections[self.roblox_user_id] = []
        
        for tower_id in self.values:
            for tower in self.all_towers:
                if tower['id'] == tower_id:
                    user_selections[self.roblox_user_id].append(tower)
                    break
        
        selected_names = []
        for t in user_selections[self.roblox_user_id]:
            name = t['name']
            if t.get('shiny'):
                name = "✨ " + name
            if t.get('trait') and t['trait'] != 'None':
                name += f" | {t['trait']}"
            selected_names.append(name)
        
        await interaction.response.send_message(
            f"**Selected {len(selected_names)} towers:**\n" +
            "\n".join([f"• {n}" for n in selected_names]) +
            "\n\n✅ Click **Confirm Restore** when ready!",
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
        
        self.rebuild_view()
    
    def rebuild_view(self):
        self.clear_items()
        
        if self.towers:
            self.add_item(TowerSelect(self.towers, self.roblox_user_id, self.page))
        
        prev_btn = Button(
            label="◀ Prev",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page == 0),
            row=1
        )
        prev_btn.callback = self.prev_page
        self.add_item(prev_btn)
        
        page_btn = Button(
            label=f"{self.page + 1}/{self.max_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=1
        )
        self.add_item(page_btn)
        
        next_btn = Button(
            label="Next ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(self.page >= self.max_pages - 1),
            row=1
        )
        next_btn.callback = self.next_page
        self.add_item(next_btn)
        
        confirm_btn = Button(
            label="✅ Confirm Restore",
            style=discord.ButtonStyle.success,
            row=2
        )
        confirm_btn.callback = self.confirm_restore
        self.add_item(confirm_btn)
        
        cancel_btn = Button(
            label="❌ Cancel",
            style=discord.ButtonStyle.danger,
            row=2
        )
        cancel_btn.callback = self.cancel_restore
        self.add_item(cancel_btn)
    
    async def prev_page(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.rebuild_view()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    async def next_page(self, interaction: discord.Interaction):
        if self.page < self.max_pages - 1:
            self.page += 1
            self.rebuild_view()
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
    
    async def confirm_restore(self, interaction: discord.Interaction):
        selected = user_selections.get(self.roblox_user_id, [])
        
        if not selected:
            await interaction.response.send_message(
                "❌ Please select at least 1 tower first!",
                ephemeral=True
            )
            return
        
        selected = selected[:5]
        
        print(f"[Bot] Selected towers to restore for {self.roblox_user_id}:")
        for t in selected:
            print(f"  - {t['name']} | Shiny: {t.get('shiny')} | Trait: {t.get('trait')}")
        
        names = []
        for t in selected:
            n = t['name']
            if t.get('shiny'):
                n = "✨ " + n
            if t.get('trait') and t['trait'] != 'None':
                n += f" | {t['trait']}"
            names.append(n)
        
        await interaction.response.send_message(
            f"⏳ **Restoring {len(selected)} towers...**\n" +
            "\n".join([f"• {n}" for n in names]),
            ephemeral=True
        )
        
        towers_to_send = []
        for t in selected:
            towers_to_send.append({
                'id': t.get('id', ''),
                'name': t.get('name', ''),
                'shiny': t.get('shiny', False),
                'trait': t.get('trait', 'None')
            })
        
        request_key = f"{self.roblox_user_id}_restore"
        pending_requests[request_key] = {
            'user_id': self.roblox_user_id,
            'discord_id': str(self.discord_user_id),
            'action': 'restore',
            'towers': towers_to_send
        }
        
        print(f"[Bot] Queued restore request for {self.roblox_user_id}")
        
        result_key = f"{self.roblox_user_id}_restore_result"
        
        for _ in range(60):
            await asyncio.sleep(1)
            
            if result_key in completed_requests:
                result = completed_requests.pop(result_key)
                
                if result.get('success'):
                    restored = result.get('restored', [])
                    
                    embed = discord.Embed(
                        title="✅ Towers Restored!",
                        description=f"Successfully restored **{len(restored)}** towers!",
                        color=discord.Color.green()
                    )
                    
                    if restored:
                        tower_list = "\n".join([f"• {t}" for t in restored[:10]])
                        if len(restored) > 10:
                            tower_list += f"\n...and {len(restored) - 10} more"
                        embed.add_field(name="Restored", value=tower_list, inline=False)
                    
                    embed.add_field(
                        name="📌 Important",
                        value="**Rejoin the game** to see your towers!",
                        inline=False
                    )
                    
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    error = result.get('error', 'Unknown error')
                    await interaction.followup.send(
                        f"❌ **Restore Failed**\n\nReason: {error}",
                        ephemeral=True
                    )
                
                user_selections.pop(self.roblox_user_id, None)
                return
        
        await interaction.followup.send(
            "⏰ **Timeout** - Game server didn't respond.\n\nMake sure the game is running and try again.",
            ephemeral=True
        )
    
    async def cancel_restore(self, interaction: discord.Interaction):
        user_selections.pop(self.roblox_user_id, None)
        await interaction.response.send_message("❌ Cancelled.", ephemeral=True)

class RestoreView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label='🔄 Restore My Towers',
        style=discord.ButtonStyle.green,
        custom_id='restore_button'
    )
    async def restore_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message('📬 Check your DMs!', ephemeral=True)
        
        try:
            dm = await interaction.user.create_dm()
            
            await dm.send(
                "**🔄 Tower Restoration**\n\n"
                "Please send your **Roblox User ID**.\n\n"
                "*You can find it in your Roblox profile URL:*\n"
                "`roblox.com/users/XXXXXXXX/profile`"
            )
            
            def check(m):
                return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
            
            try:
                msg = await bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                await dm.send("⏰ Timed out. Please try again.")
                return
            
            user_id = msg.content.strip()
            
            if not user_id.isdigit():
                await dm.send("❌ Invalid User ID! Please use only numbers.")
                return
            
            status_msg = await dm.send("⏳ Fetching your towers...")
            
            pending_requests[user_id] = {
                'user_id': user_id,
                'discord_id': str(interaction.user.id),
                'action': 'get_towers'
            }
            
            print(f"[Bot] Queued get_towers for {user_id}")
            
            for i in range(30):
                await asyncio.sleep(1)
                
                if user_id in completed_requests:
                    result = completed_requests.pop(user_id)
                    
                    if result.get('error'):
                        await status_msg.edit(content=f"❌ **Error:** {result['error']}")
                        return
                    
                    towers = result.get('towers', [])
                    
                    if not towers:
                        await status_msg.edit(content="❌ No restorable towers found!")
                        return
                    
                    user_selections.pop(user_id, None)
                    
                    await status_msg.delete()
                    
                    embed = discord.Embed(
                        title="🗼 Your Towers",
                        description=(
                            f"Found **{len(towers)}** unique towers!\n\n"
                            "Select up to **5** towers to restore."
                        ),
                        color=discord.Color.blue()
                    )
                    
                    preview = []
                    for t in towers[:5]:
                        name = t['name']
                        if t.get('shiny'):
                            name = "✨ " + name
                        if t.get('trait') and t['trait'] != 'None':
                            name += f" ({t['trait']})"
                        preview.append(f"• {name}")
                    
                    if len(towers) > 5:
                        preview.append(f"*...and {len(towers) - 5} more*")
                    
                    embed.add_field(name="Preview", value="\n".join(preview), inline=False)
                    
                    view = TowerSelectView(towers, user_id, interaction.user.id)
                    await dm.send(embed=embed, view=view)
                    return
            
            await status_msg.edit(content="⏰ Timeout - Game server not responding. Is the game running?")
            
        except discord.Forbidden:
            try:
                await interaction.followup.send(
                    "❌ I can't DM you! Please enable DMs from server members.",
                    ephemeral=True
                )
            except:
                pass
        except Exception as e:
            print(f"[Bot] Error: {e}")
            try:
                await dm.send(f"❌ An error occurred: {str(e)[:100]}")
            except:
                pass

# ====== ADMIN COMMANDS ======
@bot.command(name='reset')
async def reset_claim(ctx, user_id: str = None):
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ No permission.")
        return
    
    if not user_id or not user_id.isdigit():
        await ctx.send("❌ Usage: `!reset <roblox_user_id>`")
        return
    
    msg = await ctx.send(f"⏳ Resetting claim for `{user_id}`...")
    
    pending_requests[f"{user_id}_reset_cmd"] = {
        'user_id': user_id,
        'action': 'reset_claim'
    }
    
    for _ in range(15):
        await asyncio.sleep(1)
        if f"{user_id}_reset" in completed_requests:
            result = completed_requests.pop(f"{user_id}_reset")
            if result.get('success'):
                await msg.edit(content=f"✅ Reset successful for `{user_id}`!")
            else:
                await msg.edit(content=f"❌ Reset failed for `{user_id}`")
            return
    
    await msg.edit(content="⏰ Timeout")

@bot.command(name='check')
async def check_towers(ctx, user_id: str = None):
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ No permission.")
        return
    
    if not user_id or not user_id.isdigit():
        await ctx.send("❌ Usage: `!check <roblox_user_id>`")
        return
    
    msg = await ctx.send(f"⏳ Checking towers for `{user_id}`...")
    
    pending_requests[user_id] = {
        'user_id': user_id,
        'action': 'get_towers',
        'skip_claim_check': True
    }
    
    for _ in range(30):
        await asyncio.sleep(1)
        if user_id in completed_requests:
            result = completed_requests.pop(user_id)
            
            if result.get('error'):
                await msg.edit(content=f"❌ Error: {result['error']}")
                return
            
            towers = result.get('towers', [])
            
            if not towers:
                await msg.edit(content=f"❌ No towers found for `{user_id}`")
                return
            
            tower_list = []
            for t in towers[:15]:
                name = t['name']
                if t.get('shiny'):
                    name = "✨ " + name
                tower_list.append(f"• {name} (x{t.get('amount', 1)})")
            
            text = f"✅ Found **{len(towers)}** towers for `{user_id}`:\n"
            text += "\n".join(tower_list)
            if len(towers) > 15:
                text += f"\n...and {len(towers) - 15} more"
            
            await msg.edit(content=text)
            return
    
    await msg.edit(content="⏰ Timeout")

@bot.command(name='botstatus')
async def bot_status(ctx):
    if ctx.author.id not in ADMIN_IDS:
        return
    
    embed = discord.Embed(title="Bot Status", color=discord.Color.blue())
    embed.add_field(name="Pending", value=len(pending_requests), inline=True)
    embed.add_field(name="Completed", value=len(completed_requests), inline=True)
    embed.add_field(name="Selections", value=len(user_selections), inline=True)
    
    if pending_requests:
        keys = list(pending_requests.keys())[:5]
        embed.add_field(name="Pending Keys", value="\n".join(keys) or "None", inline=False)
    
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ Bot online: {bot.user}')
    
    bot.add_view(RestoreView())
    
    # Don't auto-send setup message to avoid rate limits
    # Use !setup command instead
    print("Use !setup command to send the restore button message")

@bot.command(name='setup')
async def setup_message(ctx):
    """Send the restore button message"""
    if ctx.author.id not in ADMIN_IDS:
        await ctx.send("❌ No permission.")
        return
    
    embed = discord.Embed(
        title="🔄 Tower Restoration System",
        description=(
            "**Lost towers due to a bug?**\n"
            "Click below to restore them!\n\n"
            "**How it works:**\n"
            "1️⃣ Click the button\n"
            "2️⃣ Send your Roblox User ID\n"
            "3️⃣ Select up to 5 towers\n"
            "4️⃣ Confirm and receive!\n\n"
            "⚠️ *You can only restore once per account!*"
        ),
        color=discord.Color.blue()
    )
    
    await ctx.send(embed=embed, view=RestoreView())
    
    # Delete the command message
    try:
        await ctx.message.delete()
    except:
        pass

# Run bot
print("[Bot] Starting Discord bot...")
token = os.environ.get('DISCORD_TOKEN')
if token:
    bot.run(token)
else:
    print("ERROR: DISCORD_TOKEN not set!")
