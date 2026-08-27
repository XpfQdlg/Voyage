"""
TokenWiser crypto — 敏感字段落盘加密

对 input_preview / session_id 等字段做 AES-256-GCM 加密后入库，
密钥文件放在项目目录之外（~/.tokenwiser/tw_key），避免"密钥与密文同目录"，
即使整个项目文件夹被拷走，没有密钥也读不出明文。

密文格式: "enc:v1:" + base64(nonce || ciphertext || tag)
无前缀的字符串视为旧明文，原样返回（兼容迁移）。

未安装 cryptography 时降级为明文透传（encrypt/decrypt 返回原文），
保持"Python 3.9+ 即可运行"的可移植性。装好后自动启用加密。
"""
import base64
import os
import secrets

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_KEY_DIR = os.path.expanduser("~/.tokenwiser")
KEY_PATH = os.path.join(_KEY_DIR, "tw_key")
_PREFIX = "enc:v1:"


def get_key():
    """加载密钥；不存在则生成 32 字节随机密钥并落盘。"""
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as f:
            key = f.read()
        if len(key) == 32:
            return key
    os.makedirs(_KEY_DIR, exist_ok=True)
    key = secrets.token_bytes(32)
    with open(KEY_PATH, "wb") as f:
        f.write(key)
    return key


def is_encrypted(value):
    """判断字符串是否为已加密密文（也用于迁移判断）。"""
    return isinstance(value, str) and value.startswith(_PREFIX)


def encrypt_value(plain, key=None):
    """加密字符串，返回带 'enc:v1:' 前缀的密文。空字符串原样返回。

    未安装 cryptography 时降级为明文透传。
    """
    if not plain or not _AVAILABLE:
        return plain or ""
    key = key or get_key()
    nonce = secrets.token_bytes(12)  # GCM 安全随机 nonce，一次一密
    ct = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_value(token, key=None):
    """解密 'enc:v1:' 密文；无前缀的旧明文原样返回。密钥错误会抛异常。

    未安装 cryptography 时原样返回（此时数据本就未加密）。
    """
    if not token or not is_encrypted(token) or not _AVAILABLE:
        return token
    key = key or get_key()
    raw = base64.b64decode(token[len(_PREFIX):])
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
