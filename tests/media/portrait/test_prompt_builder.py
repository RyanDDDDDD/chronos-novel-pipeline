from __future__ import annotations


def test_build_portrait_prompt_defaults_to_anime_preset_when_unconfigured(monkeypatch):
    from media.portrait import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "portrait_style_preset_id": "anime",
            "portrait_style_prompt": "", "portrait_negative_prompt": "",
        },
    )

    prompt, negative = prompt_builder.build_portrait_prompt("1girl, silver hair")

    assert prompt == (
        "1girl, silver hair, masterpiece, best quality, highly detailed, anime style, sharp focus"
    )
    assert negative == (
        "worst quality, low quality, blurry, extra fingers, deformed, bad anatomy, watermark, text"
    )


def test_build_portrait_prompt_layers_preset_then_freeform_addendum(monkeypatch):
    from media.portrait import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "portrait_style_preset_id": "cyberpunk",
            "portrait_style_prompt": "extra neon glow",
            "portrait_negative_prompt": "no watermark",
        },
    )

    prompt, negative = prompt_builder.build_portrait_prompt("1girl, silver hair")

    assert prompt == (
        "1girl, silver hair, cyberpunk style, neon lighting, futuristic cityscape, "
        "rain-slicked streets, holographic details, high contrast, masterpiece, best "
        "quality, highly detailed, extra neon glow"
    )
    assert negative == (
        "worst quality, low quality, blurry, pastel colors, medieval, watermark, text, "
        "no watermark"
    )


def test_build_portrait_prompt_falls_back_to_preset_only_when_tags_empty(monkeypatch):
    from media.portrait import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "portrait_style_preset_id": "anime",
            "portrait_style_prompt": "", "portrait_negative_prompt": "",
        },
    )

    prompt, _ = prompt_builder.build_portrait_prompt("")

    assert prompt == "masterpiece, best quality, highly detailed, anime style, sharp focus"


def test_build_portrait_prompt_unknown_preset_id_falls_back_to_default(monkeypatch):
    from media.portrait import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "portrait_style_preset_id": "does-not-exist",
            "portrait_style_prompt": "", "portrait_negative_prompt": "",
        },
    )

    prompt, _ = prompt_builder.build_portrait_prompt("1girl")

    assert prompt == "1girl, masterpiece, best quality, highly detailed, anime style, sharp focus"


def test_build_portrait_prompt_applies_base_model_adapter(monkeypatch):
    from media.portrait import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {
            "portrait_style_preset_id": "anime",
            "portrait_style_prompt": "", "portrait_negative_prompt": "",
        },
    )

    prompt, negative = prompt_builder.build_portrait_prompt("1girl", base_model="Pony")

    assert prompt.startswith("score_9, score_8_up, score_7_up, score_6_up, 1girl,")
    assert negative.startswith("score_4, score_5, score_6, ")
