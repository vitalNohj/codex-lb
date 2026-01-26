from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.openai.requests import (
    ResponsesCompactRequest,
    ResponsesReasoning,
    ResponsesRequest,
    ResponsesTextControls,
)
from app.core.types import JsonValue


class V1ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[JsonValue] | None = None
    input: list[JsonValue] | None = None
    instructions: str | None = None
    tools: list[JsonValue] = Field(default_factory=list)
    tool_choice: str | None = None
    parallel_tool_calls: bool | None = None
    reasoning: ResponsesReasoning | None = None
    store: bool | None = None
    stream: bool | None = None
    include: list[str] = Field(default_factory=list)
    prompt_cache_key: str | None = None
    text: ResponsesTextControls | None = None

    @field_validator("store")
    @classmethod
    def _ensure_store_false(cls, value: bool | None) -> bool | None:
        if value is True:
            raise ValueError("store must be false")
        return value

    @model_validator(mode="after")
    def _validate_input(self) -> "V1ResponsesRequest":
        if self.messages is None and self.input is None:
            raise ValueError("Provide either 'input' or 'messages'.")
        if self.messages is not None and self.input not in (None, []):
            raise ValueError("Provide either 'input' or 'messages', not both.")
        return self

    def to_responses_request(self) -> ResponsesRequest:
        data = self.model_dump(mode="json", exclude_none=True)
        messages = data.pop("messages", None)
        instructions = data.get("instructions")
        instruction_text = instructions if isinstance(instructions, str) else ""
        input_value = data.get("input")
        input_items: list[JsonValue] = input_value if isinstance(input_value, list) else []

        if messages is not None:
            instruction_text, input_items = _coerce_messages(instruction_text, messages)

        data["instructions"] = instruction_text
        data["input"] = input_items
        return ResponsesRequest.model_validate(data)


class V1ResponsesCompactRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1)
    messages: list[JsonValue] | None = None
    input: list[JsonValue] | None = None
    instructions: str | None = None

    @model_validator(mode="after")
    def _validate_input(self) -> "V1ResponsesCompactRequest":
        if self.messages is None and self.input is None:
            raise ValueError("Provide either 'input' or 'messages'.")
        if self.messages is not None and self.input not in (None, []):
            raise ValueError("Provide either 'input' or 'messages', not both.")
        return self

    def to_compact_request(self) -> ResponsesCompactRequest:
        data = self.model_dump(mode="json", exclude_none=True)
        messages = data.pop("messages", None)
        instructions = data.get("instructions")
        instruction_text = instructions if isinstance(instructions, str) else ""
        input_value = data.get("input")
        input_items: list[JsonValue] = input_value if isinstance(input_value, list) else []

        if messages is not None:
            instruction_text, input_items = _coerce_messages(instruction_text, messages)

        data["instructions"] = instruction_text
        data["input"] = input_items
        return ResponsesCompactRequest.model_validate(data)


def _coerce_messages(existing_instructions: str, messages: list[JsonValue]) -> tuple[str, list[JsonValue]]:
    instruction_parts: list[str] = []
    input_messages: list[JsonValue] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object.")
        message_dict = cast(dict[str, JsonValue], message)
        role_value = message_dict.get("role")
        role = role_value if isinstance(role_value, str) else None
        if role in ("system", "developer"):
            content_text = _content_to_text(message_dict.get("content"))
            if content_text:
                instruction_parts.append(content_text)
            continue
        input_messages.append(cast(JsonValue, message_dict))
    merged = _merge_instructions(existing_instructions, instruction_parts)
    return merged, input_messages


def _merge_instructions(existing: str, extra_parts: list[str]) -> str:
    if not extra_parts:
        return existing
    extra = "\n".join([part for part in extra_parts if part])
    if not extra:
        return existing
    if existing:
        return f"{existing}\n{extra}"
    return extra


def _content_to_text(content: object) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                part_dict = cast(dict[str, JsonValue], part)
                text = part_dict.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join([part for part in parts if part])
    if isinstance(content, dict):
        content_dict = cast(dict[str, JsonValue], content)
        text = content_dict.get("text")
        if isinstance(text, str):
            return text
        return None
    return None
