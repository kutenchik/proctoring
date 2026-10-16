from dataclasses import dataclass


@dataclass(frozen=True)
class AdvancedConfig:
    remote_enabled: bool = False
    remote_interval_seconds: float = 5.
    remote_confirmations: int = 3
    liveness_enabled: bool = False
    liveness_interval_seconds: float = 10.
    liveness_confirmations: int = 3
    identity_enabled: bool = False
    identity_model: str = 'Facenet512'
    identity_interval_seconds: float = 30.
    identity_confirmations: int = 3
    facenet_cosine_threshold: float = .3

    @property
    def enabled(self):
        return self.remote_enabled or self.liveness_enabled or self.identity_enabled


def consent_version(exam):
    values=(exam.get('monitoring_policy') or {}).get('values',{})
    if values.get('audio_evidence.enabled') is True:return 5
    return 4 if any(values.get('advanced.'+key) is True for key in
                    ('remote_enabled','liveness_enabled','identity_enabled')) else 3
