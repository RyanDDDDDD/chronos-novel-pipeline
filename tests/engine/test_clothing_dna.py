"""clothing_dna schema helper tests."""
from __future__ import annotations

from engine.setup.cast.clothing_dna import default_signature_outfit, render_clothing_dna_lines


def test_default_signature_outfit_from_palette_and_materials():
    out = default_signature_outfit({
        "color_palette": ["黑", "暗金"],
        "materials_preference": ["皮革"],
    })
    assert "黑、暗金色系" in out
    assert "皮革材质" in out
    assert "待细化" in out


def test_render_clothing_dna_lines_includes_signature_and_accessories():
    lines = render_clothing_dna_lines({
        "color_palette": ["白"],
        "materials_preference": ["棉"],
        "signature_outfit": "及膝白裙配浅灰开衫",
        "accessories": ["银链", "腕带"],
    })
    assert len(lines) == 1
    assert "招牌常服=及膝白裙配浅灰开衫" in lines[0]
    assert "配饰=银链／腕带" in lines[0]
    assert "色系=白" in lines[0]
