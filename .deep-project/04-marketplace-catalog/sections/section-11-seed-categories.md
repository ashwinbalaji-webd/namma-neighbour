Now I have all the context needed. Let me generate the section content.

# Section 11: Category Seed Data

## Overview

This section implements the category seed data for the NammaNeighbor marketplace catalog. It consists of two parts that must both be delivered:

1. A Django management command `seed_categories` that can be run on-demand.
2. A data migration `0002_seed_categories.py` that runs the same logic automatically on every deploy.

Both use `get_or_create` on the `slug` field so they are fully idempotent — running either multiple times never creates duplicate rows.

## Dependencies

This section depends on **section-01-models** being complete. The `Category` model must exist with its `slug`, `name`, `icon_url`, `requires_fssai`, and `requires_gstin` fields before the management command or migration can reference it.

No other sections block this one.

## Tests First

File: `namma_neighbor/apps/catalogue/tests/test_seed_categories.py`

```python
import pytest
from django.core.management import call_command

from namma_neighbor.apps.catalogue.models import Category


@pytest.mark.django_db
class TestSeedCategoriesCommand:
    """Tests for the seed_categories management command."""

    def test_creates_all_11_categories(self):
        """Running the command creates exactly 11 category records."""
        ...

    def test_command_is_idempotent(self):
        """Running the command twice does not create duplicate categories."""
        ...

    def test_seafood_has_requires_fssai(self):
        """The 'Seafood' category must have requires_fssai=True."""
        ...

    def test_electronics_has_requires_gstin(self):
        """The 'Electronics & Gadgets' category must have requires_gstin=True."""
        ...

    def test_other_categories_fssai_flags(self):
        """Food-adjacent categories (Organic Produce, Baked Goods, Home-cooked Meals,
        Dairy Products) must also have requires_fssai=True."""
        ...

    def test_non_food_categories_do_not_require_fssai(self):
        """Non-food categories (Flowers & Plants, Handcrafted Decor, Clothing & Textiles,
        Services, Other) must have requires_fssai=False."""
        ...
```

The full list of expected categories and their flags is documented in the implementation section below. Test stubs map to them directly.

## Category Reference Table

All 11 categories, their slugs, and their compliance flags:

| Name | Slug | requires_fssai | requires_gstin |
|------|------|----------------|----------------|
| Seafood | `seafood` | True | False |
| Organic Produce | `organic-produce` | True | False |
| Baked Goods | `baked-goods` | True | False |
| Home-cooked Meals | `home-cooked-meals` | True | False |
| Dairy Products | `dairy-products` | True | False |
| Flowers & Plants | `flowers-plants` | False | False |
| Handcrafted Decor | `handcrafted-decor` | False | False |
| Electronics & Gadgets | `electronics-gadgets` | False | True |
| Clothing & Textiles | `clothing-textiles` | False | False |
| Services | `services` | False | False |
| Other | `other` | False | False |

The slug format is lowercase, hyphenated. Ampersands in names become hyphens in slugs (e.g., `Electronics & Gadgets` → `electronics-gadgets`).

## Files to Create

### Management Command

File: `namma_neighbor/apps/catalogue/management/__init__.py` (empty, if not present)

File: `namma_neighbor/apps/catalogue/management/commands/__init__.py` (empty, if not present)

File: `namma_neighbor/apps/catalogue/management/commands/seed_categories.py`

The command class must:
- Extend `BaseCommand` from `django.core.management.base`
- Define `help = 'Seed initial product categories for the catalogue app'`
- Implement `handle(self, *args, **options)` which iterates the 11 category definitions and calls `Category.objects.get_or_create(slug=..., defaults={...})` for each
- Write a `self.stdout.write` summary at the end (e.g., "Created X, skipped Y categories")

Stub:

```python
from django.core.management.base import BaseCommand
from namma_neighbor.apps.catalogue.models import Category


CATEGORIES = [
    # (name, slug, requires_fssai, requires_gstin)
    # ... all 11 entries from the reference table above
]


class Command(BaseCommand):
    help = "Seed initial product categories for the catalogue app"

    def handle(self, *args, **options):
        """Iterate CATEGORIES and get_or_create each by slug."""
        ...
```

### Data Migration

File: `namma_neighbor/apps/catalogue/migrations/0002_seed_categories.py`

The migration must:
- Declare `dependencies = [('catalogue', '0001_initial')]`
- Define a `seed_categories(apps, schema_editor)` forward function that retrieves the `Category` model via `apps.get_model('catalogue', 'Category')` and calls `get_or_create` for each of the 11 entries
- Define a `reverse_categories(apps, schema_editor)` reverse function that deletes all seeded slugs (for clean rollback in development)
- Use `migrations.RunPython(seed_categories, reverse_categories)` as the single operation

Important: The forward function must use `apps.get_model(...)` rather than importing the model directly. Direct model imports in migrations are fragile across historical states.

Stub:

```python
from django.db import migrations


CATEGORIES = [
    # same list as management command
]


def seed_categories(apps, schema_editor):
    """Create all 11 categories using the historical model from the migration state."""
    Category = apps.get_model('catalogue', 'Category')
    ...


def reverse_categories(apps, schema_editor):
    """Delete all seeded categories (for rollback)."""
    Category = apps.get_model('catalogue', 'Category')
    ...


class Migration(migrations.Migration):

    dependencies = [
        ('catalogue', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_categories, reverse_categories),
    ]
```

## Key Implementation Notes

**Single source of truth for category data:** Define the `CATEGORIES` list once and import or duplicate it into both the management command and the migration. Duplication is acceptable here since migrations are frozen snapshots — do not import from the management command in the migration, as that would create a runtime dependency from the migration to application code.

**Idempotency via slug:** Always use `get_or_create(slug=slug, defaults={...})`. The `slug` is the stable key. If names or flags need updating, `get_or_create` will not overwrite existing rows — a separate data migration would be needed for that.

**Migration dependency:** `0001_initial.py` already creates the `Category` table (it is the first migration in this app). The `0002_seed_categories` migration depends only on `('catalogue', '0001_initial')`. No cross-app dependencies are needed here because `Category` has no FK to other apps.

**No `icon_url` in seed data:** Leave `icon_url` as blank/null for all seeded categories. Icons are optional and can be added later via Django Admin.

**FSSAI flag logic:** Any category where the goods are consumed as food requires `requires_fssai=True`. The five food categories are: Seafood, Organic Produce, Baked Goods, Home-cooked Meals, Dairy Products. Everything else is False.

**GSTIN flag logic:** Only `Electronics & Gadgets` requires `requires_gstin=True` in this initial seed. High-value goods that legally require GST invoicing. All others are False.

## Running the Command

After migrations have run:

```
python manage.py seed_categories
```

On a fresh deploy, `0002_seed_categories.py` will have already populated the table via `python manage.py migrate`. The management command is provided for re-seeding in development or after a `flush`.