import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from django.utils import timezone


# ─── Celery App Loading ────────────────────────────────────────────────────────

def test_celery_app_importable():
    from config.celery import app
    from celery import Celery
    assert isinstance(app, Celery)


def test_celery_app_accessible_from_config_package():
    import config
    from celery import Celery
    assert isinstance(config.celery_app, Celery)


def test_task_queues_contains_five_expected_queues():
    from config.celery import app
    queue_names = {q.name for q in app.conf.task_queues}
    assert {'default', 'sms', 'kyc', 'payments', 'notifications'}.issubset(queue_names)


# ─── Beat Schedule ────────────────────────────────────────────────────────────

def test_beat_schedule_contains_required_tasks():
    from django.conf import settings
    schedule = settings.CELERY_BEAT_SCHEDULE
    assert 'recheck_fssai_expiry' in schedule
    assert 'release_payment_holds' in schedule
    assert 'purge_expired_otps' in schedule


def test_celery_timezone_is_asia_kolkata():
    from django.conf import settings
    assert settings.CELERY_TIMEZONE == 'Asia/Kolkata'


# ─── OTP Celery Tasks ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_send_otp_sms_task_is_registered():
    from config.celery import app
    from apps.users.tasks import send_otp_sms
    assert send_otp_sms.name in app.tasks
    assert send_otp_sms.max_retries == 3


@pytest.mark.django_db
def test_send_otp_sms_calls_backend_send():
    from apps.users.tasks import send_otp_sms

    mock_backend = MagicMock()
    with patch('apps.users.tasks.get_sms_backend', return_value=mock_backend):
        send_otp_sms.apply(args=['9999999999', '123456'])

    mock_backend.send.assert_called_once_with('9999999999', '123456')


@pytest.mark.django_db
def test_send_otp_sms_retries_on_exception():
    from apps.users.tasks import send_otp_sms

    mock_backend = MagicMock()
    mock_backend.send.side_effect = Exception("SMS service down")

    with patch('apps.users.tasks.get_sms_backend', return_value=mock_backend):
        result = send_otp_sms.apply(args=['9999999999', '123456'])
        with pytest.raises(Exception):
            result.get()

    # max_retries=3 means 1 initial call + 3 retries = 4 total
    assert mock_backend.send.call_count == 4


@pytest.mark.django_db
def test_purge_expired_otps_deletes_old_records():
    from apps.users.models import PhoneOTP
    from apps.users.tasks import purge_expired_otps

    old = PhoneOTP.objects.create(phone='8888888881', otp_hash='a' * 64)
    PhoneOTP.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )
    recent = PhoneOTP.objects.create(phone='8888888882', otp_hash='b' * 64)

    purge_expired_otps()

    assert not PhoneOTP.objects.filter(pk=old.pk).exists()
    assert PhoneOTP.objects.filter(pk=recent.pk).exists()


@pytest.mark.django_db
def test_purge_expired_otps_keeps_recent_records():
    from apps.users.models import PhoneOTP
    from apps.users.tasks import purge_expired_otps

    recent = PhoneOTP.objects.create(phone='8888888883', otp_hash='c' * 64)

    purge_expired_otps()

    assert PhoneOTP.objects.filter(pk=recent.pk).exists()
