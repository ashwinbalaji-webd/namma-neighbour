import factory

from apps.communities.models import Building, Community, Flat, ResidentProfile, generate_unique_slug


class CommunityFactory(factory.django.DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Community {n}")
    city = factory.Sequence(lambda n: f"City {n}")
    slug = factory.LazyAttribute(lambda o: generate_unique_slug(o.name, o.city))
    is_active = True

    class Meta:
        model = Community


class BuildingFactory(factory.django.DjangoModelFactory):
    community = factory.SubFactory(CommunityFactory)
    name = factory.Sequence(lambda n: f"Block {n}")

    class Meta:
        model = Building


class FlatFactory(factory.django.DjangoModelFactory):
    building = factory.SubFactory(BuildingFactory)
    flat_number = factory.Sequence(lambda n: f"{n + 101}")

    class Meta:
        model = Flat


class ResidentProfileFactory(factory.django.DjangoModelFactory):
    """community is derived from flat.building.community; do not pass community= explicitly."""
    user = factory.SubFactory('apps.users.tests.factories.UserFactory')
    flat = factory.SubFactory(FlatFactory)
    community = factory.LazyAttribute(lambda o: o.flat.building.community)
    user_type = ResidentProfile.UserType.TENANT
    status = ResidentProfile.Status.APPROVED

    class Meta:
        model = ResidentProfile
