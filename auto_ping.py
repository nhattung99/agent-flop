import sys
import os
import time
import json
import random
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
ROOMS = [
    "lobby",
    "mb-sonnet-2-registration",
    "tclk-offers",
    "meta",
    "d-cipher-vault-960387-45-kdjzs",
    "kibble",
    "turkce-koprusu",
    "market",
    "cryptoonflop",
    "d-techno-hub",
    "mb-sovereign-council-372290-26-vqaj5",
    "zk_rollups",
    "mb-cipher-vault-275051-90-95smd",
    "d-cipher-vault-339268-96-ncmvs",
    "f9603c81e9972d0f",
    "d-realm-elhoof-vqaj5",
    "434cb357c8094fdd",
    "78643f54657eff7a",
    "3f660e608f4deedb",
    "d-sonnet-2-team-x1-hx-ez-as",
    "rates",
    "63e70ac7db7c4246",
    "d-trust-nexus-881073-90-xtr6e",
    "monflop-node",
    "flights",
    "d-sovereign-council-869917-14-4gbeo",
    "d-gpu",
    "4eb4dbb684f1916d",
    "7751426dec819103",
    "d-x",
    "71ba4d075a864054",
    "7641d38ae2dcd5f9",
    "ai2ai",
]
SEED_ROOMS = list(ROOMS)
ROOM_BURST_MIN = 10
ROOM_BURST_MAX = 100
CATALOG_REFRESH_SECONDS = 6 * 60 * 60
# DID note idle 7 ngày sẽ bị reclaim — refresh mỗi 24 giờ
NOTE_REFRESH_SECONDS = 24 * 60 * 60
PROFILE_LABEL = "Agent Flop | Panda (nhattung00)"

STATE_FILES = ("last_message.json", "bot_state.json")

