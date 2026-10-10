from __future__ import annotations

from typing import Tuple

from ..domain.models import OJSettings


def validate_problem_name(problem_name: str) -> Tuple[bool, str]:
    if not problem_name or not problem_name.strip():
        return False, "Enter a problem name first."
    return True, ""


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    if not api_key or not api_key.strip():
        return False, "Enter an API key before generating tests."
    return True, ""


def validate_oj_settings(settings: OJSettings) -> Tuple[bool, str]:
    if not settings.url.strip():
        return False, "OJ URL is invalid."
    if not settings.user.strip():
        return False, "OJ username is invalid."
    if not settings.password.strip():
        return False, "OJ password is invalid."
    if settings.time_limit <= 0:
        return False, "Time limit is invalid."
    if settings.memory_mb <= 0:
        return False, "Memory limit is invalid."
    if settings.points < 0:
        return False, "Points are invalid."
    return True, ""
