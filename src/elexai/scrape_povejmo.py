"""Headful UI automation for the povejmo.si chat (companion to the manual kit).

Drives a VISIBLE browser like a human would: selects a model from the
dropdown, opens a fresh conversation per prompt, pastes the prompt text from
``manual_kit/prompts/<qid>__<variant>.txt``, waits for the reply to finish and
writes the reply into the answers CSV - the exact format produced by manual
filling, so ``scripts/import_manual_answers.py`` works unchanged.

Safety rules baked in (see also scripts/scrape_povejmo.py):

- the ONLY file ever modified is the answers CSV passed on the command line;
  it is written atomically (temp file + replace) and a one-time ``*.csv.bak``
  copy is created before the first change; existing backups are never touched;
- nothing is ever deleted anywhere; debug artifacts (screenshots, HTML dumps,
  an append-only JSONL log) go to a separate debug folder;
- prompts are only read; sequential requests with a human-paced delay; the
  batch stops after three consecutive failures; already-answered rows are
  skipped, so runs are resumable;
- the script is intended for modest research use of a public chat UI - it does
  not touch undocumented API endpoints.
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_URL = "https://povejmo.si"
REQUIRED_COLUMNS = ("question_id", "variant", "answer_raw")


# ---------------------------------------------------------------------------
# pure helpers (tested without a browser)
# ---------------------------------------------------------------------------


def load_answers(path: Path) -> tuple[list[dict], list[str]]:
    """Read the answers CSV (tolerates a UTF-8 BOM from Excel)."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise SystemExit(f"{path}: missing columns {missing}; expected {REQUIRED_COLUMNS}")
    return rows, fieldnames


def save_answers(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """Atomic write of the CSV; creates a one-time .bak copy first."""
    path = Path(path)
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)  # never overwrite an existing backup
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    os.replace(tmp, path)


def next_unanswered_index(rows: list[dict]) -> int | None:
    for i, row in enumerate(rows):
        if not (row.get("answer_raw") or "").strip():
            return i
    return None


