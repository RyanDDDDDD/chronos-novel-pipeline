from __future__ import annotations

import pytest


@pytest.mark.parametrize("base_model", ["Pony", "pony diffusion v6 xl", "PONY"])
def test_pony_prefixes_score_tags_on_both_positive_and_negative(base_model):
    from media.portrait.base_model_adapter import adapt_for_base_model

    positive, negative = adapt_for_base_model("1girl, silver hair", "bad hands", base_model)

    assert positive == "score_9, score_8_up, score_7_up, score_6_up, 1girl, silver hair"
    assert negative == "score_4, score_5, score_6, bad hands"


@pytest.mark.parametrize("base_model", ["Flux.1 D", "flux.1 [schnell]", "FLUX"])
def test_flux_wraps_positive_in_natural_language_and_drops_negative(base_model):
    from media.portrait.base_model_adapter import adapt_for_base_model

    positive, negative = adapt_for_base_model("1girl, silver hair", "bad hands", base_model)

    assert positive == "A detailed illustration of 1girl, silver hair."
    assert negative == ""


@pytest.mark.parametrize("base_model", ["SDXL 1.0", "SD 1.5", None, "", "SD 3.5", "Illustrious XL"])
def test_other_and_unknown_architectures_pass_through_unchanged(base_model):
    from media.portrait.base_model_adapter import adapt_for_base_model

    positive, negative = adapt_for_base_model("1girl, silver hair", "bad hands", base_model)

    assert positive == "1girl, silver hair"
    assert negative == "bad hands"
