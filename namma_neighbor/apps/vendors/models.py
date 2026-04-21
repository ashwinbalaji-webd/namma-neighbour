from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimestampedModel


class LogisticsTier(models.TextChoices):
    TIER_A = "tier_a", "Self-delivery, own bike/van"
    TIER_B = "tier_b", "NammaNeighbor pickup required"


class FSSAIStatus(models.TextChoices):
    NOT_APPLICABLE = "not_applicable", "Not Applicable"
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    EXPIRED = "expired", "Expired"
    FAILED = "failed", "Failed"


class VendorCommunityStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending Review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SUSPENDED = "suspended", "Suspended"


class Vendor(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_profile",
    )
    display_name = models.CharField(max_length=150)
    bio = models.TextField(blank=True)
    logistics_tier = models.CharField(
        max_length=max(len(v) for v in LogisticsTier.values),
        choices=LogisticsTier.choices,
    )
    is_food_seller = models.BooleanField(default=False)

    govt_id_s3_key = models.CharField(max_length=500, blank=True)
    bank_proof_s3_key = models.CharField(max_length=500, blank=True)

    fssai_number = models.CharField(
        max_length=14,
        blank=True,
        validators=[RegexValidator(r"^\d{14}$", "FSSAI number must be exactly 14 digits.")],
    )
    fssai_status = models.CharField(
        max_length=max(len(v) for v in FSSAIStatus.values),
        choices=FSSAIStatus.choices,
        default=FSSAIStatus.NOT_APPLICABLE,
    )
    fssai_cert_s3_key = models.CharField(max_length=500, blank=True)
    fssai_verified_at = models.DateTimeField(null=True, blank=True)
    fssai_expiry_date = models.DateField(null=True, blank=True, db_index=True)
    fssai_business_name = models.CharField(max_length=200, blank=True)
    fssai_authorized_categories = models.JSONField(default=list)
    fssai_expiry_warning_sent = models.BooleanField(default=False)

    gstin = models.CharField(max_length=15, blank=True)
    gst_cert_s3_key = models.CharField(max_length=500, blank=True)

    razorpay_account_id = models.CharField(max_length=100, blank=True)
    razorpay_account_status = models.CharField(max_length=20, blank=True)
    razorpay_onboarding_step = models.CharField(max_length=50, blank=True)
    bank_account_verified = models.BooleanField(default=False)

    completed_delivery_count = models.PositiveIntegerField(default=0)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0.00"))

    @property
    def is_new_seller(self) -> bool:
        """Return True until vendor has >= 5 deliveries AND >= 4.5 average rating."""
        return self.completed_delivery_count < 5 or self.average_rating < Decimal("4.5")

    def __str__(self) -> str:
        return self.display_name


class VendorCommunity(TimestampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="community_memberships")
    community = models.ForeignKey(
        "communities.Community",
        on_delete=models.PROTECT,
        related_name="vendor_memberships",
    )
    status = models.CharField(
        max_length=max(len(v) for v in VendorCommunityStatus.values),
        choices=VendorCommunityStatus.choices,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_approvals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    delist_threshold = models.PositiveIntegerField(default=2)
    missed_window_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["vendor", "community"], name="unique_vendor_community"),
        ]
        indexes = [
            models.Index(fields=["community", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.vendor} @ {self.community}"
