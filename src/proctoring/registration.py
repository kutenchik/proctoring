"""Candidate identity validated once and kept immutable for a session."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import unicodedata


@dataclass(frozen=True)
class CandidateInfo:
    first_name: str
    last_name: str
    group_id: str = ""
    full_name: str = ""
    student_id: str = ""

    def __post_init__(self):
        if not isinstance(self.full_name, str):
            raise ValueError('candidate.full_name must be a string')
        object.__setattr__(self, 'full_name', self.full_name.strip())
        for name, maximum in (("first_name", 100), ("last_name", 100), ("group_id", 128),
                              ("full_name", 200), ("student_id", 128)):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"candidate.{name} must be a string")
            if any(unicodedata.category(character) == "Cc" for character in value):
                raise ValueError(f"candidate.{name} must not contain control characters")
            value = value.strip()
            if name in ("first_name", "last_name") and not value and not self.full_name:
                raise ValueError(f"candidate.{name} is required")
            if len(value) > maximum:
                raise ValueError(f"candidate.{name} must contain at most {maximum} characters")
            object.__setattr__(self, name, value)

    @classmethod
    def from_dict(cls, value: Mapping, *, require_group: bool = True) -> "CandidateInfo":
        if not isinstance(value, Mapping):
            raise ValueError("Candidate information must be a mapping")
        candidate = cls(first_name=value.get("first_name", ""),
                        last_name=value.get("last_name", ""),
                        group_id=value.get("group_id", ""), full_name=value.get("full_name", ""),
                        student_id=value.get("student_id", ""))
        if require_group and not candidate.group_id:
            raise ValueError("candidate.group_id is required")
        return candidate

    def as_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items()
                if key not in ('full_name', 'student_id') or value}
