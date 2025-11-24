from __future__ import annotations

import os
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk

from openai import OpenAI

# Set OPENAI_API_KEY in the environment (e.g. export OPENAI_API_KEY="...") before running.
# Run this script via `python company_analyzer.py`.


PROMPT_TEMPLATE = """
Provide a deep, structured analysis of {company} for a business-savvy reader.
Respond with the following sections in order, each beginning with a heading of the form:
=== SECTION NAME ===
Within each section, use bullet points prefixed with "- " and keep line lengths sensible.

Sections:
1. Company Overview
2. Business Model & Offerings
3. Scale & Markets (make clear that any figures are approximate/latest known)
4. Market Position & Competition
5. Customer Perception & Brand Reputation
6. Employee Sentiment & Culture
7. Recent Events & Notable Signals
8. Risks & Challenges
9. Opportunities & Strategic Insights
10. Partner/Employment Considerations (a short bullet list titled exactly like this)

Throughout, emphasize directional insight over precise figures, and note when a datapoint is uncertain, approximate, or derived from historical context.
""".strip()


def prompt_for_company_name() -> Optional[str]:
    """Show a Tkinter popup to ask for the company name."""
    result: dict[str, Optional[str]] = {"value": None}

    root = tk.Tk()
    root.title("Company Analyzer")
    root.resizable(False, False)
    root.geometry("420x140")
    root.attributes("-topmost", True)

    def close(result_value: Optional[str] = None) -> None:
        result["value"] = result_value
        root.destroy()

    def on_analyze() -> None:
        name = entry.get().strip()
        if name:
            close(name)
        else:
            close(None)

    frame = ttk.Frame(root, padding="12")
    frame.pack(fill="both", expand=True)

    label = ttk.Label(frame, text="Enter company name to analyze:")
    label.pack(anchor="w")

    entry = ttk.Entry(frame)
    entry.pack(fill="x", pady=(6, 12))
    entry.focus()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    analyze_btn = ttk.Button(buttons, text="Analyze", command=on_analyze)
    analyze_btn.pack(side="right", padx=(4, 0))

    cancel_btn = ttk.Button(buttons, text="Cancel", command=lambda: close(None))
    cancel_btn.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", lambda: close(None))

    root.mainloop()
    return result["value"]


def analyze_company_with_ei(company_name: str) -> str:
    """Send the prompt to OpenAI and return the raw analysis text."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is missing. Set it in your environment before running this script."
        )

    client = OpenAI(api_key=api_key)
    system_instruction = "You are an insightful research analyst who produces cleanly formatted reports."
    user_prompt = PROMPT_TEMPLATE.format(company=company_name)

    response = client.chat.completions.create(
        model="gpt-5.1",
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.35,
        max_tokens=1200,
    )

    choices = response.choices
    if not choices:
        raise ValueError("OpenAI returned no choices.")

    content = choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned an empty analysis.")

    return content.strip()


def format_analysis(raw_text: str, company_name: str) -> str:
    """Make the analysis readable with spacing, headings, and wrapping."""
    sanitized_company = company_name.strip()
    header = f"=== Company Analysis: {sanitized_company} ==="
    lines: list[str] = [header, ""]

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("==="):
            if lines and lines[-1]:
                lines.append("")
            lines.append(stripped)
            lines.append("")
        elif stripped.startswith("- "):
            wrapped = textwrap.fill(
                stripped,
                width=80,
                replace_whitespace=False,
                subsequent_indent="  ",
            )
            lines.append(wrapped)
        else:
            wrapped = textwrap.fill(stripped, width=80, replace_whitespace=False)
            lines.append(wrapped)

    return "\n".join(lines).rstrip()


def save_analysis_to_file(formatted_text: str, company_name: str) -> Path:
    """Persist the formatted analysis to a timestamped text file."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", company_name.strip())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"company_analysis_{safe_name}_{timestamp}.txt"
    path = Path(__file__).resolve().parent / filename

    path.write_text(formatted_text + "\n", encoding="utf-8")
    return path


def main() -> None:
    company_name = prompt_for_company_name()
    if not company_name:
        print("No company name provided; exiting.")
        return

    try:
        raw_analysis = analyze_company_with_ei(company_name)
    except EnvironmentError as exc:
        print(str(exc))
        return
    except Exception as exc:  # pylint: disable=broad-except
        print("Unable to reach OpenAI. Please check your connection and try again.")
        print(f"Details: {exc}")
        return

    formatted = format_analysis(raw_analysis, company_name)
    if not formatted.strip():
        print("No analysis returned. Please try again.")
        return

    print(formatted)

    try:
        saved_path = save_analysis_to_file(formatted, company_name)
        print(f"\nResults saved to {saved_path}")
    except Exception as exc:
        print("Failed to write analysis to disk.")
        print(f"Details: {exc}")


if __name__ == "__main__":
    main()
