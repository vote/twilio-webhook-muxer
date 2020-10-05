import pytest
import base64
import json
from .config import KeywordConfig, Config, parse_config
from pydantic import ValidationError


def test_valid_config():
    assert parse_config(
        base64.b64encode(
            json.dumps(
                {
                    "default": {
                        "downstreams": [
                            "http://a.com",
                            "https://b.example.com:123/a/b?c#d",
                        ],
                        "responder": 1,
                    },
                    "keywords": {
                        " STOp\n": {"downstreams": ["http://c.com"], "responder": 0,},
                        "start": {"downstreams": ["http://c.com"], "responder": None},
                    },
                }
            ).encode()
        )
    ) == Config(
        default=KeywordConfig(
            downstreams=["http://a.com", "https://b.example.com:123/a/b?c#d"],
            responder=1,
        ),
        keywords={
            "stop": KeywordConfig(downstreams=["http://c.com"], responder=0),
            "start": KeywordConfig(downstreams=["http://c.com"], responder=None),
        },
    )


def test_missing_field():
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "keywords": {
                            "STOP": {"downstreams": ["http://c.com"], "responder": 0,}
                        },
                    }
                ).encode()
            )
        )


def test_nested_error():
    # default.downstreams is str, not list
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "default": {"downstreams": "http://a.com", "responder": 0,},
                        "keywords": {
                            "STOP": {"downstreams": ["http://c.com"], "responder": 0,}
                        },
                    }
                ).encode()
            )
        )

    # keywords.STOP is missing downstreams
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "default": {
                            "downstreams": [
                                "http://a.com",
                                "https://b.example.com:123/a/b?c#d",
                            ],
                            "responder": 0,
                        },
                        "keywords": {"STOP": {"responder": 0}},
                    }
                ).encode()
            )
        )


def test_negative_responder():
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "default": {
                            "downstreams": [
                                "http://a.com",
                                "https://b.example.com:123/a/b?c#d",
                            ],
                            "responder": -1,
                        },
                        "keywords": {
                            "STOP": {"downstreams": ["http://c.com"], "responder": 0,}
                        },
                    }
                ).encode()
            )
        )


def test_responder_oob():
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "default": {
                            "downstreams": [
                                "http://a.com",
                                "https://b.example.com:123/a/b?c#d",
                            ],
                            "responder": 2,
                        },
                        "keywords": {
                            "STOP": {"downstreams": ["http://c.com"], "responder": 0,}
                        },
                    }
                ).encode()
            )
        )


def test_invalid_url():
    with pytest.raises(ValidationError):
        parse_config(
            base64.b64encode(
                json.dumps(
                    {
                        "default": {
                            "downstreams": [
                                "xxx",
                                "https://b.example.com:123/a/b?c#d",
                            ],
                            "responder": 1,
                        },
                        "keywords": {
                            "STOP": {"downstreams": ["http://c.com"], "responder": 0,}
                        },
                    }
                ).encode()
            )
        )
