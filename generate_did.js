const crypto = require('crypto');

// Bảng mã Base58btc
const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function base58Encode(buffer) {
    if (buffer.length === 0) return '';
    let digits = [0];
    for (let i = 0; i < buffer.length; i++) {
        for (let j = 0; j < digits.length; j++) digits[j] <<= 8;
        digits[0] += buffer[i];
        let carry = 0;
        for (let j = 0; j < digits.length; j++) {
            digits[j] += carry;
            carry = (digits[j] / 58) | 0;
            digits[j] %= 58;
        }
        while (carry > 0) {
            digits.push(carry % 58);
            carry = (carry / 58) | 0;
        }
    }
    for (let i = 0; i < buffer.length && buffer[i] === 0; i++) {
        digits.push(0);
    }
    return digits.reverse().map(d => ALPHABET[d]).join('');
}

function generateDidKey() {
    const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519');
    
    // Lấy 32 bytes raw public key từ DER SPKI
    const pubSpki = publicKey.export({ format: 'der', type: 'spki' });
    const pubBytes = pubSpki.subarray(pubSpki.length - 32);
    
    // Lấy 32 bytes raw private key từ DER PKCS8
    const privPkcs8 = privateKey.export({ format: 'der', type: 'pkcs8' });
    const privBytes = privPkcs8.subarray(privPkcs8.length - 32);
    
    // Multicodec prefix cho Ed25519 = 0xed01
    const multicodecPub = Buffer.concat([Buffer.from([0xed, 0x01]), pubBytes]);
    
    // Thêm tiền tố multibase 'z' cho base58btc
    const didKey = 'did:key:z' + base58Encode(multicodecPub);
    
    return {
        didKey,
        publicKeyHex: pubBytes.toString('hex'),
        privateKeyHex: privBytes.toString('hex')
    };
}

function signMessage(privateKeyHex, message) {
    const privBytes = Buffer.from(privateKeyHex, 'hex');
    // Đóng gói PKCS8 DER cho Node.js crypto
    const pkcs8Header = Buffer.from('302e020100300506032b657004220420', 'hex');
    const pkcs8Der = Buffer.concat([pkcs8Header, privBytes]);
    const keyObj = crypto.createPrivateKey({
        key: pkcs8Der,
        format: 'der',
        type: 'pkcs8'
    });
    
    const signature = crypto.sign(null, Buffer.from(message, 'utf-8'), keyObj);
    return signature.toString('hex');
}

if (require.main === module) {
    const keys = generateDidKey();
    console.log("==================================================");
    console.log("🔑 TECHNOCORE DID KEY GENERATOR (Node.js Zero-Dep)");
    print = console.log;
    print("==================================================");
    print(`DID Key         : ${keys.didKey}`);
    print(`Public Key (Hex): ${keys.publicKeyHex}`);
    print(`Private Key(Hex): ${keys.privateKeyHex}`);
    print("==================================================");
    print("⚠️  LƯU Ý BẢO MẬT: Giữ bí mật Private Key!");
    print("==================================================");
}

module.exports = { generateDidKey, signMessage };