def clean_reply(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_PLACEHOLDER_RE = re.compile(r"^[\s.…]*razmi[šs]ljam[\s.…]*$", re.IGNORECASE)
_ANSWER_FORMAT_RE = re.compile(r"SENSE_ID|ODGOVOR", re.IGNORECASE)


def is_placeholder(text: str) -> bool:
    """True for the UI's 'thinking' bubble (e.g. 'Razmišljam...').

    The RAG model shows this while it works; it can stay unchanged for many
    seconds, so it must never be mistaken for a finished answer.
    """
    return bool(_PLACEHOLDER_RE.match((text or "").strip()))


def looks_like_answer(text: str) -> bool:
    """True when the text carries the required SENSE_ID/ODGOVOR format."""
    return bool(_ANSWER_FORMAT_RE.search(text or ""))


def append_log(debug_dir: Path, record: dict) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(UTC).isoformat(), **record}
    with (debug_dir / "scrape_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# browser session
# ---------------------------------------------------------------------------


class PovejmoSession:
    """A visible Chromium session against povejmo.si (Playwright, sync API)."""

    def __init__(
        self,
        *,
        profile_dir: Path,
        headless: bool = False,
        channel: str | None = None,
        slow_mo: int = 0,
    ):
        from playwright.sync_api import sync_playwright  # lazy import

        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs: dict[str, Any] = {
            "headless": headless,
            "slow_mo": slow_mo,
            "viewport": {"width": 1280, "height": 900},
        }
        if channel:
            kwargs["channel"] = channel
        self.context = self._pw.chromium.launch_persistent_context(str(profile_dir), **kwargs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self._pw.stop()

    # -- small helpers ------------------------------------------------------

    def _first_visible(self, locator):
        for i in range(min(locator.count(), 10)):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
        return None

    def _last_visible(self, locator):
        n = locator.count()
        for i in range(n - 1, max(-1, n - 11), -1):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
        return None

    def _dismiss_overlays(self, attempts: int = 4) -> None:
        """Close the welcome/consent modals (they can appear after a delay)."""
        page = self.page
        labels = ("Razumem", "Sprejmem", "Strinjam se", "Soglašam", "V redu", "Accept all", "Accept")
        for _ in range(attempts):
            for label in labels:
                try:
                    el = self._first_visible(page.get_by_role("button", name=label, exact=False))
                except Exception:
                    el = None
                if el is None:
                    continue
                try:
                    el.click(timeout=2000)
                except Exception:
                    try:  # JS click bypasses any hit-testing quirks
                        el.evaluate("el => el.click()")
                    except Exception:
                        continue
                page.wait_for_timeout(700)
                break
            still_open = False
            for label in labels:
                try:
                    if self._first_visible(page.get_by_role("button", name=label, exact=False)):
                        still_open = True
                        break
                except Exception:
                    continue
            if not still_open:
                return
            page.wait_for_timeout(1000)

    def save_debug(self, debug_dir: Path, name: str) -> None:
        debug_dir = Path(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        try:
            self.page.screenshot(path=str(debug_dir / f"{name}_{stamp}.png"), full_page=True)
        except Exception:
            pass
        try:
            (debug_dir / f"{name}_{stamp}.html").write_text(self.page.content(), encoding="utf-8")
        except Exception:
            pass

    # -- actions ------------------------------------------------------------

    def open(self) -> None:
        self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(2500)  # the welcome modal renders after a moment
        self._dismiss_overlays()
        self.page.wait_for_timeout(800)

    def select_model(self, label: str) -> None:
        self._open_model_menu()
        if self._click_option(label):
            return
        raise RuntimeError(f"model option {label!r} not found in the dropdown")

    def _open_model_menu(self):
        page = self.page
        for finder in (
            lambda: page.locator('button[aria-label="Izberi model"]'),
            lambda: page.get_by_role("button", name="Izberi model"),
            lambda: page.locator("button").filter(has_text=re.compile(r"^GAMS", re.IGNORECASE)),
        ):
            try:
                el = self._first_visible(finder())
            except Exception:
                el = None
            if el:
                el.click(timeout=5000)
                page.wait_for_timeout(500)
                return el
        raise RuntimeError("model dropdown trigger not found")

    def _click_option(self, label: str) -> bool:
        """Click a dropdown option by text, case-insensitively (CSS uppercases labels)."""
        page = self.page
        target = label.strip().lower()
        for sel in ('[role="option"]', '[role="menuitem"]', "li", "button", "div"):
            loc = page.locator(sel)
            try:
                n = loc.count()
            except Exception:
                continue
            n = min(n, 400)
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    text = clean_reply(el.inner_text()).strip()
                except Exception:
                    continue
                if text and text.lower() == target:
                    try:
                        el.click(timeout=5000)
                        page.wait_for_timeout(600)
                        return True
                    except Exception:
                        continue
        return False

    def new_chat(self) -> None:
        page = self.page
        for name in ("Nov pogovor", "Nov klepet", "New chat", "New conversation"):
            try:
                el = self._first_visible(page.get_by_role("button", name=name, exact=False))
            except Exception:
                el = None
            if el:
                try:
                    el.click(timeout=4000)
                    page.wait_for_timeout(900)
                    return
                except Exception:
                    pass
        # fallback: reload the app (fresh temporary session)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        self._dismiss_overlays()
        page.wait_for_timeout(800)

    def _input_element(self):
        page = self.page
        for sel in ("textarea", '[contenteditable="true"]', 'div[role="textbox"]'):
            el = self._last_visible(page.locator(sel))
            if el:
                return el
        raise RuntimeError("chat input not found")

    def type_prompt(self, prompt: str) -> None:
        self.clear_input()
        el = self._input_element()
        el.click(timeout=5000)
        self.page.wait_for_timeout(200)
        self.page.keyboard.insert_text(prompt)
        self.page.wait_for_timeout(500)
        typed = re.sub(r"\s+", " ", self._input_text())
        head = re.sub(r"\s+", " ", prompt.strip())[:40]
        if head and head not in typed:
            raise RuntimeError("prompt text did not appear in the input box")

    def _input_text(self) -> str:
        try:
            el = self._input_element()
        except Exception:
            return ""
        try:
            tag = el.evaluate("el => el.tagName.toLowerCase()")
            if tag == "textarea":
                return el.input_value() or ""
            return el.inner_text() or ""
        except Exception:
            return ""

    def clear_input(self) -> None:
        """Make sure a leftover prompt from an earlier attempt cannot pile up."""
        try:
            el = self._input_element()
        except Exception:
            return
        try:
            el.fill("")
            self.page.wait_for_timeout(150)
        except Exception:
            pass
        if self._input_text().strip():
            try:
                el.click(timeout=3000)
                self.page.keyboard.press("Control+a")
                self.page.keyboard.press("Delete")
                self.page.wait_for_timeout(200)
            except Exception:
                pass

    def _click_send_button(self) -> bool:
        page = self.page
        for finder in (
            lambda: page.get_by_role("button", name=re.compile(r"po[sš]lji|send", re.IGNORECASE)),
            lambda: page.locator('button[type="submit"]'),
        ):
            el = self._last_visible(finder())
            if el:
                try:
                    el.click(timeout=4000)
                    return True
                except Exception:
                    continue
        return False

    def send_and_confirm(self, *, attempts: int = 3, settle_s: float = 5.0) -> bool:
        """Send the prompt and verify the message went out (input box cleared).

        A click that does not register leaves the prompt in the input box; that
        used to cost a full 240 s wait. Retry with Enter, then fail fast.
        """
        for attempt in range(attempts):
            if attempt == 1:
                self.page.keyboard.press("Enter")
            else:
                self._click_send_button()
            deadline = time.monotonic() + settle_s
            while time.monotonic() < deadline:
                self.page.wait_for_timeout(400)
                if not self._input_text().strip():
                    return True
        return False

    def _scan_candidates(self, locator, *, marker: str, limit: int, min_len: int = 0) -> str:
        """Newest-first scan of a locator list; skips placeholders and the prompt echo."""
        try:
            n = locator.count()
        except Exception:
            return ""
        for i in range(n - 1, max(-1, n - limit - 1), -1):
            el = locator.nth(i)
            try:
                if not el.is_visible():
                    continue
                text = clean_reply(el.inner_text())
            except Exception:
                continue
            if len(text) < min_len or is_placeholder(text):
                continue
            if marker and marker in text:
                continue
            return text
        return ""

    def last_assistant_text(self, prompt_marker: str = "") -> str:
        page = self.page
        marker = prompt_marker.strip()[:80]
        for sel in (
            '[data-message-author-role="assistant"]',
            '[data-role="assistant"]',
            '[class*="assistant"]',
        ):
            try:
                loc = page.locator(sel)
            except Exception:
                continue
            text = self._scan_candidates(loc, marker=marker, limit=6)
            if text:
                return text
        # generic fallback: message-like blocks, newest first
        try:
            loc = page.locator(
                '[class*="message"], [class*="bubble"], [class*="prose"], [class*="markdown"]'
            )
        except Exception:
            return ""
        return self._scan_candidates(loc, marker=marker, limit=25, min_len=10)

    def wait_for_reply(self, prompt_marker: str, *, timeout_s: float, stable_s: float) -> str:
        """Wait until a formatted reply stops changing.

        Only text carrying the required ``SENSE_ID``/``ODGOVOR`` format counts:
        the 'Razmišljam...' bubble (stable for many seconds while the RAG model
        thinks) and partial answers are ignored, so the stability clock starts
        on real answer text only.
        """
        deadline = time.monotonic() + timeout_s
        last_text = ""
        last_change = time.monotonic()
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(500)
            try:
                text = self.last_assistant_text(prompt_marker)
            except Exception:
                text = ""
            if text and not looks_like_answer(text):
                text = ""  # thinking placeholder or answer not started yet
            if text and text != last_text:
                last_text = text
                last_change = time.monotonic()
            if last_text and (time.monotonic() - last_change) >= stable_s:
                return last_text
        # never save a placeholder or a possibly truncated reply - the row stays
        # empty and is retried later
        raise TimeoutError(
            f"no stable SENSE_ID/ODGOVOR reply within {timeout_s:.0f}s (debug kept)"
        )

    # -- inspection (no prompts are sent) ------------------------------------

    def dump_inspect(self, out_dir: Path) -> Path:
        page = self.page
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {"url": page.url, "title": page.title(), "buttons": [], "inputs": []}
        for i in range(min(page.locator("button").count(), 60)):
            el = page.locator("button").nth(i)
            try:
                if not el.is_visible():
                    continue
                data["buttons"].append(
                    {
                        "text": clean_reply(el.inner_text())[:80],
                        "aria": el.get_attribute("aria-label"),
                        "title": el.get_attribute("title"),
                        "class": (el.get_attribute("class") or "")[:120],
                    }
                )
            except Exception:
                continue
        for sel in ("textarea", '[contenteditable="true"]', 'div[role="textbox"]'):
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        data["inputs"].append(
                            {"selector": sel, "class": (el.get_attribute("class") or "")[:120]}
                        )
                except Exception:
                    continue
        data["dropdown_options"] = []
        try:
            self._open_model_menu()
            for sel in ('[role="option"]', '[role="menuitem"]', "li", "div"):
                loc = page.locator(sel)
                for i in range(min(loc.count(), 400)):
                    el = loc.nth(i)
                    try:
                        if not el.is_visible():
                            continue
                        text = clean_reply(el.inner_text()).strip()
                    except Exception:
                        continue
                    if text and text.lower().startswith("gams"):
                        data["dropdown_options"].append({"selector": sel, "text": text[:80]})
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            data["dropdown_error"] = str(exc)
        data["message_like"] = []
        for sel in (
            '[class*="message"]',
            '[class*="bubble"]',
            '[class*="prose"]',
            '[class*="assistant"]',
            '[class*="chat"]',
            '[class*="markdown"]',
        ):
            try:
                loc = page.locator(sel)
                count = loc.count()
            except Exception:
                count = 0
            sample = []
            for i in range(max(0, count - 3), count):
                el = loc.nth(i)
                try:
                    sample.append(
                        {
                            "class": (el.get_attribute("class") or "")[:120],
                            "text": clean_reply(el.inner_text())[:100],
                        }
                    )
                except Exception:
                    continue
            data["message_like"].append({"selector": sel, "count": count, "sample": sample})
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"inspect_{stamp}.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.save_debug(out_dir, "inspect")
        return out_path


# ---------------------------------------------------------------------------
# batch runner
# ---------------------------------------------------------------------------


@dataclass
class BatchStats:
    processed: int = 0
    saved: int = 0
    failed: int = 0


def run_batch(
    *,
    csv_path: Path,
    model_label: str,
    profile_dir: Path,
    debug_dir: Path,
    limit: int | None = None,
    delay_s: float = 10.0,
    timeout_s: float = 240.0,
    stable_s: float = 2.5,
    headless: bool = False,
    channel: str | None = None,
    dry_run: bool = False,
) -> BatchStats:
    csv_path = Path(csv_path)
    rows, fieldnames = load_answers(csv_path)
    prompts_dir = csv_path.parent / "prompts"
    if not prompts_dir.is_dir():
        raise SystemExit(f"prompts folder not found next to the CSV: {prompts_dir}")

    stats = BatchStats()
    session = PovejmoSession(profile_dir=profile_dir, headless=headless, channel=channel)
    try:
        session.open()
        session.select_model(model_label)
        print(f"model selected: {model_label}")
        consecutive_failures = 0
        while True:
            if limit is not None and stats.processed >= limit:
                break
            idx = next_unanswered_index(rows)
            if idx is None:
                print("all rows are answered - nothing to do")
                break
            row = rows[idx]
            qid, variant = row["question_id"], row["variant"]
            prompt_path = prompts_dir / f"{qid}__{variant}.txt"
            if not prompt_path.exists():
                raise SystemExit(f"prompt file missing: {prompt_path}")
            prompt = prompt_path.read_text(encoding="utf-8")
            total = sum(1 for r in rows if (r.get("answer_raw") or "").strip())
            print(f"[{total + 1}/{len(rows)}] {qid} {variant} ...", flush=True)
            try:
                session.new_chat()
                session.select_model(model_label)
                session.type_prompt(prompt)
                if dry_run:
                    session.save_debug(debug_dir, f"dry_{qid}_{variant}")
                    print("    dry-run: prompt typed, NOT sent")
                    stats.processed += 1
                    break
                if not session.send_and_confirm():
                    raise RuntimeError("message was not sent (input box did not clear)")
                reply = session.wait_for_reply(prompt, timeout_s=timeout_s, stable_s=stable_s)
                if not reply.strip():
                    raise RuntimeError("empty reply")
                row["answer_raw"] = reply
                save_answers(csv_path, rows, fieldnames)
                stats.saved += 1
                consecutive_failures = 0
                print(f"    saved {len(reply)} chars")
            except Exception as exc:  # noqa: BLE001 - keep the batch going
                stats.failed += 1
                consecutive_failures += 1
                session.save_debug(debug_dir, f"fail_{qid}_{variant}")
                append_log(
                    debug_dir,
                    {
                        "question_id": qid,
                        "variant": variant,
                        "model": model_label,
                        "error": str(exc),
                    },
                )
                print(f"    FAILED: {exc} (debug saved)")
                if consecutive_failures >= 3:
                    print("three consecutive failures - stopping for safety")
                    break
            stats.processed += 1
            if not dry_run:
                pause = max(2.0, delay_s + random.uniform(-2.0, 3.0))
                time.sleep(pause)
        return stats
    finally:
        session.close()
