"""Exact-host HTTP(S) navigation policy, independent of Qt/WebEngine."""
from collections.abc import Sequence
from ipaddress import ip_address
import re
from urllib.parse import urlsplit, urlunsplit


def _hostname(value: str) -> str:
    """Normalize hostnames without accepting URL syntax or wildcard domains."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Allowed domains must be non-empty hostnames")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("Hostname must not contain whitespace or control characters")
    if "%" in value:
        raise ValueError("Hostname must not contain escaped characters or scoped IP addresses")
    try:
        return ip_address(value).compressed.lower()
    except ValueError:
        pass
    if any(character in value for character in "/\\:@%?#[]*"):
        raise ValueError("Allowed domains must contain hostnames only, without schemes, ports or paths")
    # One terminal dot is the DNS spelling of the same fully qualified hostname.
    value = value.removesuffix(".")
    try:
        ascii_name = value.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("Invalid internationalized hostname") from error
    labels = ascii_name.split(".")
    if (len(ascii_name) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    )):
        raise ValueError("Invalid hostname")
    if re.fullmatch(r"[0-9.]+", ascii_name):
        raise ValueError("Use a complete, canonical IPv4 address")
    return ascii_name


def _http_url(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("external_url must be a non-empty absolute HTTP(S) URL")
    # Browsers normalize these differently from urllib; reject ambiguous input.
    if "\\" in value or any(character.isspace() or ord(character) < 32 or ord(character) == 127
                             for character in value):
        raise ValueError("URL must not contain whitespace, backslashes or control characters")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc or not parts.hostname:
            raise ValueError("external_url must be an absolute HTTP(S) URL")
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise ValueError("Credentials in exam URLs are not supported")
        if parts.netloc.endswith(":"):
            raise ValueError("URL port must not be empty")
        if parts.netloc.startswith("[") and not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", parts.netloc):
            raise ValueError("Invalid bracketed IP address authority")
        host = _hostname(parts.hostname)
        port = parts.port  # Validate malformed/out-of-range ports before WebEngine sees them.
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority += f":{port}"
        return urlunsplit((parts.scheme.lower(), authority, parts.path, parts.query, parts.fragment)), host
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid exam navigation URL: {error}") from error


def normalize_domains(values: Sequence[str]) -> tuple[str, ...]:
    """Validate and deduplicate explicit hostname entries."""
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError("allowed_domains must be a list of hostnames")
    return tuple(dict.fromkeys(_hostname(value) for value in values))


class NavigationPolicy:
    """Allow navigation to explicit hosts, not arbitrary subdomains or resources.

    This governs document navigation. It does not filter page subresources such
    as an LMS's CDN scripts or images, and it is not a network firewall.
    """

    def __init__(self, url: str, allowed_domains: Sequence[str] = ()) -> None:
        self.external_url, origin_host = _http_url(url)
        hosts = normalize_domains(allowed_domains)
        self.allowed_domains = hosts or (origin_host,)
        if origin_host not in self.allowed_domains:
            raise ValueError("allowed_domains must include the external_url hostname")

    def allows(self, url: str) -> bool:
        try:
            _, host = _http_url(url)
        except (TypeError, ValueError):
            return False
        return host in self.allowed_domains
