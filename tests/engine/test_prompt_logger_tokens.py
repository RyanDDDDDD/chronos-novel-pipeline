"""prompt_logger.load_historical_tokens behavior."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "backend"))

from llm.prompt_logger import PromptLogger


def _write_log(path: str, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "run_header"}) + "\n")
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_load_historical_tokens_latest_prior_run_only(tmp_path):
  log_dir = tmp_path / "logs"
  log_dir.mkdir()
  old_log = log_dir / "chapter_001_20260101_000000.json"
  _write_log(str(old_log), [{"step": 1, "tokens_in": 100, "tokens_out": 50}])
  newer_log = log_dir / "chapter_001_20260102_000000.json"
  _write_log(str(newer_log), [{"step": 1, "tokens_in": 10, "tokens_out": 5}])

  pl = PromptLogger(1, logs_dir=str(log_dir))
  all_runs = pl.load_historical_tokens(latest_prior_run_only=False)
  assert all_runs[1] == (110, 55, 0)

  latest = pl.load_historical_tokens(latest_prior_run_only=True)
  assert latest[1] == (10, 5, 0)


def test_log_llm_call_records_tokens_cached(tmp_path):
    import glob

    pl = PromptLogger(7, logs_dir=str(tmp_path))
    pl.log_llm_call(
        step=1, agent="poser", model="m", system="s", user="u", response="r",
        tokens_in=100, tokens_out=20, tokens_cached=80, duration_s=0.1,
    )
    log_file = glob.glob(str(tmp_path / "chapter_007_*.json"))[0]
    entries = [json.loads(line) for line in open(log_file, encoding="utf-8") if line.strip()]
    call = next(e for e in entries if e.get("agent") == "poser")
    assert call["tokens_cached"] == 80
    assert call["tokens_in"] == 100


def test_log_llm_call_tokens_cached_defaults_zero(tmp_path):
    import glob

    pl = PromptLogger(8, logs_dir=str(tmp_path))
    pl.log_llm_call(
        step=1, agent="x", model="m", system="s", user="u", response="r",
        tokens_in=5, tokens_out=5, duration_s=0.1,
    )
    log_file = glob.glob(str(tmp_path / "chapter_008_*.json"))[0]
    entries = [json.loads(line) for line in open(log_file, encoding="utf-8") if line.strip()]
    call = next(e for e in entries if e.get("agent") == "x")
    assert call["tokens_cached"] == 0


def test_load_historical_tokens_only_steps_filter(tmp_path):
  log_dir = tmp_path / "logs"
  log_dir.mkdir()
  prior = log_dir / "chapter_002_20260101_000000.json"
  _write_log(
      str(prior),
      [
          {"step": 1, "tokens_in": 1, "tokens_out": 1},
          {"step": 2, "tokens_in": 9, "tokens_out": 9},
      ],
  )
  pl = PromptLogger(2, logs_dir=str(log_dir))
  filtered = pl.load_historical_tokens(only_steps={2}, latest_prior_run_only=True)
  assert filtered == {2: (9, 9, 0)}


def test_load_historical_tokens_sums_cached(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prior = log_dir / "chapter_003_20260101_000000.json"
    _write_log(
        str(prior),
        [
            {"step": 1, "tokens_in": 100, "tokens_out": 10, "tokens_cached": 80},
            {"step": 1, "tokens_in": 50, "tokens_out": 5, "tokens_cached": 40},
        ],
    )
    pl = PromptLogger(3, logs_dir=str(log_dir))
    assert pl.load_historical_tokens(latest_prior_run_only=True) == {1: (150, 15, 120)}
