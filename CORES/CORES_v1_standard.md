# CORES — Career Opportunity Resume Extraction Standard

## Purpose
CORES (Career Opportunity Resume Extraction Standard) is a structured, human‑readable and EI‑readable Markdown framework designed to transform traditional resumes into standardized capability profiles.

The goal of CORES is to convert career history and experience into structured signal that can be easily:
- Read by humans
- Parsed by Engineered Intelligence (EI)
- Queried by recruiters and hiring systems
- Rendered by web viewers or dashboards
- Converted into structured data (JSON, database, search index)

CORES treats the individual not as a “candidate,” but as a structured capability source.

It is designed to support a Human + EI partnership model where:
- Humans provide context, judgment, and experience
- EI provides structure, organization, and retrieval
- Systems provide portability and visibility

CORES is not a resume format.
It is a portable human capability container.

---

## Design Principles

1. Human-readable first  
CORES must remain simple to read and edit in plain text Markdown.

2. EI-friendly structure  
Anchors and labels must be consistent so EI systems can parse deterministically.

3. Zero presentation formatting  
No bold, styling, or visual markup inside core data blocks. Presentation happens in the viewer layer.

4. Deterministic anchors  
Reserved tags such as:
- COMPANY
- ROLE
- SIGNALS
- Project
- SITUATION
- WHAT I DID
must always appear in the same form.

5. Portable and system-neutral  
CORES must function across:
- Local files
- Web systems
- AI tools
- Recruiter systems
- Databases

6. Viewer-based presentation  
The CORES file is the source.
All formatting and visual presentation occurs in the viewer or rendering layer.

---

## CORES Standard Framework (v1)

```
# CORES
ID: CORE-US-2026-00000X
CORES-VERSION: 1.0
FORMAT: CORES-MD
PARSER: STANDARD

# HUMAN
Name:
Location:
WA: US
Availability:
LU:
Email:
PURL:
PPIC:

# SUMMARY

# GLOBAL
## ACHIEVEMENTS

# EXPERIENCE

## COMPANY:
### ROLE:
### SIGNALS:

### Project:
- SITUATION:
- WHAT I DID:
- TOOLS / SYSTEMS:
- RESULT:
- EVIDENCE / ARTIFACTS:
- NOTES / CAVEATS:
```

---

## Parsing Logic (Conceptual)

An EI or system reading a CORES file can reliably interpret structure using fixed anchors:

- `## COMPANY:` begins a company block  
- `### ROLE:` defines role context  
- `### SIGNALS:` contains performance indicators  
- `### Project:` begins structured project object  

Inside each project:
- `- SITUATION:` defines context  
- `- WHAT I DID:` defines actions  
- `- TOOLS / SYSTEMS:` defines environment  
- `- RESULT:` defines outcomes  
- `- EVIDENCE / ARTIFACTS:` defines proof  
- `- NOTES / CAVEATS:` defines clarifications  

This structure allows deterministic parsing without requiring JSON or database formatting.

---

## Intended Use

CORES can be used as:
- Personal master capability file
- Recruiter-shareable structured profile
- Source file for portfolio or resume rendering
- Input for AI analysis or search
- Backend data source for capability viewers
- Proof-of-concept for Human + EI structured collaboration

---

## Guiding Concept

Turning noise into signal.

CORES represents a shift from narrative resumes to structured capability intelligence,
where human experience becomes portable, queryable, and system‑readable while remaining fully human‑editable.
