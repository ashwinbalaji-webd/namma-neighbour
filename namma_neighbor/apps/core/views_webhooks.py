import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.vendors.models import Vendor
from apps.vendors.tasks import notify_vendor_account_activated

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(View):
    """Unauthenticated webhook receiver for Razorpay account lifecycle events.

    Security: HMAC-SHA256 signature verification using RAZORPAY_WEBHOOK_SECRET.
    Replay protection: NOT implemented for MVP. account.activated is idempotent.
    TODO (split 05): Add timestamp + event-ID deduplication before handling
    non-idempotent payment events.
    """

    def post(self, request, *args, **kwargs):
        signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
        if not signature:
            return JsonResponse({'error': 'invalid signature'}, status=400)

        if not self._verify_signature(request.body, signature):
            return JsonResponse({'error': 'invalid signature'}, status=400)

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'invalid body'}, status=400)

        event = payload.get('event', '')
        if event == 'account.activated':
            self._handle_account_activated(payload)

        return JsonResponse({'status': 'ok'}, status=200)

    def _verify_signature(self, raw_body: bytes, signature_header: str) -> bool:
        expected = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def _handle_account_activated(self, payload: dict) -> None:
        account_id = (
            payload.get('payload', {})
            .get('account', {})
            .get('entity', {})
            .get('id')
        )
        if not account_id:
            logger.warning("account.activated: missing account id in payload")
            return

        updated = Vendor.objects.filter(razorpay_account_id=account_id).update(
            razorpay_account_status='activated',
            bank_account_verified=True,
        )
        if not updated:
            logger.warning("account.activated: no vendor found for account_id=%s", account_id)
            return

        vendor = Vendor.objects.filter(razorpay_account_id=account_id).values('id').first()
        if vendor:
            notify_vendor_account_activated.delay(vendor['id'])
