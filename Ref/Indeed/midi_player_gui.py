#!/usr/bin/env python3
"""
Tkinter MIDI player that talks directly to winmm's MCI sequencer interface on Windows.
It avoids external Python audio libraries by sending MCI commands through ctypes so the OS's
internal synth handles playback.
"""

import ctypes
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

if sys.platform != "win32":
    raise SystemExit("This MIDI player backend currently only works on Windows.")

_mci = ctypes.windll.winmm


def _mci_command(command: str) -> int:
    """Send a widestring command to the MCI interface."""
    buf = ctypes.create_unicode_buffer(256)
    return _mci.mciSendStringW(command, buf, ctypes.sizeof(buf), None)


class MidiPlayerApp(tk.Tk):
    """Minimal GUI to open and play a MIDI file via MCI."""

    def __init__(self):
        super().__init__()
        self.title("MCI MIDI Player")
        self.geometry("460x160")
        self.resizable(False, False)
        self._current_file = ""
        self._alias = "midi_alias"
        self._is_open = False

        self._path_var = tk.StringVar(value="No file selected")
        self._create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_widgets(self):
        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Selected MIDI file:", anchor="w").pack(fill="x")
        tk.Label(
            frame,
            textvariable=self._path_var,
            relief="sunken",
            anchor="w",
            padx=6,
            pady=4,
        ).pack(fill="x", pady=(0, 10))

        row = tk.Frame(frame)
        row.pack(fill="x")
        tk.Button(row, text="Choose MIDI...", command=self._select_file, width=14).pack(side="left")
        tk.Button(row, text="Play", command=self._play, width=10).pack(side="left", padx=(10, 0))
        tk.Button(row, text="Stop", command=self._stop, width=10).pack(side="left", padx=(8, 0))

    def _select_file(self):
        path = filedialog.askopenfilename(
            title="Select MIDI file",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        if not path:
            return
        self._path_var.set(path)
        self._open_file(path)

    def _open_file(self, path: str):
        self._stop()
        if self._is_open:
            _mci_command(f"close {self._alias}")
            self._is_open = False
        quoted = path.replace('"', '""')
        result = _mci_command(f'open "{quoted}" type sequencer alias {self._alias}')
        if result != 0:
            messagebox.showerror("Open failed", f"Unable to open {os.path.basename(path)}.")
            return
        self._current_file = path
        self._is_open = True

    def _play(self):
        if not self._is_open:
            path = self._path_var.get()
            if not os.path.isfile(path):
                messagebox.showwarning("No file", "Please select a MIDI file first.")
                return
            self._open_file(path)
        _mci_command(f"play {self._alias}")

    def _stop(self):
        if self._is_open:
            _mci_command(f"stop {self._alias}")

    def _on_close(self):
        self._stop()
        if self._is_open:
            _mci_command(f"close {self._alias}")
        self.destroy()


def main():
    app = MidiPlayerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
