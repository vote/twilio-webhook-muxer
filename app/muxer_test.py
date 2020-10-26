import urllib.parse

import responses  # type: ignore
from twilio.request_validator import RequestValidator

from .config import Config, KeywordConfig
from .muxer import TwilioMuxer

MOCK_AUTH_TOKEN = "abcd"
MOCK_MUXER_URL = "https://examplemuxer.com"
MOCK_WEBHOOK_PAYLOAD = "foo=bar&1=2"
PARSED_MOCK_WEBHOOK_PAYLOAD = {"foo": "bar", "1": "2"}
MOCK_WEBHOOK_CONTENT_TYPE = "application/x-www-form-urlencoded"
MOCK_WEBHOOK_IDEMPOTENCY_TOKEN = "sometoken"
MOCK_WEBHOOK_USER_AGENT = "mock-twilio"


def sign_request(url, parsed_body):
    return RequestValidator(MOCK_AUTH_TOKEN).compute_signature(url, parsed_body)


def mux_request(config, body="foobar"):
    muxer = TwilioMuxer(
        twilio_auth_token=MOCK_AUTH_TOKEN,
        muxer_url=MOCK_MUXER_URL,
        config=config,
    )

    request_with_body = f"Body={urllib.parse.quote_plus(body)}&{MOCK_WEBHOOK_PAYLOAD}"
    parsed_request_with_body = {"Body": body, **PARSED_MOCK_WEBHOOK_PAYLOAD}

    return muxer.mux_request(
        request_with_body,
        {
            "X-Twilio-Signature": sign_request(
                MOCK_MUXER_URL, parsed_request_with_body
            ),
            "Content-Type": MOCK_WEBHOOK_CONTENT_TYPE,
            "I-Twilio-Idempotency-Token": MOCK_WEBHOOK_IDEMPOTENCY_TOKEN,
            "User-Agent": MOCK_WEBHOOK_USER_AGENT,
            "Cloudfront-Foo": "xxx",
        },
    )


def mock_response(
    downstream_url,
    request_body="foobar",
    body="<Response>some response</Response>",
    content_type="application/xml",
    status=200,
    raise_exception=False,
):
    request_with_body = (
        f"Body={urllib.parse.quote_plus(request_body)}&{MOCK_WEBHOOK_PAYLOAD}"
    )
    parsed_request_with_body = {"Body": request_body, **PARSED_MOCK_WEBHOOK_PAYLOAD}

    def request_callback(request):
        # check body
        assert request.body == request_with_body

        # check signature
        assert request.headers["X-Twilio-Signature"] == sign_request(
            downstream_url, parsed_request_with_body
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
            responses.POST, downstream_url, body=Exception("Some connection error")
        )
    else:
        responses.add_callback(
            responses.POST,
            downstream_url,
            callback=request_callback,
        )


# No responder

# Responder returns success

# Responder returns failure

# Responder errors

# Keyword matching - matched
# Keyword matching - default


@responses.activate
def test_no_responder():
    mock_response("https://downstream1.com")
    mock_response("https://downstream2.com")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com", "https://downstream2.com"],
                    responder=None,
                ),
                keywords={},
            )
        )
        == (200, "<Response></Response>", {"Content-Type": "application/xml"})
    )


@responses.activate
def test_responder_success():
    mock_response(
        "https://downstream1.com", body="body1", content_type="content1", status=201
    )
    mock_response(
        "https://downstream2.com", body="body2", content_type="content2", status=500
    )

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com", "https://downstream2.com"],
                    responder=0,
                ),
                keywords={},
            )
        )
        == (201, "body1", {"Content-Type": "content1"})
    )


@responses.activate
def test_responder_failure():
    mock_response("https://downstream1.com", raise_exception=True)
    mock_response(
        "https://downstream2.com", body="body2", content_type="content2", status=500
    )

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com", "https://downstream2.com"],
                    responder=1,
                ),
                keywords={},
            )
        )
        == (500, "body2", {"Content-Type": "content2"})
    )


@responses.activate
def test_responder_error():
    mock_response("https://downstream1.com")
    mock_response("https://downstream2.com", raise_exception=True)

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com", "https://downstream2.com"],
                    responder=1,
                ),
                keywords={},
            )
        )
        == (500, "<Response></Response>", {"Content-Type": "application/xml"})
    )


