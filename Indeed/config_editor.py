#!/usr/bin/env python3
"""
Simple GUI editor for config JSON files. It loads the JSON, shows top-level keys,
and lets you add/update/delete entries. Values are type-inferred (bool/int/float/JSON object/array)
when possible; otherwise they are saved as strings.
"""

from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Config JSON Editor"


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

    def __init__(self, widget, text: str, theme_fn):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.theme_fn = theme_fn
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if self.tipwindow or not self.text:
            return
        theme = self.theme_fn()
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
            font=("Segoe UI", 9),
            padx=6,
            pady=4,
        )
        label.pack(ipadx=1)

    def hide(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


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
        self.prefs = {"theme": "high_contrast_dark"}
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
        # Themes for accessibility.
        self.themes = {
            "high_contrast_dark": {
                "bg": "#020617",
                "fg": "#f9fafb",
                "entry_bg": "#020617",
                "entry_fg": "#f9fafb",
                "tree_bg": "#020617",
                "tree_fg": "#f9fafb",
                "status_info": "#38bdf8",
                "status_success": "#22c55e",
                "status_error": "#f43f5e",
                "tooltip_bg": "#0b1224",
                "tooltip_fg": "#f9fafb",
            },
            "light": {
                "bg": "#ffffff",
                "fg": "#111827",
                "entry_bg": "#ffffff",
                "entry_fg": "#111827",
                "tree_bg": "#ffffff",
                "tree_fg": "#111827",
                "status_info": "#1d4ed8",
                "status_success": "#15803d",
                "status_error": "#b91c1c",
                "tooltip_bg": "#f1f5f9",
                "tooltip_fg": "#111827",
            },
        }
        self.current_theme = "high_contrast_dark"
        self.path_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.val_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.type_var = tk.StringVar(value="auto")
        self.theme_var = tk.StringVar(value=self.current_theme)
        self.value_widget = None
        self.tooltip = None
        self.selection_popup = None
        self.dirty = False
        self._build_ui()
        default_path = self.base_dir / "config.json"
        self.path_var.set(str(default_path))
        self._load_history()
        self._load_prefs()
        self.load_action()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_theme(self.current_theme)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Menubar for theme selection
        menubar = tk.Menu(self.root)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_radiobutton(
            label="High Contrast (Dark)",
            variable=self.theme_var,
            value="high_contrast_dark",
            command=lambda: self.set_theme("high_contrast_dark"),
        )
        view_menu.add_radiobutton(
            label="Standard Light",
            variable=self.theme_var,
            value="light",
            command=lambda: self.set_theme("light"),
        )
        menubar.add_cascade(label="View", menu=view_menu)
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

        status_bar = ttk.Frame(top)
        status_bar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        status_bar.columnconfigure(1, weight=1)
        self.dirty_label = ttk.Label(status_bar, text="", foreground="#dc2626")
        self.dirty_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.status_label = ttk.Label(status_bar, textvariable=self.status_var, foreground="#1d4ed8")
        self.status_label.grid(row=0, column=1, sticky="w")

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
            self.tooltip = ToolTip(self.value_widget, self.help_text[key_hint], self._get_theme)
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
            font=("Segoe UI", 9),
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
        if kind == "success":
            color = theme.get("status_success", theme.get("status_info"))
        elif kind == "error":
            color = theme.get("status_error", theme.get("status_info"))
        else:
            color = theme.get("status_info")
        self.status_label.configure(foreground=color or theme.get("fg"))

    def set_dirty(self, is_dirty: bool):
        self.dirty = is_dirty
        self.dirty_label.configure(text="Unsaved changes" if is_dirty else "")

    def on_close(self):
        if self.dirty:
            ok = messagebox.askyesno("Unsaved changes", "You have unsaved changes. Quit anyway?")
            if not ok:
                return
        self.root.destroy()

    # Theme / prefs ----------------------------------------------------
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
        style.configure(
            "Treeview",
            background=theme["tree_bg"],
            fieldbackground=theme["tree_bg"],
            foreground=theme["tree_fg"],
            rowheight=22,
        )
        style.configure("Treeview.Heading", background=theme["bg"], foreground=theme["fg"])
        style.configure("TLabel", background=theme["bg"], foreground=theme["fg"])
        style.configure("TFrame", background=theme["bg"])
        style.configure("TEntry", fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])
        style.configure("TCombobox", fieldbackground=theme["entry_bg"], foreground=theme["entry_fg"])
        style.map(
            "Treeview",
            background=[("selected", theme.get("status_info", theme["fg"]))],
            foreground=[("selected", theme.get("bg", "#000000"))],
        )
        # Root background
        self.root.configure(background=theme["bg"])
        # Update status colors now.
        self.set_status(self.status_var.get(), kind="info")

    def set_theme(self, name: str) -> None:
        self.apply_theme(name)
        self.prefs["theme"] = name
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
                        self.current_theme = data.get("theme", "high_contrast_dark")
                        self.theme_var.set(self.current_theme)
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
