"""自签 HTTPS 证书：首次启动生成，存在挂载目录里，重建镜像也不丢。"""

import ipaddress
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def ensure_cert(directory, ip=""):
    directory = Path(directory)
    crt, key = directory / "cert.pem", directory / "key.pem"
    if crt.exists() and key.exists():
        return crt, key
    directory.mkdir(parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "spark-console")])
    san = [x509.DNSName("localhost")]
    if ip:
        san.append(x509.IPAddress(ipaddress.ip_address(ip)))
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(private, hashes.SHA256())
    )
    key.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key.chmod(0o600)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return crt, key


def make_context(directory, ip=""):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    crt, key = ensure_cert(directory, ip)
    ctx.load_cert_chain(crt, key)
    return ctx
