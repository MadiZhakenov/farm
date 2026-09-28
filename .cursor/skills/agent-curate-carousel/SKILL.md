---
name: agent-curate-carousel
description: >-
  Agent-gated carousel pipeline for this farm repo. Use whenever generating
  carousels, harvesting Pinterest photos, running food topics, live_one_carousel,
  rerun_food_topics, or when the user wants the agent to control/curate the
  photo selection chain. Forbids blind end-to-end batch runs. Prefer local
  Ollama gates (--llm / auto-local) when the user does not want Cursor to pick.
---

# Agent-curated carousel (mandatory)

You are the controller of the pipeline. The Python stack is a tool; it must not
run unattended from text → render **unless** the user explicitly asks for
`auto-local` (Ollama gates).

## Hard rules

1. **Never** run `rerun_food_topics.py`, `run_batch` with multiple topics, or
   `live_one_carousel.py` for unsupervised full builds when this skill applies.
2. **Only** drive `python agent_gate.py …` one stage at a time (or `auto-local`).
3. After every `AGENT GATE` message: **stop**, inspect artifacts, then decide —
   unless using `--llm` / `auto-local`.
4. If a pool is шлак (wrong vibe, stock, retail rack, wellness meal-prep,
   duplicate kitchen, off-prop): **do not** harvest the next slide. Fix query or
   `abort`.
5. **Read the actual JPG files** in the slide pool with the Read tool before any
   `pick` — unless `pick N --llm` (moondream) was requested.
6. Render only after every slide has a `pick` and `approve picks`.

## Stage order

```
new → text → [approve text] → queries → [approve queries]
  → harvest-slide 1 → [Read pool] → pick 1
  → harvest-slide 2 → … → pick N
  → approve picks → render → [Read final 1.jpg…N.jpg]
```

### Local LLM (no Cursor picks)

Requires `ollama serve` + `qwen2.5:7b` + `moondream` (`python setup_ollama.py`).

```bash
python agent_gate.py approve text --llm
python agent_gate.py approve queries --llm   # prop-locks primaries
python agent_gate.py pick 1 --llm            # moondream ranks pool
# or full:
python agent_gate.py auto-local --topic "..."
```

Deterministic controls (always on):
- forge prop-lock from `visual_scene`
- vibe soft-band (rain/glass/sky/mirror) for UGC scoring
- pre-download retail/brand/UI title blacklist

Commands (repo root):

```bash
python agent_gate.py new --topic "..."
python agent_gate.py text
python agent_gate.py approve text [--llm]
python agent_gate.py queries
python agent_gate.py approve queries [--llm]
python agent_gate.py harvest-slide 1
python agent_gate.py pick 1 --pin <pin_id>   # or --llm
# repeat per slide
python agent_gate.py approve picks
python agent_gate.py render
```

## What “шлак” means (reject)

- Organized meal-prep / wellness fridge for binge/guilt confession
- Convenience-store snack rack / retail display
- Same kitchen reused across slides
- Primary query missing the slide prop (almonds→notebook only, etc.)
- High rel + low UGC stock (tea bowl, white-bg hand) — keep DROP
- Night fridge / messy counter with ugc 0.45–0.52 and real vibe — may KEEP

## Session path

`out/agent_sessions/CURRENT` → active session dir.
`python agent_gate.py status` / `abort` as needed.
