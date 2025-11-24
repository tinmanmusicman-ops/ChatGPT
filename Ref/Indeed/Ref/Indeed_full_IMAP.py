from pathlib import Path
from typing import Iterable, List, Set, Tuple
import os

base_dir = Path(__file__).resolve().parent
os.chdir(base_dir)

import argparse
import logging
import re
from datetime import datetime

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        logging.error("File not found: %s", path)
        return ""
    except Exception as e:
        logging.exception("Failed reading %s: %s", path, e)
        return ""

def extract_note_from_text(text: str) -> str:
    """
    Very simple extractor:
    - If text contains a line starting with 'NOTE:' we take that line (minus the prefix).
    - Otherwise we trim the text and return the first non-empty paragraph.
    Replace this with your real extraction logic as needed.
    """
    if not text:
        return ""
    m = re.search(r"^NOTE:\s*(.+)$", text, flags=re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip()
    # Fallback: first non-empty paragraph
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts[0] if parts else ""

def continue_processing(note: str) -> None:
    """
    Placeholder for the next stage of your pipeline.
    This is where you'd call AI, write to Sheets, post to a DB, etc.
    """
    if not note:
        logging.warning("No note provided to continue processing.")
        return
    # Example: pretend to transform the note
    transformed = note.upper()
    logging.info("Processed note (example transform): %s", transformed)

def main() -> None:
    parser = argparse.ArgumentParser(description="Note extractor with breakpoint after extraction.")
    parser.add_argument("--note", type=str, help="Note text to extract from (takes precedence over --infile).")
    parser.add_argument("--infile", type=str, help="Path to a text file to read input from.")
    args = parser.parse_args()

    raw_text = ""
    if args.note:
        raw_text = args.note
        logging.info("Using --note argument as input.")
    elif args.infile:
        raw_text = read_text_file(Path(args.infile))
        logging.info("Loaded text from --infile: %s", args.infile)
    else:
        logging.info("No input provided; using placeholder text.")
        raw_text = "NOTE: This is a sample note captured at %s" % datetime.now().isoformat(timespec="seconds")

    note = extract_note_from_text(raw_text)
    logging.info("Extracted note preview: %s", (note[:120] + "…") if len(note) > 120 else note)

    # --- Debug pause ---
    logging.info("[DEBUG] Pausing after note extraction. Open VS Code Debug console and inspect variables: note, raw_text.")
    breakpoint()  # VS Code will stop here when running in Debug mode (F5)

    # Continue processing after user resumes debugger
    continue_processing(note)
    logging.info("Done.")

if __name__ == "__main__":
    main()
