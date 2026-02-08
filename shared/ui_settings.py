from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, Dict, Any

VisualProfile = Literal["standard", "low_vision"]

DEFAULT_UI = {
    "visual_profile": "standard",
    "font_scale": 1.0,
    "default_font_size": 12,
    "high_contrast": False,
    "theme": "dark",
    "force_large_controls": False,
}

GLOBAL_PATH = Path(__file__).resolve().parent / "Global.json"


@dataclass
class UISettings:
    visual_profile: VisualProfile
    font_scale: float
    default_font_size: int
    high_contrast: bool
    theme: str
    force_large_controls: bool


def _load_config() -> Dict[str, Any]:
    if not GLOBAL_PATH.exists():
        return {}
    with GLOBAL_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_config(data: Dict[str, Any]) -> None:
    with GLOBAL_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_ui_settings() -> UISettings:
    data = _load_config()
    ui = data.get("ui", {})
    changed = False
    for key, default in DEFAULT_UI.items():
        if key not in ui:
            ui[key] = default
            changed = True
    if changed or "ui" not in data:
        data["ui"] = ui
        _save_config(data)
    return UISettings(
        visual_profile=ui["visual_profile"],
        font_scale=float(ui["font_scale"]),
        default_font_size=int(ui["default_font_size"]),
        high_contrast=bool(ui["high_contrast"]),
        theme=str(ui["theme"]),
        force_large_controls=bool(ui["force_large_controls"]),
    )


def save_ui_settings(settings: UISettings) -> None:
    data = _load_config()
    data["ui"] = {
        "visual_profile": settings.visual_profile,
        "font_scale": settings.font_scale,
        "default_font_size": settings.default_font_size,
        "high_contrast": settings.high_contrast,
        "theme": settings.theme,
        "force_large_controls": settings.force_large_controls,
    }
    _save_config(data)


def get_theme_palette(settings: UISettings) -> Dict[str, str]:
    palettes = {
        "crt_green": {
            "bg": "#010801",
            "fg": "#7eff7e",
            "accent": "#66ff99",
            "entry_bg": "#081103",
            "button_bg": "#0b1b0b",
            "focus_outline": "#66ff99",
        },
        "dark": {
            "bg": "#050715",
            "fg": "#f3f5ff",
            "accent": "#66ff99",
            "entry_bg": "#0b0f1f",
            "button_bg": "#1a1f2f",
            "focus_outline": "#66ff99",
        },
        "light": {
            "bg": "#f7f7f7",
            "fg": "#1d1f26",
            "accent": "#1f6feb",
            "entry_bg": "#ffffff",
            "button_bg": "#e1e5f2",
            "focus_outline": "#1f6feb",
        },
    }
    palette = palettes.get(settings.theme, palettes["dark"]).copy()
    if settings.high_contrast:
        palette.update(
            {
                "bg": "#000000",
                "fg": "#ffffff",
                "accent": "#ffff00",
                "entry_bg": "#000000",
                "button_bg": "#ffffff",
                "focus_outline": "#ff00ff",
            }
        )
    return palette
