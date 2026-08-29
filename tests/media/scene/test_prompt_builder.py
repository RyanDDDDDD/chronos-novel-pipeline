from __future__ import annotations


def test_build_scene_positive_layers_preset_and_addendum(monkeypatch):
    from media.scene import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"portrait_style_preset_id": "anime",
                 "portrait_style_prompt": "extra glow",
                 "portrait_negative_prompt": "no watermark"},
    )
    pos, neg = prompt_builder.build_scene_positive("tavern, 2girls, night")
    assert pos == (
        "tavern, 2girls, night, masterpiece, best quality, highly detailed, anime style, "
        "sharp focus, extra glow"
    )
    assert neg == (
        "worst quality, low quality, blurry, extra fingers, deformed, bad anatomy, "
        "watermark, text, no watermark"
    )


def test_build_scene_positive_empty_base(monkeypatch):
    from media.scene import prompt_builder

    monkeypatch.setattr(
        "engine.modes.author_loop_skill_prefs.load_dialogue_prefs",
        lambda: {"portrait_style_preset_id": "anime",
                 "portrait_style_prompt": "", "portrait_negative_prompt": ""},
    )
    pos, _ = prompt_builder.build_scene_positive("")
    assert pos == "masterpiece, best quality, highly detailed, anime style, sharp focus"
