from django.contrib import admin

from .models import Vendor, VendorCommunity


class VendorCommunityInline(admin.TabularInline):
    """Inline showing all community approval records for a vendor."""

    model = VendorCommunity
    fields = ("community", "status", "approved_by", "approved_at", "missed_window_count", "delist_threshold")
    readonly_fields = ("approved_by", "approved_at")
    extra = 0
    can_delete = False
    show_change_link = True


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    """Admin for the Vendor model with KYB/FSSAI/Razorpay read-only fields."""

    list_display = (
        "display_name",
        "user",
        "fssai_status",
        "razorpay_account_status",
        "bank_account_verified",
        "average_rating",
        "is_new_seller",
    )
    list_filter = ("fssai_status", "razorpay_account_status")
    search_fields = ("display_name", "user__phone", "fssai_number", "gstin")
    readonly_fields = (
        # Automation-owned fields
        "fssai_verified_at",
        "razorpay_account_id",
        "razorpay_onboarding_step",
        "created_at",
        "updated_at",
        # S3 document keys (set by upload service, not editable by operators)
        "govt_id_s3_key",
        "bank_proof_s3_key",
        "fssai_cert_s3_key",
        "gst_cert_s3_key",
        # Razorpay webhook-owned
        "bank_account_verified",
    )
    inlines = [VendorCommunityInline]
    list_select_related = ("user",)


@admin.register(VendorCommunity)
class VendorCommunityAdmin(admin.ModelAdmin):
    """Standalone admin for VendorCommunity; full cross-community approval queue."""

    list_display = (
        "vendor",
        "community",
        "status",
        "approved_by",
        "approved_at",
        "missed_window_count",
        "delist_threshold",
    )
    list_filter = ("status", "community")
    # status is managed by the API approval workflow; direct edits bypass business logic
    readonly_fields = ("approved_by", "approved_at", "status")
    ordering = ("-created_at",)
    list_select_related = ("vendor", "community", "approved_by")
