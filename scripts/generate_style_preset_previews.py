"""One-time asset generation: renders one representative preview image per built-in art
style preset (media.portrait.style_presets.ART_STYLE_PRESETS) via a real Novita call, using
a fixed neutral subject so all previews are visually comparable. Run manually, once, when
adding/editing a preset -- NOT part of any test suite or CI gate (needs a real, billed
Novita API key). Output goes to src/frontend/public/art-style-presets/<id>.jpg and is meant
to be committed to git as a static UI asset.

Usage:
    python scripts/generate_style_preset_previews.py --api-key sk-... --model <novita-sd-name>
    python scripts/generate_style_preset_previews.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

#"adult" is load-bearing, not decorative: earlier previews generated from a bare "1girl"
#subject came out child-coded for a couple of style/model combinations and had to be pulled
#(see git history) -- always pin an explicit adult descriptor here, never regress to a bare
#age-ambiguous subject.
_NEUTRAL_SUBJECT = "1girl, adult woman, 25 years old, standing, portrait, upper body, looking at viewer, simple background"
_DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "frontend" / "public" / "art-style-presets"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default="", help="Novita API key (required unless --dry-run)")
    parser.add_argument("--model", default="", help="Novita checkpoint sd_name to render with (required unless --dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="List presets and exit without calling Novita or writing files")
    parser.add_argument("--out-dir", default=str(_DEFAULT_OUT_DIR), help="Directory to write <preset-id>.jpg into")
    return parser.parse_args(argv)


async def _generate_all(api_key: str, model: str, out_dir: Path) -> None:
    from media.portrait.novita_provider import NovitaImageProvider
    from media.portrait.style_presets import ART_STYLE_PRESETS

    out_dir.mkdir(parents=True, exist_ok=True)
    provider = NovitaImageProvider(api_key=api_key, model=model)
    for preset in ART_STYLE_PRESETS:
        prompt = f"{_NEUTRAL_SUBJECT}, {preset.positive_fragment}"
        image_bytes = await provider.generate(prompt, negative_prompt=preset.negative_fragment)
        (out_dir / f"{preset.id}.jpg").write_bytes(image_bytes)
        print(f"wrote {preset.id}.jpg")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    from media.portrait.style_presets import ART_STYLE_PRESETS

    if args.dry_run:
        for preset in ART_STYLE_PRESETS:
            print(f"[dry-run] would render {preset.id} ({preset.label})")
        return 0

    if not args.api_key or not args.model:
        print("error: --api-key and --model are required unless --dry-run", file=sys.stderr)
        return 1

    asyncio.run(_generate_all(args.api_key, args.model, Path(args.out_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
