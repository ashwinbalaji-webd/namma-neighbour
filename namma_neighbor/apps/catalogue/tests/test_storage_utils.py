import io

import pytest
from PIL import Image, UnidentifiedImageError

from apps.catalogue.utils import convert_to_webp, get_presigned_url, _s3_client


def make_jpeg_bytes(width=100, height=100) -> io.BytesIO:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf


def make_png_rgba_bytes(width=100, height=100) -> io.BytesIO:
    buf = io.BytesIO()
    img = Image.new("RGBA", (width, height), color=(0, 255, 0, 128))
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_convert_to_webp_jpeg_input_returns_webp_contentfile():
    jpeg = make_jpeg_bytes()
    result = convert_to_webp(jpeg)
    assert result.name.endswith(".webp")
    result.seek(0)
    reopened = Image.open(result)
    assert reopened.format == "WEBP"


def test_convert_to_webp_png_rgba_no_error():
    png = make_png_rgba_bytes()
    result = convert_to_webp(png)
    assert result.name.endswith(".webp")
    result.seek(0)
    reopened = Image.open(result)
    assert reopened.format == "WEBP"


def test_convert_to_webp_non_image_raises():
    bad_file = io.BytesIO(b"this is not an image")
    with pytest.raises(UnidentifiedImageError):
        convert_to_webp(bad_file)


def test_convert_to_webp_decompression_bomb_raises():
    import apps.catalogue.utils as utils_module
    from unittest.mock import patch as _patch
    jpeg = make_jpeg_bytes(width=20, height=20)
    with _patch.object(utils_module.Image, "MAX_IMAGE_PIXELS", 100):
        with pytest.raises(Image.DecompressionBombError):
            convert_to_webp(jpeg)


def test_get_presigned_url_returns_url_string(moto_s3):
    from unittest.mock import patch
    import apps.catalogue.utils as utils_module

    moto_client = moto_s3

    with patch.object(utils_module, "_s3_client", moto_client):
        url = get_presigned_url("media/products/1/test.webp")

    assert isinstance(url, str)
    assert len(url) > 0


def test_get_presigned_url_reuses_boto3_client():
    import apps.catalogue.utils as utils_module
    from unittest.mock import patch, MagicMock

    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "https://example.com/test"

    with patch.object(utils_module, "_s3_client", mock_client):
        get_presigned_url("some/key.webp")
        get_presigned_url("other/key.webp")
        # Both calls used the patched module-level client, not a new per-call client
        assert mock_client.generate_presigned_url.call_count == 2
        assert utils_module._s3_client is mock_client
