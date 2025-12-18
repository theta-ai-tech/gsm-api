import sys
import types
import importlib.metadata as importlib_metadata
from pathlib import Path

# Ensure repo root is importable so "tools" package resolves in tests/tools.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub email_validator so EmailStr models can be constructed without installing the package.
if "email_validator" not in sys.modules:
    mod = types.ModuleType("email_validator")

    class EmailNotValidError(ValueError): ...

    def validate_email(email: str, *_args, **_kwargs):
        local_part = email.split("@", 1)[0]
        return types.SimpleNamespace(
            email=email, normalized=email, local_part=local_part
        )

    mod.EmailNotValidError = EmailNotValidError
    mod.validate_email = validate_email
    sys.modules["email_validator"] = mod

# Stub importlib.metadata.version lookup for email-validator.
_real_version = importlib_metadata.version


def _safe_version(dist_name: str):
    if dist_name == "email-validator":
        return "2.0.0"
    return _real_version(dist_name)


importlib_metadata.version = _safe_version  # type: ignore[assignment]
