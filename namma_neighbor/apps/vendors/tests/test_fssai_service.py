import datetime
import pytest
import requests
from unittest.mock import patch, Mock
from apps.vendors.services.fssai import SurepassFSSAIClient
from apps.core.exceptions import FSSAIVerificationError, TransientAPIError


def make_mock_response(status_code, json_data):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


VALID_RESPONSE = {
    "success": True,
    "data": {
        "license_status": "active",
        "business_name": "Ravi's Kitchen",
        "expiry_date": "2026-03-31",
        "authorized_categories": ["dairy", "bakery"],
    },
}

EXPIRY_RESPONSE = {
    "success": True,
    "data": {
        "license_status": "active",
        "expiry_date": "2026-03-31",
    },
}


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_returns_normalized_dict(mock_post):
    mock_post.return_value = make_mock_response(200, VALID_RESPONSE)
    client = SurepassFSSAIClient()
    result = client.verify_fssai("12345678901234")
    assert result["status"] == "active"
    assert result["business_name"] == "Ravi's Kitchen"
    assert result["expiry_date"] == datetime.date(2026, 3, 31)
    assert result["authorized_categories"] == ["dairy", "bakery"]


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_on_http_400(mock_post):
    mock_post.return_value = make_mock_response(400, {"success": False})
    client = SurepassFSSAIClient()
    with pytest.raises(FSSAIVerificationError):
        client.verify_fssai("invalid")


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_on_http_404(mock_post):
    mock_post.return_value = make_mock_response(404, {"success": False})
    client = SurepassFSSAIClient()
    with pytest.raises(FSSAIVerificationError):
        client.verify_fssai("notfound")


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_transient_on_http_500(mock_post):
    mock_post.return_value = make_mock_response(500, {})
    client = SurepassFSSAIClient()
    with pytest.raises(TransientAPIError):
        client.verify_fssai("12345678901234")


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_transient_on_http_429(mock_post):
    mock_post.return_value = make_mock_response(429, {})
    client = SurepassFSSAIClient()
    with pytest.raises(TransientAPIError):
        client.verify_fssai("12345678901234")


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_transient_on_timeout(mock_post):
    mock_post.side_effect = requests.Timeout()
    client = SurepassFSSAIClient()
    with pytest.raises(TransientAPIError):
        client.verify_fssai("12345678901234")


@patch("apps.vendors.services.fssai.requests.post")
def test_verify_fssai_raises_transient_on_connection_error(mock_post):
    mock_post.side_effect = requests.ConnectionError()
    client = SurepassFSSAIClient()
    with pytest.raises(TransientAPIError):
        client.verify_fssai("12345678901234")


@patch("apps.vendors.services.fssai.requests.post")
def test_check_expiry_calls_expiry_endpoint(mock_post):
    mock_post.return_value = make_mock_response(200, EXPIRY_RESPONSE)
    client = SurepassFSSAIClient()
    client.check_expiry("12345678901234")
    called_url = mock_post.call_args.args[0]
    assert "fssai-expiry-check" in called_url
    assert "fssai-full-details" not in called_url


@patch("apps.vendors.services.fssai.requests.post")
def test_check_expiry_returns_normalized_dict(mock_post):
    mock_post.return_value = make_mock_response(200, EXPIRY_RESPONSE)
    client = SurepassFSSAIClient()
    result = client.check_expiry("12345678901234")
    assert result["status"] == "active"
    assert result["expiry_date"] == datetime.date(2026, 3, 31)
