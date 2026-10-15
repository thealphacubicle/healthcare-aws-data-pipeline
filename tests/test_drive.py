import requests

from healthcare_pipeline.drive import GoogleDriveClient


def test_api_key_is_sent_with_every_request():
    session = GoogleDriveClient.from_api_key("test-key")._session
    request = session.prepare_request(
        requests.Request("GET", "https://example.com", params={"q": "x"})
    )
    assert "key=test-key" in request.url
    assert "q=x" in request.url
