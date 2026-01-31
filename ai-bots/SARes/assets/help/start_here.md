# SARes — Start Here
This guide is the on-screen onboarding for SARes.

---

## Why SARes Uses Markdown (MD), Not PDF

PDF is a **presentation format**, not a data format.

PDFs are designed to look correct to humans, not to be reliably read or modified by software. Layout, columns, spacing, fonts, and visual alignment often hide or distort structure. Two PDFs that look identical can contain very different underlying data.

Because of this, PDFs are unreliable as a source of truth.

SARes treats PDFs as an **import-only format**.

When you import a PDF, SARes extracts the content and converts it into Markdown (MD). Markdown is plain text with explicit structure. Headers are headers. Paragraphs are paragraphs. Nothing is hidden, and nothing is inferred from layout.

Markdown becomes the **canonical working format** inside SARes.

This allows SARes to:
- Behave deterministically
- Fail fast instead of guessing
- Regenerate clean PDFs repeatedly
- Let humans see and fix structure directly if needed

You do not need to know Markdown to use SARes.  
Markdown exists so SARes can work with truth instead of appearance.

Once a resume is normalized into Markdown, the original PDF is no longer needed.

---

### The Symbols You May See (and Why They Matter)

You may see simple characters like these in Markdown files used by SARes:

```md
# First section (Name)
## Subheading *exmpl: Summary....)
### Section label (exampl: Company 1,2,3 ...) 
- bullet item (bulltes)
--- section break (adds a line)
```

These define structure only.  
They tell SARes what is a section, what belongs under it, and where content starts and ends.  
They do **not** control fonts, size, or visual layout.

### What This Means for You

You do not need to write or edit these characters unless something imports incorrectly.

If you do open a Markdown file, these characters exist to make structure visible and explicit.

Fixing structure once in Markdown fixes every future PDF generated from it.

---

## 1) Set your Output folder

- In the left panel, find **Output directory**.
- Click **Browse...** and choose where PDFs should be written.
- SARes remembers this folder for next time.

## 2) Import your base resume (one-time)

Use the top menu:

- **File → Import Base Resume (PDF)...**
  - Confirm the section headers used in your resume.
  - Reorder headers to match your resume’s order.
  - Optionally force bullet formatting for sections like Core Skills.
  - Choose the correct PDF layout mode if your resume is multi-column.

Or:

- **File → Import Base Resume (Markdown)...** if you already have a `.md`.

## 3) Choose a base template

- Pick a template in **Base template** (left panel).
- Use **Manage...** to add/rename/edit templates.

## 4) Choose (or create) a Summary

- Pick a Summary version (left panel).
- Use **New...** to add a new Summary.
- Summary is required.

## 5) Paste a job description (optional)

- Paste the job description in the **Job description** box.
- This is used for cover letter alignment and (optionally) resume keyword tailoring.

## 6) Pick AI mode: N / L / H

- **Option 1 (N):** Cover letter only (no resume tailoring)
- **Option 2 (L):** Light resume keyword tailoring + cover letter
- **Option 3 (H):** Heavy resume tailoring + cover letter

Generated files include `-N`, `-L`, or `-H` in the filename.

## 7) Generate PDFs

- Click **Generate PDFs**.
- If something is missing (Summary, pandoc path), SARes will block and tell you what to fix.

---

## Need help?

Use **Help → Help Chat...** to search the operator manual from inside the app.
