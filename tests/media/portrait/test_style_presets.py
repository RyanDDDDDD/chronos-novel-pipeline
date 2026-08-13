from __future__ import annotations


def test_five_built_in_presets_with_unique_ids():
    from media.portrait.style_presets import ART_STYLE_PRESETS

    assert len(ART_STYLE_PRESETS) == 5
    ids = [p.id for p in ART_STYLE_PRESETS]
    assert len(ids) == len(set(ids))
    assert "anime" in ids


def test_anime_preset_matches_legacy_hardcoded_defaults():
    from media.portrait.style_presets import get_art_style_preset

    preset = get_art_style_preset("anime")
    assert preset.positive_fragment == (
        "masterpiece, best quality, highly detailed, anime style, sharp focus"
    )
    assert preset.negative_fragment == (
        "worst quality, low quality, blurry, extra fingers, deformed, bad anatomy, "
        "watermark, text"
    )


def test_get_art_style_preset_returns_exact_match():
    from media.portrait.style_presets import get_art_style_preset

    preset = get_art_style_preset("cyberpunk")
    assert preset.id == "cyberpunk"
    assert preset.label == "赛博朋克"


def test_get_art_style_preset_falls_back_to_default_for_unknown_or_missing_id():
    from media.portrait.style_presets import DEFAULT_ART_STYLE_PRESET_ID, get_art_style_preset

    assert get_art_style_preset("does-not-exist").id == DEFAULT_ART_STYLE_PRESET_ID
    assert get_art_style_preset(None).id == DEFAULT_ART_STYLE_PRESET_ID
    assert get_art_style_preset("").id == DEFAULT_ART_STYLE_PRESET_ID
