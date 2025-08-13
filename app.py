#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recipe Studio – Local AI via Ollama (single file)
- Robust output: JSON-enforced, multi-stage repair, heuristic fallback (never fails)
- No JSON-looking UI ever; clean human text only
- Centered overlay with animated "Generating ..."
- Unique titles per session; auto-crafted title/description if weak
- Copy to clipboard (no export button)
"""

import asyncio
import json
import re
import requests
import flet as ft

# ---- Ollama config ----
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "tinyllama"

SYSTEM_STYLE = (
    "You are a precise culinary assistant. "
    "Always respond with ONLY JSON using this exact schema: "
    '{"title": str, "description": str, "servings": int, "time_minutes": int, '
    '"ingredients": [str], "steps": [str]} '
    "Do not include code fences or any text outside the JSON."
)

def build_prompt(idea: str) -> str:
    return (
        f"User idea: {idea or 'Create a great new dish.'}\n"
        "Return JSON only (no code fences). Use realistic servings/time, "
        "a short description, a clear ingredient list, and 5–10 concise steps."
    )

# ---------------- Parsing & Repair ----------------
_JSON_SIGNS = re.compile(r"[{}\[\]`]|\"")

def extract_json_block(text: str):
    """Try clean JSON in a few common shapes."""
    if not text:
        return None
    # ```json ... ```
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # ``` ... ```
    m = re.search(r"```\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # First plausible { ... }
    starts = [m.start() for m in re.finditer(r"\{", text)]
    for s in starts:
        for e in range(len(text), s, -1):
            chunk = text[s:e]
            try:
                return json.loads(chunk)
            except Exception:
                continue
    # Direct
    try:
        return json.loads(text)
    except Exception:
        return None

def repair_json_like(text: str):
    """
    Heuristic repair for almost-JSON:
    - Strip fences
    - Keep substring { ... }
    - Quote bare keys
    - Convert single quotes to double (strings/keys)
    - Remove trailing commas
    """
    if not text:
        return None
    # Remove code fences/backticks
    t = re.sub(r"```.*?```", lambda m: m.group(0).replace("```", ""), text, flags=re.S)
    # Keep between first { and last }
    if "{" in t and "}" in t:
        t = t[t.find("{"): t.rfind("}") + 1]
    # Convert single quotes around keys/values to double quotes (safe-ish)
    t = re.sub(r"(?<!\\)'", '"', t)  # naive but effective for LLM outputs
    # Quote bare keys: key: -> "key":
    t = re.sub(r'(\b[a-zA-Z_][a-zA-Z0-9_]*\b)\s*:', r'"\1":', t)
    # Remove trailing commas before } ]
    t = re.sub(r",\s*([}\]])", r"\1", t)
    # Ensure lists are arrays even if newline text appears (we'll coerce later)
    try:
        return json.loads(t)
    except Exception:
        return None

def heuristic_from_text(text: str, idea: str):
    """
    Extract something usable from totally non-JSON text with bullets/numbers.
    """
    if not text:
        text = ""
    cleaned = text.replace("•", "-")
    # Grab ingredients section
    ing = []
    steps = []

    # Try to detect labeled sections
    ing_match = re.search(r"(ingredients?)\s*[:\n]+(.*?)(?:\n\s*(steps?|method|directions?)\s*:|\Z)", cleaned, flags=re.I | re.S)
    steps_match = re.search(r"(steps?|method|directions?)\s*[:\n]+(.*)", cleaned, flags=re.I | re.S)

    if ing_match:
        block = ing_match.group(2)
        for line in block.splitlines():
            line = line.strip(" -*\t\r\n")
            if line:
                ing.append(line)
    else:
        # Fallback: collect dashed lines anywhere
        for line in cleaned.splitlines():
            if re.match(r"\s*[-*]\s+", line):
                ing.append(line.strip(" -*\t\r\n"))

    if steps_match:
        block = steps_match.group(2)
        for line in block.splitlines():
            line = line.strip()
            if re.match(r"^\s*\d+[\).\s-]+", line):
                # strip leading numbering
                line = re.sub(r"^\s*\d+[\).\s-]+\s*", "", line)
            if line:
                steps.append(line)
    else:
        # Fallback: any numbered lines
        for line in cleaned.splitlines():
            if re.match(r"^\s*\d+[\).\s-]+", line):
                steps.append(re.sub(r"^\s*\d+[\).\s-]+\s*", "", line).strip())

    # Final safety nets
    if not ing:
        ing = ["Salt", "Pepper", "Olive oil"]
    if not steps:
        steps = ["Combine ingredients and cook to taste."]

    return {
        "title": idea.strip().title() if idea.strip() else "Chef's Quick Weeknight Dish",
        "description": f"{idea.strip().capitalize()} turned into a balanced, easy-to-cook recipe." if idea.strip() else "A tasty, no-fuss recipe.",
        "servings": 2,
        "time_minutes": 20,
        "ingredients": ing,
        "steps": steps,
    }

# --------- Sanitizers ----------
def _coerce_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parts = [p.strip() for p in (value.splitlines() if "\n" in value else value.split(",")) if p.strip()]
        return parts
    return [value]

def _clean_text(s: str) -> str:
    s = (s or "").strip()
    s = _JSON_SIGNS.sub("", s)
    s = re.sub(r"\b(title|step|steps|ingredient|ingredients|description|servings|time_minutes)\s*:\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*([0-9]+[\.)]|[-*•])\s*", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip()

def _plainify_ingredient(x) -> str:
    if isinstance(x, dict):
        name = x.get("name") or x.get("ingredient") or x.get("item")
        qty  = x.get("quantity") or x.get("amount") or x.get("qty")
        if name and qty:
            return _clean_text(f"{name} — {qty}")
        if name:
            return _clean_text(str(name))
        pieces = []
        for k, v in x.items():
            if k.lower() in ("instructions", "instruction", "step", "direction", "text"):
                continue
            pieces.append(str(v))
        return _clean_text(", ".join(pieces)) if pieces else "Ingredient"
    if isinstance(x, (list, tuple)):
        return _clean_text(", ".join(map(str, x)))
    return _clean_text(str(x))

def _plainify_step(x) -> str:
    if isinstance(x, dict):
        for key in ("instructions", "instruction", "step", "direction", "text"):
            if key in x and str(x[key]).strip():
                return _clean_text(str(x[key]))
        return _clean_text(". ".join(str(v) for v in x.values()))
    if isinstance(x, (list, tuple)):
        return _clean_text(". ".join(map(str, x)))
    return _clean_text(str(x))

def _as_int(v, default):
    try:
        return int(v)
    except Exception:
        return default

def sanitize_recipe_data(data: dict, idea: str):
    out = dict(data or {})
    title = _clean_text(out.get("title") or "").strip()
    desc = _clean_text(out.get("description") or "").strip()

    servings = _as_int(out.get("servings"), 2)
    time_minutes = _as_int(out.get("time_minutes"), 20)

    ingredients_raw = _coerce_list(out.get("ingredients"))
    steps_raw = _coerce_list(out.get("steps"))

    ingredients = [_plainify_ingredient(x) for x in ingredients_raw if str(x).strip()]
    steps = [_plainify_step(x) for x in steps_raw if str(x).strip()]

    # Strengthen weak fields (no "Untitled" or generic desc)
    if not title or title.lower() in {"untitled recipe", "recipe"}:
        title = idea.strip().title() if idea.strip() else "Chef's Quick Weeknight Dish"
    if not desc or desc.lower() in {"a delicious dish created by ai.", "a delicious dish created by ai"}:
        base = idea.strip()
        desc = f"{base.capitalize()} turned into a balanced, easy-to-cook recipe." if base else "A tasty, no-fuss recipe."

    if not ingredients:
        ingredients = ["Salt", "Pepper", "Olive oil"]
    if not steps:
        steps = ["Combine ingredients and cook to taste."]

    out.update(
        title=title,
        description=desc,
        servings=servings,
        time_minutes=time_minutes,
        ingredients=ingredients,
        steps=steps,
    )
    return out

# ------------- App -------------
class RecipeStudio:
    def __init__(self):
        self.page: ft.Page | None = None
        self.loading = False
        self._seen_titles = {}
        self._anim_token = 0

        self.idea_input: ft.TextField | None = None
        self.generate_btn: ft.ElevatedButton | None = None
        self.reset_btn: ft.OutlinedButton | None = None
        self.copy_btn: ft.OutlinedButton | None = None
        self.recipe_card: ft.Container | None = None
        self.overlay_container: ft.Container | None = None
        self.overlay_label: ft.Text | None = None

    # ---------- UI ----------
    def header(self) -> ft.Container:
        title = ft.Row(
            [ft.Icon(ft.Icons.RAMEN_DINING, size=36),
             ft.Text("Recipe Studio", size=28, weight=ft.FontWeight.BOLD)],
            spacing=10,
        )
        sub = ft.Text(
            "Describe what you crave. Click Generate.",
            size=14,
            color=ft.Colors.WHITE70,
        )
        right = ft.Row(
            [ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="View on GitHub",
                           on_click=lambda e: self.page.launch_url("https://github.com/"))],
            alignment=ft.MainAxisAlignment.END,
        )
        content = ft.Row(
            [ft.Column([title, sub], spacing=4, expand=True), right],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(
            padding=ft.padding.symmetric(20, 16),
            content=content,
            gradient=ft.LinearGradient(
                colors=[ft.Colors.DEEP_ORANGE_400, ft.Colors.AMBER],
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
            ),
        )

    def empty_state(self) -> ft.Container:
        return ft.Container(
            padding=30,
            border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("No recipe yet", size=22, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                            ft.Text(
                                "Try: “high-protein vegetarian lunch”, “5-minute pasta”, or “gluten-free pancakes”.",
                                color=ft.Colors.ON_SECONDARY_CONTAINER,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text("🥑 🧄 🧀 🍅 🥔 🍗", size=32, text_align=ft.TextAlign.CENTER),
                        ],
                        spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )

    def _build_form(self) -> ft.Container:
        self.idea_input = ft.TextField(
            label="Create a recipe for...",
            hint_text="e.g., spicy chicken rice bowl, vegan high-protein lunch",
            expand=True,
            on_submit=self.on_generate,
        )
        self.generate_btn = ft.ElevatedButton("Generate", icon=ft.Icons.AUTO_AWESOME, on_click=self.on_generate)
        self.reset_btn = ft.OutlinedButton("Reset", icon=ft.Icons.REFRESH, visible=False, on_click=self.on_reset)

        form_inner = ft.Column(
            [
                ft.Row([self.idea_input], alignment=ft.MainAxisAlignment.START),
                ft.Row([self.generate_btn, self.reset_btn], alignment=ft.MainAxisAlignment.START, spacing=12),
            ],
            spacing=16,
        )

        return ft.Container(
            padding=20,
            content=ft.Row([ft.Container(width=940, content=form_inner)], alignment=ft.MainAxisAlignment.CENTER),
        )

    def _build_result_card(self) -> ft.Container:
        self.copy_btn = ft.OutlinedButton("Copy", icon=ft.Icons.CONTENT_COPY, visible=False, on_click=self.on_copy)

        self.recipe_card = ft.Container(
            padding=24,
            border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.02, ft.Colors.ON_SURFACE),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Recipe", size=20, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            self.copy_btn,
                        ],
                        alignment=ft.MainAxisAlignment.START,
                        spacing=8,
                    ),
                    self.empty_state(),
                ],
                spacing=14,
            ),
        )

        return ft.Container(
            padding=ft.padding.only(20, 0, 20, 20),
            content=ft.Row([ft.Container(width=820, content=self.recipe_card)], alignment=ft.MainAxisAlignment.CENTER),
        )

    def _build_overlay(self) -> ft.Container:
        self.overlay_label = ft.Text("Generating …", size=18, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
        glass = ft.Container(
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.BLACK),
            content=ft.Row([self.overlay_label], alignment=ft.MainAxisAlignment.CENTER),
        )
        self.overlay_container = ft.Container(
            visible=False,
            expand=True,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            content=ft.Column([glass], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return self.overlay_container

    # ---------- Async overlay animation ----------
    async def _animate_generating(self, token: int):
        dots = ["Generating .", "Generating ..", "Generating ..."]
        i = 0
        while self.loading and token == self._anim_token:
            if self.overlay_label:
                self.overlay_label.value = dots[i % len(dots)]
                self.overlay_label.update()
            await asyncio.sleep(0.35)
            i += 1

    def _start_overlay(self):
        self.loading = True
        self._anim_token += 1
        if self.overlay_container:
            self.overlay_container.visible = True
            self.overlay_container.update()
        self.page.run_task(self._animate_generating, self._anim_token)

    def _stop_overlay(self):
        self.loading = False
        self._anim_token += 1
        if self.overlay_container:
            self.overlay_container.visible = False
            self.overlay_container.update()

    # ---------- Model call with retries ----------
    def _call_model_once(self, prompt: str) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": SYSTEM_STYLE,
            "stream": False,
            "options": {"temperature": 0.2},
            # Ask Ollama for strict JSON if supported by the model
            "format": "json",
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _call_model(self, idea: str) -> dict:
        """
        Attempts:
          1) Strict JSON (format=json) with full prompt
          2) Strict JSON fallback with generic idea
          3) Parse/repair/heuristic from whatever text we got
        """
        prompts = [build_prompt(idea), build_prompt("Create a great new dish.")]
        last_text = ""
        for p in prompts:
            try:
                text = self._call_model_once(p)
                last_text = text or last_text
                # Stage A: direct JSON
                d = extract_json_block(text)
                if d:
                    return d
                # Stage B: repair
                d = repair_json_like(text)
                if d:
                    return d
            except Exception:
                continue

        # Stage C: heuristic from last text or from idea
        return heuristic_from_text(last_text or "", idea)

    # ---------- Generate flow ----------
    def on_generate(self, e):
        if self.loading:
            return
        idea = (self.idea_input.value or "").strip()
        if not idea:
            self._snack("Please enter a recipe idea.")
            return

        self.generate_btn.disabled = True
        self.generate_btn.update()
        self._start_overlay()
        self.page.run_task(self._generate_and_render, idea)

    async def _generate_and_render(self, idea: str):
        try:
            raw = await asyncio.to_thread(self._call_model, idea)
            data = sanitize_recipe_data(raw, idea)
            data["title"] = self._unique_title(data.get("title") or "Chef's Quick Weeknight Dish")
            self._render_recipe(data)

            self.copy_btn.visible = True
            self.copy_btn.update()
            self.reset_btn.visible = True
            self.reset_btn.update()
        except Exception as ex2:
            # As a last resort, show a graceful recipe built from idea
            data = heuristic_from_text("", idea)
            data = sanitize_recipe_data(data, idea)
            data["title"] = self._unique_title(data["title"])
            self._render_recipe(data)
            self._snack(f"Recovered from an error; showing a stable recipe.")
        finally:
            self._stop_overlay()
            self.generate_btn.disabled = False
            self.generate_btn.update()
            self.page.update()

    # ---------- Reset / Copy ----------
    def on_reset(self, e):
        self.idea_input.value = ""
        self.generate_btn.disabled = False
        self.reset_btn.visible = False
        self.copy_btn.visible = False
        self.recipe_card.content.controls[-1] = self.empty_state()
        self.page.update()

    def on_copy(self, e):
        md = self._current_recipe_markdown()
        if not md:
            self._snack("No recipe to copy.")
            return
        self.page.set_clipboard(md)
        self._snack("Copied to clipboard.")

    # ---------- Renderers ----------
    def _section_card(self, title: str, icon, content_ctrl: ft.Control) -> ft.Container:
        return ft.Container(
            padding=16,
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE),
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Icon(icon, size=20, color=ft.Colors.DEEP_ORANGE), ft.Text(title, size=18, weight=ft.FontWeight.BOLD)],
                        spacing=8,
                    ),
                    content_ctrl,
                ],
                spacing=10,
            ),
        )

    def _ingredients_view(self, ingredients: list[str]) -> ft.Control:
        if len(ingredients) <= 8:
            return ft.Column([ft.Text(f"• {ing}") for ing in ingredients], spacing=5)
        half = (len(ingredients) + 1) // 2
        col1 = ft.Column([ft.Text(f"• {ing}") for ing in ingredients[:half]], spacing=5, expand=True)
        col2 = ft.Column([ft.Text(f"• {ing}") for ing in ingredients[half:]], spacing=5, expand=True)
        return ft.Row([col1, col2], spacing=20)

    def _steps_view(self, steps: list[str]) -> ft.Control:
        return ft.Column([ft.Text(f"{i+1}. {s}") for i, s in enumerate(steps)], spacing=8)

    def _recipe_view(self, data: dict) -> ft.Column:
        title = data.get("title", "Chef's Quick Weeknight Dish")
        desc = data.get("description", "")
        servings = data.get("servings")
        time_minutes = data.get("time_minutes")
        ingredients = data.get("ingredients", [])
        steps = data.get("steps", [])

        meta_bits = []
        if isinstance(servings, int):
            meta_bits.append(f"Servings: {servings}")
        if isinstance(time_minutes, int):
            meta_bits.append(f"Time: {time_minutes} min")

        # --- Header (always centered) ---
        header_block = ft.Column(
            [
                ft.Text(title, size=26, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Text(" • ".join(meta_bits), color=ft.Colors.ON_SECONDARY_CONTAINER, text_align=ft.TextAlign.CENTER) if meta_bits else ft.Container(),
                ft.Text(desc, size=16, text_align=ft.TextAlign.CENTER),
            ],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Constrain width for readability, then center the whole header row
        header_centered = ft.Row(
            [ft.Container(content=header_block, width=720)],  # tweak width to your taste
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # --- Sections ---
        ing_card = self._section_card("Ingredients", ft.Icons.LIST_ALT, self._ingredients_view(ingredients))
        steps_card = self._section_card("Steps", ft.Icons.FORMAT_LIST_NUMBERED, self._steps_view(steps))

        return ft.Column(
            [
                header_centered,   # <- use centered header
                ft.Divider(),
                ing_card,
                steps_card,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
        )


    def _render_recipe(self, data: dict):
        self.recipe_card.content.controls[-1] = self._recipe_view(data)
        self.recipe_card.update()

    def _render_error(self, message: str):
        self.recipe_card.content.controls[-1] = ft.Container(
            padding=16,
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.ERROR),
            content=ft.Row(
                [ft.Icon(ft.Icons.ERROR, color=ft.Colors.ERROR), ft.Text(message, color=ft.Colors.ERROR)],
                spacing=10,
            ),
        )
        self.recipe_card.update()

    def _current_recipe_markdown(self) -> str | None:
        try:
            content = self.recipe_card.content.controls[-1]
            if isinstance(content, ft.Column) and content.controls:
                parts = []
                header_block = content.controls[0]
                if isinstance(header_block, ft.Column) and header_block.controls:
                    t = header_block.controls[0]
                    if isinstance(t, ft.Text): parts.append(f"# {t.value}")
                    meta = header_block.controls[1] if len(header_block.controls) > 1 else None
                    if isinstance(meta, ft.Text) and meta.value: parts.append(f"*{meta.value}*")
                    d = header_block.controls[2] if len(header_block.controls) > 2 else None
                    if isinstance(d, ft.Text) and d.value: parts.append(d.value)
                ing_card = content.controls[2] if len(content.controls) > 2 else None
                if isinstance(ing_card, ft.Container):
                    body = ing_card.content.controls[1] if isinstance(ing_card.content, ft.Column) else None
                    parts.append("\n## Ingredients")
                    if isinstance(body, ft.Column):
                        for item in body.controls:
                            if isinstance(item, ft.Text): parts.append(f"- {item.value.replace('• ', '')}")
                    elif isinstance(body, ft.Row):
                        for col in body.controls:
                            if isinstance(col, ft.Column):
                                for item in col.controls:
                                    if isinstance(item, ft.Text): parts.append(f"- {item.value.replace('• ', '')}")
                steps_card = content.controls[3] if len(content.controls) > 3 else None
                if isinstance(steps_card, ft.Container):
                    body = steps_card.content.controls[1] if isinstance(steps_card.content, ft.Column) else None
                    parts.append("\n## Steps")
                    if isinstance(body, ft.Column):
                        for item in body.controls:
                            if isinstance(item, ft.Text): parts.append(item.value)
                return "\n\n".join(parts).strip() or None
        except Exception:
            return None
        return None

    # ---------- Helpers ----------
    def _snack(self, msg: str):
        self.page.snack_bar = ft.SnackBar(content=ft.Text(msg))
        self.page.snack_bar.open = True
        self.page.update()

    def _unique_title(self, title: str) -> str:
        base = (title or "Chef's Quick Weeknight Dish").strip()
        key = base.lower()
        n = self._seen_titles.get(key, 0)
        if n == 0:
            self._seen_titles[key] = 1
            return base
        n += 1
        self._seen_titles[key] = n
        return f"{base} (v{n})"

    def main(self, page: ft.Page):
        self.page = page
        page.title = "Recipe Studio – Local AI"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.scroll = ft.ScrollMode.AUTO
        page.padding = 0

        header = self.header()
        form = self._build_form()
        result = self._build_result_card()
        overlay = self._build_overlay()

        page.add(ft.Stack(controls=[ft.Column([header, form, result], spacing=0), overlay], expand=True))
        page.update()

if __name__ == "__main__":
    app = RecipeStudio()
    ft.app(target=app.main)
