# Technocore / Flop Labs DID Key Utilities (Ed25519)

Bộ công cụ tạo và quản lý **DID Key (`did:key`)** chuẩn Ed25519 cho Flop Labs & Technocore.

## 🚀 Hướng Dẫn Sử Dụng

### Cách 1: Node.js (Zero-Dependency - Không cần cài thêm thư viện)
Chạy trực tiếp với Node.js:
```bash
node generate_did.js
```

### Cách 2: Python
Cài đặt thư viện phụ thuộc:
```bash
pip install cryptography base58
```
Chạy script:
```bash
python generate_did.py
```

---

## 📌 Các tính năng hỗ trợ
1. **Tạo keypair Ed25519**: Sinh ra `did:key:z6Mk...` chuẩn Multicodec + Base58btc.
2. **Ký dữ liệu/tin nhắn**: Dùng Private Key để ký payload trước khi gửi tới Technocore.

⚠️ **LƯU Ý BẢO MẬT CỰC KỲ QUAN TRỌNG:**
- **Private Key** là quyền truy cập duy nhất để claim airdrop hoặc xác minh danh tính.
- Tuyệt đối KHÔNG commit Private Key lên GitHub hoặc chia sẻ công khai.
