# Recipe Studio — Local AI via Ollama (Flet)

A polished, single‑file desktop app that turns a short idea into a clean, human‑readable recipe — **without any JSON-looking UI**.  
Runs **locally** with [Ollama](https://ollama.com/) and is built with [Flet](https://flet.dev/).

https://github.com/  ← replace with your repo URL

---

## ✨ Features

- **Robust output pipeline (never fails)**  
  1) Enforce strict JSON from the model (`format=json`)  
  2) **Repair** almost‑JSON (quote keys, fix commas, convert quotes)  
  3) **Heuristic fallback** that extracts ingredients/steps from plain text
- **Zero-JSON UI**: ingredients & steps are rendered as friendly text only
- **Centered glass overlay** with animated “Generating …” while the model runs
- **Unique titles per session** so you never see “Untitled recipe”
- **Copy to clipboard** in Markdown (no export button)
- Clean layout: centered header (title + meta + description) and readable sections

---

## 🧱 Architecture (tiny but sturdy)

```
Flet UI  ──▶  Ollama (generate)  ──▶  JSON parse  ──▶  Sanitize  ──▶  Render
             (format=json)          (extract/repair)     (text-only)    (Flet)
```

- `extract_json_block()` — tries to load a valid `{...}` block (fences handled)
- `repair_json_like()` — fixes common LLM JSON mistakes
- `heuristic_from_text()` — builds a usable recipe from plain text (bullets/lines)
- `sanitize_recipe_data()` — converts any shapes into clean strings/lists, removes JSON-y tokens, strengthens weak title/description

---

## 🚀 Quickstart

### 1) Install Ollama and pull a model
- macOS: `brew install ollama`
- Windows/Linux: see https://ollama.com/download
- Pull a small model (or your favorite):  
  ```bash
  ollama pull tinyllama
  # optional alternates
  # ollama pull llama3.1
  # ollama pull phi3:medium
  ```
- Make sure Ollama is running (it starts a server at `http://127.0.0.1:11434`).

### 2) Set up Python env
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3) Run
```bash
python app.py   # or your filename
```
> If you put the code in another file, update the command accordingly.

---

## ⚙️ Configuration

Open the top of the file and adjust:
```python
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "tinyllama"     # switch to "llama3.1" or "phi3:medium" if you like
```
You can also tweak the overlay animation speed, section widths, and the gradient in `header()` to match your brand.

---

## 🧪 What “never fails” means here

Even if the model returns non‑JSON (or oddly formatted JSON), the app:
1. Attempts strict JSON parse (`format=json`)  
2. Repairs common formatting issues  
3. Extracts ingredients/steps from plain text with heuristics  
4. **Always** renders human‑readable text — no raw JSON appears in the UI

Worst case: it falls back to safe defaults like “Salt, Pepper, Olive oil” and a short step, so the UI stays clean and predictable.

---

## 🖥️ Demo

Attach screen capture:

```markdown
[▶ Watch the demo](./demo.mp4)
```
---

## 🛠 Troubleshooting

- **`AttributeError: 'Icons' object has no attribute '_set_attr_internal'`**  
  Make sure you use `ft.Icon(ft.Icons.NAME, ...)` and **not** `ft.Icons(...)`.
- **Nothing happens on Generate**  
  Ensure the Ollama server is running and you pulled the model listed in `OLLAMA_MODEL`.
- **Firewall/Proxy issues**  
  `OLLAMA_URL` must be reachable from your app. Try `curl http://127.0.0.1:11434/api/tags`.

---

## 🗺️ Roadmap (ideas)
- Multi‑prompt sampling & best‑of selection
- Persistent recipe history (local JSON db)
- Light/Dark theme switch
- One‑click packaging with `flet pack`

---

## 🙌 Credits

- [Flet](https://flet.dev/) for a sweet Python-first UI
- [Ollama](https://ollama.com/) for local LLM serving
