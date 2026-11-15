import os
import unittest
from unittest.mock import Mock, patch

from radar.telegram import send_telegram


class TelegramSenderTests(unittest.TestCase):
    @patch("radar.telegram.requests.post")
    def test_sends_message_to_configured_chat(self, post):
        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        post.return_value = response

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:test-token",
            "TELEGRAM_CHAT_ID": "6069964318",
        }, clear=False):
            result = send_telegram("Test message")

        self.assertTrue(result["ok"])
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "6069964318")
        self.assertEqual(post.call_args.kwargs["json"]["text"], "Test message")
        self.assertIn("/bot123:test-token/sendMessage", post.call_args.args[0])

    @patch("radar.telegram.requests.post")
    def test_surfaces_telegram_api_error_without_exposing_token(self, post):
        response = Mock()
        response.ok = False
        response.status_code = 403
        response.json.return_value = {"ok": False, "description": "bot was blocked by the user"}
        post.return_value = response

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "secret-token",
            "TELEGRAM_CHAT_ID": "6069964318",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "bot was blocked by the user") as err:
                send_telegram("Test message")

        self.assertNotIn("secret-token", str(err.exception))

    def test_reports_missing_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_BOT_TOKEN"):
                send_telegram("Test message")


if __name__ == "__main__":
    unittest.main()
