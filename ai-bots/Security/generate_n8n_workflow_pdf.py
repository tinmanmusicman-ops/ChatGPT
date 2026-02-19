#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib import patches
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parent
WORKFLOW_JSON = ROOT / "n8n_security_gmail_to_sheet_exact.json"
OUTPUT_PDF = ROOT / "n8n_security_workflow_flowchart_and_tasks.pdf"
FLOW_IMAGE = ROOT / "_n8n_security_flowchart.png"


NODE_PURPOSES = {
    "Manual Trigger": "Manual test entry point. Starts one polling run on demand from the n8n editor.",
    "Schedule Trigger": "Automated polling entry point. Triggers every 5 minutes.",
    "Code - Load Config": (
        "Builds runtime config, search query, and one run-level timestamp. "
        "Defines spreadsheet id/tab, subject filter, unread mode, max per run, mark-read flags, timezone."
    ),
    "HTTP - Sheets Read Header": (
        "Calls Google Sheets API batchGet for A1:B1 to detect whether required header exists."
    ),
    "Code - Evaluate Header": (
        "Checks header values and sets headerMissing flag. Preserves config and run timestamp."
    ),
    "IF - Header Missing": "Branches: true path writes header row, false path continues directly.",
    "HTTP - Sheets Append Header": (
        "Calls Google Sheets API append to write ['Timestamp', 'Message Text'] to A1:B1 when missing."
    ),
    "Code - Rehydrate Config": "Restores config and run timestamp after branch merge.",
    "HTTP - Gmail List Messages": (
        "Calls Gmail API list endpoint with query and maxResults to fetch candidate messages."
    ),
    "Code - Expand Message IDs": (
        "Converts Gmail list response into one item per message id/thread id and enforces max_per_run."
    ),
    "HTTP - Gmail Get Message": (
        "Calls Gmail API get message endpoint with format=full for each message id."
    ),
    "Code - Clean and Filter SC": (
        "Extracts body (plain first, html fallback, subject fallback), applies text cleaning and "
        "boilerplate removal, enforces SC marker rule, strips SC marker, normalizes whitespace, "
        "and sets mark-read target."
    ),
    "IF - Keep SC Messages": "Branches: true path appends row to sheet, false path drops non-matching message.",
    "HTTP - Sheets Append Row": (
        "Calls Google Sheets API append to write [timestamp, message_text] for each kept message."
    ),
    "IF - Mark As Read Needed": (
        "Branches on whether mark_target_id is set from config flags mark_read/mark_read_thread."
    ),
    "HTTP - Gmail Mark Read": (
        "Calls Gmail modify endpoint and removes UNREAD label for message or thread target."
    ),
}


def load_workflow() -> dict[str, Any]:
    if not WORKFLOW_JSON.exists():
        raise FileNotFoundError(f"Missing workflow json: {WORKFLOW_JSON}")
    return json.loads(WORKFLOW_JSON.read_text(encoding="utf-8"))


def edge_list(connections: dict[str, Any]) -> list[tuple[str, str, int]]:
    edges: list[tuple[str, str, int]] = []
    for source, conn in connections.items():
        for branch_index, branch in enumerate(conn.get("main", [])):
            for link in branch:
                edges.append((source, link["node"], branch_index))
    return edges


def summarize_http_resources(node: dict[str, Any]) -> str:
    p = node.get("parameters", {})
    method = str(p.get("method", "")).strip()
    url = str(p.get("url", "")).strip()
    auth = str(p.get("genericAuthType", "") or p.get("authentication", "")).strip()
    timeout = p.get("options", {}).get("timeout")
    pieces = []
    if method:
        pieces.append(f"method={method}")
    if url:
        pieces.append(f"url={url}")
    if auth:
        pieces.append(f"auth={auth}")
    if timeout:
        pieces.append(f"timeout_ms={timeout}")
    return "; ".join(pieces) if pieces else "n/a"


def summarize_parameters(node: dict[str, Any]) -> str:
    name = node["name"]
    p = node.get("parameters", {})
    if node["type"] == "n8n-nodes-base.scheduleTrigger":
        return "interval: every 5 minutes"
    if node["type"] == "n8n-nodes-base.if":
        conditions = p.get("conditions", {}).get("conditions", [])
        return f"conditions={len(conditions)}"
    if node["type"] == "n8n-nodes-base.code":
        js = str(p.get("jsCode", ""))
        return f"js_lines={len(js.splitlines())}"
    if node["type"] == "n8n-nodes-base.httpRequest":
        q = p.get("queryParameters", {}).get("parameters", [])
        return f"query_params={len(q)}; body_mode={p.get('specifyBody', 'none')}"
    return f"node={name}"


