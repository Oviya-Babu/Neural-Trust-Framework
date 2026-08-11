"""X.509 cert/key generation for sensors/device_sensor.py's DTLS handshake
(Phase 8 Step 3). Genuine certificates via the `cryptography` library
(real RSA keypairs, real X.509 encoding) -- used to drive a real OpenSSL
DTLS handshake, not a hand-rolled protocol stand-in. Kept in its own module
so device_sensor.py's docstring can stay focused on the measurement
contract rather than PKI plumbing.
"""

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

KEY_SIZE = 2048


def _generate_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)


def _self_signed_cert(key, common_name: str, not_before: datetime.datetime, not_after: datetime.datetime,
                       issuer_key=None, issuer_name=None, is_ca=False):
    """If issuer_key/issuer_name are given, the cert is signed by that
    issuer (a CA-issued leaf cert); otherwise it is self-signed (used both
    for the CA root itself and for the deliberately-untrusted 'invalid
    cert' attack case). is_ca sets the BasicConstraints CA flag OpenSSL
    requires on a root before it will accept it as a trust anchor at all
    (without it, OpenSSL rejects the CA itself with 'invalid CA
    certificate', before it even gets to checking the leaf)."""
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = issuer_name if issuer_name is not None else subject
    signing_key = issuer_key if issuer_key is not None else key
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    cert = builder.sign(signing_key, hashes.SHA256())
    return cert


def _pem(key=None, cert=None) -> bytes:
    out = b""
    if key is not None:
        out += key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    if cert is not None:
        out += cert.public_bytes(serialization.Encoding.PEM)
    return out


def make_ca() -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    key = _generate_key()
    cert = _self_signed_cert(key, "device-link-test-ca", now - datetime.timedelta(days=1),
                              now + datetime.timedelta(days=365), is_ca=True)
    return {"key": key, "cert": cert, "cert_pem": _pem(cert=cert), "key_pem": _pem(key=key)}


def make_valid_server_cert(ca: dict) -> dict:
    """A server leaf cert genuinely signed by the CA, currently valid --
    the honest-operation case."""
    now = datetime.datetime.now(datetime.timezone.utc)
    key = _generate_key()
    cert = _self_signed_cert(
        key, "device-link-server", now - datetime.timedelta(minutes=5), now + datetime.timedelta(days=30),
        issuer_key=ca["key"], issuer_name=ca["cert"].subject,
    )
    return {"key": key, "cert": cert, "cert_pem": _pem(cert=cert), "key_pem": _pem(key=key),
            "combined_pem": _pem(key=key, cert=cert)}


def make_expired_server_cert(ca: dict) -> dict:
    """Attack case: expired cert -- signed by the real CA, but its validity
    window is entirely in the past. A DTLS client verifying against the CA
    must still reject this at the certificate-validity check."""
    now = datetime.datetime.now(datetime.timezone.utc)
    key = _generate_key()
    cert = _self_signed_cert(
        key, "device-link-server-expired",
        now - datetime.timedelta(days=30), now - datetime.timedelta(days=1),
        issuer_key=ca["key"], issuer_name=ca["cert"].subject,
    )
    return {"key": key, "cert": cert, "cert_pem": _pem(cert=cert), "key_pem": _pem(key=key),
            "combined_pem": _pem(key=key, cert=cert)}


def make_untrusted_server_cert() -> dict:
    """Attack case: invalid cert -- a currently-valid, well-formed cert
    that is NOT signed by the CA the client trusts (e.g. an attacker's own
    self-signed cert substituted at the device link). A DTLS client
    verifying against the real CA must reject this at chain verification."""
    now = datetime.datetime.now(datetime.timezone.utc)
    key = _generate_key()
    cert = _self_signed_cert(key, "device-link-server-untrusted",
                              now - datetime.timedelta(minutes=5), now + datetime.timedelta(days=30))
    return {"key": key, "cert": cert, "cert_pem": _pem(cert=cert), "key_pem": _pem(key=key),
            "combined_pem": _pem(key=key, cert=cert)}
