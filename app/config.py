from typing import List, Dict, Any, Optional
import base64
import json
from pydantic import BaseModel, validator
import re

# From https://github.com/django/django/blob/stable/1.3.x/django/core/validators.py#L45
# but no ftp:// support
url_regex = re.compile(
    r"^(?:http)s?://"  # http:// or https://
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain...
    r"localhost|"  # localhost...
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ...or ip
    r"(?::\d+)?"  # optional port
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


class KeywordConfig(BaseModel):
    downstreams: List[str]
    responder: Optional[int]

    @validator("responder")
    def responder_must_be_a_valid_index(cls, v, values, **kwargs):
        if v is not None:
            if v < 0:
                raise ValueError("responder must be >= 0")

            if v >= len(values.get("downstreams", [])):
                raise ValueError("responder is out-of-bounds of the downstreams list")

        return v

    @validator("downstreams")
    def downstreams_must_be_urls(cls, v):
        for url in v:
            if not url_regex.fullmatch(url):
                raise ValueError(f"Invalid URL: {url}")

        return v


class Config(BaseModel):
    default: KeywordConfig
    keywords: Dict[str, KeywordConfig]

    @validator("keywords")
    def normalize_keywords(cls, keywords):
        return {k.lower().strip(): v for k, v in keywords.items()}


def parse_config(config_env: str) -> Config:
    # Base64-decode the config. We have to base64-encode because Lambda does
    # not support having commas in environment variables
    config = json.loads(base64.b64decode(config_env))
    return Config(**config)

