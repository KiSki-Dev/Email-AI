import os, base64, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def load_aes_key():
    b64 = os.getenv("CHAT_AES_KEY_B64")
    if not b64:
        sys.exit("CHAT_AES_KEY_B64 environment variable not set.")
    AES_KEY = base64.b64decode(b64) #* 32 raw bytes
    aesgcm = AESGCM(AES_KEY)
    return aesgcm

def seal(aesgcm, plaintext: str) -> bytes: #! Encrypts a plaintext and returns nonce+ciphertext
    nonce = os.urandom(12) #* 96‑Bit    
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ct

def open_sealed(aesgcm, blob: bytes) -> str: #! Decrypts a nonce+ciphertext blob back into a string
    nonce, ct = blob[:12], blob[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()