def log_message(text):
    print(text)
    try:
        with open("bot.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

def save_message_state(state):
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    for path in STATE_FILES:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
        except Exception:
            pass

def load_progress():
    count = 1
    recent = []
    last_note_at = 0
    for path in STATE_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            last = state.get("last") or {}
            total_sent = int(state.get("total_sent") or 0)
            recent = state.get("recent") or []
            last_note_at = float(state.get("last_note_at") or 0)
            rotation = {
                "room": state.get("current_room") or "",
                "remaining": int(state.get("room_remaining") or 0),
                "burst": int(state.get("room_burst") or 0),
                "skipped": list(state.get("skipped_rooms") or []),
            }
            if last.get("status") == "error" and last.get("count"):
                count = int(last["count"])
            else:
                count = total_sent + 1
            if count < 1:
                count = 1
            return count, recent, last_note_at, rotation
        except Exception:
            continue
    return count, recent, last_note_at, {
        "room": "",
        "remaining": 0,
        "burst": 0,
        "skipped": [],
    }


def pick_room(prev, skipped):
    skipped_set = set(skipped)
    choices = [r for r in ROOMS if r not in skipped_set and r != prev]
    if not choices:
        skipped_set.clear()
        skipped[:] = []
        choices = [r for r in ROOMS if r != prev] or list(ROOMS)
    return random.choice(choices)


def assign_room_burst(prev, skipped):
    room = pick_room(prev, skipped)
    burst = random.randint(ROOM_BURST_MIN, ROOM_BURST_MAX)
    return room, burst


def refresh_room_catalog(client):
    """Gộp list cố định với catalog /rooms (chỉ ~50 room mới nhất)."""
    global ROOMS
    merged = list(dict.fromkeys(SEED_ROOMS))
    added = 0
    total = None
    try:
        live, total = client.list_public_rooms()
        for name in live:
            if not name or name.startswith("mb-pair-"):
                continue
            if name not in merged:
                merged.append(name)
                added += 1
        ROOMS = merged
        extra = f"; server báo ~{total} room, API chỉ trả {len(live)}" if total is not None else ""
        log_message(f"📡 Catalog /rooms: +{added} room live, tổng pool {len(ROOMS)}{extra}")
    except Exception as e:
        ROOMS = merged
        log_message(f"⚠️ Không lấy được /rooms: {e}. Dùng {len(ROOMS)} room cố định.")
    return ROOMS

def publish_profile_note(client):
    try:
        result = client.ensure_profile_note(PROFILE_LABEL)
        status = result.get("status")
        url = result.get("url") or client.note_url
        log_message(f"🪪 Profile note ({status}): {url}")
        return {"ok": True, "status": status, "url": url}
    except Exception as e:
        log_message(f"⚠️ Profile note chưa ghi được: {e}. Bot vẫn tiếp tục ping.")
        return {"ok": False, "status": "error", "url": client.note_url, "error": str(e)}

def run_auto_ping(once=False):
    if os.getenv("GITHUB_ACTIONS") == "true" and not os.getenv("TECHNOCORE_PRIVATE_KEY"):
        log_message("❌ Thiếu GitHub Secret TECHNOCORE_PRIVATE_KEY.")
        sys.exit(1)

    client = TechnocoreClient(DEFAULT_PRIVATE_KEY)
    refresh_room_catalog(client)
    last_catalog_at = time.time()
    count, recent, last_note_at, rotation = load_progress()
    note_state = {"ok": False, "url": client.note_url}
    skipped = list(rotation.get("skipped") or [])
    current_room = rotation.get("room") or ""
    remaining = int(rotation.get("remaining") or 0)
    burst = int(rotation.get("burst") or 0)
    if current_room not in ROOMS or remaining <= 0:
        current_room, burst = assign_room_burst(current_room, skipped)
        remaining = burst
    mode = "GitHub Actions (1 tin / lần chạy)" if once else "always-on"

    log_message("==================================================")
    log_message(f"🤖 TECHNOCORE AUTO-PING BOT (Agent Flop) — {mode}")
    log_message("==================================================")
    log_message(f"🔑 DID Key         : {client.did_key}")
    log_message(f"🪪 Profile note    : {client.note_url}")
    log_message(f"⏱️ Khoảng thời gian: 2 phút / 1 tin nhắn ({INTERVAL_SECONDS} giây)")
    log_message(f"💬 Rooms           : {', '.join(ROOMS)}")
    log_message(f"🎲 Room hiện tại   : {current_room} ({remaining}/{burst} tin còn lại)")
    log_message(f"🔢 Tiếp tục từ msg #{count} (đã gửi thành công {max(count - 1, 0)} tin)")
    log_message("==================================================")

    now = time.time()
    if (now - last_note_at) >= NOTE_REFRESH_SECONDS:
        note_state = publish_profile_note(client)
        last_note_at = now
    else:
        log_message("🪪 Profile note còn hạn, bỏ qua bước refresh.\n")

    while True:
        now = time.time()
        if not once and (now - last_catalog_at) >= CATALOG_REFRESH_SECONDS:
            refresh_room_catalog(client)
            last_catalog_at = now
        if not once and (now - last_note_at) >= NOTE_REFRESH_SECONDS:
            note_state = publish_profile_note(client)
            last_note_at = now

        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if remaining <= 0:
            prev = current_room
            current_room, burst = assign_room_burst(prev, skipped)
            remaining = burst
            log_message(f"🔄 Đổi room: {prev} → {current_room} (gửi {burst} tin rồi chuyển)")

        msg = (
            f"Agent Flop check-in #{count} | Panda (nhattung00) | "
            f"{client.did_key} | room {current_room} | active & verified at {timestamp_str}"
        )
        entry = {
            "count": count,
            "text": msg,
            "time": timestamp_str,
            "room": current_room,
            "status": "sending",
        }
        try:
            log_message(f"[{timestamp_str}] 📤 Gửi msg #{count} → #{current_room} ({remaining}/{burst})")
            log_message(f"[{timestamp_str}] 💬 Nội dung: {msg}")
            client.post_signed_message(current_room, msg)
            entry["status"] = "sent"
            log_message(f"[{timestamp_str}] ✅ Đã gửi thành công msg #{count} vào {current_room}")
            count += 1
            remaining -= 1
        except KeyboardInterrupt:
            log_message("\n🛑 Đã dừng Auto-Ping Bot.")
            sys.exit(0)
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            err_text = str(e)
            log_message(f"[{timestamp_str}] ⚠️ Lỗi khi gửi vào {current_room}: {e}")
            if "403" in err_text or "denied" in err_text.lower() or "own" in err_text.lower():
                if current_room not in skipped:
                    skipped.append(current_room)
                log_message(f"⏭️ Bỏ room {current_room} (không ghi được). Đổi room khác.")
                remaining = 0
            else:
                log_message(f"Sẽ thử lại sau {INTERVAL_SECONDS}s...")

        recent.append(entry)
        recent = recent[-20:]
        save_message_state({
            "last": entry,
            "recent": recent,
            "total_sent": count - 1,
            "did_key": client.did_key,
            "room": current_room,
            "current_room": current_room,
            "room_remaining": remaining,
            "room_burst": burst,
            "skipped_rooms": skipped,
            "interval": INTERVAL_SECONDS,
            "profile_note": note_state,
            "last_note_at": last_note_at,
        })

        if once:
            if entry.get("status") != "sent":
                sys.exit(1)
            log_message("GitHub Actions: đã gửi 1 tin, kết thúc job.")
            return

        log_message(f"⏳ Chờ {INTERVAL_SECONDS} giây (2 phút) cho lần gửi tiếp theo...\n")
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    run_auto_ping(once="--once" in sys.argv)
