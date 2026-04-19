from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Phone is required")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(max_length=13, unique=True)
    active_community = models.ForeignKey(
        "communities.Community",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_users",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.phone


class UserRole(models.Model):
    ROLE_CHOICES = [
        ("resident", "Resident"),
        ("vendor", "Vendor"),
        ("community_admin", "Community Admin"),
        ("platform_admin", "Platform Admin"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    community = models.ForeignKey(
        "communities.Community",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )

    class Meta:
        unique_together = [("user", "role", "community")]
        indexes = [models.Index(fields=["user", "community"])]

    def __str__(self):
        return f"{self.user.phone} - {self.role}"


class PhoneOTP(models.Model):
    phone = models.CharField(max_length=13)
    otp_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["phone", "created_at"])]

    def __str__(self):
        return f"{self.phone} - {self.created_at}"
