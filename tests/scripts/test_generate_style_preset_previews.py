from __future__ import annotations


def test_dry_run_lists_all_presets_without_network_or_files(tmp_path, capsys):
    from scripts.generate_style_preset_previews import main
    from media.portrait.style_presets import ART_STYLE_PRESETS

    exit_code = main(["--dry-run", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    for preset in ART_STYLE_PRESETS:
        assert preset.id in captured.out
    assert list(tmp_path.iterdir()) == []  # dry-run must not write anything


def test_missing_api_key_or_model_errors_without_dry_run(capsys):
    from scripts.generate_style_preset_previews import main

    exit_code = main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "--api-key" in captured.err
