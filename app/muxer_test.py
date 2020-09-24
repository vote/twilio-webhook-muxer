import responses
from .muxer import TwilioMuxer, is_nonempty_twiml_response
from twilio.request_validator import RequestValidator
import pytest
from unittest.mock import Mock

MOCK_AUTH_TOKEN = "abcd"
MOCK_MUXER_URL = "https://examplemuxer.com"
MOCK_WEBHOOK_PAYLOAD = "foo=bar&1=2"
PARSED_MOCK_WEBHOOK_PAYLOAD = {"foo": "bar", "1": "2"}
MOCK_WEBHOOK_CONTENT_TYPE = "application/x-www-form-urlencoded"
MOCK_WEBHOOK_IDEMPOTENCY_TOKEN = "sometoken"
MOCK_WEBHOOK_USER_AGENT = "mock-twilio"


def sign_request(url, parsed_body):
    return RequestValidator(MOCK_AUTH_TOKEN).compute_signature(url, parsed_body)


def mux_request(*downstream_urls):
    muxer = TwilioMuxer(
        twilio_auth_token=MOCK_AUTH_TOKEN,
        muxer_url=MOCK_MUXER_URL,
        downstream_urls=downstream_urls,
    )

    return muxer.mux_request(
        MOCK_WEBHOOK_PAYLOAD,
        {
            "X-Twilio-Signature": sign_request(
                MOCK_MUXER_URL, PARSED_MOCK_WEBHOOK_PAYLOAD
            ),
            "Content-Type": MOCK_WEBHOOK_CONTENT_TYPE,
            "I-Twilio-Idempotency-Token": MOCK_WEBHOOK_IDEMPOTENCY_TOKEN,
            "User-Agent": MOCK_WEBHOOK_USER_AGENT,
            "Cloudfront-Foo": "xxx",
        },
    )


def mock_response(
    upstream_url,
    body="<Response></Response>",
    content_type="application/xml",
    status=200,
    raise_exception=False,
):
    def request_callback(request):
        # check body
        assert request.body == MOCK_WEBHOOK_PAYLOAD

        # check signature
        assert request.headers["X-Twilio-Signature"] == sign_request(
            upstream_url, PARSED_MOCK_WEBHOOK_PAYLOAD
        )

        # check header passthrough
        assert request.headers["Content-Type"] == MOCK_WEBHOOK_CONTENT_TYPE
        assert (
            request.headers["I-Twilio-Idempotency-Token"]
            == MOCK_WEBHOOK_IDEMPOTENCY_TOKEN
        )
        assert request.headers["User-Agent"] == MOCK_WEBHOOK_USER_AGENT
        assert request.headers.get("Cloudfront-Foo") == None

        # Return result
        return (status, {"Content-Type": content_type}, body)

    if raise_exception:
        responses.add(
            responses.POST, upstream_url, body=Exception("Some connection error")
        )
    else:
        responses.add_callback(
            responses.POST, upstream_url, callback=request_callback,
        )


@responses.activate
def test_basic_requests():
    mock_response("https://upstream1.com")
    mock_response("https://upstream2.com")

    assert (
        mux_request("https://upstream1.com", "https://upstream2.com")
        == "<Response></Response>"
    )


@responses.activate
def test_request_errors():
    # If some requests fail, the others should go through
    mock_response("https://upstream1.com", raise_exception=True)
    mock_response("https://upstream2.com", status=500)
    mock_response("https://upstream3.com")

    assert (
        mux_request(
            "https://upstream1.com", "https://upstream2.com", "https://upstream3.com"
        )
        == "<Response></Response>"
    )


@responses.activate
def test_response_priority():
    mock_response("https://upstream1.com", raise_exception=True)
    mock_response("https://upstream2.com", status=500, body="<Response>aaa</Response>")
    mock_response("https://upstream3.com")
    mock_response(
        "https://upstream4.com", body='{"x": "y"}', content_type="application/json"
    )
    mock_response("https://upstream5.com", body="<Response>bbb</Response>")
    mock_response("https://upstream6.com", body="<Response>ccc</Response>")

    assert (
        mux_request(
            "https://upstream1.com",
            "https://upstream2.com",
            "https://upstream3.com",
            "https://upstream4.com",
            "https://upstream5.com",
            "https://upstream6.com",
        )
        == "<Response>bbb</Response>"
    )


@pytest.mark.parametrize(
    "status_code,content_type,text,expected",
    [
        (200, "application/xml", "<Response>xxx</Response>", True),
        (200, "text/xml", "<Response>xxx</Response>", True),
        (200, "text/html", "<Response>xxx</Response>", True),
        (201, "application/xml", "<Response>xxx</Response>", True),
        (500, "application/xml", "<Response>xxx</Response>", False),
        (200, "application/json", "<Response>xxx</Response>", False),
        (200, "application/xml", "<Response></Response>", False),
        (200, "application/xml", "<response> \n \t </RESPONSE>", False),
        (200, "application/xml", "  ", False),
        (200, "application/xml", "\n", False),
        (200, "application/xml", "", False),
    ],
)
def test_is_nonempty_twiml_response(status_code, content_type, text, expected):
    assert (
        is_nonempty_twiml_response(
            Mock(
                status_code=status_code,
                headers={"content-type": content_type},
                text=text,
            )
        )
        == expected
    )
