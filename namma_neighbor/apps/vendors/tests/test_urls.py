from django.urls import reverse


def test_vendor_register_url_resolves():
    url = reverse("vendors:register")
    assert url == "/api/v1/vendors/register/"


def test_vendor_documents_url_resolves():
    url = reverse("vendors:documents", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/documents/"


def test_vendor_submit_url_resolves():
    url = reverse("vendors:submit", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/submit/"


def test_vendor_status_url_resolves():
    url = reverse("vendors:status", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/status/"


def test_vendor_profile_url_resolves():
    url = reverse("vendors:profile", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/profile/"


def test_vendor_approve_url_resolves():
    url = reverse("vendors:approve", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/approve/"


def test_vendor_reject_url_resolves():
    url = reverse("vendors:reject", kwargs={"vendor_id": 1})
    assert url == "/api/v1/vendors/1/reject/"


def test_community_pending_vendors_url_resolves():
    url = reverse("communities:pending-vendors", kwargs={"slug": "test-slug"})
    assert url == "/api/v1/communities/test-slug/vendors/pending/"


def test_razorpay_webhook_url_resolves():
    url = reverse("webhooks:razorpay")
    assert url == "/api/v1/webhooks/razorpay/"
