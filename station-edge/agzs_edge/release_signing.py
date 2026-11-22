"""Единый контракт канонической подписи OTA-релизов station-edge (Ed25519 и legacy HMAC-SHA256).

Этот файл должен быть побайтово идентичен копиям в backend и station-edge,
чтобы байты канонической строки и проверка подписи никогда не расходились.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import urllib.parse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

CANONICAL_VERSION = "agzs-edge-release-v2"
ED25519_PREFIX = "ed25519:"


def normalize_channel(channel: str) -> str:
    """Нормализует имя канала в одно из трёх колец: ring0, ring1 или ring2."""
    token = (channel or "").strip().lower()
    if token in {"canary", "ring0"}:
        return "ring0"
    if token == "ring1":
        return "ring1"
    return "ring2"


def parse_version_tuple(version: str) -> tuple[int, ...]:
    """Разбирает строку версии ('0.2.1', 'v1.0.3') в кортеж целых чисел."""
    cleaned = version.strip().lstrip("vV")
    if not cleaned:
        return (0,)
    parts: list[int] = []
    for token in cleaned.split("."):
        match = re.match(r"^(\d+)", token.strip())
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def normalize_artifact_path(artifact_url: str) -> str:
    """Выделяет нормализованный путь артефакта (одинаковый для relative и full URL)."""
    raw = (artifact_url or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    path = parsed.path or raw
    return "/" + path.lstrip("/")


def canonical_release_payload(
    version: str,
    sha256: str,
    min_version: str | None = None,
    *,
    channel: str = "",
    artifact_url: str = "",
) -> bytes:
    """Каноническая байтовая строка для криптоподписи OTA-манифеста station-edge."""
    norm_channel = normalize_channel(channel) if channel.strip() else ""
    norm_path = normalize_artifact_path(artifact_url) if artifact_url.strip() else ""
    return (
        f"{CANONICAL_VERSION}\n"
        f"{version.strip()}\n"
        f"{sha256.strip().lower()}\n"
        f"{(min_version or '').strip()}\n"
        f"{norm_channel}\n"
        f"{norm_path}"
    ).encode("utf-8")


def _load_ed25519_private_key(raw_key: str) -> Ed25519PrivateKey:
    key_text = raw_key.strip()
    if not key_text:
        raise ValueError("пустой приватный ключ Ed25519")
    if key_text.startswith("-----BEGIN "):
        loaded = serialization.load_pem_private_key(key_text.encode("utf-8"), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ValueError("ожидался приватный ключ Ed25519")
        return loaded
    raw_bytes = bytes.fromhex(key_text)
    if len(raw_bytes) != 32:
        raise ValueError("приватный ключ Ed25519 в hex должен быть длиной 64 символа (32 байта)")
    return Ed25519PrivateKey.from_private_bytes(raw_bytes)


def _load_ed25519_public_key(raw_key: str) -> Ed25519PublicKey:
    key_text = raw_key.strip()
    if not key_text:
        raise ValueError("пустой публичный ключ Ed25519")
    if key_text.startswith("-----BEGIN "):
        loaded = serialization.load_pem_public_key(key_text.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise ValueError("ожидался публичный ключ Ed25519")
        return loaded
    raw_bytes = bytes.fromhex(key_text)
    if len(raw_bytes) != 32:
        raise ValueError("публичный ключ Ed25519 в hex должен быть длиной 64 символа (32 байта)")
    return Ed25519PublicKey.from_public_bytes(raw_bytes)


def generate_ed25519_keypair() -> tuple[str, str]:
    """Генерирует пару ключей Ed25519 в hex: `(private_hex_64, public_hex_64)`."""
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return priv_hex, pub_hex


def derive_ed25519_public_key(private_key: str) -> str:
    """Возвращает публичный ключ Ed25519 в hex (64 символа) из приватного ключа."""
    priv = _load_ed25519_private_key(private_key)
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def sign_release_ed25519(
    version: str,
    sha256: str,
    min_version: str | None,
    private_key: str,
    *,
    channel: str = "",
    artifact_url: str = "",
) -> str:
    """Подписывает манифест релиза приватным ключом Ed25519 -> 'ed25519:<128 hex>'."""
    priv = _load_ed25519_private_key(private_key)
    payload = canonical_release_payload(
        version,
        sha256,
        min_version,
        channel=channel,
        artifact_url=artifact_url,
    )
    sig = priv.sign(payload)
    return f"{ED25519_PREFIX}{sig.hex()}"


def verify_release_ed25519(
    version: str,
    sha256: str,
    min_version: str | None,
    signature: str | None,
    public_key: str,
    *,
    channel: str = "",
    artifact_url: str = "",
) -> bool:
    """Проверяет асимметричную подпись 'ed25519:<hex>' публичным ключом станционного узла."""
    sig_text = (signature or "").strip().lower()
    if not sig_text.startswith(ED25519_PREFIX):
        return False
    hex_sig = sig_text[len(ED25519_PREFIX) :]
    try:
        sig_bytes = bytes.fromhex(hex_sig)
        if len(sig_bytes) != 64:
            return False
        pub = _load_ed25519_public_key(public_key)
        payload = canonical_release_payload(
            version,
            sha256,
            min_version,
            channel=channel,
            artifact_url=artifact_url,
        )
        pub.verify(sig_bytes, payload)
        return True
    except (ValueError, InvalidSignature):
        return False


def sign_release_manifest(
    version: str,
    sha256: str,
    min_version: str | None,
    signing_key: str,
    *,
    channel: str = "",
    artifact_url: str = "",
) -> str:
    """Вычисляет legacy HMAC-SHA256 (hex lowercase) для релиза station-edge."""
    return hmac.new(
        signing_key.strip().encode("utf-8"),
        canonical_release_payload(
            version,
            sha256,
            min_version,
            channel=channel,
            artifact_url=artifact_url,
        ),
        hashlib.sha256,
    ).hexdigest().lower()


def verify_release_signature(
    version: str,
    sha256: str,
    min_version: str | None,
    signature: str | None,
    signing_key: str,
    *,
    channel: str = "",
    artifact_url: str = "",
) -> bool:
    """Проверяет legacy HMAC-SHA256 подпись манифеста релиза (constant-time сравнение)."""
    sig = (signature or "").strip().lower()
    key = signing_key.strip()
    if not sig or not key or sig.startswith(ED25519_PREFIX):
        return False
    expected = sign_release_manifest(
        version,
        sha256,
        min_version,
        key,
        channel=channel,
        artifact_url=artifact_url,
    )
    return hmac.compare_digest(sig, expected)


__all__ = [
    "CANONICAL_VERSION",
    "ED25519_PREFIX",
    "canonical_release_payload",
    "derive_ed25519_public_key",
    "generate_ed25519_keypair",
    "normalize_artifact_path",
    "normalize_channel",
    "parse_version_tuple",
    "sign_release_ed25519",
    "sign_release_manifest",
    "verify_release_ed25519",
    "verify_release_signature",
]
