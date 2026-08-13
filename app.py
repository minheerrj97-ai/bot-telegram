import sqlite3
import re
import requests
import threading
import time
import os
from flask import Flask, request, jsonify

# ================= CẤU HÌNH CỐ ĐỊNH =================
TELEGRAM_BOT_TOKEN = "8874646531:AAGJS2-i675Hl1RXSmqW15aG1mrHKqcNntw"
SEPAY_API_KEY = "QL5KQUNPDP67OVGAGIUGYREDSLVHRAM4X96NPUXTEWUFYS11LZSQB75DYCC0GDTX"

STK_SEPAY = "0363514145"
NGAN_HANG = "MBBank"
CHU_TAI_KHOAN = "LAM VAN HAI"

ADMIN_ID = 8593076954  # ID Admin
# =====================================================

app = Flask(__name__)

# --- KHỞI TẠO DATABASE SQLITE ---
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acc_info TEXT,
            status TEXT DEFAULT 'AVAILABLE'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('gia_acc', '10000')")
    conn.commit()
    conn.close()

init_db()

# --- CÁC HÀM XỬ LÝ KHÁCH HÀNG & KHO ACC ---
def get_acc_price():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'gia_acc'")
    row = cursor.fetchone()
    conn.close()
    return int(row[0]) if row else 10000

def set_acc_price(new_price):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES ('gia_acc', ?) ON CONFLICT(key) DO UPDATE SET value = ?", (str(new_price), str(new_price)))
    conn.commit()
    conn.close()

def update_balance(user_id, amount, tx_id):
    tx_id_str = str(tx_id)
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT tx_id FROM transactions WHERE tx_id = ?', (tx_id_str,))
    if cursor.fetchone():
        conn.close()
        return False
    
    cursor.execute('INSERT INTO transactions (tx_id, user_id, amount) VALUES (?, ?, ?)', (tx_id_str, user_id, amount))
    cursor.execute('''
        INSERT INTO users (user_id, balance) VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    ''', (user_id, amount, amount))
    
    conn.commit()
    conn.close()
    print(f"✅ [TỰ ĐỘNG CỘNG] +{amount:,.0f} VNĐ cho ID {user_id} (Mã GD: #{tx_id_str})")
    return True

