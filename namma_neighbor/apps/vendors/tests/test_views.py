import io
import re
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.test import APIClient

from apps.communities.tests.factories import CommunityFactory
from apps.vendors.models import FSSAIStatus, VendorCommunity, VendorCommunityStatus
from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory


def make_pdf():
    content = b"%PDF-1.4 " + b"x" * 200
    return InMemoryUploadedFile(
        io.BytesIO(content), "file", "cert.pdf",
        "application/pdf", len(content), None,
    )


def make_jpeg():
    content = b"\xff\xd8\xff\xe0" + b"x" * 200
    return InMemoryUploadedFile(
        io.BytesIO(content), "file", "photo.jpg",
        "image/jpeg", len(content), None,
    )


@pytest.fixture
def auth_client(vendor_user):
    client = APIClient()
    client.force_authenticate(user=vendor_user)
    return client


@pytest.fixture
def community():
    return CommunityFactory()


# ─── POST /api/v1/vendors/register/ ───

REGISTER_URL = "/api/v1/vendors/register/"


@pytest.mark.django_db
def test_register_creates_vendor_and_community(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Priya Sweets",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }, format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert "vendor_id" in data
    assert "vendor_community_id" in data
    assert data["status"] == "pending_review"
    assert "required_documents" in data


@pytest.mark.django_db
def test_register_sets_food_seller(auth_client, vendor_user, community):
    from apps.vendors.models import Vendor
    auth_client.post(REGISTER_URL, {
        "display_name": "Biryani House",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }, format="json")
    vendor = Vendor.objects.get(user=vendor_user)
    assert vendor.is_food_seller is True


@pytest.mark.django_db
def test_register_required_docs_include_fssai_for_food(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Biryani House",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
        "category_hint": "food",
    }, format="json")
    assert "fssai_cert" in resp.json()["required_documents"]


@pytest.mark.django_db
def test_register_required_docs_no_fssai_for_non_food(auth_client, vendor_user, community):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Craft Store",
        "logistics_tier": "tier_b",
        "community_slug": community.slug,
    }, format="json")
    assert "fssai_cert" not in resp.json()["required_documents"]


@pytest.mark.django_db
def test_register_returns_409_on_duplicate_community(auth_client, vendor_user, community):
    data = {"display_name": "Shop", "logistics_tier": "tier_b", "community_slug": community.slug}
    auth_client.post(REGISTER_URL, data, format="json")
    resp = auth_client.post(REGISTER_URL, data, format="json")
    assert resp.status_code == 409


@pytest.mark.django_db
def test_register_returns_404_for_unknown_slug(auth_client):
    resp = auth_client.post(REGISTER_URL, {
        "display_name": "Shop", "logistics_tier": "tier_b",
        "community_slug": "no-such-slug",
    }, format="json")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_register_returns_401_unauthenticated():
    client = APIClient()
    resp = client.post(REGISTER_URL, {"display_name": "x", "logistics_tier": "tier_b",
                                      "community_slug": "x"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_register_reuses_existing_vendor(auth_client, vendor_user):
    from apps.vendors.models import Vendor
    c1 = CommunityFactory()
    c2 = CommunityFactory()
    auth_client.post(REGISTER_URL, {"display_name": "A", "logistics_tier": "tier_b",
                                    "community_slug": c1.slug}, format="json")
    auth_client.post(REGISTER_URL, {"display_name": "B", "logistics_tier": "tier_b",
                                    "community_slug": c2.slug}, format="json")
    assert Vendor.objects.filter(user=vendor_user).count() == 1


# ─── POST /api/v1/vendors/{vendor_id}/documents/ ───

def doc_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/documents/"


@pytest.mark.django_db
def test_documents_returns_403_for_wrong_user(vendor_user, community):
    vendor = VendorFactory(user=vendor_user)
    other_client = APIClient()
    from apps.users.tests.factories import UserFactory
    other_client.force_authenticate(user=UserFactory())
    resp = other_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": make_pdf()},
                             format="multipart")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_documents_rejects_large_file(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    big = InMemoryUploadedFile(io.BytesIO(b"x" * 100), "file", "big.pdf",
                               "application/pdf", 5 * 1024 * 1024 + 1, None)
    resp = auth_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": big},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_documents_rejects_invalid_extension(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    bad = InMemoryUploadedFile(io.BytesIO(b"x" * 100), "file", "virus.exe",
                               "application/octet-stream", 100, None)
    resp = auth_client.post(doc_url(vendor.pk), {"document_type": "govt_id", "file": bad},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_documents_rejects_invalid_document_type(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "passport", "file": make_pdf()},
                            format="multipart")
    assert resp.status_code == 400


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
def test_documents_accepts_pdf_updates_field(mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    mock_upload.return_value = "documents/vendors/1/govt_id/abc.pdf"
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "govt_id", "file": make_pdf()},
                            format="multipart")
    assert resp.status_code == 200
    assert resp.json()["document_type"] == "govt_id"


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
@patch("apps.vendors.views.verify_fssai")
def test_documents_fssai_cert_with_number_triggers_task(mock_task, mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_number="12345678901234")
    mock_upload.return_value = "documents/vendors/1/fssai_cert/abc.pdf"
    auth_client.post(doc_url(vendor.pk),
                     {"document_type": "fssai_cert", "file": make_pdf()},
                     format="multipart")
    mock_task.delay.assert_called_once_with(vendor.pk)


