"""agentCP application package."""

from __future__ import annotations

import sys as _sys
from importlib import import_module as _import_module

__version__ = "0.1.0"

_COMPAT_MODULES = {
    "agent": "agentcp.pipeline.agent",
    "ai_reader": "agentcp.devtools.ai_reader",
    "config": "agentcp.settings.config",
    "generator_runtime": "agentcp.pipeline.generator_runtime",
    "localization": "agentcp.i18n.localization",
    "models": "agentcp.domain.models",
    "ui_theme": "agentcp.gui.theme",
    "utils": "agentcp.common.utils",
    "validators": "agentcp.validation.validators",
}

for _name, _target in _COMPAT_MODULES.items():
    _module = _import_module(_target)
    _sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module

__all__ = ["__version__", *_COMPAT_MODULES]
