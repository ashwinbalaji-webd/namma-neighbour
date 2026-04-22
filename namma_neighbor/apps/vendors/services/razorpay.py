import requests
from django.conf import settings

from apps.core.exceptions import RazorpayError, TransientAPIError
from apps.vendors.models import Vendor


class RazorpayClient:
    """Wraps the Razorpay Route (Linked Accounts) API.

    Uses HTTP Basic Auth with RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET.
    All requests time out after 10 seconds.

    Error translation:
      HTTP 400, 409  -> RazorpayError (permanent, no retry)
      HTTP 429, 5xx  -> TransientAPIError (retriable)
      Timeout / ConnectionError -> TransientAPIError
    """

    BASE_URL = "https://api.razorpay.com"

    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET

    def _auth(self):
        return (self.key_id, self.key_secret)

    def _handle_response(self, response: requests.Response) -> dict:
        if response.status_code in (400, 409):
            try:
                message = response.json().get("error", {}).get("description", str(response.status_code))
            except Exception:
                message = str(response.status_code)
            raise RazorpayError(message)
        if response.status_code == 429 or response.status_code >= 500:
            try:
                message = response.json().get("error", {}).get("description", str(response.status_code))
            except Exception:
                message = str(response.status_code)
            raise TransientAPIError(message)
        return response.json()

    def create_linked_account(self, vendor: Vendor) -> str:
        """POST /v2/accounts with type='route'.

        Returns the Razorpay account ID string (e.g. 'acc_XXXXX').
        Sets reference_id=str(vendor.pk) for Razorpay-side idempotency.

        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        url = f"{self.BASE_URL}/v2/accounts"
        payload = {
            "type": "route",
            "reference_id": str(vendor.pk),
            "email": f"vendor_{vendor.pk}@placeholder.example",  # TODO(split-05): collect email during full KYB
            "phone": vendor.user.phone,
            "legal_business_name": vendor.display_name,
            "business_type": "individual",  # TODO(split-05): add business_type field to Vendor
            "contact_name": vendor.display_name,  # TODO(split-05): use actual contact_name from KYB
            "profile": {
                "category": "others",  # TODO(split-05): map from Vendor product category
                "addresses": {
                    "registered": {  # TODO(split-05): collect registered address during full KYB
                        "street1": "NA",
                        "city": "NA",
                        "state": "NA",
                        "postal_code": "000000",
                        "country": "IN",
                    }
                },
            },
            "legal_info": {
                "pan": "",  # TODO(split-05): collect PAN during full KYB
            },
        }
        try:
            response = requests.post(url, json=payload, auth=self._auth(), timeout=10)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientAPIError(str(exc)) from exc
        return self._handle_response(response)["id"]

    def add_stakeholder(self, account_id: str, vendor: Vendor) -> str:
        """POST /v2/accounts/{account_id}/stakeholders.

        Returns the stakeholder_id string.
        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        url = f"{self.BASE_URL}/v2/accounts/{account_id}/stakeholders"
        payload = {
            "name": vendor.display_name,  # TODO(split-05): use actual contact_name from KYB
            "phone": vendor.user.phone,
            "phone_country_code": "IN",
            "relationship": {"director": True},  # TODO(split-05): derive from actual KYB role
        }
        try:
            response = requests.post(url, json=payload, auth=self._auth(), timeout=10)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientAPIError(str(exc)) from exc
        return self._handle_response(response)["id"]

    def submit_for_review(self, account_id: str) -> None:
        """PATCH /v2/accounts/{account_id} to trigger Razorpay compliance review.

        Returns None on success (Razorpay responds asynchronously via webhook).
        Raises RazorpayError on 400/409.
        Raises TransientAPIError on 429/5xx/timeout.
        """
        url = f"{self.BASE_URL}/v2/accounts/{account_id}"
        payload = {"tnc_accepted": True}
        try:
            response = requests.patch(url, json=payload, auth=self._auth(), timeout=10)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientAPIError(str(exc)) from exc
        self._handle_response(response)
        return None
