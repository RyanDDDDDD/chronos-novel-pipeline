"""Run-time token accumulator: Each subsystem builds one at the beginning of the run, and records at the LLM call location.

begin() resets the grid (override semantics); record() accumulates persistence.
Statistics bypass: any exception logger.warning swallows, never blocks creation/build."""
from __future__ import annotations

from loguru import logger

from api.services.token_ledger import add_to_cell, reset_cell


class TokenAccountant:
    def __init__(
        self, *, novel_id: str, subsystem: str, key: str, model: str,
    ) -> None:
        self.novel_id = novel_id
        self.subsystem = subsystem
        self.key = key
        self.model = model

    def begin(self) -> None:
        """
run starts by resetting the grid (implementing override semantics). Don’t throw away failure."""
        try:
            reset_cell(self.subsystem, self.key, novel_id=self.novel_id)
        except Exception as e:  #noqa: BLE001 — Statistical bypass, never blocking
            logger.warning("[token-acc] begin 失败 {}/{}：{}", self.subsystem, self.key, e)

    async def record(
        self, tokens_in: int, tokens_out: int, tokens_cached: int = 0, *, model: str | None = None,
    ) -> None:
        effective_model = model or self.model
        try:
            add_to_cell(
                self.subsystem, self.key, tokens_in, tokens_out, tokens_cached,
                effective_model, novel_id=self.novel_id,
            )
        except Exception as e:  #noqa: BLE001 — Statistical bypass, never blocking
            logger.warning("[token-acc] record 失败 {}/{}：{}", self.subsystem, self.key, e)
