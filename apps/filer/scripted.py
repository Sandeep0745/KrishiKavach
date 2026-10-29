"""Scripted fill: Playwright types the same values into the same fields, by id (SystemDesign §14.3).

It is the fallback for the browser agent and the default while CREDIT_SAVER is on. It works in the window the agent used and
carries on from whichever page of the form is open.
"""
from __future__ import annotations

import asyncio
import re

# (field id, kind) in the order they appear on each page (SystemDesign §14.2)
PAGES: dict[int, list[tuple[str, str]]] = {
    1: [("application_no", "text"), ("farmer_name", "text"), ("mobile", "text"), ("state", "select"), ("district", "select"), ("tehsil", "text"),
        ("village", "text")],
    2: [("season", "select"), ("crop", "select"), ("khasra_no", "text"), ("insured_area_ha", "text"), ("loss_date", "text"), ("loss_time", "text"),
        ("cause_of_loss", "select"), ("crop_stage", "radio"), ("affected_area_ha", "text"), ("damage_pct", "text"), ("remarks", "text")],
    3: [("photo", "file"), ("gps_lat", "text"), ("gps_lon", "text"), ("submitted_by", "select"), ("declaration", "check")],
}
CONFIRMATION = re.compile(r"/claim/confirmation/(FCS-\d+)")


def page_number(url: str) -> int | None:
    """Which page of the form a URL is: 1, 2 or 3; 0 for the confirmation page; None for anything else."""
    if CONFIRMATION.search(url):
        return 0
    m = re.search(r"/claim/[^/]+/step([123])", url)
    return int(m.group(1)) if m else None


class PortalBrowser:
    """A Playwright connection to the Filer's browser window."""

    def __init__(self, portal_url: str, field_delay_ms: int = 250) -> None:
        self.portal_url = portal_url.rstrip("/")
        self.delay = field_delay_ms / 1000
        self._pw = None
        self._browser = None

    async def connect(self, ws_url: str) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(ws_url)

    async def close(self) -> None:
        # Disconnect only: the window belongs to the Filer process, not to this connection.
        for closer in (getattr(self._browser, "close", None), getattr(self._pw, "stop", None)):
            if closer is not None:
                try:
                    await asyncio.wait_for(closer(), 5)
                except Exception:  # noqa: BLE001
                    pass
        self._browser = self._pw = None

    def _context(self):
        return self._browser.contexts[0] if self._browser.contexts else None

    def portal_pages(self) -> list:
        ctx = self._context()
        return [p for p in (ctx.pages if ctx else []) if p.url.startswith(self.portal_url)]

    async def page(self):
        """The portal tab: the one furthest into the form if there are several, otherwise any tab, otherwise a new one."""
        pages = self.portal_pages()
        if pages:
            return max(pages, key=lambda p: (page_number(p.url) is not None, page_number(p.url) == 0, page_number(p.url) or 0))
        ctx = self._context() or await self._browser.new_context()
        return ctx.pages[0] if ctx.pages else await ctx.new_page()

    async def go_home(self) -> None:
        """Before a filing starts: one portal tab, on the start page. A confirmation page left from an earlier filing must never be
        mistaken for this one's."""
        pages = self.portal_pages()
        for extra in pages[1:]:
            try:
                await extra.close()
            except Exception:  # noqa: BLE001
                pass
        page = pages[0] if pages else await self.page()
        await page.goto(self.portal_url + "/", wait_until="domcontentloaded", timeout=15000)
        await page.bring_to_front()

    async def open_form(self) -> None:
        """Open page 1 of the form directly (plain navigation, no reading of the page)."""
        page = await self.page()
        await page.goto(self.portal_url + "/claim/new/step1", wait_until="domcontentloaded", timeout=15000)
        await page.bring_to_front()

    async def where(self) -> int | None:
        """Which page of the form the window is on: 1, 2, 3; 0 for the confirmation page; None for anything else."""
        return page_number((await self.page()).url)

    async def reference_on_screen(self) -> str | None:
        for page in self.portal_pages():
            m = CONFIRMATION.search(page.url)
            if m:
                try:
                    shown = (await page.locator("#reference").inner_text(timeout=3000)).strip()
                except Exception:  # noqa: BLE001
                    shown = ""
                return shown or m.group(1)
        return None

    async def _fill(self, page, field: str, kind: str, value: str, photo_path: str | None) -> str:
        if kind == "file":
            await page.set_input_files(f"#{field}", photo_path)
            return "upload"
        if kind == "select":
            await page.select_option(f"#{field}", label=value)
            return "select"
        if kind == "radio":
            await page.check(f'input[name="{field}"][value="{value}"]')
            return "choose"
        if kind == "check":
            if value in ("on", "true", "yes", "1"):
                await page.check(f"#{field}")
            return "tick"
        await page.fill(f"#{field}", value)
        return "fill"

    async def fill(self, form: dict, photo_path: str, on_step) -> tuple[str, int]:
        """Fill and submit from whichever page is open (each page is filled again from its first field). Returns (reference, steps)."""
        page = await self.page()
        page.set_default_timeout(6000)  # the portal is on this computer: anything slower than this is a fault, not a wait
        await page.bring_to_front()
        steps = 0
        at = page_number(page.url)
        if at == 0:
            shown = await self.reference_on_screen()
            if shown:
                return shown, steps
        if at is None:
            if page.url.rstrip("/") != self.portal_url:
                await page.goto(self.portal_url + "/", wait_until="domcontentloaded", timeout=15000)
            steps += 1
            on_step(steps, "click", "report_crop_loss")
            await page.click("#start")
            await page.wait_for_url(re.compile(r"/claim/new/step1"), timeout=15000)
            at = 1
        for number in (1, 2, 3):
            if number < at:
                continue
            for field, kind in PAGES[number]:
                value = str(form.get(field, ""))
                if kind == "text" and value == "" and field in ("gps_lat", "gps_lon", "remarks"):
                    continue  # optional and empty: leave it alone
                steps += 1
                try:
                    action = await self._fill(page, field, kind, value, photo_path)
                except Exception as e:  # noqa: BLE001 - say which field, in one line
                    raise RuntimeError(f"could not fill '{field}' with '{value[:40]}' on page {number}: {str(e).splitlines()[0][:120]}") from None
                on_step(steps, action, field)
                if self.delay:
                    await asyncio.sleep(self.delay)
            steps += 1
            on_step(steps, "click", "submit" if number == 3 else "next")
            await page.click("#submit" if number == 3 else "#next")
            target = CONFIRMATION if number == 3 else re.compile(rf"/claim/[^/]+/step{number + 1}")
            try:
                await page.wait_for_url(target, timeout=15000)
            except Exception:
                errors = ""
                try:
                    errors = (await page.locator("#errors").inner_text(timeout=1000)).strip().replace("\n", "; ")
                except Exception:  # noqa: BLE001
                    pass
                raise RuntimeError(f"page {number} of the form was not accepted" + (f": {errors}" if errors else "")) from None
        shown = (await page.locator("#reference").inner_text(timeout=5000)).strip()
        if not shown:
            raise RuntimeError("the confirmation page showed no reference number")
        return shown, steps