@pytest.mark.django_db
@patch("apps.vendors.views.upload_vendor_document")
@patch("apps.vendors.views.verify_fssai")
def test_documents_fssai_cert_without_number_warns(mock_task, mock_upload, auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_number="")
    mock_upload.return_value = "documents/vendors/1/fssai_cert/abc.pdf"
    resp = auth_client.post(doc_url(vendor.pk),
                            {"document_type": "fssai_cert", "file": make_pdf()},
                            format="multipart")
    mock_task.delay.assert_not_called()
    assert resp.json().get("missing_fssai_number") is True


# ─── POST /api/v1/vendors/{vendor_id}/submit/ ───

def submit_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/submit/"


@pytest.mark.django_db
def test_submit_returns_400_missing_govt_id(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="",
                           bank_proof_s3_key="some_key")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_missing_bank_proof(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="some_key",
                           bank_proof_s3_key="")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_fssai_failed(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1",
                           bank_proof_s3_key="k2", fssai_status=FSSAIStatus.FAILED)
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_returns_400_food_seller_missing_fssai_cert(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, is_food_seller=True,
                           govt_id_s3_key="k1", bank_proof_s3_key="k2",
                           fssai_cert_s3_key="")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_succeeds_sets_pending_review(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    vc = VendorCommunityFactory(vendor=vendor)
    resp = auth_client.post(submit_url(vendor.pk),
                            {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_review"


@pytest.mark.django_db
def test_submit_returns_403_for_wrong_user(vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    vc = VendorCommunityFactory(vendor=vendor)
    from apps.users.tests.factories import UserFactory
    other = APIClient()
    other.force_authenticate(user=UserFactory())
    resp = other.post(submit_url(vendor.pk),
                      {"community_slug": vc.community.slug}, format="json")
    assert resp.status_code == 403


# ─── GET /api/v1/vendors/{vendor_id}/status/ ───

def status_url(vendor_id):
    return f"/api/v1/vendors/{vendor_id}/status/"


@pytest.mark.django_db
def test_status_returns_fssai_status(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, fssai_status=FSSAIStatus.VERIFIED)
    resp = auth_client.get(status_url(vendor.pk))
    assert resp.status_code == 200
    assert resp.json()["fssai_status"] == "verified"


@pytest.mark.django_db
def test_status_missing_documents_empty_when_complete(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, govt_id_s3_key="k1", bank_proof_s3_key="k2")
    resp = auth_client.get(status_url(vendor.pk))
    assert resp.json()["missing_documents"] == []


@pytest.mark.django_db
def test_status_missing_documents_includes_fssai_for_food_seller(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user, is_food_seller=True, fssai_cert_s3_key="")
    resp = auth_client.get(status_url(vendor.pk))
    assert "fssai_cert" in resp.json()["missing_documents"]


@pytest.mark.django_db
def test_status_community_statuses_count(auth_client, vendor_user):
    vendor = VendorFactory(user=vendor_user)
    VendorCommunityFactory(vendor=vendor)
    VendorCommunityFactory(vendor=vendor)
    resp = auth_client.get(status_url(vendor.pk))
    assert len(resp.json()["community_statuses"]) == 2


@pytest.mark.django_db
def test_status_returns_403_for_wrong_user(vendor_user):
    vendor = VendorFactory(user=vendor_user)
    from apps.users.tests.factories import UserFactory
    other = APIClient()
    other.force_authenticate(user=UserFactory())
    resp = other.get(status_url(vendor.pk))
    assert resp.status_code == 403
