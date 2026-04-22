import datetime
import requests
from django.conf import settings
from apps.core.exceptions import FSSAIVerificationError, TransientAPIError


class SurepassFSSAIClient:
    BASE_URL = "https://kyc-api.surepass.io/api/v1"

    def _headers(self):
        return {
            "Authorization": f"Bearer {settings.SUREPASS_TOKEN}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, response):
        status = response.status_code
        if status in (400, 404):
            raise FSSAIVerificationError()
        if status == 429 or status >= 500:
            raise TransientAPIError()
        if status >= 400:
            raise TransientAPIError()

    def _post(self, endpoint: str, license_number: str) -> dict:
        try:
            response = requests.post(
                f"{self.BASE_URL}{endpoint}",
                json={"id": license_number},
                headers=self._headers(),
                timeout=10,
            )
        except (requests.Timeout, requests.ConnectionError):
            raise TransientAPIError()
        self._raise_for_status(response)
        try:
            body = response.json()
            if not body.get("success"):
                raise FSSAIVerificationError()
            return body["data"]
        except (KeyError, TypeError, ValueError):
            raise FSSAIVerificationError()

    def verify_fssai(self, license_number: str) -> dict:
        data = self._post("/fssai/fssai-full-details", license_number)
        try:
            return {
                "status": data["license_status"],
                "business_name": data["business_name"],
                "expiry_date": datetime.date.fromisoformat(data["expiry_date"]),
                "authorized_categories": data.get("authorized_categories") or [],
            }
        except (KeyError, TypeError, ValueError):
            raise FSSAIVerificationError()

    def check_expiry(self, license_number: str) -> dict:
        data = self._post("/fssai/fssai-expiry-check", license_number)
        try:
            return {
                "status": data["license_status"],
                "expiry_date": datetime.date.fromisoformat(data["expiry_date"]),
            }
        except (KeyError, TypeError, ValueError):
            raise FSSAIVerificationError()
