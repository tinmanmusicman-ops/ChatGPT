from __future__ import annotations

import json
from pathlib import Path


ASSETS_DIR = Path(__file__).parent


def lines_for_contact(contact: dict[str, str]) -> list[str]:
    lines: list[str] = []
    location = contact.get("location", "").strip()
    if location:
        lines.append(location)
    email = contact.get("email", "").strip()
    phone = contact.get("phone", "").strip()
    if email or phone:
        pair = " | ".join(part for part in (email, phone) if part)
        lines.append(pair)
    linkedin = contact.get("linkedin", "").strip()
    if linkedin:
        lines.append(linkedin)
    return lines


def format_education(education: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for entry in education:
        degree = entry.get("degree", "").strip()
        school = entry.get("school", "").strip()
        location = entry.get("location", "").strip()
        if degree or school or location:
            parts = []
            if degree:
                parts.append(degree)
            if school:
                parts.append(school)
            if location:
                parts.append(location)
            lines.append("- " + " – ".join(parts))
    return lines


def render_resume(data: dict[str, object]) -> str:
    md_lines: list[str] = []
    md_lines.append("<!-- render: nameAfter=2 contactLeading=11 contactAfter=1 -->")
    md_lines.append(f"# {data.get('name', '').strip()}")
    contact = data.get("contact", {})
    if isinstance(contact, dict):
        md_lines.extend(lines_for_contact(contact))
    md_lines.append("---")
    title = data.get("title", "").strip()
    if title:
        md_lines.append(f"## {title}")
    summary = data.get("summary", "").strip()
    if summary:
        md_lines.append(summary)
    skills = data.get("skills", [])
    if isinstance(skills, list) and skills:
        md_lines.append("## Core Skills")
        for skill in skills:
            skill_text = str(skill).strip()
            if skill_text:
                md_lines.append(f"- {skill_text}")
    achievements = data.get("achievements_2024_2025", [])
    if isinstance(achievements, list) and achievements:
        md_lines.append("## Achievements (2024-2025)")
        for achievement in achievements:
            text = str(achievement).strip()
            if text:
                md_lines.append(f"- {text}")
    experience = data.get("experience", [])
    if isinstance(experience, list) and experience:
        md_lines.append("## Professional Experience")
        md_lines.append("---")
        for entry in experience:
            if not isinstance(entry, dict):
                continue
            company = entry.get("company", "").strip()
            title = entry.get("title", "").strip()
            location = entry.get("location", "").strip()
            start = entry.get("start", "").strip()
            end = entry.get("end", "").strip()
            header_parts: list[str] = []
            if company:
                header_parts.append(company)
            if title:
                header_parts.append(f"- {title}")
            header_line = " ".join(header_parts).strip()
            if header_line:
                md_lines.append(f"### {header_line}")
            if location:
                md_lines.append(location)
            if start or end:
                range_text = " - ".join(part for part in (start, end) if part)
                md_lines.append(f"*{range_text}*")
            highlights = entry.get("highlights", [])
            for highlight in highlights or []:
                text = str(highlight).strip()
                if text:
                    md_lines.append(f"- {text}")
    education = data.get("education", [])
    education_lines = format_education(education) if isinstance(education, list) else []
    if education_lines:
        md_lines.append("## Education")
        md_lines.extend(education_lines)
    certifications = data.get("certifications", [])
    if isinstance(certifications, list) and certifications:
        md_lines.append("## Certifications")
        for certification in certifications:
            text = str(certification).strip()
            if text:
                md_lines.append(f"- {text}")
    return "\n".join(line for line in md_lines if line is not None)


def main() -> None:
    json_paths = sorted(ASSETS_DIR.glob("base_resume*.json"))
    for json_path in json_paths:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        number = json_path.stem.replace("base_resume", "")
        if not number:
            continue
        md_path = ASSETS_DIR / f"resume{number}.md"
        md_path.write_text(render_resume(data), encoding="utf-8")


if __name__ == "__main__":
    main()
