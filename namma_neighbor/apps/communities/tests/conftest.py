import pytest
from rest_framework.test import APIClient

from apps.communities.models import Building, Community, generate_unique_slug
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
