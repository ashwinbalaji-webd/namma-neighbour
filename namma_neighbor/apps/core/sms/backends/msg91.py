import requests
from django.conf import settings
from apps.core.sms.base import BaseSMSBackend


class MSG91SMSBackend(BaseSMSBackend):
    def send(self, phone: str, otp: str) -> None:
        phone_without_plus = phone.lstrip('+')
        headers = {'authkey': settings.MSG91_AUTH_KEY}
        payload = {
            'mobile': phone_without_plus,
            'otp': otp,
        }
        response = requests.post(
            'https://control.msg91.com/api/v5/otp',
            json=payload,
            headers=headers,
        )
        return response.json()
