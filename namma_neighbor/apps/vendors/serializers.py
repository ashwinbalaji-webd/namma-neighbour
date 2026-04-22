from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.communities.models import Community
from apps.core.storage import generate_document_presigned_url
from apps.vendors.models import (
    FSSAIStatus,
    LogisticsTier,
    Vendor,
    VendorCommunity,
    VendorCommunityStatus,
)
from apps.vendors.services.storage import validate_document_file

_DOCUMENT_KEY_NAMES = [
    ("govt_id", "govt_id_s3_key"),
    ("bank_proof", "bank_proof_s3_key"),
    ("fssai_cert", "fssai_cert_s3_key"),
    ("gst_cert", "gst_cert_s3_key"),
]


class VendorRegistrationSerializer(serializers.Serializer):
    """Handles vendor registration and first community membership creation.

    Resolves community_slug to Community; wraps Vendor + VendorCommunity
    creation in transaction.atomic(). Returns required_documents list.
    """
    display_name = serializers.CharField(max_length=150)
    bio = serializers.CharField(allow_blank=True, required=False, default="")
    logistics_tier = serializers.ChoiceField(choices=LogisticsTier.choices)
    community_slug = serializers.CharField(write_only=True)
    category_hint = serializers.CharField(required=False, default="")

    def validate(self, attrs):
        slug = attrs.pop("community_slug")
        try:
            community = Community.objects.get(slug=slug)
        except Community.DoesNotExist:
            raise serializers.ValidationError({"community_slug": "Community not found."})
        attrs["community"] = community
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        community = validated_data.pop("community")
        category_hint = validated_data.pop("category_hint", "")

        with transaction.atomic():
            vendor, _ = Vendor.objects.update_or_create(
                user=user,
                defaults={
                    "display_name": validated_data["display_name"],
                    "bio": validated_data.get("bio", ""),
                    "logistics_tier": validated_data["logistics_tier"],
                },
            )

            if VendorCommunity.objects.filter(vendor=vendor, community=community).exists():
                raise serializers.ValidationError(
                    {"community": "Already registered for this community."},
                    code="duplicate_community",
                )

            # Set food seller flag after duplicate check so rollback is safe
            if category_hint == "food":
                vendor.is_food_seller = True
                vendor.save(update_fields=["is_food_seller"])

            try:
                vendor_community = VendorCommunity.objects.create(
                    vendor=vendor,
                    community=community,
                    status=VendorCommunityStatus.PENDING_REVIEW,
                )
            except IntegrityError:
                raise serializers.ValidationError(
                    {"community": "Already registered for this community."},
                    code="duplicate_community",
                )

        return vendor, vendor_community

    def to_representation(self, instance):
        vendor, vendor_community = instance
        docs = ["govt_id", "bank_proof"]
        if vendor.is_food_seller:
            docs.append("fssai_cert")
        return {
            "vendor_id": vendor.pk,
            "vendor_community_id": vendor_community.pk,
            "status": vendor_community.status,
            "required_documents": docs,
        }

    def save(self, **kwargs):
        if self.instance is not None:
            raise RuntimeError(
                "VendorRegistrationSerializer does not support update. "
                "Do not pass instance= to this serializer."
            )
        validated_data = {**self.validated_data, **kwargs}
        self.instance = self.create(validated_data)
        return self.to_representation(self.instance)


class DocumentUploadSerializer(serializers.Serializer):
    """Validates document_type choice and file content (size, extension, magic bytes).

    Does NOT perform S3 upload — that is handled by the view after validation.
    """
    DOCUMENT_TYPE_CHOICES = ["govt_id", "fssai_cert", "bank_proof", "gst_cert"]

    document_type = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)
    file = serializers.FileField()

    def validate_file(self, value):
        validate_document_file(value)
        return value


class VendorStatusSerializer(serializers.ModelSerializer):
    """Read-only serializer for vendor application status.

    Computes missing_documents from is_food_seller + s3_key fields.
    Includes community_statuses for all VendorCommunity memberships.
    """
    vendor_id = serializers.IntegerField(source="pk", read_only=True)
    missing_documents = serializers.SerializerMethodField()
    community_statuses = serializers.SerializerMethodField()

    def get_missing_documents(self, vendor):
        missing = []
        if not vendor.govt_id_s3_key:
            missing.append("govt_id")
        if not vendor.bank_proof_s3_key:
            missing.append("bank_proof")
        if vendor.is_food_seller and not vendor.fssai_cert_s3_key:
            missing.append("fssai_cert")
        return missing

    def get_community_statuses(self, vendor):
        qs = vendor.community_memberships.select_related("community").all()
        return [
            {
                "community_slug": vc.community.slug,
                "status": vc.status,
                "rejection_reason": vc.rejection_reason,
            }
            for vc in qs
        ]

    class Meta:
        model = Vendor
        fields = ["vendor_id", "fssai_status", "fssai_expiry_date",
                  "missing_documents", "community_statuses"]


class PendingVendorSerializer(serializers.ModelSerializer):
    """Serializes VendorCommunity records for the admin pending queue.

    Adds document_urls (presigned S3 URLs for non-empty s3_keys) and
    fssai_warning flag. Presigned URL generation uses s3v4, ExpiresIn=3600.
    Note: the calling view must use select_related('vendor') to avoid N+1.
    """
    vendor_id = serializers.IntegerField(source="vendor.pk", read_only=True)
    display_name = serializers.CharField(source="vendor.display_name", read_only=True)
    bio = serializers.CharField(source="vendor.bio", read_only=True)
    logistics_tier = serializers.CharField(source="vendor.logistics_tier", read_only=True)
    fssai_status = serializers.CharField(source="vendor.fssai_status", read_only=True)
    fssai_business_name = serializers.CharField(source="vendor.fssai_business_name", read_only=True)
    average_rating = serializers.DecimalField(
        source="vendor.average_rating", max_digits=3, decimal_places=2, read_only=True
    )
    is_new_seller = serializers.BooleanField(source="vendor.is_new_seller", read_only=True)
    fssai_warning = serializers.SerializerMethodField()
    document_urls = serializers.SerializerMethodField()

    def get_fssai_warning(self, vendor_community):
        return vendor_community.vendor.fssai_status == FSSAIStatus.FAILED

    def get_document_urls(self, vendor_community):
        vendor = vendor_community.vendor
        urls = {}
        for doc_type, field_name in _DOCUMENT_KEY_NAMES:
            key = getattr(vendor, field_name, "")
            if key:
                urls[doc_type] = generate_document_presigned_url(key)
        return urls

    class Meta:
        model = VendorCommunity
        fields = [
            "vendor_id", "display_name", "bio", "logistics_tier",
            "fssai_status", "fssai_business_name", "fssai_warning",
            "average_rating", "is_new_seller", "document_urls",
        ]


class VendorPublicProfileSerializer(serializers.ModelSerializer):
    """Read-only public profile. Exposes only display-safe fields.

    Explicitly excludes: fssai_number, fssai_*, razorpay_*, *_s3_key,
    bank_account_verified, gstin, gst_cert_s3_key, govt_id_s3_key,
    bank_proof_s3_key, user.
    """
    vendor_id = serializers.IntegerField(source="pk", read_only=True)
    is_new_seller = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vendor
        fields = ["vendor_id", "display_name", "bio", "average_rating", "is_new_seller"]
        read_only_fields = ["vendor_id", "display_name", "bio", "average_rating", "is_new_seller"]
