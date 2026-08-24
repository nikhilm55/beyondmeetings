from beyondmeetings.desktop_app import run_native_app


class FakeWebview:
    def __init__(self):
        self.windows = []
        self.started = False

    def create_window(self, *args, **kwargs):
        self.windows.append((args, kwargs))

    def start(self):
        self.started = True


def test_native_app_reuses_the_local_server_and_opens_a_window(monkeypatch):
    monkeypatch.setattr("beyondmeetings.desktop_app.server_is_running", lambda p: True)
    webview = FakeWebview()
    assert run_native_app(webview_module=webview) == 0
    assert webview.started is True
    assert webview.windows[0][0][1] == "http://127.0.0.1:7788/"


def test_native_app_can_open_settings_in_the_same_window(monkeypatch):
    monkeypatch.setattr("beyondmeetings.desktop_app.server_is_running", lambda p: True)
    webview = FakeWebview()
    run_native_app(page="/setup", webview_module=webview)
    assert webview.windows[0][0][1].endswith("/setup")


def test_native_app_starts_the_detached_server_before_the_window(monkeypatch):
    monkeypatch.setattr("beyondmeetings.desktop_app.server_is_running", lambda p: False)
    order = []
    webview = FakeWebview()
    run_native_app(
        webview_module=webview,
        launcher=lambda p: order.append("launch"),
        waiter=lambda p, timeout=0: order.append("wait") or True,
    )
    assert order == ["launch", "wait"]
