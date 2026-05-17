from nexus.cloudreve.uri import FileUri


def test_file_uri_parses_cloudreve_user_space_with_path_and_query():
    uri = FileUri.parse("cloudreve://luPa@my/projects/report.pdf?name=report")

    assert uri.raw == "cloudreve://luPa@my/projects/report.pdf?name=report"
    assert uri.scheme == "cloudreve"
    assert uri.host == "my"
    assert uri.user == "luPa"
    assert uri.path == "/projects/report.pdf"
    assert uri.query == "name=report"


def test_file_uri_rejects_non_cloudreve_scheme():
    try:
        FileUri.parse("s3://bucket/file.txt")
    except ValueError as exc:
        assert "cloudreve" in str(exc)
    else:
        raise AssertionError("Expected invalid scheme to raise")

