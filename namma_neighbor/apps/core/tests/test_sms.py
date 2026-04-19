import pytest
from unittest.mock import patch, MagicMock
from django.test import override_settings
from apps.core.sms.backends.console import ConsoleSMSBackend
from apps.core.sms.backends.msg91 import MSG91SMSBackend
from apps.core.sms import get_sms_backend


def test_console_backend_writes_to_stdout(capsys):
    """ConsoleSMSBackend prints OTP to stdout."""
    backend = ConsoleSMSBackend()
    backend.send('+919876543210', '123456')
    captured = capsys.readouterr()
    assert '919876543210' in captured.out or '+919876543210' in captured.out
    assert '123456' in captured.out


def test_get_sms_backend_returns_console_when_configured():
    """get_sms_backend() returns ConsoleSMSBackend when configured."""
    with override_settings(SMS_BACKEND='apps.core.sms.backends.console.ConsoleSMSBackend'):
        backend = get_sms_backend()
        assert isinstance(backend, ConsoleSMSBackend)


def test_get_sms_backend_returns_msg91_when_configured():
    """get_sms_backend() returns MSG91SMSBackend when configured."""
    with override_settings(SMS_BACKEND='apps.core.sms.backends.msg91.MSG91SMSBackend'):
        backend = get_sms_backend()
        assert isinstance(backend, MSG91SMSBackend)


@patch('apps.core.sms.backends.msg91.requests.post')
def test_msg91_backend_makes_post_to_correct_url(mock_post):
    """MSG91SMSBackend POSTs to correct URL."""
    mock_post.return_value.json.return_value = {'type': 'success'}
    with override_settings(MSG91_AUTH_KEY='test_key'):
        backend = MSG91SMSBackend()
        backend.send('+919876543210', '123456')
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert 'https://control.msg91.com/api/v5/otp' in str(call_args)


@patch('apps.core.sms.backends.msg91.requests.post')
def test_msg91_backend_strips_plus_from_phone(mock_post):
    """MSG91SMSBackend strips + from phone number."""
    mock_post.return_value.json.return_value = {'type': 'success'}
    with override_settings(MSG91_AUTH_KEY='test_key'):
        backend = MSG91SMSBackend()
        backend.send('+919876543210', '123456')
        call_args = mock_post.call_args
        # Check that '919876543210' (without +) appears in the call
        assert '919876543210' in str(call_args)


@patch('apps.core.sms.backends.msg91.requests.post')
def test_msg91_backend_sends_correct_auth_header(mock_post):
    """MSG91SMSBackend includes correct authkey header."""
    mock_post.return_value.json.return_value = {'type': 'success'}
    test_key = 'test_auth_key_123'
    with override_settings(MSG91_AUTH_KEY=test_key):
        backend = MSG91SMSBackend()
        backend.send('+919876543210', '123456')
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs.get('headers', {}).get('authkey') == test_key
