#!/usr/bin/env python3
"""
Mini preferences viewer for config_editor_prefs.json.
Shows the adjustable options (theme mode, font size, custom theme palette)
and embeds the Theme Color Picker UI for editing custom colors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple
import json
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
PREFS_PATH = BASE_DIR / "config_editor_prefs.json"


def load_prefs() -> Dict:
    if PREFS_PATH.exists():
        with open(PREFS_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"theme": "high_contrast_dark", "font_size": "medium", "custom_theme": {}}


def save_prefs(data: Dict) -> None:
    with open(PREFS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


class ThemeColorPicker(tk.Toplevel):
    """Modal dialog reused from config_editor.py for editing palette colors."""

    def __init__(self, host: "PrefsDemoApp"):
        super().__init__(host.root)
        self.host = host
        self.title("Theme Color Picker")
        self.geometry("640x540")
        self.minsize(640, 540)
        self.resizable(False, False)
        self.transient(host.root)
        self.grab_set()

        active_theme = host.get_active_theme()
        self.configure(background=active_theme.get("bg"))

        metadata = host.get_custom_metadata()
        self.mode_var = tk.StringVar(value=metadata.get("mode", "dark"))
        self.high_contrast_var = tk.BooleanVar(value=metadata.get("high_contrast", False))
        initial_palette = host.get_current_palette(preferred_mode=self.mode_var.get())
        self.color_fields = [
            ("Primary background", "primary_bg"),
            ("Secondary background", "secondary_bg"),
            ("Text color", "text_color"),
            ("Accent / highlight", "accent_color"),
        ]
        self.color_vars = {
            key: tk.StringVar(value=initial_palette.get(key, "#ffffff")) for _, key in self.color_fields
        }

        container = ttk.Frame(self, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=0)

        colors_group = ttk.LabelFrame(container, text="Color Selection")
        colors_group.grid(row=0, column=0, sticky="ew")
        for idx, (label, key) in enumerate(self.color_fields):
            row = ttk.Frame(colors_group)
            row.grid(row=idx, column=0, sticky="ew", pady=4)
            row.columnconfigure(1, weight=1)
            ttk.Label(row, text=label).grid(row=0, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(row, textvariable=self.color_vars[key], width=14, state="readonly").grid(
                row=0, column=1, sticky="w"
            )
            ttk.Button(row, text="Pick Color", command=lambda k=key: self._choose_color(k)).grid(
                row=0, column=2, padx=(8, 0)
            )

        accessibility_group = ttk.LabelFrame(container, text="Accessibility")
        accessibility_group.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        mode_row = ttk.Frame(accessibility_group)
        mode_row.grid(row=0, column=0, sticky="w", pady=(4, 4))
        ttk.Radiobutton(
            mode_row,
            text="Dark Mode",
            value="dark",
            variable=self.mode_var,
            command=self._on_mode_change,
        ).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(
            mode_row,
            text="Light Mode",
            value="light",
            variable=self.mode_var,
            command=self._on_mode_change,
        ).pack(side="left")
        ttk.Checkbutton(
            accessibility_group,
            text="High contrast text",
            variable=self.high_contrast_var,
            command=self.update_preview,
        ).grid(row=1, column=0, sticky="w", pady=(0, 4))

        preview_group = ttk.LabelFrame(container, text="Live Preview")
        preview_group.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        preview_group.columnconfigure(0, weight=1)
        self.preview_card = tk.Frame(preview_group, bd=1, relief="solid", padx=16, pady=16)
        self.preview_card.grid(row=0, column=0, sticky="ew", pady=(6, 12))
        self.preview_header = tk.Label(self.preview_card, text="Preview title")
        self.preview_header.pack(anchor="w")
        self._preview_default_text = "Sample body copy for readability checks."
        self.preview_body = tk.Label(
            self.preview_card,
            text=self._preview_default_text,
            wraplength=360,
            justify="left",
        )
        self.preview_body.pack(anchor="w", pady=(8, 12))
        self.preview_button = tk.Button(self.preview_card, text="Accent Button")
        self.preview_button.pack(anchor="center")

        actions_panel = ttk.LabelFrame(container, text="Actions")
        actions_panel.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(12, 0))
        ttk.Button(actions_panel, text="Apply", command=self._on_apply).pack(fill="x", pady=(4, 2), padx=8)
        ttk.Button(actions_panel, text="Reset to Default", command=self._on_reset).pack(fill="x", pady=2, padx=8)
        ttk.Button(actions_panel, text="Cancel", command=self._on_cancel).pack(fill="x", pady=(2, 4), padx=8)

        self.update_preview()

    def _choose_color(self, key: str):
        initial = self.color_vars[key].get() or "#ffffff"
        _, color = colorchooser.askcolor(color=initial, parent=self)
        if color:
            self.color_vars[key].set(color)
            self.update_preview()

    def _collect_palette(self):
        return {key: var.get() for key, var in self.color_vars.items()}

    def update_preview(self):
        palette = self._collect_palette()
        metadata = {"mode": self.mode_var.get(), "high_contrast": self.high_contrast_var.get()}
        theme = self.host.derive_theme_from_palette(palette, metadata)
        self.preview_card.configure(background=theme["bg"])
        self.preview_header.configure(background=theme["bg"], foreground=theme["fg"])
        self.preview_body.configure(background=theme["bg"], foreground=theme["fg"])
        self.preview_button.configure(
            background=theme.get("selection_bg", theme["bg"]),
            foreground=theme["fg"],
            activebackground=theme.get("status_info", theme["fg"]),
            activeforeground=theme["fg"],
        )
        if self.host.contrast_ratio(theme["bg"], theme["fg"]) < 4.5:
            self.preview_body.configure(text="Warning: Low contrast - readability may suffer")
        else:
            self.preview_body.configure(text=self._preview_default_text)

    def _on_apply(self):
        palette = self._collect_palette()
        metadata = {"mode": self.mode_var.get(), "high_contrast": self.high_contrast_var.get()}
        self.host.apply_custom_colors(palette, metadata)
        self.destroy()

    def _on_cancel(self):
        self.destroy()

    def _on_reset(self):
        defaults = self.host.get_palette_defaults(self.mode_var.get())
        for key, value in defaults.items():
            self.color_vars[key].set(value)
        self.high_contrast_var.set(False)
        self.update_preview()

    def _on_mode_change(self):
        defaults = self.host.get_palette_defaults(self.mode_var.get())
        for key, value in defaults.items():
            self.color_vars[key].set(value)
        self.update_preview()


class PrefsDemoApp:
    """Lightweight GUI that showcases everything stored in config_editor_prefs."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Config Editor Prefs Demo")
        self.prefs = load_prefs()
        self.theme_var = tk.StringVar(value=self.prefs.get("theme", "high_contrast_dark"))
        self.font_var = tk.StringVar(value=self.prefs.get("font_size", "medium"))
        self.custom_info_var = tk.StringVar()
        self.preview_frame = None
        self.preview_text = None
        self._picker = None
        self._build_ui()
        self.refresh_custom_details()
        self.update_preview()

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        theme_group = ttk.LabelFrame(container, text="Theme Mode")
        theme_group.grid(row=0, column=0, sticky="ew")
        for idx, (label, value) in enumerate(
            [("High Contrast Dark", "high_contrast_dark"), ("Standard Light", "light"), ("Custom", "custom")]
        ):
            ttk.Radiobutton(
                theme_group,
                text=label,
                value=value,
                variable=self.theme_var,
                command=self.on_theme_change,
            ).grid(row=0, column=idx, padx=4, pady=4, sticky="w")

        font_group = ttk.LabelFrame(container, text="Font Size")
        font_group.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Combobox(
            font_group,
            values=["small", "medium", "large"],
            state="readonly",
            textvariable=self.font_var,
        ).grid(row=0, column=0, padx=4, pady=4)

        custom_group = ttk.LabelFrame(container, text="Custom Theme Details")
        custom_group.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(custom_group, textvariable=self.custom_info_var, justify="left").grid(row=0, column=0, sticky="w")

        preview_group = ttk.LabelFrame(container, text="Preview")
        preview_group.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.preview_frame = tk.Frame(preview_group, bd=1, relief="solid", padx=16, pady=16)
        self.preview_frame.pack(fill="x", padx=6, pady=6)
        tk.Label(self.preview_frame, text="Preview title").pack(anchor="w")
        self.preview_text = tk.Label(
            self.preview_frame,
            text="Example copy showing the active theme + font settings.",
            wraplength=360,
            justify="left",
        )
        self.preview_text.pack(anchor="w", pady=(8, 12))

        btn_row = ttk.Frame(container)
        btn_row.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(btn_row, text="Theme Color Picker", command=self.open_picker).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btn_row, text="Save Prefs", command=self.save).grid(row=0, column=1, padx=4)
        ttk.Button(btn_row, text="Reload", command=self.reload).grid(row=0, column=2, padx=4)

    def on_theme_change(self):
        self.prefs["theme"] = self.theme_var.get()
        self.update_preview()

    def refresh_custom_details(self):
        custom = self.prefs.get("custom_theme", {})
        colors = custom.get("colors") or {}
        lines = ["No custom palette saved."]
        if colors:
            lines = [f"{label.replace('_', ' ').title()}: {value}" for label, value in colors.items()]
        meta = custom.get("metadata") or {}
        if meta:
            lines.append(f"Mode: {meta.get('mode', 'dark')}  High contrast: {meta.get('high_contrast', False)}")
        self.custom_info_var.set("\n".join(lines))

    def open_picker(self):
        if self._picker and self._picker.winfo_exists():
            self._picker.lift()
            return
        self._picker = ThemeColorPicker(self)
        self._picker.bind("<Destroy>", lambda e: setattr(self, "_picker", None))

    def save(self):
        self.prefs["theme"] = self.theme_var.get()
        self.prefs["font_size"] = self.font_var.get()
        save_prefs(self.prefs)
        messagebox.showinfo("Saved", f"Preferences saved to\n{PREFS_PATH}")

    def reload(self):
        self.prefs = load_prefs()
        self.theme_var.set(self.prefs.get("theme", "high_contrast_dark"))
        self.font_var.set(self.prefs.get("font_size", "medium"))
        self.refresh_custom_details()
        self.update_preview()

    # ---- palette helpers borrowed from config_editor -----------------
    def get_palette_defaults(self, mode: str):
        mode_key = "light" if mode == "light" else "dark"
        if mode_key == "light":
            return {
                "primary_bg": "#ffffff",
                "secondary_bg": "#f3f4f6",
                "text_color": "#111827",
                "accent_color": "#1d4ed8",
            }
        return {
            "primary_bg": "#020617",
            "secondary_bg": "#111827",
            "text_color": "#f9fafb",
            "accent_color": "#38bdf8",
        }

    def get_custom_metadata(self):
        custom = self.prefs.get("custom_theme", {})
        metadata = custom.get("metadata", {})
        if not metadata:
            metadata = {
                "mode": "dark" if self.theme_var.get() == "high_contrast_dark" else "light",
                "high_contrast": False,
            }
        return metadata

    def get_current_palette(self, preferred_mode: Optional[str] = None):
        custom = self.prefs.get("custom_theme", {})
        colors = custom.get("colors")
        metadata = custom.get("metadata", {})
        if colors and (preferred_mode is None or metadata.get("mode") == preferred_mode):
            defaults = self.get_palette_defaults(metadata.get("mode", "dark"))
            return {**defaults, **colors}
        fallback = preferred_mode or ("dark" if self.theme_var.get() == "high_contrast_dark" else "light")
        return self.get_palette_defaults(fallback)

    def apply_custom_colors(self, palette: Dict, metadata: Dict):
        # Persist selected palette for next load.
        self.prefs["custom_theme"] = {"colors": palette, "metadata": metadata}
        self.theme_var.set("custom")
        self.prefs["theme"] = "custom"
        save_prefs(self.prefs)
        self.refresh_custom_details()
        self.update_preview()

    def derive_theme_from_palette(self, palette: Dict, metadata: Dict):
        mode = metadata.get("mode", "dark")
        high_contrast = metadata.get("high_contrast", False)
        primary = palette.get("primary_bg", "#020617")
        secondary = palette.get("secondary_bg", primary)
        text_color = palette.get("text_color", "#f9fafb")
        accent = palette.get("accent_color", "#38bdf8")
        if high_contrast:
            text_color = "#f8fafc" if mode == "dark" else "#0f172a"
            accent = "#f97316" if mode == "dark" else "#2563eb"
        tree_bg = secondary if mode == "light" else self.blend_colors(primary, secondary, 0.35)
        return {
            "bg": primary,
            "fg": text_color,
            "entry_bg": secondary,
            "entry_fg": text_color,
            "tree_bg": tree_bg,
            "tree_fg": text_color,
            "status_info": accent,
            "selection_bg": self.blend_colors(accent, primary, 0.5),
        }

    def blend_colors(self, base: str, target: str, factor: float) -> str:
        base_rgb = self.hex_to_rgb(base)
        target_rgb = self.hex_to_rgb(target)
        blended = tuple(
            max(0, min(255, int(base_c + (target_c - base_c) * factor))) for base_c, target_c in zip(base_rgb, target_rgb)
        )
        return self.rgb_to_hex(blended)

    @staticmethod
    def hex_to_rgb(color: str) -> Tuple[int, int, int]:
        value = color.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def contrast_ratio(self, color_a: str, color_b: str) -> float:
        def rel_luminance(rgb: Tuple[int, int, int]) -> float:
            def adjust(channel: int) -> float:
                c = channel / 255.0
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            r, g, b = rgb
            return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

        lum1 = rel_luminance(self.hex_to_rgb(color_a))
        lum2 = rel_luminance(self.hex_to_rgb(color_b))
        lighter = max(lum1, lum2)
        darker = min(lum1, lum2)
        return (lighter + 0.05) / (darker + 0.05)

    def get_active_theme(self):
        mode = self.theme_var.get()
        if mode == "custom":
            palette = self.get_current_palette()
            metadata = self.prefs.get("custom_theme", {}).get("metadata", {}) or self.get_custom_metadata()
            return self.derive_theme_from_palette(palette, metadata)
        if mode == "light":
            palette = self.get_palette_defaults("light")
            return self.derive_theme_from_palette(palette, {"mode": "light", "high_contrast": False})
        palette = self.get_palette_defaults("dark")
        return self.derive_theme_from_palette(palette, {"mode": "dark", "high_contrast": True})

    def update_preview(self):
        theme = self.get_active_theme()
        self.preview_frame.configure(background=theme["bg"])
        self.preview_text.configure(background=theme["bg"], foreground=theme["fg"])


def main():
    root = tk.Tk()
    PrefsDemoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
