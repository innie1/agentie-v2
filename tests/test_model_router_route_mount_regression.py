import asyncio
import unittest

import main


class ModelRouterRouteMountRegressionTests(unittest.TestCase):
    def test_model_router_routes_are_mounted_on_actual_app(self):
        paths = [getattr(route, "path", None) for route in main.app.routes]
        self.assertEqual(paths.count("/platform/model-routing/status"), 1)
        self.assertEqual(paths.count("/platform/model-routing/mode"), 1)
        self.assertEqual(paths.count("/platform-model-router.js"), 1)

    def test_actual_connected_script_contains_model_mode_control(self):
        routes = [route for route in main.app.routes if getattr(route, "path", None) == "/platform-next4.js"]
        self.assertEqual(len(routes), 1)
        body = asyncio.run(routes[0].endpoint()).body.decode("utf-8")
        for marker in ("model-router-control", "Local", "Auto", "Powerful", "/platform/model-routing/status"):
            self.assertIn(marker, body)


if __name__ == "__main__":
    unittest.main()
