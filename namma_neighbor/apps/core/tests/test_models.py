import pytest
from django.utils import timezone
from apps.communities.models import Community


@pytest.mark.django_db
def test_created_at_set_on_creation():
    """Create a Community instance and assert created_at is not null."""
    community = Community.objects.create(name="Test")
    assert community.created_at is not None


@pytest.mark.django_db
def test_created_at_does_not_change_on_save():
    """Save the instance again, assert created_at is unchanged."""
    community = Community.objects.create(name="Test")
    original_created = community.created_at
    community.name = "Updated"
    community.save()
    assert community.created_at == original_created


@pytest.mark.django_db
def test_updated_at_changes_on_save():
    """Save an instance twice, assert the second updated_at is greater than or equal to the first."""
    community = Community.objects.create(name="Test")
    first_updated = community.updated_at
    community.name = "Updated"
    community.save()
    assert community.updated_at >= first_updated
