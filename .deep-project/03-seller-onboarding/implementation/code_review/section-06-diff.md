diff --git a/namma_neighbor/apps/vendors/serializers.py b/namma_neighbor/apps/vendors/serializers.py
index 236cd38b..3753bdb8 100644
--- a/namma_neighbor/apps/vendors/serializers.py
+++ b/namma_neighbor/apps/vendors/serializers.py
@@ -1 +1,201 @@
+from django.db import transaction
 from rest_framework import serializers
+
+from apps.communities.models import Community
+from apps.core.storage import generate_document_presigned_url
+from apps.vendors.models import (
+    FSSAIStatus,
+    LogisticsTier,
+    Vendor,
+    VendorCommunity,
+    VendorCommunityStatus,
+)
+from apps.vendors.services.storage import validate_document_file
+
+_DOCUMENT_KEY_NAMES = [
+    ("govt_id", "govt_id_s3_key"),
+    ("bank_proof", "bank_proof_s3_key"),
+    ("fssai_cert", "fssai_cert_s3_key"),
+    ("gst_cert", "gst_cert_s3_key"),
+]
+
+
+class VendorRegistrationSerializer(serializers.Serializer):
+    """Handles vendor registration and first community membership creation.
+
+    Resolves community_slug to Community; wraps Vendor + VendorCommunity
+    creation in transaction.atomic(). Returns required_documents list.
+    """
+    display_name = serializers.CharField(max_length=150)
+    bio = serializers.CharField(allow_blank=True, required=False, default="")
+    logistics_tier = serializers.ChoiceField(choices=LogisticsTier.choices)
+    community_slug = serializers.CharField(write_only=True)
+    category_hint = serializers.CharField(required=False, default="")
+
+    def validate(self, attrs):
+        slug = attrs.pop("community_slug")
+        try:
+            community = Community.objects.get(slug=slug)
+        except Community.DoesNotExist:
+            raise serializers.ValidationError({"community_slug": "Community not found."})
+        attrs["community"] = community
+        return attrs
+
+    def create(self, validated_data):
+        user = self.context["request"].user
+        community = validated_data.pop("community")
+        category_hint = validated_data.pop("category_hint", "")
+
+        with transaction.atomic():
+            vendor, _ = Vendor.objects.update_or_create(
+                user=user,
+                defaults={
+                    "display_name": validated_data["display_name"],
+                    "bio": validated_data.get("bio", ""),
+                    "logistics_tier": validated_data["logistics_tier"],
+                },
+            )
+
+            if category_hint == "food":
+                vendor.is_food_seller = True
+                vendor.save(update_fields=["is_food_seller"])
+
+            if VendorCommunity.objects.filter(vendor=vendor, community=community).exists():
+                raise serializers.ValidationError(
+                    {"community": "Already registered for this community."},
+                    code="duplicate_community",
+                )
+
+            vendor_community = VendorCommunity.objects.create(
+                vendor=vendor,
+                community=community,
+                status=VendorCommunityStatus.PENDING_REVIEW,
+            )
+
+        return vendor, vendor_community
+
+    def to_representation(self, instance):
+        vendor, vendor_community = instance
+        docs = ["govt_id", "bank_proof"]
+        if vendor.is_food_seller:
+            docs.append("fssai_cert")
+        return {
+            "vendor_id": vendor.pk,
+            "vendor_community_id": vendor_community.pk,
+            "status": VendorCommunityStatus.PENDING_REVIEW,
+            "required_documents": docs,
+        }
+
+    def save(self, **kwargs):
+        validated_data = {**self.validated_data, **kwargs}
+        self.instance = self.create(validated_data)
+        return self.to_representation(self.instance)
+
+
+class DocumentUploadSerializer(serializers.Serializer):
+    """Validates document_type choice and file content (size, extension, magic bytes).
+
+    Does NOT perform S3 upload — that is handled by the view after validation.
+    """
+    DOCUMENT_TYPE_CHOICES = ["govt_id", "fssai_cert", "bank_proof", "gst_cert"]
+
+    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)
+    file = serializers.FileField()
+
+    def validate_file(self, value):
+        validate_document_file(value)
+        return value
+
+
+class VendorStatusSerializer(serializers.ModelSerializer):
+    """Read-only serializer for vendor application status.
+
+    Computes missing_documents from is_food_seller + s3_key fields.
+    Includes community_statuses for all VendorCommunity memberships.
+    """
+    vendor_id = serializers.IntegerField(source="pk", read_only=True)
+    missing_documents = serializers.SerializerMethodField()
+    community_statuses = serializers.SerializerMethodField()
+
+    def get_missing_documents(self, vendor):
+        missing = []
+        if not vendor.govt_id_s3_key:
+            missing.append("govt_id")
+        if not vendor.bank_proof_s3_key:
+            missing.append("bank_proof")
+        if vendor.is_food_seller and not vendor.fssai_cert_s3_key:
+            missing.append("fssai_cert")
+        return missing
+
+    def get_community_statuses(self, vendor):
+        qs = vendor.community_memberships.select_related("community").all()
+        return [
+            {
+                "community_slug": vc.community.slug,
+                "status": vc.status,
+                "rejection_reason": vc.rejection_reason,
+            }
+            for vc in qs
+        ]
+
+    class Meta:
+        model = Vendor
+        fields = ["vendor_id", "fssai_status", "fssai_expiry_date",
+                  "missing_documents", "community_statuses"]
+
+
+class PendingVendorSerializer(serializers.ModelSerializer):
+    """Serializes VendorCommunity records for the admin pending queue.
+
+    Adds document_urls (presigned S3 URLs for non-empty s3_keys) and
+    fssai_warning flag. Presigned URL generation uses s3v4, ExpiresIn=3600.
+    Note: the calling view must use select_related('vendor') to avoid N+1.
+    """
+    vendor_id = serializers.IntegerField(source="vendor.pk", read_only=True)
+    display_name = serializers.CharField(source="vendor.display_name", read_only=True)
+    bio = serializers.CharField(source="vendor.bio", read_only=True)
+    logistics_tier = serializers.CharField(source="vendor.logistics_tier", read_only=True)
+    fssai_status = serializers.CharField(source="vendor.fssai_status", read_only=True)
+    fssai_business_name = serializers.CharField(source="vendor.fssai_business_name", read_only=True)
+    average_rating = serializers.DecimalField(
+        source="vendor.average_rating", max_digits=3, decimal_places=2, read_only=True
+    )
+    is_new_seller = serializers.BooleanField(source="vendor.is_new_seller", read_only=True)
+    fssai_warning = serializers.SerializerMethodField()
+    document_urls = serializers.SerializerMethodField()
+
+    def get_fssai_warning(self, vendor_community):
+        return vendor_community.vendor.fssai_status == FSSAIStatus.FAILED
+
+    def get_document_urls(self, vendor_community):
+        vendor = vendor_community.vendor
+        urls = {}
+        for doc_type, field_name in _DOCUMENT_KEY_NAMES:
+            key = getattr(vendor, field_name, "")
+            if key:
+                urls[doc_type] = generate_document_presigned_url(key)
+        return urls
+
+    class Meta:
+        model = VendorCommunity
+        fields = [
+            "vendor_id", "display_name", "bio", "logistics_tier",
+            "fssai_status", "fssai_business_name", "fssai_warning",
+            "average_rating", "is_new_seller", "document_urls",
+        ]
+
+
+class VendorPublicProfileSerializer(serializers.ModelSerializer):
+    """Read-only public profile. Exposes only display-safe fields.
+
+    Explicitly excludes: fssai_number, fssai_*, razorpay_*, *_s3_key,
+    bank_account_verified, gstin, gst_cert_s3_key, govt_id_s3_key,
+    bank_proof_s3_key, user.
+    """
+    vendor_id = serializers.IntegerField(source="pk", read_only=True)
+    is_new_seller = serializers.BooleanField(read_only=True)
+
+    class Meta:
+        model = Vendor
+        fields = ["vendor_id", "display_name", "bio", "average_rating", "is_new_seller"]
+        read_only_fields = ["vendor_id", "display_name", "bio", "average_rating", "is_new_seller"]
diff --git a/namma_neighbor/apps/vendors/tests/test_serializers.py b/namma_neighbor/apps/vendors/tests/test_serializers.py
new file mode 100644
index 00000000..dba82ff5
--- /dev/null
+++ b/namma_neighbor/apps/vendors/tests/test_serializers.py
@@ -0,0 +1,269 @@
+import io
+from unittest.mock import patch
+
+import pytest
+from django.core.files.uploadedfile import InMemoryUploadedFile
+from rest_framework.test import APIRequestFactory
+
+from apps.communities.tests.factories import CommunityFactory
+from apps.vendors.models import FSSAIStatus, VendorCommunity, VendorCommunityStatus
+from apps.vendors.serializers import (
+    DocumentUploadSerializer,
+    PendingVendorSerializer,
+    VendorPublicProfileSerializer,
+    VendorRegistrationSerializer,
+    VendorStatusSerializer,
+)
+from apps.vendors.tests.factories import VendorCommunityFactory, VendorFactory
+
+
+def make_file(name, content, size=None):
+    data = io.BytesIO(content)
+    file_size = size if size is not None else len(content)
+    return InMemoryUploadedFile(
+        file=data, field_name="file", name=name,
+        content_type="application/octet-stream", size=file_size, charset=None,
+    )
+
+
+def make_request(user):
+    factory = APIRequestFactory()
+    request = factory.post("/")
+    request.user = user
+    return request
+
+
+# --- VendorRegistrationSerializer ---
+
+@pytest.mark.django_db
+def test_registration_creates_vendor_and_community(vendor_user):
+    community = CommunityFactory()
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community.slug,
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert s.is_valid(), s.errors
+    result = s.save()
+    assert result["vendor_id"] is not None
+    assert result["vendor_community_id"] is not None
+    assert VendorCommunity.objects.filter(pk=result["vendor_community_id"]).exists()
+
+
+@pytest.mark.django_db
+def test_registration_sets_food_seller_on_category_hint(vendor_user):
+    community = CommunityFactory()
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community.slug,
+        "category_hint": "food",
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert s.is_valid(), s.errors
+    result = s.save()
+    from apps.vendors.models import Vendor
+    vendor = Vendor.objects.get(pk=result["vendor_id"])
+    assert vendor.is_food_seller is True
+
+
+@pytest.mark.django_db
+def test_registration_required_docs_include_fssai_for_food(vendor_user):
+    community = CommunityFactory()
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community.slug,
+        "category_hint": "food",
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert s.is_valid(), s.errors
+    result = s.save()
+    assert "fssai_cert" in result["required_documents"]
+
+
+@pytest.mark.django_db
+def test_registration_required_docs_no_fssai_for_non_food(vendor_user):
+    community = CommunityFactory()
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community.slug,
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert s.is_valid(), s.errors
+    result = s.save()
+    assert "fssai_cert" not in result["required_documents"]
+
+
+@pytest.mark.django_db
+def test_registration_duplicate_community_raises_conflict(vendor_user):
+    community = CommunityFactory()
+    vendor = VendorFactory(user=vendor_user)
+    VendorCommunityFactory(vendor=vendor, community=community)
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community.slug,
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert s.is_valid(), s.errors
+    with pytest.raises(Exception) as exc_info:
+        s.save()
+    # Should raise a ValidationError with code indicating duplicate
+    assert "duplicate_community" in str(exc_info.value) or "community" in str(exc_info.value).lower()
+
+
+@pytest.mark.django_db
+def test_registration_invalid_community_slug_fails_validation(vendor_user):
+    data = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": "nonexistent-slug",
+    }
+    s = VendorRegistrationSerializer(data=data, context={"request": make_request(vendor_user)})
+    assert not s.is_valid()
+
+
+@pytest.mark.django_db
+def test_registration_reuses_existing_vendor(vendor_user):
+    community1 = CommunityFactory()
+    community2 = CommunityFactory()
+    data1 = {
+        "display_name": "Priya Sweets",
+        "logistics_tier": "tier_b",
+        "community_slug": community1.slug,
+    }
+    s1 = VendorRegistrationSerializer(data=data1, context={"request": make_request(vendor_user)})
+    assert s1.is_valid(), s1.errors
+    result1 = s1.save()
+
+    data2 = {
+        "display_name": "Priya Sweets Updated",
+        "logistics_tier": "tier_b",
+        "community_slug": community2.slug,
+    }
+    s2 = VendorRegistrationSerializer(data=data2, context={"request": make_request(vendor_user)})
+    assert s2.is_valid(), s2.errors
+    result2 = s2.save()
+    assert result1["vendor_id"] == result2["vendor_id"]
+
+
+# --- DocumentUploadSerializer ---
+
+def test_document_upload_rejects_file_over_5mb():
+    data = {"document_type": "govt_id"}
+    f = make_file("doc.pdf", b"x" * 100, size=5 * 1024 * 1024 + 1)
+    s = DocumentUploadSerializer(data={**data, "file": f})
+    assert not s.is_valid()
+
+
+def test_document_upload_rejects_invalid_extension():
+    data = {"document_type": "govt_id"}
+    f = make_file("malware.exe", b"x" * 100)
+    s = DocumentUploadSerializer(data={**data, "file": f})
+    assert not s.is_valid()
+
+
+def test_document_upload_accepts_valid_pdf():
+    data = {"document_type": "govt_id"}
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.pdf", content)
+    s = DocumentUploadSerializer(data={**data, "file": f})
+    assert s.is_valid(), s.errors
+
+
+def test_document_upload_rejects_invalid_document_type():
+    content = b"%PDF-1.4 " + b"x" * 200
+    f = make_file("cert.pdf", content)
+    s = DocumentUploadSerializer(data={"document_type": "passport", "file": f})
+    assert not s.is_valid()
+
+
+# --- VendorStatusSerializer ---
+
+@pytest.mark.django_db
+def test_status_missing_documents_empty_when_all_present():
+    vendor = VendorFactory(
+        govt_id_s3_key="documents/vendors/1/govt_id/abc.pdf",
+        bank_proof_s3_key="documents/vendors/1/bank_proof/abc.pdf",
+    )
+    s = VendorStatusSerializer(vendor)
+    assert s.data["missing_documents"] == []
+
+
+@pytest.mark.django_db
+def test_status_missing_documents_includes_govt_id_when_absent():
+    vendor = VendorFactory(govt_id_s3_key="", bank_proof_s3_key="some_key")
+    s = VendorStatusSerializer(vendor)
+    assert "govt_id" in s.data["missing_documents"]
+
+
+@pytest.mark.django_db
+def test_status_missing_documents_includes_fssai_cert_for_food_seller():
+    vendor = VendorFactory(is_food_seller=True, fssai_cert_s3_key="")
+    s = VendorStatusSerializer(vendor)
+    assert "fssai_cert" in s.data["missing_documents"]
+
+
+@pytest.mark.django_db
+def test_status_community_statuses_reflects_memberships():
+    vc = VendorCommunityFactory()
+    s = VendorStatusSerializer(vc.vendor)
+    statuses = s.data["community_statuses"]
+    assert len(statuses) == 1
+    assert statuses[0]["status"] == VendorCommunityStatus.PENDING_REVIEW
+
+
+# --- PendingVendorSerializer ---
+
+@pytest.mark.django_db
+def test_pending_vendor_document_urls_for_nonempty_keys():
+    vendor = VendorFactory(govt_id_s3_key="documents/vendors/1/govt_id/abc.pdf")
+    vc = VendorCommunityFactory(vendor=vendor)
+    with patch("apps.vendors.serializers.generate_document_presigned_url") as mock_url:
+        mock_url.return_value = "https://example.com/signed"
+        s = PendingVendorSerializer(vc)
+        urls = s.data["document_urls"]
+    assert "govt_id" in urls
+    assert urls["govt_id"] == "https://example.com/signed"
+
+
+@pytest.mark.django_db
+def test_pending_vendor_fssai_warning_true_when_failed():
+    vendor = VendorFactory(fssai_status=FSSAIStatus.FAILED)
+    vc = VendorCommunityFactory(vendor=vendor)
+    with patch("apps.vendors.serializers.generate_document_presigned_url", return_value="https://x.com"):
+        s = PendingVendorSerializer(vc)
+        assert s.data["fssai_warning"] is True
+
+
+@pytest.mark.django_db
+def test_pending_vendor_fssai_warning_false_when_not_failed():
+    vendor = VendorFactory(fssai_status=FSSAIStatus.VERIFIED)
+    vc = VendorCommunityFactory(vendor=vendor)
+    with patch("apps.vendors.serializers.generate_document_presigned_url", return_value="https://x.com"):
+        s = PendingVendorSerializer(vc)
+        assert s.data["fssai_warning"] is False
+
+
+# --- VendorPublicProfileSerializer ---
+
+@pytest.mark.django_db
+def test_public_profile_returns_safe_fields():
+    vendor = VendorFactory()
+    s = VendorPublicProfileSerializer(vendor)
+    data = s.data
+    assert set(data.keys()) == {"vendor_id", "display_name", "bio", "average_rating", "is_new_seller"}
+
+
+@pytest.mark.django_db
+def test_public_profile_excludes_sensitive_fields():
+    vendor = VendorFactory()
+    s = VendorPublicProfileSerializer(vendor)
+    data = s.data
+    sensitive = ["fssai_number", "razorpay_account_id", "govt_id_s3_key",
+                 "bank_proof_s3_key", "fssai_cert_s3_key", "gstin"]
+    for field in sensitive:
+        assert field not in data
