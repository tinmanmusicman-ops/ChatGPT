import math
from pathlib import Path

# TAM workflow quick verification touchpoint.


class SimplePDF:
    def __init__(self, filename: str):
        self.filename = filename
        self.contents: list[str] = []
        self.objects: list[str] = []
        self.next_obj_id = 1
        self.pages: list[int] = []
        self.font_obj = self._add_object(
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        )

    def _add_object(self, body: str) -> int:
        obj_id = self.next_obj_id
        self.next_obj_id += 1
        self.objects.append(f"{obj_id} 0 obj\n{body}\nendobj\n")
        return obj_id

    def _escape(self, text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def draw_rect(self, x, y, w, h, fill_color=None, stroke_color="0 0 0"):
        cmds = []
        if fill_color:
            cmds.append(f"{fill_color} rg")
        cmds.append(f"{stroke_color} RG")
        cmds.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re")
        cmds.append("B" if fill_color else "S")
        self.contents.extend(cmds)

    def draw_polygon(self, points, fill_color=None, stroke_color="0 0 0"):
        cmds = []
        if fill_color:
            cmds.append(f"{fill_color} rg")
        cmds.append(f"{stroke_color} RG")
        first = points[0]
        cmds.append(f"{first[0]:.2f} {first[1]:.2f} m")
        for x, y in points[1:]:
            cmds.append(f"{x:.2f} {y:.2f} l")
        cmds.append("h")
        cmds.append("B" if fill_color else "S")
        self.contents.extend(cmds)

    def draw_text(self, x, y, text, size=10, max_width=260):
        lines = []
        for word in text.split():
            if not lines:
                lines.append(word)
                continue
            candidate = lines[-1] + " " + word
            if len(candidate) * size * 0.5 > max_width:
                lines.append(word)
            else:
                lines[-1] = candidate
        if not lines:
            lines = [""]
        for idx, line in enumerate(lines):
            yy = y - idx * (size + 2)
            self.contents.append(
                f"BT /F1 {size} Tf {x:.2f} {yy:.2f} Td ({self._escape(line)}) Tj ET"
            )

    def draw_line(self, x1, y1, x2, y2, label=None):
        self.contents.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
        # simple arrow head
        angle = math.atan2(y2 - y1, x2 - x1)
        left = (x2 - 6 * math.cos(angle - 0.3), y2 - 6 * math.sin(angle - 0.3))
        right = (x2 - 6 * math.cos(angle + 0.3), y2 - 6 * math.sin(angle + 0.3))
        self.contents.append(
            f"{x2:.2f} {y2:.2f} m {left[0]:.2f} {left[1]:.2f} l {right[0]:.2f} {right[1]:.2f} l h f"
        )
        if label:
            lx = (x1 + x2) / 2
            ly = (y1 + y2) / 2 + 8
            self.draw_text(lx, ly, label, size=8, max_width=120)

    def start_end(self, x, y, text):
        self.draw_rect(x - 70, y - 18, 140, 36, fill_color="0.82 0.95 0.82", stroke_color="0 0.5 0")
        self.draw_text(x - 60, y + 6, text, size=9)

    def process(self, x, y, text):
        self.draw_rect(x - 90, y - 22, 180, 44, fill_color="0.91 0.94 0.99", stroke_color="0.10 0.45 0.91")
        self.draw_text(x - 80, y + 6, text, size=9)

    def decision(self, x, y, text):
        pts = [(x, y + 32), (x + 92, y), (x, y - 32), (x - 92, y)]
        self.draw_polygon(pts, fill_color="1 0.95 0.80", stroke_color="0.85 0.64 0")
        self.draw_text(x - 70, y + 10, text, size=9)

    def save_page(self):
        stream = "\n".join(self.contents)
        content_obj = self._add_object(f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream")
        page_obj = self._add_object(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_obj} 0 R /Resources << /Font << /F1 {self.font_obj} 0 R >> >> >>"
        )
        self.pages.append(page_obj)

    def finalize(self):
        pages_kids = "[" + " ".join(f"{pid} 0 R" for pid in self.pages) + "]"
        pages_obj = self._add_object(f"<< /Type /Pages /Count {len(self.pages)} /Kids {pages_kids} >>")
        catalog_obj = self._add_object(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>")

        xref_positions = []
        buffer = "%PDF-1.4\n"
        for obj in self.objects:
            xref_positions.append(len(buffer.encode("utf-8")))
            buffer += obj
        xref_start = len(buffer.encode("utf-8"))
        buffer += "xref\n0 {}\n".format(len(self.objects) + 1)
        buffer += "0000000000 65535 f \n"
        for pos in xref_positions:
            buffer += f"{pos:010d} 00000 n \n"
        buffer += f"trailer\n<< /Size {len(self.objects) + 1} /Root {catalog_obj} 0 R >>\nstartxref\n{xref_start}\n%%EOF"
        Path(self.filename).write_bytes(buffer.encode("utf-8"))


def build_flowchart(path: str) -> None:
    pdf = SimplePDF(path)
    cx = 306
    y = {
        "start": 750,
        "load_config": 690,
        "logger": 630,
        "sheet_config": 570,
        "ensure_openai": 510,
        "job_desc": 450,
        "empty_check": 390,
        "closed_check": 330,
        "worksheet": 270,
        "row_choice": 210,
        "save_jd_pdf": 150,
        "generate_docs": 90,
        "save_outputs": 30,
        "cover_review": -30,
        "pdf_gate": -90,
        "upload": -150,
        "success": -210,
        "error": 210,
        "skip": 330,
    }

    pdf.start_end(cx, y["start"], "Start / __main__ entry")
    pdf.process(cx, y["load_config"], "Load bot config from config.json")
    pdf.process(cx, y["logger"], "Configure logger")
    pdf.process(cx, y["sheet_config"], "Load sheet column mapping")
    pdf.process(cx, y["ensure_openai"], "Ensure OpenAI SDK available")
    pdf.process(cx, y["job_desc"], "Read job description from clipboard")
    pdf.decision(cx, y["empty_check"], "Job description empty?")
    pdf.decision(cx, y["closed_check"], "Closed-job indicator found?")
    pdf.process(cx, y["worksheet"], "Load service credentials; resolve worksheet context")
    pdf.process(cx, y["row_choice"], "Select spreadsheet row (marker or RESUME_SHEET_ROW)")
    pdf.process(cx, y["save_jd_pdf"], "Save job description PDF")
    pdf.process(cx, y["generate_docs"], "Generate resume and cover letter text (OpenAI)")
    pdf.process(cx, y["save_outputs"], "Save resume.txt / cover_letter.txt and resume PDF")
    pdf.decision(cx, y["cover_review"], "Cover letter saved after review?")
    pdf.decision(cx, y["pdf_gate"], "All PDFs ready? (resume, cover letter, JD)")
    pdf.process(cx, y["upload"], "Upload PDFs to Drive; write links to sheet; clear marker")
    pdf.start_end(cx, y["success"], "Success / return 0")
    pdf.start_end(cx - 170, y["error"], "Error exit / return 1")
    pdf.start_end(cx + 170, y["skip"], "Job closed – skip")

    pdf.draw_line(cx, y["start"] - 18, cx, y["load_config"] + 22)
    pdf.draw_line(cx, y["load_config"] - 22, cx, y["logger"] + 22)
    pdf.draw_line(cx, y["logger"] - 22, cx, y["sheet_config"] + 22)
    pdf.draw_line(cx, y["sheet_config"] - 22, cx, y["ensure_openai"] + 22)
    pdf.draw_line(cx, y["ensure_openai"] - 22, cx, y["job_desc"] + 22)
    pdf.draw_line(cx, y["job_desc"] - 22, cx, y["empty_check"] + 32)

    pdf.draw_line(cx, y["empty_check"] - 32, cx, y["closed_check"] + 32, label="No")
    pdf.draw_line(cx - 92, y["empty_check"], cx - 170, y["error"] + 18, label="Yes")

    pdf.draw_line(cx, y["closed_check"] - 32, cx, y["worksheet"] + 22, label="No")
    pdf.draw_line(cx + 92, y["closed_check"], cx + 170, y["skip"] + 18, label="Yes")

    pdf.draw_line(cx, y["worksheet"] - 22, cx, y["row_choice"] + 22)
    pdf.draw_line(cx, y["row_choice"] - 22, cx, y["save_jd_pdf"] + 22)
    pdf.draw_line(cx, y["save_jd_pdf"] - 22, cx, y["generate_docs"] + 22)
    pdf.draw_line(cx, y["generate_docs"] - 22, cx, y["save_outputs"] + 22)
    pdf.draw_line(cx, y["save_outputs"] - 22, cx, y["cover_review"] + 32)

    pdf.draw_line(cx, y["cover_review"] - 32, cx, y["pdf_gate"] + 32, label="Yes")
    pdf.draw_line(cx - 92, y["cover_review"], cx - 30, y["pdf_gate"] + 32, label="No")

    pdf.draw_line(cx, y["pdf_gate"] - 32, cx, y["upload"] + 22, label="Yes")
    pdf.draw_line(cx + 92, y["pdf_gate"], cx + 30, y["success"] + 22, label="No")

    pdf.draw_line(cx, y["upload"] - 22, cx, y["success"] + 22)

    pdf.save_page()
    pdf.finalize()


if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent / "resume_py_flowchart.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    build_flowchart(str(out_path))
