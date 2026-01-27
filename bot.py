import discord
from discord.ext import commands
from discord.ui import Button, View
from flask import Flask, request, jsonify
from threading import Thread
import asyncio
import os

# ====== WEB SERVER ======
app = Flask('')

pending_requests = {}
completed_requests = {}

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
    
    completed_requests[data['user_id']] = data
    return jsonify({'status': 'success'})

def run_web():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run_web).start()

# ====== DISCORD BOT ======
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

class RestoreView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🔄 Restore My Items', style=discord.ButtonStyle.green, custom_id='restore')
    async def restore(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            '📩 Check your DMs!',
            ephemeral=True
        )
        
        try:
            dm = await interaction.user.create_dm()
            await dm.send('**Send your Roblox User ID:**\n(Find it at roblox.com/users/YOURID/profile)')
            
            def check(m):
                return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)
            
            msg = await bot.wait_for('message', check=check, timeout=120)
            user_id = msg.content.strip()
            
            if not user_id.isdigit():
                await dm.send('❌ Invalid! Numbers only.')
                return
            
            await dm.send('⏳ Processing...')
            
            pending_requests[user_id] = {
                'user_id': user_id,
                'discord_id': str(interaction.user.id)
            }
            
            for i in range(30):
                await asyncio.sleep(1)
                if user_id in completed_requests:
                    result = completed_requests.pop(user_id)
                    
                    embed = discord.Embed(
                        title='✅ Items Restored!',
                        color=discord.Color.green()
                    )
                    embed.add_field(name='Items', value=f"```{result.get('items', 'Check in-game')}```")
                    embed.add_field(name='Join', value=result.get('ps_link', 'Join any server'))
                    
                    await dm.send(embed=embed)
                    return
            
            await dm.send('⚠️ Timeout - check in-game!')
            
        except Exception as e:
            print(f'Error: {e}')

@bot.event
async def on_ready():
    print(f'✅ Bot online: {bot.user}')
    bot.add_view(RestoreView())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = discord.Embed(
        title='🔄 Item Restoration',
        description='Click below to restore your items!',
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=RestoreView())

bot.run(os.environ.get('DISCORD_TOKEN'))