def generate_flowchart_image(workflow: dict[str, Any]) -> None:
    nodes = workflow["nodes"]
    node_map = {n["name"]: n for n in nodes}
    edges = edge_list(workflow["connections"])

    xs = [n["position"][0] for n in nodes]
    ys = [n["position"][1] for n in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(1, max_x - min_x)
    span_y = max(1, max_y - min_y)

    def to_plot(pos: list[int]) -> tuple[float, float]:
        x = (pos[0] - min_x) / span_x
        y = 1.0 - ((pos[1] - min_y) / span_y)
        return x, y

    fig = plt.figure(figsize=(16, 9), dpi=150)
    ax = fig.add_subplot(111)
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.axis("off")
    ax.set_title("n8n Security Gmail to Sheets Poller - Flowchart", fontsize=16, pad=14)

    for src, dst, branch in edges:
        sp = to_plot(node_map[src]["position"])
        dp = to_plot(node_map[dst]["position"])
        color = "#1f77b4" if branch == 0 else "#d62728"
        ax.annotate(
            "",
            xy=(dp[0], dp[1]),
            xytext=(sp[0], sp[1]),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.4, alpha=0.8),
            zorder=1,
        )

    for n in nodes:
        x, y = to_plot(n["position"])
        w, h = 0.10, 0.06
        fill = "#f4f8ff"
        if n["type"].endswith("if"):
            fill = "#fff4e5"
        elif "trigger" in n["type"].lower():
            fill = "#e8ffe8"
        elif "httpRequest" in n["type"]:
            fill = "#e8f7ff"
        elif "code" in n["type"]:
            fill = "#f6f1ff"
        rect = patches.FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0.006,rounding_size=0.008",
            linewidth=1.0,
            edgecolor="#333333",
            facecolor=fill,
            zorder=2,
        )
        ax.add_patch(rect)
        ax.text(
            x,
            y,
            n["name"],
            ha="center",
            va="center",
            fontsize=7,
            zorder=3,
            wrap=True,
        )

    plt.tight_layout()
    fig.savefig(FLOW_IMAGE, bbox_inches="tight")
    plt.close(fig)


def build_pdf(workflow: dict[str, Any]) -> None:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleSmall",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
    )
    mono = ParagraphStyle(
        "Mono",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=8,
        leading=10,
    )

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.45 * inch,
        title="n8n Security Workflow Flowchart and Task Details",
    )

    flow: list[Any] = []
    flow.append(Paragraph("n8n Workflow Report: Security Gmail to Sheets Poller", title_style))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(f"Workflow name: {workflow.get('name', 'n/a')}", body))
    flow.append(Paragraph(f"Source JSON: {WORKFLOW_JSON}", mono))
    flow.append(Paragraph(f"Generated PDF: {OUTPUT_PDF}", mono))
    flow.append(Spacer(1, 8))

    nodes = workflow.get("nodes", [])
    conns = workflow.get("connections", {})
    edges = edge_list(conns)
    flow.append(
        Paragraph(
            f"Summary: {len(nodes)} tasks/nodes, {len(edges)} connections, executionOrder={workflow.get('settings', {}).get('executionOrder', 'n/a')}",
            body,
        )
    )
    flow.append(Spacer(1, 10))

    flow.append(Paragraph("Flowchart", h2))
    flow.append(Spacer(1, 4))
    flow.append(Image(str(FLOW_IMAGE), width=7.6 * inch, height=4.25 * inch))
    flow.append(Spacer(1, 10))

    flow.append(Paragraph("External Resource Inventory", h2))
    inv_rows = [
        ["Resource", "Used By", "Purpose"],
        [
            "Gmail API",
            "HTTP - Gmail List Messages; HTTP - Gmail Get Message; HTTP - Gmail Mark Read",
            "List unread/filtered messages, fetch full message payload, remove UNREAD label",
        ],
        [
            "Google Sheets API",
            "HTTP - Sheets Read Header; HTTP - Sheets Append Header; HTTP - Sheets Append Row",
            "Read header A1:B1, add header if missing, append rows with timestamp and cleaned message text",
        ],
        [
            "n8n OAuth2 credentials",
            "All HTTP - Gmail/Sheets nodes",
            "Authentication for Google APIs",
        ],
        [
            "n8n runtime JS engine",
            "Code nodes",
            "Config building, branching preparation, text extraction/cleanup, SC marker logic",
        ],
    ]
    table = Table(inv_rows, colWidths=[1.35 * inch, 2.7 * inch, 3.35 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde7f7")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 10))

    flow.append(Paragraph("Task-by-Task Details", h2))
    flow.append(Spacer(1, 4))

    node_map = {n["name"]: n for n in nodes}
    incoming: dict[str, list[str]] = {n["name"]: [] for n in nodes}
    outgoing: dict[str, list[str]] = {n["name"]: [] for n in nodes}
    for src, dst, branch in edges:
        incoming.setdefault(dst, []).append(f"{src} [branch={branch}]")
        outgoing.setdefault(src, []).append(f"{dst} [branch={branch}]")

    ordered = sorted(nodes, key=lambda n: n["position"][0])
    for n in ordered:
        name = n["name"]
        flow.append(Paragraph(f"{name}", ParagraphStyle("NodeName", parent=h2, fontSize=11)))
        flow.append(Paragraph(f"Type: {n.get('type', 'n/a')} v{n.get('typeVersion', 'n/a')}", body))
        flow.append(Paragraph(f"Purpose: {NODE_PURPOSES.get(name, 'No custom description provided.')}", body))
        flow.append(Paragraph(f"Key Parameters: {summarize_parameters(n)}", body))
        if n.get("type") == "n8n-nodes-base.httpRequest":
            flow.append(Paragraph(f"HTTP Resource Use: {summarize_http_resources(n)}", body))
        else:
            flow.append(Paragraph("HTTP Resource Use: n/a", body))
        flow.append(
            Paragraph(
                f"Inbound: {', '.join(incoming.get(name, [])) if incoming.get(name) else 'none'}",
                body,
            )
        )
        flow.append(
            Paragraph(
                f"Outbound: {', '.join(outgoing.get(name, [])) if outgoing.get(name) else 'none'}",
                body,
            )
        )
        flow.append(Spacer(1, 6))

    doc.build(flow)


def main() -> None:
    workflow = load_workflow()
    generate_flowchart_image(workflow)
    build_pdf(workflow)
    print(str(OUTPUT_PDF))


if __name__ == "__main__":
    main()
