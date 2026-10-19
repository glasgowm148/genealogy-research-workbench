import unittest
from unittest.mock import Mock

from genealogy.adapters import (
    WikiTreeApiError,
    WikiTreeHttpClient,
    WikiTreeRequestError,
    WikiTreeResponseError,
    WikiTreeWafChallengeError,
)


def response(*, status_code=200, headers=None, data=None, text=""):
    result = Mock()
    result.status_code = status_code
    result.headers = headers or {"Content-Type": "application/json"}
    result.text = text
    result.json.return_value = data if data is not None else [{"status": 0}]
    return result


class WikiTreeHttpClientTests(unittest.TestCase):
    def test_configuration_and_explicit_app_id_are_passed_to_transport(self) -> None:
        transport = Mock(return_value=response(data=[{"status": 0, "profile": {}}]))
        client = WikiTreeHttpClient(
            app_id="ExampleResearch",
            transport=transport,
            base_url="https://example.invalid/api.php",
            timeout=12,
            headers={"X-Test": "yes"},
        )

        envelope = client.post({"action": "getProfile"})

        self.assertEqual(envelope["status"], 0)
        transport.assert_called_once_with(
            "https://example.invalid/api.php",
            data={"action": "getProfile", "appId": "ExampleResearch"},
            timeout=12,
            headers={"X-Test": "yes"},
        )

    def test_retries_transport_and_server_failures_with_injected_backoff(self) -> None:
        unavailable = response(status_code=503, headers={"Retry-After": "invalid"})
        success = response(data=[{"status": 0, "profile": {"Name": "Example-1"}}])
        transport = Mock(side_effect=[OSError("offline"), unavailable, success])
        sleeper = Mock()
        client = WikiTreeHttpClient(
            app_id="ExampleResearch",
            transport=transport,
            max_attempts=3,
            backoff=lambda attempt: attempt + 0.5,
            sleeper=sleeper,
        )

        result = client.post({"action": "getProfile"})

        self.assertEqual(result["profile"]["Name"], "Example-1")
        self.assertEqual(sleeper.call_args_list[0].args, (1.5,))
        self.assertEqual(sleeper.call_args_list[1].args, (2.5,))

    def test_transport_failure_reports_configured_attempt_count(self) -> None:
        client = WikiTreeHttpClient(
            app_id="ExampleResearch",
            transport=Mock(side_effect=OSError("offline")),
            max_attempts=2,
            sleeper=Mock(),
        )
        with self.assertRaisesRegex(WikiTreeRequestError, "after 2 attempts: offline"):
            client.post({"action": "getProfile"})

    def test_waf_non_json_malformed_and_api_errors_are_distinguished(self) -> None:
        cases = [
            (
                response(status_code=202, headers={"X-Amzn-Waf-Action": "challenge"}),
                WikiTreeWafChallengeError,
                "AWS WAF challenged",
            ),
            (
                response(headers={"Content-Type": "text/html"}, text="<html>blocked</html>"),
                WikiTreeResponseError,
                "non-JSON content: <html>blocked</html>",
            ),
            (response(data={"status": 0}), WikiTreeResponseError, "Unexpected empty response"),
            (response(data=["invalid"]), WikiTreeResponseError, "response structure"),
            (response(data=[{"status": "Error"}]), WikiTreeApiError, "status: 'Error'"),
        ]
        for result, error_type, message in cases:
            with self.subTest(error_type=error_type):
                client = WikiTreeHttpClient(app_id="ExampleResearch", transport=Mock(return_value=result))
                with self.assertRaisesRegex(error_type, message):
                    client.post({"action": "getProfile"})

    def test_invalid_json_includes_a_short_content_preview(self) -> None:
        result = response(text="line one\nline two")
        result.json.side_effect = ValueError("invalid JSON")
        client = WikiTreeHttpClient(app_id="ExampleResearch", transport=Mock(return_value=result))
        with self.assertRaisesRegex(WikiTreeResponseError, "line one line two"):
            client.post({"action": "getProfile"})


if __name__ == "__main__":
    unittest.main()
