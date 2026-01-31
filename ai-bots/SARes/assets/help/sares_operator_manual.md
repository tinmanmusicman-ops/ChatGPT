# SARes Operator Manual

This manual explains how to use SARes from a user perspective.
The in-app Help Chat answers only from this manual.

## Quick start
[tags: quickstart, start, output, import, template, summary, generate]
1. Set your Output directory.
2. Import your base resume (PDF) or (Markdown).
3. Verify section headers during PDF import (and adjust if needed).
4. Choose (or create) a Summary.
5. Paste an optional Job description.
6. Pick AI mode (N / L / H).
7. Click Generate PDFs.

## Output directory
[tags: output, folder, save, files, location]
SARes writes all generated PDFs to your configured Output directory.
Use the Browse button to change it. The app remembers your selection.

## Import base resume (PDF)
[tags: import, pdf, base, resume, headers, mapping, columns]
Use File → Import Base Resume (PDF) to bootstrap your internal base resume Markdown.
During import, SARes shows a header mapping screen:
- Confirm the section headers used in your resume.
- Reorder them to match your resume’s order.
- Optionally force bullet formatting for sections like Core Skills.

If your PDF is multi-column, choose the layout mode that matches the document.

## Import base resume (Markdown)
[tags: import, markdown, md, base, resume]
Use File → Import Base Resume (Markdown) if you already have a resume in Markdown.
SARes stores the imported Markdown as an internal base template.

## PDF header presets
[tags: preset, presets, headers, mapping, save, load]
The header mapping window supports Presets:
- Pick an existing preset to load headers (and bulletize flags).
- Edit the list (add/remove/reorder).
- Click Save Current to store your customized preset for future imports.

## Force bullets under a header
[tags: bullets, bulletize, skills, core skills, formatting]
On the header mapping screen, each header can be marked “Bullets”.
When enabled, every non-empty line under that header is imported as a Markdown bullet (`- `)
until the next `##` section header.

## Base templates
[tags: templates, base, edit, manage, multiple]
Base templates are the internal “source of truth” resumes used for generation.
Use File → Templates & Summaries… to:
- Add a new base template (via PDF or Markdown import)
- Rename templates
- Edit base templates (deterministic; no rewriting unless you type it)

## Summary presets
[tags: summary, presets, versions, edit]
Summaries are the only user-editable part of the resume in the control-tower workflow.
Use the Summary selector to switch versions.
Use New… to create a new Summary, and Save to store it.

## AI mode (N / L / H)
[tags: ai, mode, cover letter, tailoring, light, heavy, non]
SARes supports three modes:
- N: Cover letter only (no resume tailoring)
- L: Light resume keyword tailoring + cover letter
- H: Heavy resume tailoring + cover letter

Generated filenames include -N, -L, or -H so you can tell which mode produced the output.

## Cover letter generation rules
[tags: cover letter, grounded, hallucination, safety]
Cover letters are generated using a source-grounded prompt:
- No invented experience
- No added employers, skills, metrics, or claims not supported by your base resume
If generation violates constraints, SARes fails loudly.

## Troubleshooting: pandoc
[tags: pandoc, missing, error, install]
If pandoc is missing, SARes cannot render PDFs.
Install pandoc and either:
- Ensure `pandoc.exe` is on PATH, or
- Set the Pandoc path in the app.

## Troubleshooting: wkhtmltopdf
[tags: wkhtmltopdf, missing, error, install]
wkhtmltopdf is required as the PDF engine for pandoc.
If it is missing, SARes will report an error.

