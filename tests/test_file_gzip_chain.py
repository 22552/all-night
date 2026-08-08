import gzip
import os

from night import Night, _gzip_cached_file, send_file


def test_send_file_can_be_registered_directly_and_returned(tmp_path):
    source = tmp_path / "hello.txt"
    source.write_text("hello night")

    app = Night()
    app.get("/direct", send_file(str(source)))

    @app.get("/returned")
    def returned():
        return send_file(str(source))

    with app.test_client() as client:
        direct = client.get("/direct")
        returned_response = client.get("/returned")

    assert direct.text == "hello night"
    assert returned_response.text == "hello night"
    assert "content-encoding" not in direct.headers
    assert "content-encoding" not in returned_response.headers


def test_file_gzip_chain_global_default_and_raw_override(tmp_path):
    payload = ("Night gzip chain!" * 256).encode()
    source = tmp_path / "payload.txt"
    source.write_bytes(payload)

    app = Night()
    app.get("/forced", send_file(str(source)).gz())
    app.gz(9)
    app.get("/global", send_file(str(source)))
    app.get("/raw", send_file(str(source)).raw())

    @app.get("/returned")
    def returned():
        return send_file(str(source))

    with app.test_client() as client:
        forced = client.get("/forced")
        global_default = client.get("/global")
        raw = client.get("/raw")
        returned_response = client.get("/returned")

    for response in (forced, global_default, returned_response):
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["content-type"].startswith("text/plain")
        assert gzip.decompress(response.data) == payload

    assert "content-encoding" not in raw.headers
    assert raw.data == payload


def test_gzip_temp_cache_reuses_and_invalidates_by_source_metadata(tmp_path):
    source = tmp_path / "cache.txt"
    source.write_bytes(b"a" * 4096)

    first, first_key, _ = _gzip_cached_file(str(source), 6)
    second, second_key, _ = _gzip_cached_file(str(source), 6)
    assert first == second
    assert first_key == second_key
    assert os.path.isfile(first)
    assert gzip.decompress(open(first, "rb").read()) == b"a" * 4096

    source.write_bytes(b"b" * 4097)
    third, third_key, _ = _gzip_cached_file(str(source), 6)
    assert third != first
    assert third_key != first_key
    assert gzip.decompress(open(third, "rb").read()) == b"b" * 4097
