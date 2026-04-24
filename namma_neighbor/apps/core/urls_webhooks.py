from django.urls import path

from apps.core.views_webhooks import RazorpayWebhookView

app_name = "webhooks"

urlpatterns = [
    path("razorpay/", RazorpayWebhookView.as_view(), name="razorpay"),
]
