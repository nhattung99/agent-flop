try:
    import sys
    import json
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    from cryptography.hazmat.primitives.asymmetric import ed25519
    import base58
except ImportError:
    print("❌ Thiếu thư viện! Vui lòng cài đặt trước:")
    print("   pip install cryptography base58")
    sys.exit(1)

def generate_did_key():
    # 1. Tạo Ed25519 Private Key
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    # 2. Lấy raw bytes (32 bytes mỗi loại)
    pub_bytes = public_key.public_bytes_raw()
    priv_bytes = private_key.private_bytes_raw()
    
    # 3. Multicodec prefix cho Ed25519 public key = 0xed01 (2 bytes)
    multicodec_prefix = b'\xed\x01'
    multicodec_pub = multicodec_prefix + pub_bytes
    
    # 4. Base58btc encoding với tiền tố multibase 'z'
    did_key = "did:key:z" + base58.b58encode(multicodec_pub).decode('ascii')
    
    return {
        "did_key": did_key,
        "public_key_hex": pub_bytes.hex(),
        "private_key_hex": priv_bytes.hex()
    }

def sign_payload(private_key_hex: str, message: str) -> str:
    priv_bytes = bytes.fromhex(private_key_hex)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
    signature = private_key.sign(message.encode('utf-8'))
    return signature.hex()

if __name__ == "__main__":
    key_pair = generate_did_key()
    print("==================================================")
    print("🔑 TECHNOCORE DID KEY GENERATOR (Ed25519)")
    print("==================================================")
    print(f"DID Key         : {key_pair['did_key']}")
    print(f"Public Key (Hex): {key_pair['public_key_hex']}")
    print(f"Private Key(Hex): {key_pair['private_key_hex']}")
    print("==================================================")
    print("⚠️  LƯU Ý BẢO MẬT: Giữ bí mật Private Key!")
    print("   Dùng Private Key này để ký tin nhắn/claim airdrop sau này.")
    print("==================================================")
