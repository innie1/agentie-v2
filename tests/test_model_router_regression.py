import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agentie.core import model_routing, runner
from agentie.models import provider


class ModelRouterRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_file = model_routing.ROUTING_FILE
        self.old_workspace = model_routing.WORKSPACE
        root = Path(self.temp.name)
        model_routing.WORKSPACE = root
        model_routing.ROUTING_FILE = root / "model_routing.json"
        model_routing._STATUS_CACHE["at"] = 0.0
        model_routing._STATUS_CACHE["value"] = None
        runner._PROVIDER_COOLDOWNS.clear()

    def tearDown(self):
        runner._PROVIDER_COOLDOWNS.clear()
        model_routing.ROUTING_FILE = self.old_file
        model_routing.WORKSPACE = self.old_workspace
        model_routing._STATUS_CACHE["at"] = 0.0
        model_routing._STATUS_CACHE["value"] = None
        self.temp.cleanup()

    def test_default_mode_is_auto_and_mode_persists(self):
        self.assertEqual(model_routing.get_mode(), "auto")
        state = model_routing.set_mode("local")
        self.assertEqual(state["mode"], "local")
        self.assertEqual(model_routing.get_mode(), "local")
        self.assertTrue(model_routing.ROUTING_FILE.exists())

    def test_invalid_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "local, auto, or powerful"):
            model_routing.set_mode("mystery")

    def test_auto_prefers_local_for_simple_work(self):
        route = model_routing.choose_model_route("Summarize these notes in three bullets.", mode="auto", local_available=True, cloud_configured=True)
        self.assertEqual(route["tier"], "local")
        self.assertEqual(route["reason"], "local_default")
        self.assertTrue(route["allow_cloud_fallback"])

    def test_auto_routes_complex_or_consequential_work_to_powerful(self):
        for message in (
            "Debug this repository and implement the fix, then commit it.",
            "Send this customer email after checking the details.",
            "Do deep research on the latest market changes.",
        ):
            route = model_routing.choose_model_route(message, mode="auto", local_available=True, cloud_configured=True)
            self.assertEqual(route["tier"], "powerful", message)
            self.assertTrue(route["task"]["requires_powerful"], message)

    def test_manual_local_never_allows_cloud_fallback(self):
        route = model_routing.choose_model_route("Commit and push this repository change.", mode="local", local_available=True, cloud_configured=True)
        self.assertEqual(route["tier"], "local")
        self.assertFalse(route["allow_cloud_fallback"])
        self.assertEqual(route["reason"], "manual_local")

    def test_manual_powerful_always_uses_cloud_tier(self):
        route = model_routing.choose_model_route("Say hello.", mode="powerful", local_available=True, cloud_configured=True)
        self.assertEqual(route["tier"], "powerful")
        self.assertEqual(route["reason"], "manual_powerful")

    def test_auto_uses_powerful_when_local_runtime_is_unavailable(self):
        route = model_routing.choose_model_route("Summarize this.", mode="auto", local_available=False, cloud_configured=True)
        self.assertEqual(route["tier"], "powerful")
        self.assertEqual(route["reason"], "local_runtime_unavailable")

    def test_auto_best_effort_local_when_complex_but_cloud_is_not_configured(self):
        route = model_routing.choose_model_route("Debug this codebase and implement the fix.", mode="auto", local_available=True, cloud_configured=False)
        self.assertEqual(route["tier"], "local")
        self.assertEqual(route["reason"], "cloud_unavailable_best_effort_local")
        self.assertFalse(route["allow_cloud_fallback"])

    def test_local_escalation_only_accepts_model_runtime_failures(self):
        self.assertTrue(model_routing.should_escalate_local_error(RuntimeError("connection refused")))
        self.assertTrue(model_routing.should_escalate_local_error(RuntimeError("404 model 'gemma4' not found")))
        self.assertTrue(model_routing.should_escalate_local_error(RuntimeError("tools are not supported")))
        self.assertFalse(model_routing.should_escalate_local_error(RuntimeError("approval required before sending")))
        self.assertFalse(model_routing.should_escalate_local_error(RuntimeError("permission denied for this action")))

    def test_local_provider_is_openai_compatible_and_configurable(self):
        with patch.dict(os.environ, {"AGENTIE_LOCAL_MODEL": "gemma4:test", "AGENTIE_LOCAL_BASE_URL": "http://127.0.0.1:9999/v1/"}, clear=False):
            info = provider.get_provider_info("local")
        self.assertEqual(info["provider"], "local")
        self.assertEqual(info["tier"], "local")
        self.assertEqual(info["model"], "gemma4:test")
        self.assertEqual(info["base_url"], "http://127.0.0.1:9999/v1")

    def test_auto_runner_retries_once_on_safe_local_runtime_failure(self):
        route = {"mode": "auto", "tier": "local", "reason": "local_default", "local_available": True, "cloud_configured": True, "task": {"score": 0, "reasons": []}, "allow_cloud_fallback": True}
        local = {"provider": "local", "tier": "local", "model": "gemma4", "base_url": "http://127.0.0.1:11434/v1"}
        cloud = {"provider": "gemini", "tier": "powerful", "model": "cloud-model", "base_url": "https://example.invalid"}
        def info(tier="powerful"):
            return local if tier == "local" else cloud
        attempt = AsyncMock(side_effect=[RuntimeError("connection refused"), "cloud answer"])
        with patch.object(runner, "choose_model_route", return_value=route), \
             patch.object(runner, "get_provider_info", side_effect=info), \
             patch.object(runner, "_attempt", new=attempt), \
             patch.object(runner, "record_event") as event:
            output = asyncio.run(runner.run_agent("simple task", "general", None))
        self.assertEqual(output, "cloud answer")
        self.assertEqual(attempt.await_count, 2)
        self.assertTrue(any(call.args and call.args[0] == "model_escalation" for call in event.call_args_list))

    def test_local_runner_does_not_retry_cloud(self):
        route = {"mode": "local", "tier": "local", "reason": "manual_local", "local_available": True, "cloud_configured": True, "task": {"score": 0, "reasons": []}, "allow_cloud_fallback": False}
        local = {"provider": "local", "tier": "local", "model": "gemma4", "base_url": "http://127.0.0.1:11434/v1"}
        attempt = AsyncMock(side_effect=RuntimeError("connection refused"))
        with patch.object(runner, "choose_model_route", return_value=route), \
             patch.object(runner, "get_provider_info", return_value=local), \
             patch.object(runner, "_attempt", new=attempt):
            with self.assertRaisesRegex(RuntimeError, "Local mode will not send this task to a cloud model"):
                asyncio.run(runner.run_agent("simple task", "general", None))
        self.assertEqual(attempt.await_count, 1)

    def test_connected_platform_exposes_model_router_api_and_ui(self):
        from agentie.core import platform_next4_api
        paths = [getattr(r, "path", None) for r in platform_next4_api.router.routes]
        self.assertIn("/platform/model-routing/status", paths)
        self.assertIn("/platform/model-routing/mode", paths)
        self.assertIn("/platform-model-router.js", paths)
        layer = next(r for r in platform_next4_api.router.routes if getattr(r, "path", None) == "/platform-next4.js")
        body = asyncio.run(layer.endpoint()).body.decode("utf-8")
        for marker in ("model-router-control", "Local", "Auto", "Powerful", "/platform/model-routing/mode"):
            self.assertIn(marker, body)

    def test_runner_source_records_route_and_escalation_reason(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertIn('record_event("model_route"', source)
        self.assertIn('record_event("model_escalation"', source)
        self.assertIn("allow_cloud_fallback", source)

    def test_example_env_documents_local_model_without_new_python_dependency(self):
        root = Path(__file__).resolve().parents[1]
        env = (root / ".env.example").read_text(encoding="utf-8")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        for marker in ("AGENTIE_LOCAL_MODEL=gemma4", "AGENTIE_LOCAL_BASE_URL", "AGENTIE_LOCAL_ENABLED"):
            self.assertIn(marker, env)
        self.assertNotIn("ollama>=", pyproject.lower())


if __name__ == "__main__":
    unittest.main()
