import pytest
from rest_framework.test import APIClient

from apps.communities.models import Building, Community, Flat, ResidentProfile, generate_unique_slug
from apps.users.models import UserRole
from apps.users.tests.factories import UserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def user_a(db):
    return UserFactory()


@pytest.fixture
def user_b(db):
    return UserFactory()


@pytest.fixture
def existing_community(db):
    return Community.objects.create(
        name="Green Meadows",
        city="Bengaluru",
        slug=generate_unique_slug("Green Meadows", "Bengaluru"),
    )


@pytest.fixture
def community(db):
    return Community.objects.create(
        name="Sunrise Apartments",
        city="Bengaluru",
        slug=generate_unique_slug("Sunrise Apartments", "Bengaluru"),
    )


@pytest.fixture
def community_with_buildings(db):
    c = Community.objects.create(
        name="Tower Heights",
        city="Mumbai",
        slug=generate_unique_slug("Tower Heights", "Mumbai"),
    )
    Building.objects.create(community=c, name="Tower A")
    Building.objects.create(community=c, name="Tower B")
    return c


@pytest.fixture
def community_admin(db, community_with_buildings):
    user = UserFactory(active_community=community_with_buildings)
    UserRole.objects.create(user=user, role='community_admin', community=community_with_buildings)
    return user


@pytest.fixture
def approved_resident(db, community_with_buildings):
    user = UserFactory(active_community=community_with_buildings)
    building = Building.objects.filter(community=community_with_buildings).first()
    flat, _ = Flat.objects.get_or_create(building=building, flat_number="201")
    UserRole.objects.create(user=user, role='resident', community=community_with_buildings)
    ResidentProfile.objects.create(
        user=user, community=community_with_buildings, flat=flat,
        user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.APPROVED,
    )
    return user


@pytest.fixture
def pending_resident(db, community_with_buildings):
    user = UserFactory()
    building = Building.objects.filter(community=community_with_buildings).first()
    flat, _ = Flat.objects.get_or_create(building=building, flat_number="101")
    profile = ResidentProfile.objects.create(
        user=user, community=community_with_buildings, flat=flat,
        user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.PENDING,
    )
    return profile


@pytest.fixture
def community_with_residents(db, community_with_buildings):
    building = Building.objects.filter(community=community_with_buildings).first()
    for i in range(3):
        user = UserFactory()
        flat, _ = Flat.objects.get_or_create(building=building, flat_number=f"30{i + 1}")
        ResidentProfile.objects.create(
            user=user, community=community_with_buildings, flat=flat,
            user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.APPROVED,
        )
    return community_with_buildings


@pytest.fixture
def community_with_mixed_residents(db, community_with_buildings):
    building = Building.objects.filter(community=community_with_buildings).first()
    statuses = [ResidentProfile.Status.PENDING, ResidentProfile.Status.APPROVED, ResidentProfile.Status.PENDING]
    for i, s in enumerate(statuses):
        user = UserFactory()
        flat, _ = Flat.objects.get_or_create(building=building, flat_number=f"40{i + 1}")
        ResidentProfile.objects.create(
            user=user, community=community_with_buildings, flat=flat,
            user_type=ResidentProfile.UserType.TENANT, status=s,
        )
    return community_with_buildings


@pytest.fixture
def community_with_25_residents(db, community_with_buildings):
    building = Building.objects.filter(community=community_with_buildings).first()
    for i in range(25):
        user = UserFactory()
        flat, _ = Flat.objects.get_or_create(building=building, flat_number=f"5{i + 1:02d}")
        ResidentProfile.objects.create(
            user=user, community=community_with_buildings, flat=flat,
            user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.APPROVED,
        )
    return community_with_buildings


@pytest.fixture
def other_community_admin(db):
    other_community = Community.objects.create(
        name="Other Community",
        city="Mumbai",
        slug=generate_unique_slug("Other Community", "Mumbai"),
    )
    user = UserFactory(active_community=other_community)
    UserRole.objects.create(user=user, role='community_admin', community=other_community)
    return user


@pytest.fixture
def rejected_resident_user(db, community_with_buildings):
    user = UserFactory()
    building = Building.objects.filter(community=community_with_buildings).first()
    flat, _ = Flat.objects.get_or_create(building=building, flat_number="901")
    ResidentProfile.objects.create(
        user=user, community=community_with_buildings, flat=flat,
        user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.REJECTED,
    )
    return user


@pytest.fixture
def admin_user(db, community_with_buildings):
    user = UserFactory(active_community=community_with_buildings)
    UserRole.objects.create(user=user, role='community_admin', community=community_with_buildings)
    return user


@pytest.fixture
def resident_user(db, community_with_buildings):
    user = UserFactory(active_community=community_with_buildings)
    UserRole.objects.create(user=user, role='resident', community=community_with_buildings)
    return user


@pytest.fixture
def other_community(db):
    return Community.objects.create(
        name="Other Towers",
        city="Delhi",
        slug=generate_unique_slug("Other Towers", "Delhi"),
    )


@pytest.fixture
def pending_resident_profile(db, community_with_buildings):
    user = UserFactory()
    building = Building.objects.filter(community=community_with_buildings).first()
    flat, _ = Flat.objects.get_or_create(building=building, flat_number="801")
    return ResidentProfile.objects.create(
        user=user, community=community_with_buildings, flat=flat,
        user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.PENDING,
    )


@pytest.fixture
def admin_client(db):
    from django.test import Client

    from apps.users.models import User
    user = User.objects.create_superuser(phone='+910000000099', password='adminpass')
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def community_admin_token(community_admin):
    from apps.users.serializers import CustomTokenObtainPairSerializer
    refresh = CustomTokenObtainPairSerializer.get_token(community_admin)
    return f'Bearer {str(refresh.access_token)}'


@pytest.fixture
def other_resident(db, other_community):
    building = Building.objects.create(community=other_community, name="Block A")
    flat, _ = Flat.objects.get_or_create(building=building, flat_number="101")
    user = UserFactory()
    return ResidentProfile.objects.create(
        user=user, community=other_community, flat=flat,
        user_type=ResidentProfile.UserType.TENANT, status=ResidentProfile.Status.PENDING,
    )
