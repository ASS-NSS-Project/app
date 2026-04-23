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
        aiaas_base_url="https://aiaas.example.com/v1",
        aiaas_api_key="shared-key",
        aiaas_llm_model="llama-3.3-70b-instruct",
        aiaas_vlm_model="qwen2.5-vl-7b-instruct",
    )
    assert s.aiaas_base_url == "https://aiaas.example.com/v1"
    assert s.aiaas_api_key == "shared-key"
    assert s.aiaas_llm_model == "llama-3.3-70b-instruct"
    assert s.aiaas_vlm_model == "qwen2.5-vl-7b-instruct"


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
