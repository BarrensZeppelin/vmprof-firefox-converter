import os
from pathlib import Path

import pytest

from vmprofconvert import convert_stats


@pytest.mark.firefox_profiler
# pypy-pystone.prof has jitted frames, which the profiler renders with its
# fallback category; example.prof only exercises the plain python ones
@pytest.mark.parametrize("profile_name", ["example.prof", "pypy-pystone.prof"])
def test_generated_profile_loads_in_firefox_profiler(tmp_path, profile_name):
    playwright = pytest.importorskip("playwright.sync_api")

    source_profile = Path(__file__).parent / "profiles" / profile_name
    converted_profile = tmp_path / "converted.json"
    converted_profile.write_text(
        convert_stats(os.fspath(source_profile)), encoding="utf-8"
    )

    browser_errors = []
    console_errors = []
    with playwright.sync_playwright() as browser_tools:
        launch_options = {}
        if executable_path := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
            launch_options["executable_path"] = executable_path
        browser = browser_tools.chromium.launch(**launch_options)
        page = browser.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        # a component that throws while rendering is caught by a react error
        # boundary, which only logs to the console
        page.on(
            "console",
            lambda message: message.type == "error"
            and console_errors.append(message.text),
        )

        def fail(reason):
            pytest.fail(
                f"{reason}\n"
                f"Page contents:\n{page.locator('body').inner_text()}\n"
                f"JavaScript errors:\n{chr(10).join(browser_errors + console_errors)}"
            )

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
            fail("Firefox Profiler did not load the generated profile.")

        try:
            page.wait_for_selector(".treeViewRow", timeout=60_000)
        except playwright.TimeoutError:
            fail("Firefox Profiler did not render a call tree for the generated profile.")

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
