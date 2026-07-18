"""Boot smoke test: the whole app must import and wire its routers.

Guards the failure class where a service rewrite silently drops a symbol that a
route module still imports (Phase-1 push dropped `send_email` while workspaces.py
depended on it — which passed unit tests but would crash uvicorn on boot)."""

from app.services import notify


def test_app_boots_and_wires_routers():
    import app.main as m

    paths = m.app.openapi()["paths"].keys()
    for expected in (
        "/api/v1/chat",
        "/api/v1/media/videos",
        "/api/v1/media/files/{name}",
        "/api/v1/media/films",
        "/api/v1/media/videos/storyboard",
        "/api/v1/admin/overview",
        "/api/v1/admin/devices",
        "/api/v1/admin/push-test",
        "/api/v1/workspaces",
        "/api/v1/devices",
    ):
        assert any(expected in p for p in paths), f"missing route: {expected}"


def test_notify_keeps_email_and_push_surface():
    # Both halves of the notification seam must exist together.
    assert callable(notify.send_email)          # workspace invites (Gmail plugin)
    assert callable(notify.notify_user)         # FCM push
    assert callable(notify.notify_arena_done)
