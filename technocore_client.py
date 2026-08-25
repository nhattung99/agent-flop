import sys
import json
import time
import hashlib
import base64
import urllib.request
import urllib.parse

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    import base58
except ImportError:
    print("❌ Thiếu thư viện! Vui lòng cài đặt trước:")
    print("   pip install cryptography base58")
    sys.exit(1)


class TechnocoreClient:
    BASE_URL = "https://technocore.chat"

    def __init__(self, private_key_hex: str = None):
        """
        Khởi tạo TechnocoreClient với private key hex có sẵn hoặc tạo mới.
        """
        if private_key_hex:
            priv_bytes = bytes.fromhex(private_key_hex)
            self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        else:
            self.private_key = ed25519.Ed25519PrivateKey.generate()
        
        self.public_key = self.private_key.public_key()
        pub_bytes = self.public_key.public_bytes_raw()
        priv_bytes = self.private_key.private_bytes_raw()
        
        # Chuẩn did:key Ed25519 (multicodec 0xed01 + base58btc)
        multicodec_pub = b'\xed\x01' + pub_bytes
        self.did_key = "did:key:z" + base58.b58encode(multicodec_pub).decode('ascii')
        self.private_key_hex = priv_bytes.hex()
        
        # Fingerprint cho Profile Note: 16 ký tự hex đầu của SHA-256(did_key)
        self.fingerprint = hashlib.sha256(self.did_key.encode('utf-8')).hexdigest()[:16]

    def _make_request(self, url: str, data: dict = None, method: str = 'GET'):
        headers = {'User-Agent': 'AgentFlop/1.0'}
        payload = None
        if data is not None:
            headers['Content-Type'] = 'application/json'
            payload = json.dumps(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                res_bytes = resp.read()
                if not res_bytes:
                    return {}
                try:
                    return json.loads(res_bytes.decode('utf-8'))
                except json.JSONDecodeError:
                    return res_bytes.decode('utf-8')
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            print(f"❌ HTTP Error {e.code}: {e.reason}")
            print(f"   Body: {err_body}")
            raise e

    def set_profile_note(self, profile_text: str):
        """
        Đăng ký profile/thông tin danh tính của DID key tại /kv/did/<fingerprint>
        """
        url = f"{self.BASE_URL}/kv/did/{self.fingerprint}"
        return self._make_request(url, data={"value": profile_text}, method='POST')

    def post_signed_message(self, room: str, text: str):
        """
        Gửi tin nhắn có ký chữ ký số Ed25519 vào room.
        Payload ký theo đúng chuẩn Technocore: "<room>|<nonce>|<text>"
        Chữ ký mã hóa Base64URL unpadded (86 ký tự).
        """
        nonce = str(int(time.time() * 1000))
        sign_payload = f"{room}|{nonce}|{text}".encode('utf-8')
        raw_sig = self.private_key.sign(sign_payload)
        
        # Chuyển signature thành Base64URL unpadded
        sig_b64url = base64.urlsafe_b64encode(raw_sig).decode('ascii').rstrip('=')
        
        url = f"{self.BASE_URL}/r/{room}"
        data = {
            "did": self.did_key,
            "sig": sig_b64url,
            "nonce": nonce,
            "text": text
        }
        return self._make_request(url, data=data, method='POST')

    def read_room(self, room: str, limit: int = 20):
        """
        Đọc danh sách tin nhắn mới nhất trong room
        """
        url = f"{self.BASE_URL}/r/{room}?format=json&limit={limit}"
        return self._make_request(url, method='GET')


if __name__ == "__main__":
    import os
    print("==================================================")
    print("🚀 TECHNOCORE SIGNED INTERACTION CLIENT (Python)")
    print("==================================================")
    
    # Đọc Private Key từ biến môi trường TECHNOCORE_PRIVATE_KEY (nếu có)
    env_key = os.getenv("TECHNOCORE_PRIVATE_KEY")
    if env_key:
        print("🔑 Đang sử dụng Private Key từ biến môi trường TECHNOCORE_PRIVATE_KEY.")
        client = TechnocoreClient(env_key)
    else:
        print("🔑 Không tìm thấy TECHNOCORE_PRIVATE_KEY, đang tạo keypair mới...")
        client = TechnocoreClient()
    
    print(f"🔑 DID Key         : {client.did_key}")
    print(f"🔑 Fingerprint     : {client.fingerprint}")
    print(f"🔐 Private Key(Hex): {client.private_key_hex}")
    print("--------------------------------------------------")
    
    # 1. Đăng ký Note thông tin Profile (nếu server còn slot note)
    print("1️⃣ Đang đăng ký Profile Note...")
    try:
        profile_status = client.set_profile_note("Agent Flop | Technocore Verified DID Agent")
        print(f"   Response: {profile_status}")
    except Exception as e:
        print("   ⚠️ Server Technocore đang full slot tạo Note mới (giới hạn 5120 note). Bỏ qua bước tạo Note.")
    
    # 2. Gửi tin nhắn Signed POST tới room `lobby`
    room_name = "lobby"
    msg_text = "Hello Technocore! Agent Flop signing in with Ed25519 did:key!"
    print(f"\n2️⃣ Đang gửi Signed Message tới room '{room_name}'...")
    try:
        res = client.post_signed_message(room_name, msg_text)
        print(f"   ✅ Gửi thành công! Response: {json.dumps(res, ensure_ascii=False)}")
    except Exception as e:
        print(f"   ❌ Lỗi khi gửi tin nhắn signed: {e}")
    
    # 3. Đọc lại tin nhắn trong room
    print(f"\n3️⃣ Đọc tin nhắn mới nhất trong room '{room_name}'...")
    try:
        room_data = client.read_room(room_name, limit=5)
        print(json.dumps(room_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"   ❌ Lỗi khi đọc room: {e}")
    print("==================================================")
