from django.contrib import admin
from django.db import IntegrityError

from .models import Building, Community, ResidentProfile, _generate_invite_code


class BuildingInline(admin.TabularInline):
    model = Building
    fields = ('name',)
    extra = 1
    can_delete = False


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'pincode', 'admin_user', 'resident_count', 'vendor_count', 'is_active', 'is_reviewed')
    list_filter = ('is_active', 'is_reviewed', 'city')
    search_fields = ('name', 'city', 'pincode', 'admin_user__phone')
    readonly_fields = ('invite_code', 'slug', 'resident_count', 'vendor_count', 'created_at', 'updated_at')
    inlines = [BuildingInline]
    actions = ['deactivate_communities', 'mark_as_reviewed', 'regenerate_invite_codes']
    fieldsets = (
        ('Community Info', {'fields': ('name', 'slug', 'city', 'pincode', 'address')}),
        ('Admin', {'fields': ('admin_user', 'is_active', 'is_reviewed')}),
        ('Invite', {'fields': ('invite_code',)}),
        ('Metrics', {'fields': ('resident_count', 'vendor_count', 'commission_pct')}),
    )

    @admin.action(description='Deactivate selected communities')
    def deactivate_communities(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description='Mark as reviewed')
    def mark_as_reviewed(self, request, queryset):
        queryset.update(is_reviewed=True)

    @admin.action(description='Regenerate invite codes')
    def regenerate_invite_codes(self, request, queryset):
        for community in queryset:
            for _ in range(10):
                candidate = _generate_invite_code()
                try:
                    Community.objects.filter(pk=community.pk).update(invite_code=candidate)
                    break
                except IntegrityError:
                    continue
            else:
                self.message_user(request, f"Could not generate unique invite code for {community.name}", level='error')


@admin.register(ResidentProfile)
class ResidentProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'community', 'flat', 'user_type', 'status', 'created_at')
    list_filter = ('status', 'community', 'user_type')
    search_fields = ('user__phone', 'community__name', 'flat__flat_number')
    readonly_fields = ('created_at', 'updated_at', 'user')
    actions = ['approve_selected', 'reject_selected']

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Approve selected residents')
    def approve_selected(self, request, queryset):
        queryset.update(status='APPROVED')

    @admin.action(description='Reject selected residents')
    def reject_selected(self, request, queryset):
        queryset.update(status='REJECTED')
