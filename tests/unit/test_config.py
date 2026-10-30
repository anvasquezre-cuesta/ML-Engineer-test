import pytest
from pydantic import ValidationError

from app.config import Settings


def test_ac_cfg_01_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("OCR_DPI", "150")

    settings = Settings(_env_file=None)

    assert settings.ocr_dpi == 150
    assert settings.ocr_lang == "eng"


def test_ac_cfg_02_threshold_out_of_range_rejected(monkeypatch):
    monkeypatch.setenv("FUZZY_THRESHOLD", "1.5")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_ac_cfg_03_ner_defaults():
    settings = Settings(_env_file=None)

    assert settings.ner_model == "en_core_web_sm"
    assert settings.ner_drop_all_caps is True


def test_ac_cfg_04_bbox_origin_default():
    assert Settings(_env_file=None).bbox_origin == "top-left"


@pytest.mark.parametrize(("name", "value"), [("TOP_K", "0"), ("MIN_SCORE", "1.5")])
def test_ac_ask_06_invalid_retrieval_settings_fail_at_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
