from django.conf import settings


def test_surepass_token_setting_exists():
    assert hasattr(settings, 'SUREPASS_TOKEN')
    assert settings.SUREPASS_TOKEN == 'test-surepass-token'


def test_razorpay_webhook_secret_setting_exists():
    assert hasattr(settings, 'RAZORPAY_WEBHOOK_SECRET')
    assert settings.RAZORPAY_WEBHOOK_SECRET != ''


def test_beat_schedule_contains_auto_delist_missed_windows():
    assert 'auto_delist_missed_windows' in settings.CELERY_BEAT_SCHEDULE


def test_auto_delist_task_path_is_correct():
    entry = settings.CELERY_BEAT_SCHEDULE['auto_delist_missed_windows']
    assert entry['task'] == 'apps.vendors.tasks.auto_delist_missed_windows'


def test_recheck_fssai_expiry_fires_at_0600_ist():
    schedule = settings.CELERY_BEAT_SCHEDULE['recheck_fssai_expiry']['schedule']
    assert schedule.hour == {6}
    assert schedule.minute == {0}


def test_auto_delist_fires_at_0630_ist():
    schedule = settings.CELERY_BEAT_SCHEDULE['auto_delist_missed_windows']['schedule']
    assert schedule.hour == {6}
    assert schedule.minute == {30}


def test_auto_delist_queue_is_kyc():
    entry = settings.CELERY_BEAT_SCHEDULE['auto_delist_missed_windows']
    assert entry['options']['queue'] == 'kyc'


def test_razorpay_key_id_setting_exists():
    assert hasattr(settings, 'RAZORPAY_KEY_ID')
    assert settings.RAZORPAY_KEY_ID == 'test-key-id'


def test_razorpay_key_secret_setting_exists():
    assert hasattr(settings, 'RAZORPAY_KEY_SECRET')
    assert settings.RAZORPAY_KEY_SECRET == 'test-key-secret'
