#!/usr/bin/env python3
"""
Simple GUI editor for config JSON files. It loads the JSON, shows top-level keys,
and lets you add/update/delete entries. Values are type-inferred (bool/int/float/JSON object/array)
when possible; otherwise they are saved as strings.
"""

from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

import json
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
import webbrowser

APP_TITLE = "Config JSON Editor"
EI_GUIDE_URL = "https://cdn.botpress.cloud/webchat/v3.4/shareable.html?configUrl=https://files.bpcontent.cloud/2025/11/23/04/20251123044527-N8XXQ6V7.json"


def infer_value(text: str):
    """Try to turn the typed text into a proper Python/JSON value."""
    s = text.strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if s.lower() == "null":
        return None
    try:
        if s.startswith("{") or s.startswith("[") or (
            (s.startswith('"') and s.endswith('"'))
            or (s.startswith("'") and s.endswith("'"))
        ):
            return json.loads(s)
    except Exception:
        pass
    try:
        return int(s)
    except Exception:
        pass
    try:
        return float(s)
    except Exception:
        pass
    return text


def coerce_value(text: str, mode: str):
    """Coerce value based on selected mode."""
    if mode == "bool":
        lowered = text.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        return False if not lowered else True  # fallback guess
    return infer_value(text)


class ToolTip:
    """Simple tooltip helper for Tk widgets (theme-aware)."""

    def __init__(self, widget, text: str, theme_fn, font_fn):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.theme_fn = theme_fn
        self.font_fn = font_fn
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tipwindow or not self.text:
            return
        theme = self.theme_fn()
        font_val = self.font_fn()
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify=tk.LEFT,
            background=theme.get("tooltip_bg"),
            relief=tk.SOLID,
            borderwidth=1,
            fg=theme.get("tooltip_fg"),
            font=font_val,
            padx=6,
            pady=4,
        )
        label.pack(ipadx=1)

    def hide(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class ThemeColorPicker(tk.Toplevel):
    """Modal dialog that lets users customize UI colors with preview."""

    def __init__(self, editor: "ConfigEditor", base_theme: str):
        super().__init__(editor.root)
        self.editor = editor
        self.base_theme = base_theme
        self.title("Theme Color Picker")
        self.geometry("680x560")
        self.minsize(680, 560)
        self.resizable(False, False)
        self.transient(editor.root)
        self.grab_set()

        active_theme = editor._get_theme()
        self.configure(background=active_theme.get("bg"))

        initial_palette, metadata = editor.get_palette_for_theme(base_theme)
        self.mode_var = tk.StringVar(value=metadata.get("mode", "dark"))
        self.high_contrast_var = tk.BooleanVar(value=metadata.get("high_contrast", False))
        self.color_fields = [
            ("Primary background", "primary_bg"),
            ("Secondary background", "secondary_bg"),
            ("Entry background", "entry_bg"),
            ("Entry text", "entry_fg"),
            ("List background", "list_bg"),
            ("List text", "list_fg"),
            ("List highlight", "list_highlight"),
            ("Tree background", "tree_bg"),
            ("Tree text", "tree_fg"),
            ("Primary text", "text_color"),
            ("Accent / highlight", "accent_color"),
            ("Selection color", "selection_bg"),
            ("Status info", "status_info"),
            ("Status success", "status_success"),
            ("Status error", "status_error"),
            ("Dirty warning", "dirty_color"),
            ("Tooltip background", "tooltip_bg"),
            ("Tooltip text", "tooltip_fg"),
        ]
        self.color_vars = {
            key: tk.StringVar(value=initial_palette.get(key, "#ffffff")) for _, key in self.color_fields
        }
        self.color_buttons = {}

        container = ttk.Frame(self, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=0)

        main_panel = ttk.Frame(container)
        main_panel.grid(row=0, column=0, sticky="nsew")
        main_panel.rowconfigure(0, weight=1)
        main_panel.columnconfigure(0, weight=1)

        self._scroll_canvas = tk.Canvas(main_panel, highlightthickness=0, borderwidth=0)
        scroll_y = ttk.Scrollbar(main_panel, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=scroll_y.set)
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")

        scroll_frame = ttk.Frame(self._scroll_canvas)
        self._scroll_canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        scroll_frame.bind(
            "<Configure>",
            lambda e: self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all")),
        )
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        scroll_frame.columnconfigure(0, weight=1)
        colors_group = ttk.LabelFrame(scroll_frame, text="Color Selection")
        colors_group.grid(row=0, column=0, sticky="ew")
        for idx, (label, key) in enumerate(self.color_fields):
            row = ttk.Frame(colors_group)
            row.grid(row=idx, column=0, sticky="ew", pady=4)
            row.columnconfigure(1, weight=1)
            ttk.Label(row, text=label).grid(row=0, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(row, textvariable=self.color_vars[key], width=14, state="readonly").grid(
                row=0, column=1, sticky="w"
            )
            btn = tk.Button(row, text="Pick Color", command=lambda k=key: self._choose_color(k), width=12)
            btn.grid(row=0, column=2, padx=(8, 0))
            self.color_buttons[key] = btn

        accessibility_group = ttk.LabelFrame(scroll_frame, text="Accessibility")
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

        preview_group = ttk.LabelFrame(self, text="Live Preview")
        preview_group.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 10))
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
        self.preview_status = tk.Label(self.preview_card, text="Status: sample error message")
        self.preview_status.pack(anchor="w", pady=(12, 4))
        self.preview_status_success = tk.Label(self.preview_card, text="Status: sample success message")
        self.preview_status_success.pack(anchor="w", pady=(0, 4))
        self.preview_status_info = tk.Label(self.preview_card, text="Status: informational")
        self.preview_status_info.pack(anchor="w", pady=(0, 4))
        self.preview_dirty = tk.Label(self.preview_card, text="Unsaved changes")
        self.preview_dirty.pack(anchor="w", pady=(12, 4))
        self.preview_dirty_warning = tk.Label(
            self.preview_card,
            text="Dirty warning sample",
            relief="groove",
            padx=6,
            pady=2,
        )
        self.preview_dirty_warning.pack(anchor="w", pady=(0, 8))
        self.preview_tooltip = tk.Label(
            self.preview_card,
            text="Tooltip sample",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=2,
        )
        self.preview_tooltip.pack(anchor="w", pady=(4, 8))
        self.preview_secondary = tk.Frame(self.preview_card, bd=1, relief="ridge", padx=10, pady=6)
        self.preview_secondary.pack(fill="x", pady=(8, 8))
        self.preview_secondary_label = tk.Label(self.preview_secondary, text="Secondary area")
        self.preview_secondary_label.pack(anchor="w", pady=(0, 4))
        self.preview_entry = tk.Entry(self.preview_secondary)
        self.preview_entry.insert(0, "Entry sample")
        self.preview_entry.pack(fill="x")
        self.preview_tree = tk.Frame(self.preview_card, bd=1, relief="groove", padx=8, pady=6)
        self.preview_tree.pack(fill="x", pady=(8, 8))
        self.preview_tree_header = tk.Label(self.preview_tree, text="Tree Header")
        self.preview_tree_header.pack(fill="x", pady=(0, 4))
        self.preview_tree_row = tk.Label(self.preview_tree, text="Tree Row Sample")
        self.preview_tree_row.pack(fill="x")
        self.preview_list_block = tk.Frame(self.preview_card, bd=1, relief="ridge", padx=10, pady=6)
        self.preview_list_block.pack(fill="x", pady=(8, 8))
        self.preview_list_bg_label = tk.Label(self.preview_list_block, text="List background sample")
        self.preview_list_bg_label.pack(fill="x", pady=(0, 4))
        self.preview_list_selected_label = tk.Label(self.preview_list_block, text="List selected sample")
        self.preview_list_selected_label.pack(fill="x")
        self.preview_list = tk.Listbox(self.preview_card, height=3)
        for item in ("List item one", "List item two", "List item three"):
            self.preview_list.insert("end", item)
        self.preview_list.pack(fill="x", pady=(12, 0))

        actions_panel = ttk.LabelFrame(container, text="Actions")
        actions_panel.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        ttk.Button(actions_panel, text="Apply", command=self._on_apply).pack(fill="x", pady=(4, 2), padx=8)
        ttk.Button(actions_panel, text="Reset to Default", command=self._on_reset).pack(fill="x", pady=2, padx=8)
        ttk.Button(actions_panel, text="Cancel", command=self._on_cancel).pack(fill="x", pady=(2, 4), padx=8)

        self.update_preview()
        self._refresh_color_buttons()

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
        theme = self.editor._derive_theme_from_palette(palette, metadata)
        self.preview_card.configure(background=theme["bg"])
        self.preview_header.configure(background=theme["bg"], foreground=theme["fg"])
        self.preview_body.configure(background=theme["bg"], foreground=theme["fg"])
        accent = theme.get("accent_color", theme.get("selection_bg", theme["bg"]))
        self.preview_button.configure(
            background=accent,
            foreground=theme["fg"],
            activebackground=theme.get("selection_bg", accent),
            activeforeground=theme["fg"],
        )
        dirty_fg = theme.get("dirty_fg", theme.get("status_error", theme["fg"]))
        self.preview_dirty.configure(background=theme["bg"], foreground=dirty_fg)
        self.preview_dirty_warning.configure(background=theme["bg"], foreground=dirty_fg)
        status_fg = theme.get("status_error", theme["fg"])
        self.preview_status.configure(background=theme["bg"], foreground=status_fg)
        success_fg = theme.get("status_success", theme["fg"])
        self.preview_status_success.configure(background=theme["bg"], foreground=success_fg)
        info_fg = theme.get("status_info", theme["fg"])
        self.preview_status_info.configure(background=theme["bg"], foreground=info_fg)
        list_bg = theme.get("list_bg", theme.get("tree_bg", theme["bg"]))
        list_fg = theme.get("list_fg", theme["fg"])
        list_sel_bg = theme.get("list_highlight", theme.get("selection_bg", list_bg))
        self.preview_list.configure(
            background=list_bg,
            foreground=list_fg,
            selectbackground=list_sel_bg,
            selectforeground=list_fg,
            highlightbackground=list_bg,
        )
        self.preview_list_block.configure(background=list_bg)
        self.preview_list_bg_label.configure(background=list_bg, foreground=list_fg)
        self.preview_list_selected_label.configure(background=list_sel_bg, foreground=list_fg)
        self.preview_tooltip.configure(
            background=theme.get("tooltip_bg", theme["bg"]),
            foreground=theme.get("tooltip_fg", theme["fg"]),
        )
        secondary_bg = theme.get("entry_bg", theme.get("bg"))
        secondary_fg = theme.get("entry_fg", theme["fg"])
        self.preview_secondary.configure(background=secondary_bg)
        self.preview_secondary_label.configure(background=secondary_bg, foreground=secondary_fg)
        self.preview_entry.configure(
            background=secondary_bg,
            foreground=secondary_fg,
            insertbackground=secondary_fg,
            disabledbackground=secondary_bg,
            disabledforeground=secondary_fg,
            highlightbackground=secondary_bg,
        )
        tree_bg = theme.get("tree_bg", theme.get("bg"))
        tree_fg = theme.get("tree_fg", theme["fg"])
        self.preview_tree.configure(background=tree_bg)
        self.preview_tree_header.configure(background=tree_bg, foreground=tree_fg)
        self.preview_tree_row.configure(
            background=theme.get("list_highlight", tree_bg),
            foreground=tree_fg,
        )
        if self.editor._contrast_ratio(theme["bg"], theme["fg"]) < 4.5:
            self.preview_body.configure(text="Warning: Low contrast - readability may suffer")
        else:
            self.preview_body.configure(text=self._preview_default_text)
        self._refresh_color_buttons()

    def _on_apply(self):
        palette = self._collect_palette()
        metadata = {"mode": self.mode_var.get(), "high_contrast": self.high_contrast_var.get()}
        self.editor.apply_custom_colors(palette, metadata, base_theme=self.base_theme)
        self.destroy()

    def _on_cancel(self):
        self.destroy()

    def _on_reset(self):
        defaults = self.editor.get_palette_defaults(self.mode_var.get())
        for key, value in defaults.items():
            self.color_vars[key].set(value)
        self.high_contrast_var.set(False)
        self.update_preview()

    def _on_mode_change(self):
        defaults = self.editor.get_palette_defaults(self.mode_var.get())
        for key, value in defaults.items():
            self.color_vars[key].set(value)
        self.update_preview()

    def _on_mousewheel(self, event):
        if not hasattr(self, "_scroll_canvas"):
            return
        delta = int(-1 * (event.delta / 120))
        self._scroll_canvas.yview_scroll(delta, "units")

    def _refresh_color_buttons(self):
        for key, btn in self.color_buttons.items():
            color = self.color_vars[key].get() or "#ffffff"
            fg = self._label_color_for_bg(color)
            btn.configure(background=color, activebackground=color, foreground=fg, activeforeground=fg)

    def _label_color_for_bg(self, color: str) -> str:
        try:
            contrast_white = self.editor._contrast_ratio(color, "#ffffff")
            contrast_black = self.editor._contrast_ratio(color, "#000000")
        except Exception:
            return "#000000"
        return "#ffffff" if contrast_white >= contrast_black else "#000000"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


