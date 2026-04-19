"""
Unit tests for config.py Settings.

These tests do not require any backing services.
They instantiate Settings directly with controlled values.
"""

from backend.config import Settings  # type: ignore[import]


def test_settings_s3_fields():
    """S3 settings are passed through to fields directly."""
    s = Settings(
        s3_endpoint_url="https://s3.cesnet.cz",
        s3_access_key="mykey",
        s3_secret_key="mysecret",
        s3_region="eu-central-1",
        s3_use_path_style=False,
        s3_bucket_evidence="cesnet-evidence",
        s3_bucket_docs="cesnet-docs",
    )
    assert s.s3_endpoint_url == "https://s3.cesnet.cz"
    assert s.s3_access_key == "mykey"
    assert s.s3_secret_key == "mysecret"
    assert s.s3_region == "eu-central-1"
    assert s.s3_use_path_style is False
    assert s.s3_bucket_evidence == "cesnet-evidence"
    assert s.s3_bucket_docs == "cesnet-docs"


def test_settings_llm_vlm_fields():
    """LLM and VLM settings are passed through to fields directly."""
    s = Settings(
        llm_base_url="https://aiaas.example.com/v1",
        llm_api_key="llm-key",
        llm_model="llama-3.3-70b-instruct",
        vlm_base_url="https://aiaas.example.com/v1",
        vlm_api_key="vlm-key",
        vlm_model="qwen2.5-vl-7b-instruct",
    )
    assert s.llm_base_url == "https://aiaas.example.com/v1"
    assert s.llm_api_key == "llm-key"
    assert s.llm_model == "llama-3.3-70b-instruct"
    assert s.vlm_base_url == "https://aiaas.example.com/v1"
    assert s.vlm_api_key == "vlm-key"
    assert s.vlm_model == "qwen2.5-vl-7b-instruct"


def test_settings_chunking_defaults():
    """Chunking config defaults are sane."""
    s = Settings()
    assert s.chunking.prose.target_tokens == 500
    assert s.chunking.prose.overlap_tokens == 50
    assert s.chunking.table.max_tokens == 1500
    assert s.chunking.vlm.max_tokens == 800
