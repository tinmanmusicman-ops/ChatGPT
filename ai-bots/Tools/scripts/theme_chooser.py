from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(BASE_DIR))
from shared.ui_settings import UISettings, load_ui_settings, save_ui_settings, get_theme_palette


def build_control(root: tk.Widget, label: str, widget: tk.Widget) -> ttk.Frame:
    row = ttk.Frame(root)
    ttk.Label(row, text=label).pack(side="left", padx=(0, 6))
    widget.pack(side="left", fill="x", expand=True)
    return row


def update_preview(root: tk.Tk, settings: UISettings) -> None:
    palette = get_theme_palette(settings)
    root.configure(bg=palette["bg"])
    for child in root.winfo_children():
        try:
            child.configure(bg=palette["bg"])
        except tk.TclError:
            pass


def launch_ui_settings() -> None:
    settings = load_ui_settings()
    root = tk.Tk()
    root.title("UI Settings")
    palette = get_theme_palette(settings)
    root.configure(bg=palette["bg"])
    font_size = int(settings.default_font_size * settings.font_scale)

    visual_var = tk.StringVar(value=settings.visual_profile)
    font_scale_var = tk.DoubleVar(value=settings.font_scale)
    font_size_var = tk.IntVar(value=settings.default_font_size)
    theme_var = tk.StringVar(value=settings.theme)
    high_contrast_var = tk.BooleanVar(value=settings.high_contrast)
    large_controls_var = tk.BooleanVar(value=settings.force_large_controls)

    container = ttk.Frame(root, padding=16)
    container.pack(fill="both", expand=True)

    build_control(
        container,
        "Visual Profile",
        ttk.Combobox(container, values=["standard", "low_vision"], textvariable=visual_var, state="readonly"),
    ).pack(fill="x", pady=6)
    build_control(
        container,
        "Font Scale",
        ttk.Spinbox(container, from_=1.0, to=2.5, increment=0.1, textvariable=font_scale_var),
    ).pack(fill="x", pady=6)
    build_control(
        container,
        "Base Font Size",
        ttk.Spinbox(container, from_=10, to=20, textvariable=font_size_var),
    ).pack(fill="x", pady=6)
    build_control(
        container,
        "Theme",
        ttk.Combobox(container, values=["dark", "light", "crt_green"], textvariable=theme_var, state="readonly"),
    ).pack(fill="x", pady=6)
    ttk.Checkbutton(container, text="High Contrast", variable=high_contrast_var).pack(anchor="w", pady=6)
    ttk.Checkbutton(container, text="Force Large Controls", variable=large_controls_var).pack(anchor="w", pady=6)

    def on_save() -> None:
        new_settings = UISettings(
            visual_profile=visual_var.get(),  # type: ignore[arg-type]
            font_scale=float(font_scale_var.get()),
            default_font_size=int(font_size_var.get()),
            high_contrast=high_contrast_var.get(),
            theme=theme_var.get(),
            force_large_controls=large_controls_var.get(),
        )
        save_ui_settings(new_settings)
        messagebox.showinfo("Saved", "UI settings saved.")
        update_preview(root, new_settings)

    ttk.Button(container, text="Save", command=on_save).pack(fill="x", pady=(12, 0))
    root.mainloop()


if __name__ == "__main__":
    launch_ui_settings()
