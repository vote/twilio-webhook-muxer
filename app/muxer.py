import json
from typing import Any, Dict, List
import sentry_sdk
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from urllib.parse import parse_qsl
import os
from twilio.request_validator import RequestValidator
from threading import Thread
import requests

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    environment=os.environ["SENTRY_ENVIRONMENT"],
    integrations=[AwsLambdaIntegration()],
)
# Which request headers should be passed downstream
PRESERVE_HEADERS = {"content-type", "i-twilio-idempotency-token", "user-agent"}


class TwilioMuxer:
    def __init__(
        self, twilio_auth_token: str, muxer_url: str, downstream_urls: List[str]
    ):
        self.validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
        self.muxer_url = muxer_url
        self.downstream_urls = downstream_urls

    def make_downstream_request(
        self, url: str, parsed_body: Dict[str, str], request_headers: Dict[str, str]
    ):
        downstream_headers = {
            k: v for k, v in request_headers.items() if k.lower() in PRESERVE_HEADERS
        }

        downstream_headers["X-Twilio-Signature"] = self.validator.compute_signature(
            url, parsed_body
        )

        requests.post(url, data=parsed_body, headers=downstream_headers)

    def mux_request(self, request_body: str, request_headers: Dict[str, str]):
        parsed_body = dict(parse_qsl(request_body, keep_blank_values=True))

        request_valid = self.validator.validate(
            self.muxer_url,
            parsed_body,
            request_headers.get(
                "x-twilio-signature", request_headers.get("X-Twilio-Signature")
            ),
        )

        if not request_valid:
            raise RuntimeError(f"Invalid Twilio signature")

        threads = [
            Thread(
                target=self.make_downstream_request,
                args=(url, parsed_body, request_headers),
            )
            for url in self.downstream_urls
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()


muxer = TwilioMuxer(
    twilio_auth_token=os.environ["TWILIO_AUTH_TOKEN"],
    muxer_url=os.environ["TWILIO_CALLBACK_URL"],
    downstream_urls=[u.strip() for u in os.environ["DOWNSTREAM_URLS"].split(",")],
)


def handler(event: Any, context: Any):
    request_body = event["body"]
    request_headers = event["headers"]

    muxer.mux_request(request_body, request_headers)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True}),
    }
