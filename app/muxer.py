import os
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl
import logging
import sys

import requests
import sentry_sdk
import re
from sentry_sdk.integrations.aws_lambda import AwsLambdaIntegration
from twilio.request_validator import RequestValidator

from .config import Config, parse_config

# Which request headers should be passed downstream
PRESERVE_HEADERS = {"content-type", "i-twilio-idempotency-token", "user-agent"}

# How long to wait for responses from downstreams (in seconds)
# Twilio has a default timeout of 15 seconds we we will wait up to 10
DOWNSTREAM_TIMEOUT = 10


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
    def __init__(self, twilio_auth_token: str, muxer_url: str, config: Config):
        self.validator = RequestValidator(twilio_auth_token)
        self.muxer_url = muxer_url
        self.config = config

    def mux_request(
        self, request_body: str, request_headers: Dict[str, str]
    ) -> Tuple[int, str, Dict[str, str]]:
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

        request_body_normalized = parsed_body.get("Body", "").strip().lower()
        request_config = self.config.keywords.get(
            request_body_normalized, self.config.default
        )

        def make_downstream_request(url: str) -> Optional[requests.Response]:
            downstream_headers = {
                k: v
                for k, v in request_headers.items()
                if k.lower() in PRESERVE_HEADERS
            }

            downstream_headers["X-Twilio-Signature"] = self.validator.compute_signature(
                url, parsed_body
            )

            try:
                result = requests.post(
                    url, data=parsed_body, headers=downstream_headers
                )
            except Exception as e:
                logging.exception(f"Request failed to downstream {url}")
                sentry_sdk.capture_exception(e)
                return None

            try:
                result.raise_for_status()
            except Exception as e:
                logging.exception(
                    f"Request to downstream {url} return status code {result.status_code}"
                )
                sentry_sdk.capture_exception(e)

            # We return result whether or not raise_for_status() errored -- we're
            # just doing raise_for_status so we can capture errors; we always want
            # to return the result
            return result

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = list(
                executor.map(make_downstream_request, request_config.downstreams)
            )

        if request_config.responder is None:
            return 200, "<Response></Response>", {"Content-Type": "application/xml"}

        result = results[request_config.responder]
        if result is None:
            return 500, "<Response></Response>", {"Content-Type": "application/xml"}

        return result.status_code, result.text, dict(result.headers)


if "pytest" not in sys.modules:
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=os.environ["SENTRY_ENVIRONMENT"],
        integrations=[AwsLambdaIntegration()],
    )

    muxer = TwilioMuxer(
        twilio_auth_token=os.environ["TWILIO_AUTH_TOKEN"],
        muxer_url=os.environ["TWILIO_CALLBACK_URL"],
        config=parse_config(os.environ["DOWNSTREAM_CONFIG"]),
    )


def handler(event: Any, context: Any):
    request_body = event["body"]
    request_headers = event["headers"]

    status_code, body, headers = muxer.mux_request(request_body, request_headers)

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": body,
    }
