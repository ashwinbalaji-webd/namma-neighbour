from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User, UserRole, PhoneOTP


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Personal info", {"fields": ("active_community",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "password1", "password2"),
            },
        ),
    )
    list_display = ("phone", "is_staff", "is_superuser", "active_community")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("phone",)
    ordering = ("phone",)


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "community")
    list_filter = ("role", "community")
    search_fields = ("user__phone", "role")


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "is_used", "attempt_count", "created_at")
    list_filter = ("is_used", "created_at")
    search_fields = ("phone",)
    readonly_fields = ("otp_hash",)
