import os
from pathlib import Path

import pytest

from vmprofconvert import convert_stats


@pytest.mark.firefox_profiler
def test_generated_profile_loads_in_firefox_profiler(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")

    source_profile = Path(__file__).parent / "profiles" / "example.prof"
    converted_profile = tmp_path / "example.json"
    converted_profile.write_text(
        convert_stats(os.fspath(source_profile)), encoding="utf-8"
    )

    browser_errors = []
    with playwright.sync_playwright() as browser_tools:
        launch_options = {}
        if executable_path := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
            launch_options["executable_path"] = executable_path
        browser = browser_tools.chromium.launch(**launch_options)
        page = browser.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))

        page.goto(
            "https://profiler.firefox.com/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        page.locator('input[type="file"]').set_input_files(
            os.fspath(converted_profile)
        )

        try:
            page.wait_for_function(
                """
                () => window.getState?.().app.view.phase === "DATA_LOADED"
                """,
                timeout=60_000,
            )
        except playwright.TimeoutError:
            pytest.fail(
                "Firefox Profiler did not load the generated profile.\n"
                f"Page contents:\n{page.locator('body').inner_text()}\n"
                f"JavaScript errors:\n{chr(10).join(browser_errors)}"
            )

        result = page.evaluate(
            """
            () => ({
                phase: window.getState().app.view.phase,
                importedFrom: window.profile.meta.importedFrom,
                threadCount: window.profile.threads.length,
                sampleCount: window.profile.threads.reduce(
                    (count, thread) => count + thread.samples.length,
                    0
                ),
            })
            """
        )
        browser.close()

    assert result["phase"] == "DATA_LOADED"
    assert result["importedFrom"] == "VMProf"
    assert result["threadCount"] >= 1
    assert result["sampleCount"] > 0
    assert not browser_errors, "\n".join(browser_errors)
