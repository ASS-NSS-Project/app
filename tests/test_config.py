"""
Configuration unit tests for `config.Settings`.

Coverage:
- PostgreSQL URL composition from POSTGRES_* fields.
- S3/CESNET settings mapping (endpoint, credentials, region, path-style, buckets).
- AIaaS model settings mapping (shared base URL/key, LLM/VLM model names).
- Chunking default values for prose/table/VLM strategies.
- Authentication settings defaults and overrides (JWT/admin bootstrap fields).
"""
from config import Settings

def test_settings_database_url():
    s = Settings(
        postgres_user="testuser",
        postgres_password="testpass",
        postgres_host="db.example.com",
        postgres_db="testdb",
    )

    assert s.database_url == "postgresql://testuser:testpass@db.example.com/testdb"


def test_settings_s3_fields():
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
    s = Settings(
        query_base_url="https://llm.example.com/v1",
        query_api_key="query-key",
        query_model="llama-3.3-70b-instruct",
        vlm_base_url="https://vlm.example.com/v1",
        vlm_api_key="vlm-key",
        vlm_model="qwen2.5-vl-7b-instruct",
    )

    assert s.query_base_url == "https://llm.example.com/v1"
    assert s.query_api_key == "query-key"
    assert s.query_model == "llama-3.3-70b-instruct"
    assert s.vlm_base_url == "https://vlm.example.com/v1"
    assert s.vlm_api_key == "vlm-key"
    assert s.vlm_model == "qwen2.5-vl-7b-instruct"


def test_settings_chunking_defaults():
    s = Settings()

    assert s.chunking.prose.target_tokens == 500
    assert s.chunking.prose.overlap_tokens == 50
    assert s.chunking.table.max_tokens == 1500
    assert s.chunking.vlm.max_tokens == 800


def test_settings_auth_fields():
    s = Settings(
        jwt_secret="supersecret",
        first_admin_email="ops@example.com",
        first_admin_password="hunter2",
    )
    
    assert s.jwt_secret == "supersecret"
    assert s.first_admin_email == "ops@example.com"
    assert s.first_admin_password == "hunter2"
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_expire_minutes == 480
