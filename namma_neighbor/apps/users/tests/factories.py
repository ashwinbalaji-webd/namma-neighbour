import factory
from apps.users.models import User, UserRole, PhoneOTP
from apps.communities.tests.factories import CommunityFactory


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    phone = factory.Sequence(lambda n: f"+9198765{n:04d}")


class UserRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserRole

    user = factory.SubFactory(UserFactory)
    role = "resident"
    community = None


class PhoneOTPFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PhoneOTP

    phone = factory.Sequence(lambda n: f"+9198765{n:04d}")
    otp_hash = factory.Faker("sha256")
    is_used = False
    attempt_count = 0
