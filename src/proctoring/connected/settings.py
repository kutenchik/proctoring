from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ConnectedConfig:
    enabled: bool = False
    server_url: str = ""
    allow_loopback_http: bool = False
    timeout_seconds: float = 5.0

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.allow_loopback_http) is not bool:
            raise ValueError('connected flags must be booleans')
        if not isinstance(self.server_url, str):
            raise ValueError('connected.server_url must be text')
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 0.5 <= self.timeout_seconds <= 30):
            raise ValueError('connected.timeout_seconds must be 0.5–30')
