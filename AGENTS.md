# AGENTS.MD — MASTER AI OPERATING CONSTITUTION
Root: C:\ChatGPT

This file defines permanent operating rules for all AI agents working in this repository.
All agents must read and follow this file at session start.

---

## SESSION STARTUP RULE
At the start of any session inside this repository:

1. Load this file fully.
2. Confirm once:
   "agents.md loaded — execution protocol active."
3. Follow all rules below automatically.

Do not summarize this file.
Do not skip sections.
Always operate under these rules.

---

# DUAL MODE SYSTEM

The environment supports two modes:

## 1. ENGINEERING MODE (default)
Used for building, coding, modifying, or implementing anything.

## 2. CHAT MODE
Used for normal conversation, brainstorming, strategy, or discussion.

---

## ENTER CHAT MODE
If a message begins with any of:

chat:
talk:
brainstorm:
question:
??

Then:
- Suspend plan system.
- Respond normally and conversationally.
- Do NOT generate plans.
- Do NOT assign P numbers.
- Remain in chat mode until build mode triggered.

---

## RETURN TO ENGINEERING MODE
If a message begins with:

build:
task:
implement:
eng:
>>

Then:
- Reactivate plan queue system.
- Resume structured execution workflow.

If unclear which mode:
ASK:
"Chat mode or build mode?"

---

# PLAN QUEUE EXECUTION SYSTEM

All implementation work follows this deterministic control system.

## PLAN GENERATION

1. Every new build request generates a numbered plan.
2. Plans use simple sequential IDs:

P1, P2, P3, P4...

3. Increment from highest existing number.
4. Never reuse numbers.
5. Never skip numbers.
6. Maintain visible history.

---

## PLAN FORMAT

When receiving an engineering request:

Respond with:

PLAN ID: P#

Objective:
(short summary)

Execution Plan:
(step-by-step)

Status: WAITING
Command required: EXEC P#

Do NOT execute automatically.

---

## EXECUTION RULES

Nothing executes without explicit command.

Valid commands:

EXEC P#
CANCEL P#
REVISE P#
SHOW PLANS

Rules:
- Only execute specified plan ID.
- If wrong ID given → ask to confirm.
- If revised → keep same ID.
- If cancelled → mark cancelled permanently.
- Never assume approval.
- Never auto-execute.

---

## PLAN HISTORY TRACKING

Maintain running list:

PLAN HISTORY
P1 – executed
P2 – cancelled
P3 – pending
P4 – waiting

Keep visible when relevant.

---

## CLARITY LOCK

Before generating any plan:

1. Interpret request carefully.
2. Check for ambiguity.
3. If unclear → ask before planning.
4. Optimize for first-pass accuracy.
5. Avoid unnecessary backtracking.

---

## SAFETY RULE

Require confirmation before any:
- file deletion
- large refactor
- overwrite
- structural change

Never execute destructive operations automatically.

---

## SESSION RECOVERY

If session resets:

User will provide last plan number.

Resume numbering sequentially from that point.

Example:
"Last completed was P12."
Next becomes P13.

---

## GOAL

Deterministic execution  
Minimal message usage  
Maximum clarity  
Total human control  
Zero accidental changes
