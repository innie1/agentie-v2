from unittest.mock import patch

from agentie.core import desktop_runtime


def test_show_desktop_uses_healthy_display_when_guestcontrol_is_temporarily_unavailable():
    ready = {"running": True, "display_ready": True, "browser_ready": False, "backend": "virtualbox"}
    with (
        patch.object(desktop_runtime, "start_computer", return_value=ready),
        patch.object(desktop_runtime, "ensure_guest_runtime") as repair,
        patch.object(desktop_runtime, "acquire_user", return_value=ready),
    ):
        result = desktop_runtime.route_desktop_request("show desktop", "session")
    repair.assert_not_called()
    assert result["card"]["display_ready"] is True
    assert result["message"] == "Agentie Computer ready for you."


def test_show_desktop_repairs_when_display_is_not_ready():
    starting = {"running": True, "display_ready": False, "browser_ready": False}
    ready = {"running": True, "display_ready": True, "browser_ready": True, "backend": "virtualbox"}
    with (
        patch.object(desktop_runtime, "start_computer", return_value=starting),
        patch.object(desktop_runtime, "ensure_guest_runtime") as repair,
        patch.object(desktop_runtime, "computer_status", return_value=ready),
        patch.object(desktop_runtime, "acquire_user", return_value=ready),
    ):
        result = desktop_runtime.route_desktop_request("show desktop", "session")
    repair.assert_called_once_with()
    assert result["card"]["display_ready"] is True


def test_show_desktop_never_claims_ready_when_display_is_unavailable():
    unavailable = {
        "running": True,
        "display_ready": False,
        "browser_ready": False,
        "backend": "virtualbox",
        "last_error": "Display bridge is unavailable.",
    }
    with (
        patch.object(desktop_runtime, "_ensure_visible_computer", return_value=unavailable),
        patch.object(desktop_runtime, "acquire_user", return_value=unavailable),
        patch.object(desktop_runtime, "computer_status", return_value=unavailable),
    ):
        result = desktop_runtime.route_desktop_request("show desktop", "session")
    assert result["message"] == "Display bridge is unavailable."
    assert result["card"]["error"] == "Display bridge is unavailable."
