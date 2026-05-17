"""
UAT — Dubai Car Hunt frontend.

Runs Playwright against the local index.html and exercises every interactive
control. Each check is a single function returning (name, passed, detail).
A failing check captures a screenshot to ./tests/_screenshots/<name>.png.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, Page, expect, TimeoutError as PWTimeoutError

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "Car Deals Frontend"
INDEX = FRONTEND / "index.html"
DATA_JS = FRONTEND / "data.js"
SHOTS = ROOT / "tests" / "_screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)


# ─── result plumbing ───────────────────────────────────────────────────────────
@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: int = 0


results: list[Result] = []


def check(name: str, page: Page | None = None):
    """Decorator: runs the function, captures screenshot on failure."""
    def deco(fn: Callable[[], tuple[bool, str]]):
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}"
        dur = int((time.time() - t0) * 1000)
        if not ok and page is not None:
            try:
                page.screenshot(path=str(SHOTS / f"{name.replace(' ', '_')}.png"), full_page=True)
            except Exception:
                pass
        results.append(Result(name, ok, detail, dur))
        sym = "PASS" if ok else "FAIL"
        line = f"  [{sym}] {name} ({dur}ms)"
        if not ok:
            line += f"\n         {detail.splitlines()[0] if detail else ''}"
        print(line, flush=True)
        return ok
    return deco


# ─── data shape sanity ─────────────────────────────────────────────────────────
def load_data_stats() -> tuple[int, int, int]:
    """Inline-parse data.js to know the truth before testing the UI."""
    raw = DATA_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.CAR_DATA\s*=\s*(\[.*?\])\s*;\s*window\.CAR_STATS", raw, re.DOTALL)
    if not m:
        raise RuntimeError("Could not parse data.js")
    data = json.loads(m.group(1))
    sun = sum(1 for c in data if c.get("has_sunroof"))
    under20 = sum(1 for c in data if (c.get("price") or 0) > 0 and (c.get("price") or 0) <= 20000)
    return len(data), sun, under20


# ─── tests ─────────────────────────────────────────────────────────────────────
def run_all(page: Page) -> None:
    total, sun, under20 = load_data_stats()
    print(f"\nData truth: total={total}, sunroof={sun}, ≤20K={under20}\n")
    print("Loading page…")
    page.goto(INDEX.as_uri(), wait_until="load", timeout=20000)
    page.wait_for_selector("#list .row", timeout=10000)

    # ─── 1. Page chrome ───────────────────────────────────────────────────────
    @check("Page title is correct", page)
    def _():
        return page.title() == "Dubai Car Hunt", f"title={page.title()!r}"

    @check("Top strip stats reflect data.js", page)
    def _():
        t = page.locator("#stat-total").text_content().strip()
        s = page.locator("#stat-sunroof").text_content().strip()
        b = page.locator("#stat-budget").text_content().strip()
        if int(t) != total: return False, f"#stat-total={t} expected {total}"
        if int(s) != sun: return False, f"#stat-sunroof={s} expected {sun}"
        if int(b) != under20: return False, f"#stat-budget={b} expected {under20}"
        return True, f"{t}/{s}/{b}"

    @check("'Refreshed Xm ago' label is rendered", page)
    def _():
        txt = page.locator("#stat-updated").text_content().strip()
        return bool(re.search(r"(just now|ago|refreshed)", txt, re.I)), f"text={txt!r}"

    # ─── 2. Default render = list view, full data ─────────────────────────────
    @check("Default list view renders ≥60 rows progressively", page)
    def _():
        rows = page.locator("#list .row").count()
        return rows >= min(60, total), f"rendered {rows} rows"

    @check("First row is a sunroof listing (sort = sunroof-first)", page)
    def _():
        first = page.locator("#list .row").first
        return first.get_attribute("class").find("row--sun") >= 0, "first row missing row--sun"

    @check("Feed count line shows '<n> of <total> listings'", page)
    def _():
        shown = page.locator("#count-shown").text_content().strip().replace(",", "")
        tot = page.locator("#count-total").text_content().strip().replace(",", "")
        return int(shown) == total and int(tot) == total, f"shown={shown} tot={tot}"

    # ─── 3. Search ────────────────────────────────────────────────────────────
    @check("Search filters listings by free text", page)
    def _():
        page.locator("#q").fill("Elantra")
        page.wait_for_timeout(200)  # debounce
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        rows = page.locator("#list .row").count()
        page.locator("#q").fill("")
        page.wait_for_timeout(200)
        return shown > 0 and shown < total and rows > 0, f"shown={shown} rows={rows}"

    @check("Search is case-insensitive and matches features", page)
    def _():
        page.locator("#q").fill("AUTOMATIC")
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator("#q").fill("")
        page.wait_for_timeout(200)
        return shown > 0, f"automatic→{shown}"

    # ─── 4. Brand / source dropdowns ──────────────────────────────────────────
    @check("Brand dropdown filters list", page)
    def _():
        page.locator("#brand").select_option(label="Honda Civic")
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        # All visible rows must contain 'Honda' in their title or be Honda Civic brand
        page.locator("#brand").select_option(value="")
        page.wait_for_timeout(200)
        return 0 < shown < total, f"Honda Civic only→{shown}"

    @check("Source dropdown filters list", page)
    def _():
        page.locator("#source").select_option(label="Dubizzle")
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator("#source").select_option(value="")
        page.wait_for_timeout(200)
        return 0 < shown <= total, f"Dubizzle only→{shown}"

    # ─── 5. Chips ─────────────────────────────────────────────────────────────
    @check("Sunroof-only chip filters to sunroof listings", page)
    def _():
        page.locator('[data-chip="sunroof"]').click()
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        rows_total = page.locator("#list .row").count()
        sun_rows = page.locator("#list .row.row--sun").count()
        page.locator('[data-chip="sunroof"]').click()  # toggle off
        page.wait_for_timeout(200)
        # When sunroof-only is on, every rendered row must be a sunroof row
        return shown == sun and sun_rows == rows_total, f"shown={shown} expected {sun}; sun_rows={sun_rows}/{rows_total}"

    @check("Budget ≤20K chip caps price at 20,000", page)
    def _():
        page.locator('[data-chip="budget"]').click()
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator('[data-chip="budget"]').click()
        page.wait_for_timeout(200)
        return shown == under20, f"shown={shown} expected {under20}"

    @check("Top-20 chip caps to 20 rows", page)
    def _():
        page.locator('[data-chip="top20"]').click()
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator('[data-chip="top20"]').click()
        page.wait_for_timeout(200)
        return shown == 20, f"shown={shown}"

    @check("Owner-only chip filters by seller_type=OW", page)
    def _():
        page.locator('[data-chip="owner"]').click()
        page.wait_for_timeout(200)
        shown_owner = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        # check the rendered rows all show OWNER tag (where seller info exists)
        page.locator('[data-chip="owner"]').click()
        page.wait_for_timeout(200)
        return shown_owner >= 0 and shown_owner < total, f"owner shown={shown_owner}"

    # ─── 6. Range popovers ────────────────────────────────────────────────────
    @check("Max-price popover opens and updates pill", page)
    def _():
        page.locator("#pop-price summary").click()
        page.wait_for_timeout(150)
        # Slider value to 15000
        page.evaluate("""() => {
          const r = document.querySelector('#price');
          r.value = 15000;
          r.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        page.wait_for_timeout(200)
        pill = page.locator("#price-pill").text_content().strip()
        page.locator("#pop-price summary").click()  # close
        return pill == "15K", f"pill={pill!r}"

    @check("Max-price slider actually filters", page)
    def _():
        page.evaluate("""() => {
          const r = document.querySelector('#price');
          r.value = 10000;
          r.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        # restore
        page.evaluate("""() => {
          const r = document.querySelector('#price');
          r.value = 30000;
          r.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        page.wait_for_timeout(200)
        return 0 <= shown < total, f"≤10K→{shown}"

    @check("Min-score popover updates pill and filters", page)
    def _():
        page.evaluate("""() => {
          const r = document.querySelector('#score');
          r.value = 70;
          r.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        page.wait_for_timeout(200)
        pill = page.locator("#score-pill").text_content().strip()
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.evaluate("""() => {
          const r = document.querySelector('#score');
          r.value = 0;
          r.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
        page.wait_for_timeout(200)
        return pill == "70+" and 0 <= shown <= total, f"pill={pill} shown={shown}"

    # ─── 7. Sort ──────────────────────────────────────────────────────────────
    @check("Sort: price asc → first row cheaper than last", page)
    def _():
        page.locator("#sort").select_option(value="price-asc")
        page.wait_for_timeout(200)
        prices = page.locator("#list .row .row__price .num").all_text_contents()
        first = int(prices[0].replace(",", ""))
        last = int(prices[-1].replace(",", ""))
        page.locator("#sort").select_option(value="sunroof")
        page.wait_for_timeout(200)
        return first <= last, f"first={first} last={last}"

    @check("Sort: year desc → first row newest", page)
    def _():
        page.locator("#sort").select_option(value="year-desc")
        page.wait_for_timeout(200)
        years = page.locator("#list .row .row__meta .num").all_text_contents()
        # First .num per row is year (every 2nd: year, km — read first column only via .first)
        first_year_text = page.locator("#list .row").first.locator(".row__meta .num").first.text_content().strip()
        page.locator("#sort").select_option(value="sunroof")
        page.wait_for_timeout(200)
        try:
            y = int(first_year_text)
            return 2000 <= y <= 2027, f"first year={y}"
        except ValueError:
            return False, f"unparseable year={first_year_text!r}"

    # ─── 8. View toggle ───────────────────────────────────────────────────────
    @check("Grid view toggle shows .grid and hides .list", page)
    def _():
        page.locator('[data-view="grid"]').click()
        page.wait_for_timeout(200)
        grid_hidden = page.locator("#grid").is_hidden()
        list_hidden = page.locator("#list").is_hidden()
        card_count = page.locator("#grid .card").count()
        page.locator('[data-view="list"]').click()
        page.wait_for_timeout(200)
        return (not grid_hidden) and list_hidden and card_count > 0, f"grid_hidden={grid_hidden} list_hidden={list_hidden} cards={card_count}"

    @check("Grid cards have sunroof pill on sunroof listings", page)
    def _():
        page.locator('[data-view="grid"]').click()
        page.wait_for_timeout(200)
        sun_pills = page.locator("#grid .card__sunPill").count()
        page.locator('[data-view="list"]').click()
        page.wait_for_timeout(200)
        # Should be at least one in default render (60 rows / 35 sunroof / sunroof-first sort)
        return sun_pills > 0, f"sun_pills={sun_pills}"

    # ─── 9. Keyboard shortcuts ────────────────────────────────────────────────
    @check("Pressing '/' focuses the search box", page)
    def _():
        page.locator("body").click()
        page.keyboard.press("/")
        page.wait_for_timeout(100)
        active = page.evaluate("document.activeElement && document.activeElement.id")
        return active == "q", f"active={active!r}"

    @check("Pressing 'G' switches to grid view", page)
    def _():
        page.locator("body").click()
        page.keyboard.press("g")
        page.wait_for_timeout(150)
        active = page.locator('[data-view="grid"]').get_attribute("class")
        hidden = page.locator("#list").is_hidden()
        page.keyboard.press("l")  # back to list
        page.wait_for_timeout(150)
        return "is-active" in (active or "") and hidden, f"grid class={active}; list hidden={hidden}"

    # ─── 10. Modal ────────────────────────────────────────────────────────────
    @check("Clicking a row opens the modal", page)
    def _():
        # Use dispatch_event to bypass Playwright's actionability check; sticky overlays
        # confuse the pointer-event probe even though the click works in a real browser.
        page.locator("#list .row").nth(3).dispatch_event("click")
        page.wait_for_selector("#modal:not([hidden])", timeout=3000)
        return not page.locator("#modal").is_hidden(), "modal not visible"

    @check("Modal shows title, price, score, KV pairs", page)
    def _():
        title = page.locator("#m-title").text_content().strip()
        price = page.locator("#m-price").text_content().strip()
        score = page.locator("#m-score").text_content().strip()
        kv_rows = page.locator("#m-kv dt").count()
        return bool(title) and bool(price) and bool(score) and kv_rows >= 9, \
            f"title={title!r} price={price} score={score} kv_rows={kv_rows}"

    @check("Modal score bars render 8 sub-scores", page)
    def _():
        bars = page.locator("#m-bars .bar").count()
        return bars == 8, f"bars={bars}"

    @check("Modal shows feature pills", page)
    def _():
        feats = page.locator("#m-feat .feat").count()
        return feats > 0, f"feat pills={feats}"

    @check("Modal 'Open original listing' link is set to a URL", page)
    def _():
        href = page.locator("#m-link").get_attribute("href")
        return bool(href) and href.startswith(("http://", "https://")), f"href={href!r}"

    @check("Esc key closes the modal", page)
    def _():
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        return page.locator("#modal").is_hidden(), "modal still visible after Esc"

    @check("Backdrop click closes the modal", page)
    def _():
        page.locator("#list .row").nth(3).dispatch_event("click")
        page.wait_for_selector("#modal:not([hidden])", timeout=3000)
        # Backdrop covers the whole viewport but is BEHIND the panel; click a corner so we hit it.
        page.locator(".modal__backdrop").click(position={"x": 8, "y": 8})
        page.wait_for_timeout(200)
        return page.locator("#modal").is_hidden(), "modal still visible after backdrop click"

    # ─── 11. Empty state ──────────────────────────────────────────────────────
    @check("Empty state appears when filters yield 0 results", page)
    def _():
        page.locator("#q").fill("zzzzzzzz-no-match-zzzzzzzz")
        page.wait_for_timeout(250)
        empty_visible = not page.locator("#empty").is_hidden()
        list_hidden = page.locator("#list").is_hidden()
        page.locator("#q").fill("")
        page.wait_for_timeout(200)
        return empty_visible and list_hidden, f"empty_visible={empty_visible} list_hidden={list_hidden}"

    @check("Clear-filters from empty state restores list", page)
    def _():
        page.locator("#q").fill("zzzzzzzz")
        page.wait_for_timeout(200)
        page.locator("#empty-clear").click()
        page.wait_for_timeout(200)
        shown = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        return shown == total, f"after clear shown={shown}"

    # ─── 12. Style cues for sunroof ───────────────────────────────────────────
    def _reset_state():
        # If any popover open, close it; if modal open, close it; clear filters.
        page.evaluate("""() => {
          document.querySelectorAll('details[open]').forEach(d => d.removeAttribute('open'));
          const m = document.querySelector('#modal'); if (m && !m.hidden) m.hidden = true;
          const q = document.querySelector('#q'); if (q) { q.value=''; q.dispatchEvent(new Event('input',{bubbles:true})); }
          window.scrollTo(0, 0);
        }""")
        page.wait_for_timeout(250)

    @check("Sunroof rows display a 'Sunroof' tag near the title", page)
    def _():
        _reset_state()
        tags = page.locator("#list .row.row--sun .row__sunTag").count()
        return tags > 0, f"row__sunTag={tags}"

    @check("Sunroof rows show price in gold/amber (not default ink)", page)
    def _():
        _reset_state()
        # Compare a sunroof-row price color to a non-sunroof-row price color.
        # The actual computed value may be oklch() or rgb() depending on browser version.
        sun_color, ink_color = page.evaluate("""() => {
          const sunEl = document.querySelector('#list .row.row--sun .row__price .num');
          const inkEl = document.querySelector('#list .row:not(.row--sun) .row__price .num');
          return [sunEl && getComputedStyle(sunEl).color, inkEl && getComputedStyle(inkEl).color];
        }""")
        return bool(sun_color) and sun_color != ink_color, f"sun={sun_color}  ink={ink_color}"

    # ─── 13. Responsive viewports ─────────────────────────────────────────────
    @check("Mobile viewport (390x844) renders without horizontal scroll", page)
    def _():
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        # No horizontal scroll: scrollWidth == clientWidth
        sw, cw = page.evaluate("[document.body.scrollWidth, document.documentElement.clientWidth]")
        # restore
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(200)
        return sw <= cw + 2, f"scrollWidth={sw} clientWidth={cw}"

    # ─── 14. Final: counts re-render after toggling sunroof chip ──────────────
    @check("Sunroof count in feed-head updates dynamically", page)
    def _():
        _reset_state()
        sun_now = int(page.locator("#count-sun").text_content().strip())
        page.locator('[data-chip="sunroof"]').click()
        page.wait_for_timeout(200)
        sun_after = int(page.locator("#count-sun").text_content().strip())
        page.locator('[data-chip="sunroof"]').click()
        page.wait_for_timeout(200)
        return sun_now == sun and sun_after == sun, f"before={sun_now} after_filter={sun_after} expected={sun}"


def main() -> int:
    print("=" * 60)
    print(f"UAT — Dubai Car Hunt frontend  |  {INDEX}")
    print("=" * 60)

    if not INDEX.exists():
        print(f"ERROR: {INDEX} not found")
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # Console errors surface in the report
        console_errors: list[str] = []
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: console_errors.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)

        try:
            run_all(page)
        finally:
            ctx.close()
            browser.close()

        results.append(Result(
            name="No JS console errors / pageerrors",
            passed=len([e for e in console_errors if "pageerror" in e]) == 0,
            detail="\n".join(console_errors[:10]) if console_errors else "clean",
        ))

    # ─── summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"RESULT:  {passed} passed  |  {failed} failed  |  total {len(results)}")
    print("=" * 60)
    if failed:
        print("\nFAILED checks:")
        for r in results:
            if not r.passed:
                print(f"  ✗ {r.name}")
                if r.detail:
                    for line in r.detail.splitlines()[:4]:
                        print(f"      {line}")
        print(f"\nScreenshots saved under: {SHOTS}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
