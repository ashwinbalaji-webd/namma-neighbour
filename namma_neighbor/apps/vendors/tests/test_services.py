import pytest
import requests
from unittest.mock import patch, Mock

from apps.vendors.services.razorpay import RazorpayClient
from apps.core.exceptions import RazorpayError, TransientAPIError


def make_response(status_code, json_data=None):
    r = Mock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    return r


@pytest.fixture
def razorpay_client():
    return RazorpayClient()


# --- create_linked_account ---

@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_calls_correct_url(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(200, {"id": "acc_test123"})
    razorpay_client.create_linked_account(vendor)
    url = mock_post.call_args.args[0]
    assert url.endswith("/v2/accounts")


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_payload_type_route(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(200, {"id": "acc_test123"})
    razorpay_client.create_linked_account(vendor)
    payload = mock_post.call_args.kwargs["json"]
    assert payload["type"] == "route"


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_payload_reference_id(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(200, {"id": "acc_test123"})
    razorpay_client.create_linked_account(vendor)
    payload = mock_post.call_args.kwargs["json"]
    assert payload["reference_id"] == str(vendor.pk)


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_returns_account_id(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(200, {"id": "acc_test123"})
    result = razorpay_client.create_linked_account(vendor)
    assert result == "acc_test123"


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_raises_razorpay_error_on_400(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(400)
    with pytest.raises(RazorpayError):
        razorpay_client.create_linked_account(vendor)


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_raises_razorpay_error_on_409(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(409)
    with pytest.raises(RazorpayError):
        razorpay_client.create_linked_account(vendor)


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_raises_transient_on_500(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(500)
    with pytest.raises(TransientAPIError):
        razorpay_client.create_linked_account(vendor)


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_raises_transient_on_429(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(429)
    with pytest.raises(TransientAPIError):
        razorpay_client.create_linked_account(vendor)


@patch("apps.vendors.services.razorpay.requests.post")
def test_create_linked_account_raises_transient_on_timeout(mock_post, vendor, razorpay_client):
    mock_post.side_effect = requests.Timeout()
    with pytest.raises(TransientAPIError):
        razorpay_client.create_linked_account(vendor)


# --- add_stakeholder ---

@patch("apps.vendors.services.razorpay.requests.post")
def test_add_stakeholder_calls_correct_url(mock_post, vendor, razorpay_client):
    account_id = "acc_test123"
    mock_post.return_value = make_response(200, {"id": "sth_abc"})
    razorpay_client.add_stakeholder(account_id, vendor)
    url = mock_post.call_args.args[0]
    assert f"/v2/accounts/{account_id}/stakeholders" in url


@patch("apps.vendors.services.razorpay.requests.post")
def test_add_stakeholder_returns_stakeholder_id(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(200, {"id": "sth_abc"})
    result = razorpay_client.add_stakeholder("acc_test123", vendor)
    assert result == "sth_abc"


@patch("apps.vendors.services.razorpay.requests.post")
def test_add_stakeholder_raises_razorpay_error_on_400(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(400)
    with pytest.raises(RazorpayError):
        razorpay_client.add_stakeholder("acc_test123", vendor)


@patch("apps.vendors.services.razorpay.requests.post")
def test_add_stakeholder_raises_transient_on_500(mock_post, vendor, razorpay_client):
    mock_post.return_value = make_response(500)
    with pytest.raises(TransientAPIError):
        razorpay_client.add_stakeholder("acc_test123", vendor)


# --- submit_for_review ---

@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_sends_patch_to_correct_url(mock_patch, razorpay_client):
    account_id = "acc_test123"
    mock_patch.return_value = make_response(200, {"id": account_id})
    razorpay_client.submit_for_review(account_id)
    url = mock_patch.call_args.args[0]
    assert f"/v2/accounts/{account_id}" in url


@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_returns_none(mock_patch, razorpay_client):
    mock_patch.return_value = make_response(200, {"id": "acc_test123"})
    result = razorpay_client.submit_for_review("acc_test123")
    assert result is None


@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_raises_razorpay_error_on_400(mock_patch, razorpay_client):
    mock_patch.return_value = make_response(400)
    with pytest.raises(RazorpayError):
        razorpay_client.submit_for_review("acc_test123")


@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_raises_transient_on_500(mock_patch, razorpay_client):
    mock_patch.return_value = make_response(500)
    with pytest.raises(TransientAPIError):
        razorpay_client.submit_for_review("acc_test123")


@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_sends_tnc_accepted_payload(mock_patch, razorpay_client):
    mock_patch.return_value = make_response(200, {"id": "acc_test123"})
    razorpay_client.submit_for_review("acc_test123")
    payload = mock_patch.call_args.kwargs["json"]
    assert payload == {"tnc_accepted": True}


@patch("apps.vendors.services.razorpay.requests.post")
def test_add_stakeholder_raises_transient_on_timeout(mock_post, vendor, razorpay_client):
    mock_post.side_effect = requests.Timeout()
    with pytest.raises(TransientAPIError):
        razorpay_client.add_stakeholder("acc_test123", vendor)


@patch("apps.vendors.services.razorpay.requests.patch")
def test_submit_for_review_raises_transient_on_timeout(mock_patch, razorpay_client):
    mock_patch.side_effect = requests.Timeout()
    with pytest.raises(TransientAPIError):
        razorpay_client.submit_for_review("acc_test123")
