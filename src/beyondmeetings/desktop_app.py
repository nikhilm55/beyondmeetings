"""Native desktop window around the local beyondMeetings application.

The business logic stays in the loopback-only FastAPI server, so Linux,
Windows and macOS use exactly the same UI and storage code. pywebview supplies
the small native window for each platform (WebKit, Edge WebView2, or Cocoa).
"""
from __future__ import annotations

from .desktop import DEFAULT_PORT, launch_server, server_is_running, wait_for_server


def run_native_app(
    port: int = DEFAULT_PORT,
    page: str = "/",
    webview_module=None,
    launcher=launch_server,
    waiter=wait_for_server,
) -> int:
    """Start the local server if needed and block until the window closes."""
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError as exc:  # pragma: no cover - installation failure
            raise RuntimeError(
                "The desktop window is not installed. Reinstall beyondMeetings "
                "with the 'desktop' extra."
            ) from exc

    if not server_is_running(port):
        launcher(port)
        if not waiter(port):
            raise RuntimeError(f"Could not start the local app server on port {port}.")

    url = f"http://127.0.0.1:{port}{page}"
    webview_module.create_window(
        "beyondMeetings", url, width=1040, height=760, min_size=(720, 560)
    )
    webview_module.start()
    return 0
