import os
import concurrent.futures
from typing import Any, Dict, List
from urllib.parse import parse_qsl
import logging

import requests
import sentry_sdk
import re
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from twilio.request_validator import RequestValidator

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    environment=os.environ["SENTRY_ENVIRONMENT"],
    integrations=[AwsLambdaIntegration()],
)
# Which request headers should be passed downstream
PRESERVE_HEADERS = {"content-type", "i-twilio-idempotency-token", "user-agent"}


def is_nonempty_twiml_response(response: Any) -> bool:
    if response.status_code < 200 or response.status_code >= 300:
        return False

    if response.headers.get("content-type") not in (
        "application/xml",
        "text/xml",
        "text/html",
    ):
        return False

    if re.sub(r"\s", "", response.text.lower()) in ("", "<response></response>"):
        return False

    return True


class TwilioMuxer:
    def __init__(
        self, twilio_auth_token: str, muxer_url: str, downstream_urls: List[str]
    ):
        self.validator = RequestValidator(twilio_auth_token)
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

        return requests.post(url, data=parsed_body, headers=downstream_headers)

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

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(
                    self.make_downstream_request, url, parsed_body, request_headers
                )
                for url in self.downstream_urls
            ]

            response = None
            for url, future in zip(self.downstream_urls, futures):
                try:
                    result = future.result()
                except Exception as e:
                    logging.exception(f"Request failed to downstream {url}")
                    sentry_sdk.capture_exception(e)
                    continue

                try:
                    result.raise_for_status()
                except Exception as e:
                    logging.exception(
                        f"Request to downstream {url} return status code {result.status_code}"
                    )
                    sentry_sdk.capture_exception(e)
                    continue

                if (not response) and is_nonempty_twiml_response(result):
                    response = result.text

        return response or "<Response></Response>"


muxer = TwilioMuxer(
    twilio_auth_token=os.environ["TWILIO_AUTH_TOKEN"],
    muxer_url=os.environ["TWILIO_CALLBACK_URL"],
    downstream_urls=[u.strip() for u in os.environ["DOWNSTREAM_URLS"].split(",")],
)


def handler(event: Any, context: Any):
    request_body = event["body"]
    request_headers = event["headers"]

    twiml_response = muxer.mux_request(request_body, request_headers)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/xml"},
        "body": twiml_response,
    }