def adjust_user_balance(user_id, amount):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, balance) VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
    ''', (user_id, amount, amount))
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    new_bal = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return new_bal

def get_balance(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def extract_user_id(text):
    if not text:
        return None
    match = re.search(r'NAP[^\d]*(\d+)', str(text), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None

def buy_facebook_account(user_id):
    gia_acc = get_acc_price()
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    balance = row[0] if row else 0
    
    if balance < gia_acc:
        conn.close()
        return False, f"⚠️ Số dư không đủ! Giá acc: **{gia_acc:,.0f}đ**, bạn có **{balance:,.0f}đ**.\nGõ `/nap` để nạp thêm."
    
    cursor.execute("SELECT id, acc_info FROM accounts WHERE status = 'AVAILABLE' LIMIT 1")
    acc = cursor.fetchone()
    if not acc:
        conn.close()
        return False, "❌ Kho hiện tại đã hết tài khoản Facebook!"
    
    acc_id, acc_info = acc
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (gia_acc, user_id))
    cursor.execute("UPDATE accounts SET status = 'SOLD' WHERE id = ?", (acc_id,))
    
    conn.commit()
    conn.close()
    return True, f"🎉 **MUA ACC THÀNH CÔNG!**\n\nThông tin tài khoản:\n`{acc_info}`"

def count_available_accounts():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM accounts WHERE status = 'AVAILABLE'")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

# --- HÀM GỬI TELEGRAM ---
def send_telegram_msg(chat_id, text, photo_url=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    try:
        payload = {"chat_id": chat_id, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = requests.compat.json.dumps(reply_markup)

        if photo_url:
            payload["photo"] = photo_url
            payload["caption"] = text
            requests.post(url + "sendPhoto", data=payload)
        else:
            payload["text"] = text
            requests.post(url + "sendMessage", data=payload)
    except Exception as e:
        print("Lỗi tin nhắn:", e)

def tao_ma_qr_nap_tien(chat_id, amount):
    memo = f"NAP {chat_id}"
    qr_url = f"https://qr.sepay.vn/img?bank={NGAN_HANG}&acc={STK_SEPAY}&template=compact&amount={amount}&des={memo}"
    
    caption = (
        f"💳 **MÃ QR NẠP TIỀN TỰ ĐỘNG**\n\n"
        f"🏦 Ngân hàng: **MB Bank**\n"
        f"🔢 STK: `{STK_SEPAY}`\n"
        f"👤 Chủ TK: **{CHU_TAI_KHOAN}**\n"
        f"💵 Số tiền: **{amount:,.0f} VNĐ**\n"
        f"📝 Nội dung CK: `{memo}`\n\n"
        f"⚡ *Hệ thống tự động cộng tiền sau 5 - 10 giây ngay khi bạn hoàn tất chuyển khoản!*"
    )
    send_telegram_msg(chat_id, caption, photo_url=qr_url)

# --- LUỒNG TỰ ĐỘNG QUÉT ĐỐI SOÁT SEPAY API LIÊN TỤC 24/24 ---
def auto_check_sepay_loop():
    """Tự động kiểm tra danh sách biến động số dư SePay mỗi 15 giây"""
    url = "https://my.sepay.vn/userapi/transactions/list"
    headers = {
        "Authorization": f"Bearer {SEPAY_API_KEY}",
        "Content-Type": "application/json"
    }
    while True:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                transactions = data.get("transactions", [])
                for tx in transactions:
                    tx_id = tx.get("id")
                    raw_amount = tx.get("amount_in") or tx.get("transferAmount") or 0
                    amount = int(float(raw_amount))
                    full_content = f"{tx.get('transaction_content', '')} {tx.get('code', '')} {tx.get('content', '')} {tx.get('description', '')}"
                    
                    user_id = extract_user_id(full_content)
                    if user_id and amount > 0:
                        if update_balance(user_id, amount, tx_id):
                            new_bal = get_balance(user_id)
                            msg = (
                                f"✅ **NẠP TIỀN THÀNH CÔNG (TỰ ĐỘNG)!**\n\n"
                                f"💰 Số tiền cộng: **+{amount:,.0f} VNĐ**\n"
                                f"💳 Số dư khả dụng: **{new_bal:,.0f} VNĐ**\n\n"
                                f"Gõ `/mua` để chọn tài khoản Facebook ngay!"
                            )
                            send_telegram_msg(user_id, msg)
        except Exception as e:
            pass
        time.sleep(15)

# --- LUỒNG TỰ ĐỘNG GIỮ SERVER KHÔNG NGUỶ 24/24 ---
def keep_alive_loop():
    """Tự ping URL chính nó để giữ server online liên tục"""
    time.sleep(30)
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    while True:
        try:
            if render_url:
                requests.get(render_url, timeout=5)
        except:
            pass
        time.sleep(240) # Ping 4 phút / lần

# --- LUỒNG LẮP LẠI LỆNH TELEGRAM BOT ---
def telegram_bot_loop():
    offset = 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    while True:
        try:
            res = requests.get(url, params={"offset": offset, "timeout": 10}).json()
            for update in res.get("result", []):
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    cb = update["callback_query"]
                    chat_id = cb["message"]["chat"]["id"]
                    data = cb.get("data", "")

                    if data.startswith("nap_"):
                        amount = int(data.split("_")[1])
                        tao_ma_qr_nap_tien(chat_id, amount)
                    continue

                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "").strip()

                if not chat_id:
                    continue

                # Lưu User vào Database
                conn = sqlite3.connect('bot.db')
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (chat_id,))
                conn.commit()
                conn.close()

                # ADMIN GỬI FILE TXT NẠP ACC HÀNG LOẠT
                if "document" in msg and chat_id == ADMIN_ID:
                    doc = msg["document"]
                    file_name = doc.get("file_name", "")
                    if file_name.endswith(".txt"):
                        file_id = doc.get("file_id")
                        file_res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}").json()
                        if file_res.get("ok"):
                            file_path = file_res["result"]["file_path"]
                            content = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}").text
                            
                            lines = [line.strip() for line in content.splitlines() if line.strip()]
                            added_count = 0
                            
                            conn = sqlite3.connect('bot.db')
                            cursor = conn.cursor()
                            for line in lines:
                                cursor.execute("INSERT INTO accounts (acc_info) VALUES (?)", (line,))
                                added_count += 1
                            conn.commit()
                            conn.close()
                            
                            total_acc = count_available_accounts()
                            send_telegram_msg(chat_id, f"✅ **ĐÃ TỰ ĐỘNG THÊM HÀNG LOẠT!**\n\n📄 File: `{file_name}`\n📥 Đã đọc: **{added_count} acc**\n📦 Tồn kho hiện tại: **{total_acc} acc**")
                    else:
                        send_telegram_msg(chat_id, "⚠️ Vui lòng gửi file đuôi `.txt`!")
                    continue

                if not text:
                    continue

                gia_acc = get_acc_price()

                if text == "/start":
                    bal = get_balance(chat_id)
                    stock = count_available_accounts()
                    reply = (
                        f"👋 **CHÀO MỪNG BẠN ĐẾN BOT BÁN ACC FB**\n\n"
                        f"🆔 ID của bạn: `{chat_id}`\n"
                        f"💰 Số dư: **{bal:,.0f} VNĐ**\n"
                        f"💵 Giá Acc FB: **{gia_acc:,.0f} VNĐ**\n"
                        f"📦 Kho hiện có: **{stock} acc**\n\n"
                        f"📌 **CÁC LỆNH:**\n"
                        f"👉 `/nap` - Nạp tiền tự động\n"
                        f"👉 `/mua` - Mua tài khoản Facebook\n"
                        f"👉 `/sodu` - Xem số dư"
                    )
                    send_telegram_msg(chat_id, reply)

                elif text.startswith("/nap"):
                    parts = text.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        tao_ma_qr_nap_tien(chat_id, int(parts[1]))
                    else:
                        buttons = {
                            "inline_keyboard": [
                                [{"text": "💵 2.000đ", "callback_data": "nap_2000"}, {"text": "💵 5.000đ", "callback_data": "nap_5000"}],
                                [{"text": "💵 10.000đ", "callback_data": "nap_10000"}, {"text": "💵 20.000đ", "callback_data": "nap_20000"}]
                            ]
                        }
                        send_telegram_msg(chat_id, "💵 **CHỌN SỐ TIỀN CẦN NẠP:**", reply_markup=buttons)

                elif text == "/sodu":
                    bal = get_balance(chat_id)
                    send_telegram_msg(chat_id, f"💰 Số dư khả dụng: **{bal:,.0f} VNĐ**")

                elif text == "/mua":
                    success, response = buy_facebook_account(chat_id)
                    send_telegram_msg(chat_id, response)

                # --- CÁC LỆNH ADMIN ---
                elif text == "/admin":
                    if chat_id != ADMIN_ID:
                        send_telegram_msg(chat_id, "⛔ Bạn không phải Admin!")
                        continue
                    stock = count_available_accounts()
                    msg = (
                        f"👑 **MENU QUẢN LÝ ADMIN**\n\n"
                        f"💵 Giá bán acc hiện tại: **{gia_acc:,.0f}đ**\n"
                        f"📦 Tồn kho hiện tại: **{stock} acc**\n\n"
                        f"📌 **CÁC LỆNH:**\n"
                        f"🔹 *Gửi file `.txt`* -> Tự động nạp hàng loạt acc\n"
                        f"🔹 `/setgia 15000` -> Sửa giá acc thành 15,000đ\n"
                        f"🔹 `/congtien 8593076954 50000` -> Cộng tiền cho user\n"
                        f"🔹 `/trutien 8593076954 10000` -> Trừ tiền của user\n"
                        f"🔹 `/thongbao Nội dung` -> Gửi thông báo đến toàn bộ user"
                    )
                    send_telegram_msg(chat_id, msg)

                elif text.startswith("/setgia"):
                    if chat_id != ADMIN_ID:
                        send_telegram_msg(chat_id, "⛔ Bạn không phải Admin!")
                        continue
                    parts = text.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        new_price = int(parts[1])
                        set_acc_price(new_price)
                        send_telegram_msg(chat_id, f"✅ Đã đổi giá bán Acc Facebook thành: **{new_price:,.0f} VNĐ**")
                    else:
                        send_telegram_msg(chat_id, "⚠️ Cú pháp: `/setgia 15000`")

                elif text.startswith("/congtien"):
                    if chat_id != ADMIN_ID:
                        send_telegram_msg(chat_id, "⛔ Bạn không phải Admin!")
                        continue
                    parts = text.split()
                    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                        target_id = int(parts[1])
                        add_amount = int(parts[2])
                        new_bal = adjust_user_balance(target_id, add_amount)
                        send_telegram_msg(chat_id, f"✅ Đã cộng **+{add_amount:,.0f}đ** cho ID `{target_id}`. Số dư mới: **{new_bal:,.0f}đ**.")
                        send_telegram_msg(target_id, f"🎉 Admin đã cộng **+{add_amount:,.0f} VNĐ** vào tài khoản của bạn!")
                    else:
                        send_telegram_msg(chat_id, "⚠️ Cú pháp: `/congtien <id_user> <số_tiền>`")

                elif text.startswith("/trutien"):
                    if chat_id != ADMIN_ID:
                        send_telegram_msg(chat_id, "⛔ Bạn không phải Admin!")
                        continue
                    parts = text.split()
                    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                        target_id = int(parts[1])
                        sub_amount = int(parts[2])
                        new_bal = adjust_user_balance(target_id, -sub_amount)
                        send_telegram_msg(chat_id, f"✅ Đã trừ **-{sub_amount:,.0f}đ** của ID `{target_id}`. Số dư mới: **{new_bal:,.0f}đ**.")
                    else:
                        send_telegram_msg(chat_id, "⚠️ Cú pháp: `/trutien <id_user> <số_tiền>`")

                elif text.startswith("/thongbao"):
                    if chat_id != ADMIN_ID:
                        send_telegram_msg(chat_id, "⛔ Bạn không phải Admin!")
                        continue
                    content = text.replace("/thongbao", "").strip()
                    if not content:
                        send_telegram_msg(chat_id, "⚠️ Cú pháp: `/thongbao Nội dung thông báo`")
                    else:
                        users = get_all_users()
                        sent = 0
                        for u in users:
                            try:
                                send_telegram_msg(u, f"📢 **THÔNG BÁO TỪ HỆ THỐNG**\n\n{content}")
                                sent += 1
                                time.sleep(0.05)
                            except:
                                pass
                        send_telegram_msg(chat_id, f"✅ Đã gửi thông báo đến **{sent}/{len(users)}** người dùng!")

        except Exception as e:
            time.sleep(2)

# --- WEBSERVER API & WEBHOOK SEPAY ---
@app.route('/', methods=['GET'])
def home():
    return "Bot Online 24/7 Running!", 200

@app.route('/webhook/sepay', methods=['POST'])
def sepay_webhook():
    try:
        data = request.json
        if not data:
            return jsonify({"success": False}), 400

        raw_amount = data.get('transferAmount') or data.get('amount_in') or 0
        amount = int(float(raw_amount))
        full_content = f"{data.get('content', '')} {data.get('description', '')} {data.get('code', '')}"
        tx_id = data.get('id')

        user_id = extract_user_id(full_content)
        if user_id and amount > 0:
            if update_balance(user_id, amount, tx_id):
                new_bal = get_balance(user_id)
                msg = (
                    f"✅ **NẠP TIỀN THÀNH CÔNG (TỰ ĐỘNG)!**\n\n"
                    f"💰 Số tiền cộng: **+{amount:,.0f} VNĐ**\n"
                    f"💳 Số dư mới: **{new_bal:,.0f} VNĐ**\n\n"
                    f"Gõ `/mua` để lấy tài khoản ngay!"
                )
                send_telegram_msg(user_id, msg)

        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Luồng Bot Telegram
    t1 = threading.Thread(target=telegram_bot_loop)
    t1.daemon = True
    t1.start()
    
    # Luồng tự động quét SePay API 15 giây / lần
    t2 = threading.Thread(target=auto_check_sepay_loop)
    t2.daemon = True
    t2.start()

    # Luồng Keep-Alive chống ngủ
    t3 = threading.Thread(target=keep_alive_loop)
    t3.daemon = True
    t3.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
