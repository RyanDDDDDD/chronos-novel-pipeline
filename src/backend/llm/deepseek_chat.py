"""DeepSeek-aware ChatOpenAI: round-trip reasoning_content for thinking + tools.

langchain_openai drops ``reasoning_content`` on both ingest and egress -- including
streamed deltas, where upstream's ``_convert_delta_to_message_chunk`` only lifts
``function_call``/``tool_calls`` into ``additional_kwargs`` and silently ignores any
other field. DeepSeek's thinking-mode API requires every assistant message that
performed a tool call to carry ``reasoning_content`` when replayed, or the next
request returns HTTP 400 -- so callers that stream (e.g. setup_chat's
``astream_events``) need it captured from chunks too, not just non-streaming
``_create_chat_result``."""
from __future__ import annotations

from typing import Any

import openai
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


class DeepSeekChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that preserves DeepSeek thinking-mode reasoning_content."""

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload_messages = payload.get("messages")
        if not payload_messages or self._use_responses_api(payload):
            return payload
        ai_iter = iter(m for m in messages if isinstance(m, AIMessage))
        for pm in payload_messages:
            if pm.get("role") != "assistant":
                continue
            ai = next(ai_iter, None)
            if ai is None:
                break
            rc = (ai.additional_kwargs or {}).get("reasoning_content")
            if rc is not None:
                pm["reasoning_content"] = rc
            elif pm.get("tool_calls"):
                pm["reasoning_content"] = ""
        return payload

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info=generation_info)
        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        for gen, choice in zip(result.generations, response_dict.get("choices", []), strict=False):
            if not isinstance(gen.message, AIMessage):
                continue
            rc = (choice.get("message") or {}).get("reasoning_content")
            if rc is None:
                continue
            gen.message.additional_kwargs = {
                **(gen.message.additional_kwargs or {}),
                "reasoning_content": rc,
            }
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None or not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk
        choices = chunk.get("choices") or []
        delta = choices[0].get("delta") if choices else None
        rc = (delta or {}).get("reasoning_content")
        if rc:
            generation_chunk.message.additional_kwargs = {
                **(generation_chunk.message.additional_kwargs or {}),
                "reasoning_content": rc,
            }
        return generation_chunk