class ConfigEditor:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        ttk.Style().theme_use("clam")
        self.data = {}
        self.history = {}
        self.base_dir = base_dir
        self.history_path = self.base_dir / "config_editor_history.json"
        self.prefs_path = self.base_dir / "config_editor_prefs.json"
        self.prefs = {
            "theme": "green_screen",
            "font_size": "medium",
            "custom_themes": {},
            "ei_guide_url": EI_GUIDE_URL,
        }
        self.font_sizes = {
            "small": {"base": 9, "rowheight": 20},
            "medium": {"base": 11, "rowheight": 24},
            "large": {"base": 14, "rowheight": 30},
        }
        # Pre-populated choices for known keys (editable combobox).
        self.known_choices = {
            "openai_temperature": ["0.0", "0.2", "0.5", "0.7", "1.0"],
            "openai_model": [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4.1",
                "gpt-4.1-mini",
            ],
        }
        # Help text for tooltips.
        self.help_text = {
            "openai_temperature": (
                "Temperature controls randomness:\n"
                "0.0 = deterministic\n"
                "0.2 = low variation\n"
                "0.5 = balanced\n"
                "0.7 = creative\n"
                "1.0 = very creative/unpredictable"
            )
        }
        self.themes = {
            "high_contrast_dark": {
                "bg": "#020617",
                "fg": "#f9fafb",
                "entry_bg": "#020617",
                "entry_fg": "#f9fafb",
                "tree_bg": "#2b2b2b",
                "tree_fg": "#f9fafb",
                "list_bg": "#313131",
                "list_fg": "#f9fafb",
                "list_highlight": "#3b82f6",
                "status_info": "#38bdf8",
                "status_success": "#22c55e",
                "status_error": "#f43f5e",
                "tooltip_bg": "#0b1224",
                "tooltip_fg": "#f9fafb",
                "selection_bg": "#2b0f3f",
                "dirty_fg": "#f87171",
            },
            "light": {
                "bg": "#ffffff",
                "fg": "#111827",
                "entry_bg": "#ffffff",
                "entry_fg": "#111827",
                "tree_bg": "#ffffff",
                "tree_fg": "#111827",
                "list_bg": "#f4f4f4",
                "list_fg": "#111827",
                "list_highlight": "#dbeafe",
                "status_info": "#1d4ed8",
                "status_success": "#15803d",
                "status_error": "#b91c1c",
                "tooltip_bg": "#f1f5f9",
                "tooltip_fg": "#111827",
                "selection_bg": "#93c5fd",
                "dirty_fg": "#b91c1c",
            },
            "stinky": {
                "bg": "#05140a",
                "fg": "#e7ffef",
                "entry_bg": "#0c2414",
                "entry_fg": "#dcffe7",
                "tree_bg": "#0a1b11",
                "tree_fg": "#d8ffe0",
                "list_bg": "#0f2b1a",
                "list_fg": "#e7ffef",
                "list_highlight": "#1fa87c",
                "status_info": "#20c997",
                "status_success": "#2dd4bf",
                "status_error": "#f87171",
                "tooltip_bg": "#0f2a18",
                "tooltip_fg": "#d5ffe2",
                "selection_bg": "#1f8f68",
                "dirty_fg": "#f87171",
            },
            "green_screen": {
                "bg": "#001b00",
                "fg": "#00ff66",
                "entry_bg": "#002200",
                "entry_fg": "#66ff99",
                "tree_bg": "#001b00",
                "tree_fg": "#00ff66",
                "list_bg": "#001b00",
                "list_fg": "#00ff66",
                "list_highlight": "#004d00",
                "status_info": "#00ff66",
                "status_success": "#33ff99",
                "status_error": "#ff3333",
                "tooltip_bg": "#002200",
                "tooltip_fg": "#66ff99",
                "selection_bg": "#003300",
                "dirty_fg": "#99ffcc",
            },
        }
        self.current_theme = "green_screen"
        self.path_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.val_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.type_var = tk.StringVar(value="auto")
        self.theme_var = tk.StringVar(value=self.current_theme)
        self.font_size_var = tk.StringVar(value="medium")
        self.value_widget = None
        self.tooltip = None
        self.selection_popup = None
        self._color_picker = None
        self.view_menu = None
        self.user_theme_data = {}
        self.dirty = False
        self._build_ui()
        default_path = self.base_dir / "config.json"
        self.path_var.set(str(default_path))
        self._load_history()
        self._load_prefs()
        self._hydrate_user_themes()
        self._populate_view_menu()
        self.load_action()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_theme(self.current_theme)
        self._position_main_window()
        self._update_window_bounds()

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Scrollable container
        container = ttk.Frame(self.root)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0)
        self.canvas = canvas
        vscroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        hscroll = ttk.Scrollbar(container, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        top = ttk.Frame(canvas, padding=10)
        self.top_frame = top
        self._canvas_window_id = canvas.create_window((0, 0), window=top, anchor="nw")

        def _on_top_config(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_config(event):
            if getattr(self, "_canvas_window_id", None) is not None:
                # Do not force width; allow horizontal overflow for hscroll to work
                pass

        top.bind("<Configure>", _on_top_config)
        top.bind("<Configure>", self._update_window_bounds, add="+")
        canvas.bind("<Configure>", _on_canvas_config)
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )
        canvas.bind_all(
            "<Shift-MouseWheel>",
            lambda e: canvas.xview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        # Menubar for theme selection
        menubar = tk.Menu(self.root)
        self.view_menu = tk.Menu(menubar, tearoff=0)
        self._populate_view_menu()
        menubar.add_cascade(label="View", menu=self.view_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Launch EI Guide", command=self.launch_ei_guide)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

        path_row = ttk.Frame(top)
        path_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        path_row.columnconfigure(1, weight=1)
        ttk.Label(path_row, text="Config path:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(path_row, textvariable=self.path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(path_row, text="Browse", command=self.browse_action).grid(row=0, column=2, padx=6)
        ttk.Button(path_row, text="Load", command=self.load_action).grid(row=0, column=3, padx=3)
        ttk.Button(path_row, text="Save", command=self.save_action).grid(row=0, column=4, padx=(3, 3))
        ttk.Button(path_row, text="Toggle Theme", command=self.toggle_theme).grid(row=0, column=5, padx=(3, 0))
        ttk.Button(path_row, text="Theme Colors", command=self.open_theme_picker).grid(row=0, column=6, padx=(3, 0))
        ttk.Label(path_row, text="Font Size:").grid(row=0, column=7, sticky="e", padx=(8, 4))
        font_combo = ttk.Combobox(
            path_row,
            values=["Small", "Medium", "Large"],
            state="readonly",
            textvariable=self.font_size_var,
            width=8,
        )
        font_combo.grid(row=0, column=8, sticky="w")
        font_combo.bind("<<ComboboxSelected>>", lambda e: self.set_font_size(self.font_size_var.get().lower()))

        cols = ("key", "value")
        self.tree = ttk.Treeview(top, columns=cols, show="headings", height=14)
        self.tree.heading("key", text="Key")
        self.tree.heading("value", text="Value")
        self.tree.column("key", width=200, anchor="w")
        self.tree.column("value", width=360, anchor="w")
        yscroll = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Delete>", lambda e: self.delete_action())
        top.rowconfigure(1, weight=1)

        form = ttk.Frame(top)
        form.grid(row=2, column=0, sticky="ew", pady=(8, 6))
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Key:").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.key_var).grid(row=0, column=1, sticky="ew", padx=(4, 8))
        ttk.Label(form, text="Value:").grid(row=0, column=2, sticky="w")
        # Value widget placeholder (entry or dropdown depending on type).
        self.value_container = form
        self.value_col = 3
        self.value_row = 0
        self._build_value_widget(kind="entry")
        form.columnconfigure(3, weight=1)
        type_opts = ttk.Frame(form)
        type_opts.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        ttk.Label(type_opts, text="Value type:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        for idx, (label, val) in enumerate([("Auto", "auto"), ("True/False", "bool")]):
            ttk.Radiobutton(
                type_opts, text=label, value=val, variable=self.type_var, command=self.on_type_change
            ).grid(row=0, column=idx + 1, sticky="w", padx=(0, 8))
        ttk.Button(form, text="Add/Update", command=self.add_update_action).grid(row=0, column=4, padx=(4, 4))
        ttk.Button(form, text="Edit JSON", command=self.edit_json_action).grid(row=0, column=5, padx=(4, 4))
        ttk.Button(form, text="Delete Selected", command=self.delete_action).grid(row=0, column=6)

        chatbot_row = ttk.Frame(top)
        chatbot_row.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        chatbot_row.columnconfigure(0, weight=1)
        self.chatbot_button = tk.Button(
            chatbot_row,
            text="Configuration Chatbot",
            command=self.launch_ei_guide,
            cursor="hand2",
            font=("Segoe UI", 12, "bold"),
            relief="flat",
            padx=12,
            pady=6,
        )
        self.chatbot_button.grid(row=0, column=0, sticky="n")

        status_bar = ttk.Frame(top)
        status_bar.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        status_bar.columnconfigure(1, weight=1)
        self.dirty_label = ttk.Label(status_bar, text="", foreground="#dc2626")
        self.dirty_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.status_label = ttk.Label(status_bar, textvariable=self.status_var, foreground="#1d4ed8")
        self.status_label.grid(row=0, column=1, sticky="w")

    def _update_window_bounds(self, event=None):
        self.root.update_idletasks()
        req_w = self.top_frame.winfo_reqwidth() + 20
        req_h = self.top_frame.winfo_reqheight() + 20
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        max_w = min(max(req_w, 200), screen_w)
        max_h = min(max(req_h, 200), screen_h)
        self.root.maxsize(max_w, max_h)
        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()
        new_w = min(cur_w, max_w)
        new_h = min(cur_h, max_h)
        if new_w != cur_w or new_h != cur_h:
            self.root.geometry(f"{new_w}x{new_h}")

    def browse_action(self):
        path = filedialog.askopenfilename(title="Select config JSON", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self.path_var.set(path)
            self.set_status(f"Selected {path}")

    def load_action(self):
        path = Path(self.path_var.get()).expanduser()
        if not path.exists():
            create = messagebox.askyesno("Config not found", "No config.json found in this directory. Would you like to create a new blank one?")
            if create:
                try:
                    path.write_text("{}", encoding="utf-8")
                except Exception as exc:
                    messagebox.showerror("Create failed", f"Could not create config: {exc}")
                    self.set_status("Create failed", kind="error")
                    return
            else:
                self.set_status(f"Not found: {path}", kind="error")
                return
        try:
            self.data = load_json(path)
            if not isinstance(self.data, dict):
                raise ValueError("Config root must be a JSON object (key/value pairs)")
            self.refresh_tree()
            self.set_status(f"Loaded {path}", kind="info")
            self.set_dirty(False)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            self.set_status("Load failed", kind="error")

    def save_action(self):
        path = Path(self.path_var.get()).expanduser()
        # Rebuild data from the tree to reflect any unsaved changes.
        new_data = {}
        for item in self.tree.get_children(""):
            key, val_str = self.tree.item(item, "values")
            new_data[key] = infer_value(str(val_str))
        self.data = new_data
        # Confirm overwrite.
        if path.exists():
            ok = messagebox.askyesno("Confirm Save", f"Overwrite existing file?\n\n{path}")
            if not ok:
                self.set_status("Save canceled", kind="info")
                return
        try:
            save_json(path, self.data)
            self._save_history()
            self.set_status(f"Saved to {path}", kind="success")
            self.set_dirty(False)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            self.set_status("Save failed", kind="error")

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children(""))
        for key in sorted(self.data.keys()):
            val = self.data[key]
            display = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
            self.tree.insert("", "end", values=(key, display))

    def on_select(self, event=None):
        """When a row is clicked, load its key/value into the edit boxes."""
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        key, _ = self.tree.item(item, "values")
        val = self.data.get(key)
        display = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        self.key_var.set(key)
        self.val_var.set(display)
        # Preselect type button based on current value.
        if isinstance(val, bool):
            self.type_var.set("bool")
            self.on_type_change()
            self.val_var.set("True" if val else "False")
        else:
            self.type_var.set("auto")
            self.on_type_change(key_hint=key)
        self.set_status(f"Editing {key}", kind="info")

    def add_update_action(self):
        key = self.key_var.get().strip()
        val_text = self._get_value_text()
        if not key:
            messagebox.showwarning("Missing key", "Please enter a key name.")
            return
        parsed = coerce_value(val_text, self.type_var.get())
        self.data[key] = parsed
        # Update history for non-boolean entries so repeat values are easy to pick.
        if self.type_var.get() != "bool":
            self._update_history(key, val_text)
        self._save_history()
        self.refresh_tree()
        self.set_status(f"Set {key}", kind="success")
        self.set_dirty(True)

    def edit_json_action(self):
        """Open a small dialog to edit JSON values (objects/arrays) with validation."""
        key = self.key_var.get().strip()
        if not key:
            messagebox.showwarning("Missing key", "Select or enter a key before editing JSON.")
            return
        existing_text = self._get_value_text()
        # Try to pretty-print existing JSON if valid.
        try:
            parsed = json.loads(existing_text)
            existing_text = json.dumps(parsed, indent=2)
        except Exception:
            pass

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Edit JSON for {key}")
        dlg.geometry("520x380")
        dlg.transient(self.root)
        dlg.grab_set()

        theme = self._get_theme()
        txt = tk.Text(dlg, wrap="word", background=theme.get("entry_bg"), foreground=theme.get("entry_fg"))
        txt.insert("1.0", existing_text)
        txt.pack(fill="both", expand=True, padx=10, pady=10)

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        def on_save():
            raw = txt.get("1.0", "end").strip()
            try:
                parsed_val = json.loads(raw)
            except Exception as exc:
                messagebox.showerror("Invalid JSON", f"Could not parse JSON:\n{exc}")
                return
            self.type_var.set("auto")
            self.val_var.set(json.dumps(parsed_val))
            dlg.destroy()
            self.add_update_action()

        # Keyboard: Ctrl+Enter commits JSON.
        txt.bind("<Control-Return>", lambda e: on_save())
        txt.bind("<Control-KP_Enter>", lambda e: on_save())

        ttk.Button(btns, text="Save", command=on_save).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")

    def _get_value_text(self) -> str:
        """Return the current text/value from the active widget."""
        if isinstance(self.value_widget, ttk.Combobox):
            return self.value_widget.get()
        return self.val_var.get()

    def _get_font(self):
        return self.current_font

    def _build_value_widget(self, kind: str, key_hint: str = ""):
        """Create the value input widget: entry (with history/choices) or boolean dropdown."""
        # Destroy prior widget if present.
        if self.value_widget is not None:
            self.value_widget.destroy()
            if self.tooltip:
                self.tooltip.hide()
                self.tooltip = None
            if self.selection_popup:
                self.selection_popup.destroy()
                self.selection_popup = None
        if kind == "bool":
            self.value_widget = ttk.Combobox(
                self.value_container,
                values=["True", "False"],
                textvariable=self.val_var,
                state="readonly",
            )
        else:
            # For non-bool, offer a combobox with history values for this key.
            hist_vals = self.history.get(key_hint, []) if key_hint else []
            preset = self.known_choices.get(key_hint, [])
            values = preset + [v for v in hist_vals if v not in preset]
            is_locked = bool(preset)
            self.value_widget = ttk.Combobox(
                self.value_container,
                values=values,
                textvariable=self.val_var,
                state="readonly" if is_locked else "normal",
            )
        self.value_widget.grid(row=self.value_row, column=self.value_col, sticky="ew", padx=(4, 8))
        # Attach tooltip if available.
        if key_hint in self.help_text and isinstance(self.value_widget, ttk.Combobox):
            self.tooltip = ToolTip(self.value_widget, self.help_text[key_hint], self._get_theme, self._get_font)
            # Also show a timed popup when a value is selected.
            self.value_widget.bind("<<ComboboxSelected>>", lambda e, k=key_hint: self._show_selection_popup(k))
        elif self.tooltip:
            self.tooltip.hide()
            self.tooltip = None
        # Enter key commits the value.
        self.value_widget.bind("<Return>", lambda e: self.add_update_action())

    def on_type_change(self, key_hint: str = ""):
        """Switch the value widget based on selected type."""
        mode = self.type_var.get()
        if mode == "bool":
            self._build_value_widget("bool")
        else:
            self._build_value_widget("entry", key_hint=key_hint or self.key_var.get().strip())

    def delete_action(self):
        selection = self.tree.selection()
        if not selection:
            return
        for item in selection:
            key, _ = self.tree.item(item, "values")
            if key in self.data:
                self.data.pop(key, None)
        self.refresh_tree()
        self.set_status("Deleted selection", kind="info")
        self.set_dirty(True)

    # History helpers -------------------------------------------------
    def _load_history(self):
        try:
            if self.history_path.exists():
                with open(self.history_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        self.history = {k: v for k, v in data.items() if isinstance(v, list)}
        except Exception:
            self.history = {}

    def _save_history(self):
        try:
            with open(self.history_path, "w", encoding="utf-8") as fh:
                json.dump(self.history, fh, indent=2)
        except Exception:
            pass

    def _update_history(self, key: str, val_text: str, max_len: int = 10):
        if not key or not val_text:
            return
        lst = self.history.get(key, [])
        # Avoid duplicates; move to front.
        lst = [v for v in lst if v != val_text]
        lst.insert(0, val_text)
        self.history[key] = lst[:max_len]

    def _show_selection_popup(self, key: str):
        """Show a balloon for selected values (e.g., openai_temperature) for 10 seconds."""
        if self.selection_popup:
            self.selection_popup.destroy()
            self.selection_popup = None
        if key != "openai_temperature":
            return
        val = self._get_value_text().strip()
        if not val:
            return
        # Detail per value.
        detail_map = {
            "0.0": "Deterministic and repeatable.",
            "0.2": "Very low variation; mostly stable answers.",
            "0.5": "Balanced: mix of stability and creativity.",
            "0.7": "Creative: more varied and inventive wording.",
            "1.0": "Highly creative/unpredictable responses.",
        }
        detail = detail_map.get(val, "Controls randomness: lower = stable, higher = creative.")
        msg = f"Temperature {val}: {detail}"
        # Position near widget.
        x = self.value_widget.winfo_rootx() + 10
        y = self.value_widget.winfo_rooty() + self.value_widget.winfo_height() + 5
        theme = self._get_theme()
        popup = tk.Toplevel(self.value_widget)
        popup.wm_overrideredirect(True)
        popup.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            popup,
            text=msg,
            justify=tk.LEFT,
            background=theme.get("tooltip_bg"),
            relief=tk.SOLID,
            borderwidth=1,
            fg=theme.get("tooltip_fg"),
            font=self._get_font(),
            padx=6,
            pady=4,
        )
        lbl.pack(ipadx=1)
        self.selection_popup = popup
        # Auto-close after 10 seconds.
        popup.after(10000, lambda: popup.destroy())

    # Status / dirty helpers ------------------------------------------
    def set_status(self, msg: str, kind: str = "info"):
        self.status_var.set(msg)
        theme = self._get_theme()
        dirty_color = theme.get("dirty_fg") or theme.get("status_error") or theme.get("status_info") or theme.get("fg")
        self.status_label.configure(foreground=dirty_color)

    def set_dirty(self, is_dirty: bool):
        self.dirty = is_dirty
        self.dirty_label.configure(text="Unsaved changes" if is_dirty else "")

    def on_close(self):
        if self.dirty:
            ok = messagebox.askyesno("Unsaved changes", "You have unsaved changes. Quit anyway?")
            if not ok:
                return
        self.root.destroy()

    def launch_ei_guide(self):
        webbrowser.open(self.get_ei_guide_url())

    def show_about_dialog(self):
        message = (
            "Config Editor\n"
            "Built with respect for the roots of computing — from green-screen terminals to modern intelligent systems.\n\n"
            "This interface honors the legacy of seasoned professionals who remember when screens glowed green and precision mattered."
        )
        messagebox.showinfo("About Config Editor", message, parent=self.root)

    def open_theme_picker(self):
        if self._color_picker and self._color_picker.winfo_exists():
            self._color_picker.lift()
            return
        base_theme = self.theme_var.get()
        self._color_picker = ThemeColorPicker(self, base_theme)
        self._position_theme_picker(self._color_picker)
        self._color_picker.bind("<Destroy>", lambda e: setattr(self, "_color_picker", None))

    def _position_theme_picker(self, picker: tk.Toplevel):
        self.root.update_idletasks()
        picker.update_idletasks()
        picker_w = picker.winfo_width()
        picker_h = picker.winfo_height()
        screen_w = picker.winfo_screenwidth()
        screen_h = picker.winfo_screenheight()
        root_w = self.root.winfo_width()
        root_x = screen_w - root_w - picker_w - 50
        x = max(min(root_x + root_w + 20, screen_w - picker_w - 10), 10)
        y = max(20, screen_h * 0.05)
        picker.geometry(f"+{int(x)}+{int(y)}")

    def _position_main_window(self, initial: bool = False):
        self.root.update_idletasks()
        width = self.top_frame.winfo_reqwidth() + 40
        height = self.top_frame.winfo_reqheight() + 40
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(width, screen_w)
        height = min(height, screen_h)
        self.root.geometry(f"{int(width)}x{int(height)}")
        x = max(10, screen_w - width - 20)
        y = max(10, screen_h * 0.05)
        self.root.geometry(f"+{int(x)}+{int(y)}")

    def get_ei_guide_url(self) -> str:
        return self.prefs.get("ei_guide_url") or EI_GUIDE_URL

    # Theme / prefs ----------------------------------------------------
    def get_palette_defaults(self, mode: str):
        mode_key = "light" if mode == "light" else "dark"
        if mode_key == "light":
            return {
                "primary_bg": "#ffffff",
                "secondary_bg": "#f3f4f6",
                "entry_bg": "#ffffff",
                "entry_fg": "#111827",
                "list_bg": "#f4f4f4",
                "list_fg": "#111827",
                "list_highlight": "#dbeafe",
                "tree_bg": "#e5e7eb",
                "tree_fg": "#111827",
                "text_color": "#111827",
                "accent_color": "#1d4ed8",
                "selection_bg": "#93c5fd",
                "status_info": "#2563eb",
                "status_success": "#16a34a",
                "status_error": "#b91c1c",
                "dirty_color": "#b91c1c",
                "tooltip_bg": "#f3f4f6",
                "tooltip_fg": "#111827",
            }
        return {
            "primary_bg": "#020617",
            "secondary_bg": "#111827",
            "entry_bg": "#0f172a",
            "entry_fg": "#f9fafb",
            "list_bg": "#1f2937",
            "list_fg": "#f9fafb",
            "list_highlight": "#1e3a8a",
            "tree_bg": "#0f172a",
            "tree_fg": "#f9fafb",
            "text_color": "#f9fafb",
            "accent_color": "#38bdf8",
            "selection_bg": "#0ea5e9",
            "status_info": "#38bdf8",
            "status_success": "#22c55e",
            "status_error": "#f43f5e",
            "dirty_color": "#f87171",
            "tooltip_bg": "#1e293b",
            "tooltip_fg": "#f8fafc",
        }

    def get_palette_for_theme(self, theme_name: str) -> Tuple[dict, dict]:
        data = self.user_theme_data.get(theme_name)
        if data:
            metadata = data.get("metadata", {})
            mode = metadata.get("mode", "dark")
            palette = {**self.get_palette_defaults(mode), **data.get("colors", {})}
            metadata = {
                "mode": mode,
                "high_contrast": metadata.get("high_contrast", False),
            }
            return palette, metadata
        theme = self.themes.get(theme_name)
        if theme:
            palette = self._theme_to_palette(theme)
            mode = "light" if theme_name == "light" else "dark"
            return palette, {"mode": mode, "high_contrast": False}
        mode = "light" if theme_name == "light" else "dark"
        return self.get_palette_defaults(mode), {"mode": mode, "high_contrast": False}

    def apply_custom_colors(self, palette: dict, metadata: dict, base_theme: str):
        theme_name = self._create_user_theme(base_theme, palette, metadata)
        self.prefs["custom_themes"] = self.user_theme_data
        self.prefs["theme"] = theme_name
        self._save_prefs()
        self.theme_var.set(theme_name)
        self._populate_view_menu()
        self.apply_theme(theme_name)

    def _populate_view_menu(self):
        if not self.view_menu:
            return
        self.view_menu.delete(0, "end")
        built_ins = [
            ("High Contrast (Dark)", "high_contrast_dark"),
            ("Standard Light", "light"),
            ("Stinky Contrast", "stinky"),
            ("Green Screen CRT", "green_screen"),
        ]
        for label, value in built_ins:
            self.view_menu.add_radiobutton(
                label=label,
                variable=self.theme_var,
                value=value,
                command=lambda n=value: self.set_theme(n),
            )
        if self.user_theme_data:
            self.view_menu.add_separator()
            for name in sorted(self.user_theme_data.keys()):
                self.view_menu.add_radiobutton(
                    label=name,
                    variable=self.theme_var,
                    value=name,
                    command=lambda n=name: self.set_theme(n),
                )
        self.view_menu.add_separator()
        self.view_menu.add_command(label="Theme Color Picker...", command=self.open_theme_picker)

    def _hydrate_user_themes(self):
        stored = self.prefs.get("custom_themes", {})
        if not isinstance(stored, dict):
            stored = {}
        cleaned = {}
        for name, data in stored.items():
            colors = data.get("colors")
            metadata = data.get("metadata", {})
            if not isinstance(colors, dict) or not isinstance(metadata, dict):
                continue
            base_key = self._canonical_base_theme_key(metadata.get("base_theme") or name)
            cleaned[base_key] = {"colors": colors, "metadata": {**metadata, "base_theme": base_key}}
        self.user_theme_data = {}
        for base_key, data in cleaned.items():
            colors = data["colors"]
            metadata = data["metadata"]
            derived = self._derive_theme_from_palette(colors, metadata)
            label = self._format_theme_label(base_key)
            if label in self.user_theme_data:
                label = self._ensure_unique_theme_name(label, self.user_theme_data)
            self.themes[label] = derived
            self.user_theme_data[label] = {"colors": colors, "metadata": metadata}
        self.prefs["custom_themes"] = self.user_theme_data
        self._save_prefs()

    def _create_user_theme(self, base_theme: str, palette: dict, metadata: dict) -> str:
        base_key = self._canonical_base_theme_key(base_theme)
        label = self._format_theme_label(base_key)
        if label not in self.user_theme_data:
            label = self._ensure_unique_theme_name(label, self.user_theme_data)
        derived = self._derive_theme_from_palette(palette, metadata)
        self.themes[label] = derived
        self.user_theme_data[label] = {
            "colors": palette,
            "metadata": {**metadata, "base_theme": base_key},
        }
        return label

    def _canonical_base_theme_key(self, name: str) -> str:
        if not name:
            return "custom_theme"
        normalized = name.replace("_", " ").strip().lower()
        while normalized.endswith(" custom"):
            normalized = normalized[: -len(" custom")].strip()
        known = {
            "high contrast (dark)": "high_contrast_dark",
            "high contrast dark": "high_contrast_dark",
            "standard light": "light",
            "light": "light",
            "stinky": "stinky",
            "stinky contrast": "stinky",
            "green screen crt": "green_screen",
            "green screen": "green_screen",
        }
        if normalized in known:
            return known[normalized]
        return "_".join(normalized.split()) or "custom_theme"

    def _format_theme_label(self, base_key: str) -> str:
        pretty = base_key.replace("_", " ").title().strip() or "Custom Theme"
        if base_key in {"high_contrast_dark", "light", "stinky", "green_screen"}:
            return f"{pretty} Custom"
        return pretty

    def _ensure_unique_theme_name(self, base_label: str, existing: Optional[dict] = None) -> str:
        if existing is None:
            existing = self.user_theme_data
        candidate = base_label
        idx = 2
        while candidate in existing or candidate in self.themes:
            candidate = f"{base_label} {idx}"
            idx += 1
        return candidate

    def _theme_to_palette(self, theme: dict) -> dict:
        palette = {
            "primary_bg": theme.get("bg"),
            "secondary_bg": theme.get("entry_bg", theme.get("bg")),
            "entry_bg": theme.get("entry_bg"),
            "entry_fg": theme.get("entry_fg", theme.get("fg")),
            "list_bg": theme.get("list_bg", theme.get("tree_bg")),
            "list_fg": theme.get("list_fg", theme.get("fg")),
            "list_highlight": theme.get("list_highlight", theme.get("selection_bg")),
            "tree_bg": theme.get("tree_bg"),
            "tree_fg": theme.get("tree_fg", theme.get("fg")),
            "text_color": theme.get("fg"),
            "accent_color": theme.get("status_info", theme.get("selection_bg")),
            "selection_bg": theme.get("selection_bg"),
            "status_info": theme.get("status_info"),
            "status_success": theme.get("status_success"),
            "status_error": theme.get("status_error"),
            "dirty_color": theme.get("dirty_fg"),
            "tooltip_bg": theme.get("tooltip_bg"),
            "tooltip_fg": theme.get("tooltip_fg"),
        }
        return {k: v for k, v in palette.items() if v}

    def _derive_theme_from_palette(self, palette: dict, metadata: dict):
        mode = metadata.get("mode", "dark")
        high_contrast = metadata.get("high_contrast", False)
        primary = palette.get("primary_bg", "#020617")
        secondary = palette.get("secondary_bg", primary)
        text_color = palette.get("text_color", "#f9fafb")
        accent = palette.get("accent_color", "#38bdf8")
        dirty_color = palette.get("dirty_color", "#f87171" if mode == "dark" else "#b91c1c")
        list_highlight = palette.get("list_highlight")
        if high_contrast:
            text_color = "#f8fafc" if mode == "dark" else "#0f172a"
            accent = "#f97316" if mode == "dark" else "#2563eb"
            if not list_highlight:
                list_highlight = accent
        tree_bg = palette.get("tree_bg") or (secondary if mode == "light" else self._blend_colors(primary, secondary, 0.35))
        list_bg = palette.get("list_bg") or (secondary if mode == "light" else self._blend_colors(primary, secondary, 0.45))
        selection_bg = palette.get("selection_bg") or self._blend_colors(accent, primary, 0.5)
        theme = {
            "bg": primary,
            "fg": text_color,
            "entry_bg": palette.get("entry_bg", secondary),
            "entry_fg": palette.get("entry_fg", text_color),
            "tree_bg": tree_bg,
            "tree_fg": palette.get("tree_fg", text_color),
            "list_bg": list_bg,
            "list_fg": palette.get("list_fg", text_color),
            "list_highlight": list_highlight or selection_bg,
            "dirty_fg": dirty_color,
            "status_info": palette.get("status_info", accent),
            "status_success": palette.get("status_success", self._blend_colors(accent, "#22c55e", 0.4)),
            "status_error": palette.get("status_error", ("#f43f5e" if mode == "dark" else "#b91c1c")),
            "tooltip_bg": palette.get("tooltip_bg", self._blend_colors(primary, secondary, 0.5)),
            "tooltip_fg": palette.get("tooltip_fg", text_color),
            "selection_bg": selection_bg,
        }
        return theme

    @staticmethod
    def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
        value = color.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _blend_colors(self, base: str, target: str, factor: float) -> str:
        base_rgb = self._hex_to_rgb(base)
        target_rgb = self._hex_to_rgb(target)
        blended = tuple(
            max(0, min(255, int(base_c + (target_c - base_c) * factor))) for base_c, target_c in zip(base_rgb, target_rgb)
        )
        return self._rgb_to_hex(blended)

    def _contrast_ratio(self, color_a: str, color_b: str) -> float:
        def rel_luminance(rgb: Tuple[int, int, int]) -> float:
            def adjust(channel: int) -> float:
                c = channel / 255.0
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            r, g, b = rgb
            return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

        lum1 = rel_luminance(self._hex_to_rgb(color_a))
        lum2 = rel_luminance(self._hex_to_rgb(color_b))
        lighter = max(lum1, lum2)
        darker = min(lum1, lum2)
        return (lighter + 0.05) / (darker + 0.05)

    def _get_theme(self):
        return self.themes.get(self.current_theme, self.themes["high_contrast_dark"])

    def apply_theme(self, name: str) -> None:
        theme = self.themes.get(name) or self.themes["high_contrast_dark"]
        self.current_theme = name if name in self.themes else "high_contrast_dark"
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            ".",
            background=theme["bg"],
            foreground=theme["fg"],
        )
        # Fonts and sizes
        font_conf = self.font_sizes.get(self.font_size_var.get(), self.font_sizes["medium"])
        base_font = ("Segoe UI", font_conf["base"])
        self.current_font = base_font
        style.configure(
            "Treeview",
            background=theme["tree_bg"],
            fieldbackground=theme["tree_bg"],
            foreground=theme["tree_fg"],
            rowheight=font_conf["rowheight"],
            font=base_font,
        )
        style.configure("Treeview.Heading", background=theme["bg"], foreground=theme["fg"], font=base_font)
        style.configure("TLabel", background=theme["bg"], foreground=theme["fg"], font=base_font)
        style.configure("TFrame", background=theme["bg"])
        style.configure("TEntry", fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"], font=base_font)
        style.configure(
            "TCombobox",
            fieldbackground=theme["entry_bg"],
            foreground=theme["entry_fg"],
            background=theme["entry_bg"],
            font=base_font,
        )
        style.configure("TButton", font=base_font)
        style.configure("TScrollbar", background=theme["tree_bg"], troughcolor=theme["tree_bg"])
        style.configure("TButton", background=theme["tree_bg"], foreground=theme["fg"])
        style.configure("TMenubutton", background=theme["entry_bg"], foreground=theme["entry_fg"], font=base_font)
        style.configure("Horizontal.TScrollbar", background=theme["tree_bg"], troughcolor=theme["tree_bg"])
        style.map(
            "TButton",
            background=[
                ("active", theme.get("selection_bg", theme["tree_bg"])),
                ("pressed", theme.get("selection_bg", theme["tree_bg"])),
                ("focus", theme.get("selection_bg", theme["tree_bg"])),
            ],
            foreground=[("active", theme["fg"]), ("pressed", theme["fg"]), ("focus", theme["fg"])],
        )
        style.map(
            "TScrollbar",
            background=[("active", theme["tree_bg"]), ("!disabled", theme["tree_bg"])],
            troughcolor=[("active", theme["tree_bg"]), ("!disabled", theme["tree_bg"])],
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", theme["tree_bg"]), ("!disabled", theme["tree_bg"])],
            troughcolor=[("active", theme["tree_bg"]), ("!disabled", theme["tree_bg"])],
        )
        style.map(
            "TEntry",
            fieldbackground=[
                ("active", theme["entry_bg"]),
                ("focus", theme["entry_bg"]),
                ("!disabled", theme["entry_bg"]),
            ],
            background=[
                ("active", theme["entry_bg"]),
                ("focus", theme["entry_bg"]),
                ("!disabled", theme["entry_bg"]),
            ],
            foreground=[("!disabled", theme["entry_fg"])],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", theme["entry_bg"]), ("!disabled", theme["entry_bg"])],
            background=[("readonly", theme["entry_bg"]), ("!disabled", theme["entry_bg"])],
            foreground=[("readonly", theme["entry_fg"]), ("!disabled", theme["entry_fg"])],
        )
        style.map(
            "Treeview",
            background=[("selected", theme.get("selection_bg", theme.get("status_info", theme["fg"])))],
            foreground=[("selected", theme.get("tree_fg", "#ffffff"))],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", theme["tree_bg"]), ("pressed", theme["tree_bg"])],
            foreground=[("active", theme["tree_fg"]), ("pressed", theme["tree_fg"])],
        )
        # Root background
        self.root.configure(background=theme["tree_bg"] if self.current_theme == "high_contrast_dark" else theme["bg"])
        if hasattr(self, "canvas"):
            self.canvas.configure(background=theme["tree_bg"] if self.current_theme == "high_contrast_dark" else theme["bg"])
        list_bg = theme.get("list_bg") or ("#3a3a3a" if self.current_theme == "high_contrast_dark" else "#f4f4f4")
        list_fg = theme.get("list_fg") or (theme["fg"] if self.current_theme == "high_contrast_dark" else "black")
        list_highlight = theme.get("list_highlight", theme.get("selection_bg", list_bg))
        self.root.option_add("*TCombobox*Listbox.background", list_bg)
        self.root.option_add("*TCombobox*Listbox.foreground", list_fg)
        self.root.option_add("*TCombobox*Listbox*selectBackground", list_highlight)
        self.root.option_add("*TCombobox*Listbox*selectForeground", list_fg)
        self.root.option_add("*Listbox.background", list_bg)
        self.root.option_add("*Listbox.foreground", list_fg)
        self.root.option_add("*Listbox*selectBackground", list_highlight)
        self.root.option_add("*Listbox*selectForeground", list_fg)
        if hasattr(self, "dirty_label"):
            dirty_color = theme.get("dirty_fg", theme.get("status_error", theme["fg"]))
            self.dirty_label.configure(foreground=dirty_color)
        if hasattr(self, "chatbot_button"):
            self.chatbot_button.configure(
                background=theme.get("selection_bg", theme["bg"]),
                activebackground=theme.get("status_info", theme["bg"]),
                foreground=theme.get("fg"),
                activeforeground=theme.get("fg"),
                highlightthickness=0,
                bd=0,
            )
        # Update status colors now.
        self.set_status(self.status_var.get(), kind="info")

    def set_theme(self, name: str) -> None:
        if name not in self.themes:
            return
        self.apply_theme(name)
        self.prefs["theme"] = name
        self._save_prefs()

    def set_font_size(self, size_name: str) -> None:
        size_key = size_name.lower()
        if size_key not in self.font_sizes:
            size_key = "medium"
        self.font_size_var.set(size_key)
        self.prefs["font_size"] = size_key
        self.apply_theme(self.current_theme)
        self._save_prefs()

    def toggle_theme(self):
        new_theme = "light" if self.current_theme == "high_contrast_dark" else "high_contrast_dark"
        self.set_theme(new_theme)

    def _load_prefs(self):
        try:
            if self.prefs_path.exists():
                with open(self.prefs_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict) and "theme" in data:
                        self.prefs.update(data)
                        self.current_theme = data.get("theme", "green_screen")
                        self.theme_var.set(self.current_theme)
                    if isinstance(data, dict) and "font_size" in data:
                        size_val = data.get("font_size", "medium")
                        self.font_size_var.set(size_val)
                        self.prefs["font_size"] = size_val
                    if isinstance(data, dict):
                        custom_themes = data.get("custom_themes")
                        if isinstance(custom_themes, dict):
                            self.prefs["custom_themes"] = custom_themes
                        else:
                            legacy = data.get("custom_theme")
                            if isinstance(legacy, dict) and legacy.get("colors") and legacy.get("metadata"):
                                self.prefs["custom_themes"] = {"Custom Theme": legacy}
                    if isinstance(data, dict) and "ei_guide_url" in data:
                        self.prefs["ei_guide_url"] = data.get("ei_guide_url", EI_GUIDE_URL)
            self.prefs.setdefault("custom_themes", {})
            self.prefs.setdefault("ei_guide_url", EI_GUIDE_URL)
        except Exception:
            pass

    def _save_prefs(self):
        try:
            with open(self.prefs_path, "w", encoding="utf-8") as fh:
                json.dump(self.prefs, fh, indent=2)
        except Exception:
            pass


def main():
    root = tk.Tk()
    ConfigEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
