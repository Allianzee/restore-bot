import discord
from discord.ext import commands
from flask import Flask, request, jsonify
from threading import Thread
import os
import time

# ====== FLASK SERVER ======
app = Flask(__name__)

pending_requests = {}
completed_requests = {}

@app.route('/')
def home():
    return 'Bot is alive!'

@app.route('/health')
def health():
    return 'OK'

@app.route('/get_request')
def get_request():
    secret = request.args.get('secret')
    if secret != os.environ.get('SECRET_KEY', 'RealSecretKey'):
        return jsonify({'error': 'bad secret'}), 403
    
    if pending_requests:
        key = list(pending_requests.keys())[0]
        data = pending_requests.pop(key)
        return jsonify(data)
    return jsonify({'status': 'no_requests'})

@app.route('/submit_result', methods=['POST'])
def submit_result():
    data = request.json
    if data.get('secret') != os.environ.get('SECRET_KEY', 'RealSecretKey'):
        return jsonify({'error': 'bad secret'}), 403
    completed_requests[data.get('user_id')] = data
    return jsonify({'status': 'ok'})

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

# Start Flask
Thread(target=run_flask, daemon=True).start()
time.sleep(2)

# ====== DISCORD BOT ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'✅ BOT IS ONLINE: {bot.user}')
    print('Use !ping to test')

@bot.command()
async def ping(ctx):
    await ctx.send('🏓 Pong! Bot is working!')

@bot.command()
async def status(ctx):
    await ctx.send(f'Pending: {len(pending_requests)} | Completed: {len(completed_requests)}')

# Run bot
token = os.environ.get('DISCORD_TOKEN')
if token:
    print('Starting bot...')
    bot.run(token)
else:
    print('ERROR: No DISCORD_TOKEN set!')
