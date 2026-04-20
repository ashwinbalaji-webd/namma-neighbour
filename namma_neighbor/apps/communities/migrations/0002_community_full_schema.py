import secrets
import string
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_invite_codes(apps, schema_editor):
    Community = apps.get_model('communities', 'Community')
    alphabet = string.ascii_uppercase + string.digits
    db_alias = schema_editor.connection.alias
    for community in Community.objects.using(db_alias).filter(invite_code=''):
        candidate = ''.join(secrets.choice(alphabet) for _ in range(6))
        while Community.objects.using(db_alias).filter(invite_code=candidate).exists():
            candidate = ''.join(secrets.choice(alphabet) for _ in range(6))
        community.invite_code = candidate
        community.save(using=db_alias, update_fields=['invite_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('communities', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Scalar fields with safe defaults
        migrations.AddField(
            model_name='community',
            name='address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='community',
            name='admin_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='administered_communities', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='community',
            name='city',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='community',
            name='commission_pct',
            field=models.DecimalField(decimal_places=2, default=Decimal('7.50'), max_digits=5),
        ),
        migrations.AddField(
            model_name='community',
            name='is_reviewed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='community',
            name='pincode',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
        migrations.AddField(
            model_name='community',
            name='resident_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='community',
            name='vendor_count',
            field=models.PositiveIntegerField(default=0),
        ),
        # invite_code: add without unique, backfill existing rows, then enforce unique
        migrations.AddField(
            model_name='community',
            name='invite_code',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
        migrations.RunPython(backfill_invite_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='community',
            name='invite_code',
            field=models.CharField(db_index=True, max_length=6, unique=True),
        ),
        # slug: nullable so existing rows don't conflict; views assign on creation
        migrations.AddField(
            model_name='community',
            name='slug',
            field=models.SlugField(blank=True, default=None, max_length=120, null=True, unique=True),
        ),
        # Building
        migrations.CreateModel(
            name='Building',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('community', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='buildings', to='communities.community')),
            ],
            options={
                'unique_together': {('community', 'name')},
            },
        ),
        # Flat
        migrations.CreateModel(
            name='Flat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('flat_number', models.CharField(max_length=20)),
                ('floor', models.IntegerField(blank=True, null=True)),
                ('building', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='flats', to='communities.building')),
            ],
            options={
                'unique_together': {('building', 'flat_number')},
            },
        ),
        # ResidentProfile — inherits TimestampedModel (created_at, updated_at)
        migrations.CreateModel(
            name='ResidentProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user_type', models.CharField(choices=[('OWNER_RESIDING', 'Owner (Residing)'), ('OWNER_NON_RESIDING', 'Owner (Non-Residing)'), ('TENANT', 'Tenant'), ('FAMILY_DEPENDENT', 'Family Dependent')], max_length=20)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING', max_length=10)),
                ('community', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='residents', to='communities.community')),
                ('flat', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='residents', to='communities.flat')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='resident_profile', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
