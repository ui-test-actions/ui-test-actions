import unittest
from unittest.mock import Mock

from webdriver_driver import WebDriverConnection, WebDriverMobile, parse_source


class WebDriverTest(unittest.TestCase):
    def test_only_accepts_explicit_loopback(self):
        for url in ("https://127.0.0.1:4723", "http://localhost:4723", "http://192.0.2.1:4723",
                    "http://127.0.0.1:4723/foo", "http://127.0.0.1:4723?hello", "http://user@127.0.0.1:4723"):
            with self.assertRaises(ValueError):
                WebDriverConnection(url)
        connector = WebDriverConnection("http://127.0.0.1:4723/wd/hub")
        self.assertEqual((connector.host, connector.port, connector.path), ("127.0.0.1", 4723, "/wd/hub"))

    def test_tree_coordinates_and_secure_values(self):
        source = ('<App><XCUIElementTypeButton name="Save" x="10" y="20" width="100" height="50"/>'
                  '<XCUIElementTypeSecureTextField name="private" value="private" label="private"/></App>')
        tree = parse_source(source, (2, 3))
        self.assertEqual(tree["nodes"][1]["bounds"], {"x": 20, "y": 60, "width": 200, "height": 150})
        self.assertEqual((tree["nodes"][2]["name"], tree["nodes"][2]["text"]), ("", ""))
        with self.assertRaises(RuntimeError):
            parse_source('<!DOCTYPE App [<!ENTITY x "unsafe">]><App/>', (1, 1))

    def test_synchronized_touch_tracks(self):
        driver = WebDriverMobile.__new__(WebDriverMobile)
        driver.scale, driver.viewport = (2, 2), (100, 100)
        driver.call = Mock()
        tracks = [
            [{"x": 50, "y": 50, "duration_ms": 0}, {"x": 40, "y": 40, "duration_ms": 450}],
            [{"x": 70, "y": 70, "duration_ms": 0}, {"x": 80, "y": 80, "duration_ms": 450}],
        ]
        self.assertEqual(driver.gesture(tracks), {"fingers": 2})
        method, path, body = driver.call.call_args.args
        self.assertEqual((method, path), ("POST", "/actions"))
        self.assertEqual([finger["actions"][2]["duration"] for finger in body["actions"]], [450, 450])
        self.assertEqual(body["actions"][0]["actions"][2]["x"], 20)
        tracks[1][1]["duration_ms"] = 350
        with self.assertRaises(ValueError):
            driver.gesture(tracks)
        driver.call.assert_called_once()
