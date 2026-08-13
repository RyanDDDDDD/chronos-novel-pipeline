from engine.archive.archive_error import validate_archive


def _archive(**overrides):
    base = {
        "name": "测试角色",
        "role": "submissive",
        "extensions": {},
        "personality": "外冷内热",
    }
    base.update(overrides)
    return base


def test_validate_archive_accepts_profile_without_clothing_or_state():
    errors = validate_archive(_archive())
    assert not errors


def test_validate_archive_rejects_invalid_sliders_type():
    errors = validate_archive(_archive(sliders="not-a-dict"))
    assert any(e.field == "sliders" for e in errors)
