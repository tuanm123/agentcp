from __future__ import annotations

import json
import os
from typing import Any

import customtkinter as ctk

# ── Premium Color Palette ──────────────────────────────────────────
# Each value is (light_mode, dark_mode).

COLORS: dict[str, tuple[str, str]] = {
    # Backgrounds
    "window":            ("#FAFAFA", "#09090B"),
    "surface":           ("#FFFFFF", "#1A1D28"),
    "surface_raised":    ("#FFFFFF", "#222636"),
    "surface_secondary": ("#F1F3F8", "#2A2E3D"),
    "surface_hover":     ("#E8EBF2", "#323750"),

    # Borders & Dividers
    "border":            ("#E2E5EE", "#3A3F52"),
    "border_focus":      ("#818CF8", "#818CF8"),

    # Typography
    "text":              ("#1E1F2B", "#F1F2F6"),
    "text_secondary":    ("#64668A", "#A0A3BD"),
    "muted":             ("#9194B0", "#6B6F8A"),

    # Accent — Electric Indigo
    "accent":            ("#4F46E5", "#818CF8"),
    "accent_hover":      ("#4F46E5", "#6366F1"),
    "accent_soft":       ("#EEF0FF", "#252848"),
    "accent_glow":       ("#C7D2FE", "#3730A3"),

    # Additional tokens required by tests
    "teal":              ("#0D9488", "#14B8A6"),
    "code_bg":           ("#FFFFFF", "#1E1E1E"),

    # Semantic
    "success":           ("#10B981", "#34D399"),
    "success_soft":      ("#ECFDF5", "#1A3A2A"),
    "warning":           ("#F59E0B", "#FBBF24"),
    "warning_soft":      ("#FFFBEB", "#3D2E0A"),
    "danger":            ("#EF4444", "#F87171"),
    "danger_soft":       ("#FEF2F2", "#3D1A1A"),
}

# ── Radius & Spacing ──────────────────────────────────────────────

CARD_RADIUS = 10
CONTROL_RADIUS = 8
HEADER_RADIUS = 10
APPEARANCE_MODE = "Dark"

SPACING_XS = 4
SPACING_SM = 6
SPACING_MD = 12
SPACING_LG = 20
SPACING_XL = 28

# ── Theme Loader ──────────────────────────────────────────────────

def apply_theme(ctk_module: Any = ctk) -> None:
    """Load *app_theme.json* and set it as the active CTk theme."""
    theme_path = os.path.join(os.path.dirname(__file__), "app_theme.json")
    if os.path.isfile(theme_path):
        ctk_module.set_default_color_theme(theme_path)
