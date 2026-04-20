import re
import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils.text import slugify

from apps.core.models import TimestampedModel


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _generate_invite_code() -> str:
    """Return a cryptographically random 6-character uppercase alphanumeric string."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))


def generate_unique_slug(name: str, city: str) -> str:
    """Return a slug derived from name+city, with numeric suffix on collision."""
    base = slugify(f"{name}-{city}")
    candidate = base
    counter = 2
    while Community.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def infer_floor(flat_number: str) -> int | None:
    """
    Infer floor from flat number. Rule: if flat_number starts with >= 2 digits,
    floor = all but the last two digits interpreted as int.
    Examples: '304' -> 3, '1205' -> 12, '12' -> 1, 'A4' -> None.
    """
    try:
        m = re.match(r'^(\d{2,})', flat_number)
        if not m:
            return None
        digits = m.group(1)
        prefix = digits[:-2]
        return int(prefix) if prefix else int(digits[0])
    except Exception:
        return None


# ─── Community ────────────────────────────────────────────────────────────────

class Community(TimestampedModel):
    """
    Central entity for a residential community.

    IMPORTANT: resident_count and vendor_count must ONLY be updated with:
        Community.objects.filter(pk=pk).update(resident_count=F('resident_count') + 1)
    Never use model_instance.resident_count += 1; model_instance.save().
    """

    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    slug = models.SlugField(unique=True, max_length=120, blank=True, null=True, default=None)
    city = models.CharField(max_length=100, blank=True, default='')
    pincode = models.CharField(max_length=6, blank=True, default='')
    address = models.TextField(blank=True, default='')
    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='administered_communities',
    )
    commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('7.50'),
    )
    invite_code = models.CharField(max_length=6, unique=True, blank=True, db_index=True)
    resident_count = models.PositiveIntegerField(default=0)
    vendor_count = models.PositiveIntegerField(default=0)
    is_reviewed = models.BooleanField(default=False)

    class Meta:
        db_table = 'communities_community'

    def save(self, *args, **kwargs):
        if not self.invite_code:
            candidate = _generate_invite_code()
            while Community.objects.filter(invite_code=candidate).exists():
                candidate = _generate_invite_code()
            self.invite_code = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ─── Building ─────────────────────────────────────────────────────────────────

class Building(models.Model):
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='buildings',
    )
    name = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('community', 'name')

    def __str__(self):
        return f"{self.community.name} — {self.name}"


# ─── Flat ─────────────────────────────────────────────────────────────────────

class Flat(models.Model):
    building = models.ForeignKey(
        Building,
        on_delete=models.CASCADE,
        related_name='flats',
    )
    flat_number = models.CharField(max_length=20)
    floor = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('building', 'flat_number')

    def __str__(self):
        return f"{self.building.name} / {self.flat_number}"


# ─── ResidentProfile ──────────────────────────────────────────────────────────

class ResidentProfile(TimestampedModel):
    class UserType(models.TextChoices):
        OWNER_RESIDING = 'OWNER_RESIDING', 'Owner (Residing)'
        OWNER_NON_RESIDING = 'OWNER_NON_RESIDING', 'Owner (Non-Residing)'
        TENANT = 'TENANT', 'Tenant'
        FAMILY_DEPENDENT = 'FAMILY_DEPENDENT', 'Family Dependent'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='resident_profile',
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name='residents',
    )
    flat = models.ForeignKey(
        Flat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='residents',
    )
    user_type = models.CharField(max_length=20, choices=UserType.choices)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    def __str__(self):
        return f"{self.user} @ {self.community.name} ({self.status})"
