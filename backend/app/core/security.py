"""认证与密钥工具：密码 bcrypt 哈希、JWT 签发/校验、敏感配置 Fernet 对称加解密。"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet
from jose import jwt

from app.config import settings

ALGORITHM = "HS256"  # JWT 签名算法，密钥取自 settings.SECRET_KEY


def hash_password(password: str) -> str:
    """bcrypt 加盐哈希密码。盐随机生成，同一密码每次结果不同，比较必须用 verify_password。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与存储哈希是否匹配（bcrypt.checkpw 内置恒定时间比较，抗时序侧信道）。"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, role: str) -> str:
    """签发 JWT：payload 含 sub(用户 id)、role、exp(过期时间)，HS256 + SECRET_KEY 签名。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解析并校验 JWT 签名与过期时间；签名无效/已过期抛 JWTError，由调用方转 401。"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def _fernet() -> Fernet:
    # Fernet 要求 32 字节 urlsafe_base64 密钥：用 AES_KEY 的 sha256 派生，长度恒为 32 字节
    key = hashlib.sha256(settings.AES_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plain: str) -> str:
    """对称加密敏感串（如模型 API Key）后落库，解密用 decrypt_secret。

    密钥由 settings.AES_KEY 派生：轮换 AES_KEY 后旧密文将无法解密，需重新录入明文。
    """
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(enc: str) -> str:
    """解密 encrypt_secret 的产物；密文损坏或密钥不匹配抛 InvalidToken。"""
    return _fernet().decrypt(enc.encode("utf-8")).decode("utf-8")
