"""ScreenshotTool. Artifacts are written under artifacts/<assessment_id>/."""
from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

log = logging.getLogger(__name__)


async def capture_screenshot(page: Page, artifact_dir: Path, name: str,
                             *, full_page: bool = False) -> str | None:
    """Capture one screenshot. Returns the relative path, or None on failure."""
    shots = artifact_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    path = shots / f"{name}.png"
    try:
        await page.screenshot(path=str(path), full_page=full_page)
        log.info("screenshot captured: %s", path.name)
        return str(path.relative_to(artifact_dir.parent.parent))
    except Exception as exc:                                    # noqa: BLE001
        log.warning("screenshot failed: %s", exc)
        return None
