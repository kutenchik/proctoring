"""Session-local PIN verification without retaining a plaintext PIN."""

import hashlib
import hmac
import secrets


class PinVerifier:
    """Salted PBKDF2 plus constant-time digest comparison.

    This is a local demo gate, not an anti-tamper boundary on a managed device.
    Neither candidate PINs nor their hashes are written to logs.
    """

    _ITERATIONS = 210_000

    def __init__(self, pin: str):
        if not isinstance(pin, str) or not pin:
            raise ValueError("Proctor PIN must be a nonempty string")
        self._salt = secrets.token_bytes(16)
        self._digest = self._derive(pin)

    def _derive(self, value: str) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", value.encode("utf-8"), self._salt, self._ITERATIONS
        )

    def verify(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        return hmac.compare_digest(self._digest, self._derive(text))