@responses.activate
def test_matching_default():
    mock_response("https://downstream1.com", body="d1")
    mock_response("https://downstream2.com", body="d2")
    mock_response("https://downstream3.com", body="d3")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com"],
                    responder=0,
                ),
                keywords={
                    "stop": KeywordConfig(
                        downstreams=["https://downstream2.com"], responder=0
                    ),
                    " HELP ": KeywordConfig(
                        downstreams=["https://downstream3.com"], responder=0
                    ),
                },
            )
        )
        == (200, "d1", {"Content-Type": "application/xml"})
    )

    responses.assert_call_count("https://downstream1.com", 1)
    responses.assert_call_count("https://downstream2.com", 0)
    responses.assert_call_count("https://downstream3.com", 0)


@responses.activate
def test_matching_stop():
    mock_response("https://downstream1.com", body="d1", request_body="stop")
    mock_response("https://downstream2.com", body="d2", request_body="stop")
    mock_response("https://downstream3.com", body="d3", request_body="stop")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com"],
                    responder=0,
                ),
                keywords={
                    "stop": KeywordConfig(
                        downstreams=["https://downstream2.com"], responder=0
                    ),
                    " HELP ": KeywordConfig(
                        downstreams=["https://downstream3.com"], responder=0
                    ),
                },
            ),
            body=" StOP\n",
        )
        == (200, "d2", {"Content-Type": "application/xml"})
    )

    responses.assert_call_count("https://downstream1.com", 0)
    responses.assert_call_count("https://downstream2.com", 1)
    responses.assert_call_count("https://downstream3.com", 0)


@responses.activate
def test_matching_help():
    mock_response("https://downstream1.com", body="d1", request_body="help")
    mock_response("https://downstream2.com", body="d2", request_body="help")
    mock_response("https://downstream3.com", body="d3", request_body="help")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com"],
                    responder=0,
                ),
                keywords={
                    "stop": KeywordConfig(
                        downstreams=["https://downstream2.com"], responder=0
                    ),
                    " HELP ": KeywordConfig(
                        downstreams=["https://downstream3.com"], responder=0
                    ),
                },
            ),
            body="help",
        )
        == (200, "d3", {"Content-Type": "application/xml"})
    )

    responses.assert_call_count("https://downstream1.com", 0)
    responses.assert_call_count("https://downstream2.com", 0)
    responses.assert_call_count("https://downstream3.com", 1)


@responses.activate
def test_alternates():
    mock_response("https://downstream1.com", body="d1", request_body="stop")
    mock_response("https://downstream2.com", body="d2", request_body="stop")
    mock_response("https://downstream3.com", body="d3", request_body="stop")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com"],
                    responder=0,
                ),
                keywords={
                    "stop": KeywordConfig(
                        downstreams=["https://downstream2.com"],
                        responder=0,
                        alternates={
                            "stip",
                            "stop texting me",
                        },
                    ),
                    " HELP ": KeywordConfig(
                        downstreams=["https://downstream3.com"], responder=0
                    ),
                },
            ),
            body="stop texting  me!!!!",
        )
        == (200, "d2", {"Content-Type": "application/xml"})
    )

    responses.assert_call_count("https://downstream1.com", 0)
    responses.assert_call_count("https://downstream2.com", 1)
    responses.assert_call_count("https://downstream3.com", 0)


@responses.activate
def test_normalization():
    mock_response("https://downstream1.com", body="d1", request_body="stop")
    mock_response("https://downstream2.com", body="d2", request_body="stop")
    mock_response("https://downstream3.com", body="d3", request_body="stop")

    assert (
        mux_request(
            Config(
                default=KeywordConfig(
                    downstreams=["https://downstream1.com"],
                    responder=0,
                ),
                keywords={
                    "STOP": KeywordConfig(
                        downstreams=["https://downstream2.com"],
                        responder=0,
                        alternates={
                            "stip",
                            "stop texting me",
                        },
                    ),
                    " HELP ": KeywordConfig(
                        downstreams=["https://downstream3.com"], responder=0
                    ),
                },
            ),
            body="stop !!!!",
        )
        == (200, "d2", {"Content-Type": "application/xml"})
    )

    responses.assert_call_count("https://downstream1.com", 0)
    responses.assert_call_count("https://downstream2.com", 1)
    responses.assert_call_count("https://downstream3.com", 0)
