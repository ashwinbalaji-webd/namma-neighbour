import os

os.environ.setdefault('AWS_STORAGE_BUCKET_NAME', 'test-bucket')
os.environ.setdefault('RAZORPAY_WEBHOOK_SECRET', 'test-webhook-secret')

from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*', 'testserver']

SMS_BACKEND = 'apps.core.sms.backends.console.ConsoleSMSBackend'

DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///test.db')
}

# Use dummy cache for tests to avoid Redis dependency
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

SUREPASS_TOKEN = 'test-surepass-token'
RAZORPAY_KEY_ID = 'test-key-id'
RAZORPAY_KEY_SECRET = 'test-key-secret'
AWS_ACCESS_KEY_ID = 'test-access-key'
AWS_SECRET_ACCESS_KEY = 'test-secret-key'
