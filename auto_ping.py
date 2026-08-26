import sys
import os
import time
import json
from technocore_client import TechnocoreClient

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Private Key cố định của bạn (Có thể lấy từ ENV hoặc gán mặc định)
DEFAULT_PRIVATE_KEY = os.getenv(
    "TECHNOCORE_PRIVATE_KEY", 
    "b044ae6441be14d75dcb3ac3bda89a66753efb0b866a5b2a78acc0a0c30d9629"
)

# Khoảng thời gian gửi tin nhắn (120 giây = 2 phút)
INTERVAL_SECONDS = 120
ROOM_NAME = "lobby"

def log_message(text):
    print(text)
    try:
        with open("bot.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

def run_auto_ping():
    client = TechnocoreClient(DEFAULT_PRIVATE_KEY)
    # Clear log file on startup
    try:
        with open("bot.log", "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    log_message("==================================================")
    log_message("🤖 TECHNOCORE AUTO-PING BOT (Agent Flop)")
    log_message("==================================================")
    log_message(f"🔑 DID Key         : {client.did_key}")
    log_message(f"⏱️ Khoảng thời gian: 2 phút / 1 tin nhắn ({INTERVAL_SECONDS} giây)")
    log_message(f"💬 Room            : {ROOM_NAME}")
    log_message("==================================================")
    log_message("Press Ctrl+C to stop.\n")

    count = 1
    while True:
        try:
            timestamp_str = time.strftime("%H:%M:%S", time.localtime())
            msg = f"Agent Flop check-in #{count} | Panda (nhattung00) | active & verified at {timestamp_str}"
            
            log_message(f"[{timestamp_str}] 📤 Sending msg #{count}...")
            res = client.post_signed_message(ROOM_NAME, msg)
            
            log_message(f"[{timestamp_str}] ✅ Gửi thành công msg #{count}!")
            count += 1
            
        except KeyboardInterrupt:
            log_message("\n🛑 Đã dừng Auto-Ping Bot.")
            sys.exit(0)
        except Exception as e:
            log_message(f"⚠️ Lỗi khi gửi: {e}. Sẽ thử lại sau {INTERVAL_SECONDS}s...")
        
        log_message(f"⏳ Chờ {INTERVAL_SECONDS} giây (2 phút) cho lần gửi tiếp theo...\n")
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    run_auto_ping()
