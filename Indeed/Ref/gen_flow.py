import pathlib, math

node_height = 90
gap = 20
x = 116
width = 380
start_y = 690
line_color = (0.38, 0.91, 0.78)

nodes = [
    {
        "title": "Start / main()",
        "lines": [
            "Load config, enable debug logging when requested",
            "Clear sheet once when flagged per run",
            "Debug mode reads email_body.txt and exits",
            "Normal loop runs until max_emails_per_run"
        ]
    },
    {
        "title": "get_unread_email_body()",
        "lines": [
            "Login IMAP, select INBOX, search Primary unseen",
            "Fetch first message (HTML preferred)",
            "Detect forwarded sender via regex",
            "Filter body with keywords/domains; non-job -> NotRead"
        ]
    },
    {
        "title": "process_email_payload()",
        "lines": [
            "Trim body, skip empty payloads, log source",
            "Call extract_jobs_from_email() for AI parse",
            "Subject fallback populates missing locations",
            "Append jobs to sheet, log completion status"
        ]
    },
    {
        "title": "extract_jobs_from_email()",
        "lines": [
            "Build OpenAI client, combine subject + body",
            "Call Responses.create with EXTRACTION_PROMPT",
            "Parse JSON, enforce max_jobs_per_email",
            "Normalize job_name/salary/location/SWOT"
        ]
    },
    {
        "title": "append_jobs_to_sheet()",
        "lines": [
            "Get worksheet via service account credentials",
            "Ensure headers, wrapping, and cached URLs",
            "Build rows with hyperlink, company, metadata",
            "Append rows, update URL cache, add notes"
        ]
    },
    {
        "title": "Helper utilities",
        "lines": [
            "is_relevant_job_email() enforces heuristics",
            "extract_original_sender_from_body() finds forwarded from",
            "_format_swot_text() cleans JSON/string notes",
            "get_gsheet_worksheet() caches client/worksheet"
        ]
    },
    {
        "title": "Finish / Exit",
        "lines": [
            "Log processed_count and run summary",
            "Exit after the loop finishes"
        ]
    }
]

colors = [
    (0.22, 0.66, 0.94),
    (0.12, 0.18, 0.39),
    (0.10, 0.25, 0.34),
    (0.58, 0.29, 0.88),
    (0.24, 0.34, 0.64),
    (0.07, 0.15, 0.31),
    (0.22, 0.66, 0.94)
]

commands = []

def esc(text):
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def add_rect(x_pos, y_pos, w, h, color):
    commands.append(f"{color[0]} {color[1]} {color[2]} rg")
    commands.append(f"{x_pos} {y_pos} {w} {h} re")
    commands.append("f")


def add_centered_title(x_pos, y_pos, w, text, size=14):
    approx = len(text) * size * 0.5
    start_x = x_pos + max(0, (w - approx) / 2)
    add_text(start_x, y_pos, [text], size=size, leading=size + 4)


def add_text(x_pos, y_pos, lines, size=11, leading=13):
    commands.append("0.95 0.95 0.95 rg")
    commands.append("BT")
    commands.append(f"/F1 {size} Tf")
    commands.append(f"{leading} TL")
    commands.append(f"1 0 0 1 {x_pos:.2f} {y_pos:.2f} Tm")
    for idx, line in enumerate(lines):
        commands.append(f"({esc(line)}) Tj")
        if idx != len(lines) - 1:
            commands.append("T*")
    commands.append("ET")


def add_line_with_arrow(x_pos, start_y, end_y):
    commands.append(f"{line_color[0]} {line_color[1]} {line_color[2]} RG")
    commands.append("3 w")
    commands.append(f"{x_pos} {start_y:.2f} m {x_pos} {end_y:.2f} l S")
    commands.append(f"{line_color[0]} {line_color[1]} {line_color[2]} rg")
    commands.append(f"{x_pos - 5} {end_y + 4:.2f} m")
    commands.append(f"{x_pos + 5} {end_y + 4:.2f} l")
    commands.append(f"{x_pos} {end_y:.2f} l")
    commands.append("h")
    commands.append("f")


commands.append("0.95 0.95 0.95 rg")
commands.append("BT")
commands.append("/F1 20 Tf")
commands.append("1 0 0 1 110 770 Tm")
commands.append("(Indeed Email Processor Flow) Tj")
commands.append("ET")
commands.append("0.78 0.86 1 rg")
commands.append("BT")
commands.append("/F1 11 Tf")
commands.append("1 0 0 1 110 748 Tm")
commands.append("(Detailed Vizeo-style pipeline with helper steps) Tj")
commands.append("ET")

node_positions = []
for idx, node in enumerate(nodes):
    y = start_y - idx * (node_height + gap)
    node_positions.append(y)
    color = colors[idx]
    add_rect(x, y, width, node_height, color)
    add_centered_title(x, y + node_height - 24, width, node["title"], size=14)
    desc_x = x + 14
    desc_y = y + node_height - 42
    add_text(desc_x, desc_y, node["lines"], size=10, leading=12)

for idx in range(len(nodes) - 1):
    start_line = node_positions[idx] - 6
    end_line = node_positions[idx + 1] + node_height + 6
    add_line_with_arrow(306, start_line, end_line)

stream = "\n".join(commands) + "\n"
stream_bytes = stream.encode('utf-8')
length = len(stream_bytes)

objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
    "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    f"5 0 obj\n<< /Length {length} >>\nstream\n{stream}endstream\nendobj\n",
]

header = "%PDF-1.4\n"
body = ""
offsets = []
for obj in objects:
    offsets.append(len((header + body).encode('utf-8')))
    body += obj
total_pdf = (header + body).encode('utf-8')
xref_offset = len(total_pdf)

xref_entries = ["xref", f"0 {len(objects) + 1}", "0000000000 65535 f "]
for offset in offsets:
    xref_entries.append(f"{offset:010d} 00000 n ")

trailer = "trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".format(size=len(objects) + 1, start=xref_offset)
pdf_content = total_pdf + "\n".join(xref_entries).encode('utf-8') + trailer.encode('utf-8')
path = pathlib.Path('flowchart-vizeo-detailed.pdf')
path.write_bytes(pdf_content)
print(f'Written {path}')
