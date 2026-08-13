from __future__ import annotations

import base64
import contextvars
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
from contextlib import contextmanager

from app.harness.events import utc_now_iso
from app.persistence.sqlite_store import task_store


class LLMProvider:
    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[2]
        self.env_path = self.project_root / ".env"
        self.default_model = "gpt-5.5"
        self._user_config_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("valuesee_user_llm_config", default=None)
        self.known_agents = [
            "planner",
            "reporter",
            "supervisor",
            "project_analyzer",
            "code_reviewer",
            "file_reviewer",
            "task_qa",
            "learning_coach",
            "memory_extractor",
            "shopping_intent",
            "shopping_product",
            "shopping_sku_matching",
            "shopping_review",
            "shopping_risk",
            "shopping_recommendation",
            "shopping_supervisor",
            "shopping_reporter",
        ]
        self.prompt_versions = [
            {
                "agent": "planner",
                "prompt_family": "planner",
                "prompt_version": "planner.v1",
                "title": "Baseline planner",
                "description": "Default task decomposition prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "planner",
                "prompt_family": "planner",
                "prompt_version": "planner.v2",
                "title": "Governance workflow planner",
                "description": "Adds risk gates, artifacts, and human review hints to planning.",
                "system_suffix": "请额外标注风险门禁、产物沉淀点、是否需要人工审核，以及适合转成 Workflow 节点的步骤。",
                "is_active": False,
            },
            {
                "agent": "reporter",
                "prompt_family": "reporter",
                "prompt_version": "reporter.v1",
                "title": "Baseline reporter",
                "description": "Default final report generation prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "reporter",
                "prompt_family": "reporter",
                "prompt_version": "reporter.v2",
                "title": "Governance reporter",
                "description": "Emphasizes risk level, evidence, next actions, and ownership.",
                "system_suffix": "请把结论组织为：关键证据、风险等级、责任归属、下一步动作、可沉淀知识。不要只写泛泛建议。",
                "is_active": False,
            },
            {
                "agent": "supervisor",
                "prompt_family": "supervisor",
                "prompt_version": "supervisor.v1",
                "title": "Baseline supervisor",
                "description": "Default multi-agent quality gate prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "supervisor",
                "prompt_family": "supervisor",
                "prompt_version": "supervisor.v2",
                "title": "Strict risk gate",
                "description": "Makes review-required and blocking risk judgement more explicit.",
                "system_suffix": "请优先判断是否存在阻断风险、是否必须人工审核、还缺少哪个 Agent 的证据，并给出短句结论。",
                "is_active": False,
            },
            {
                "agent": "project_analyzer",
                "prompt_family": "project_analyzer.architecture",
                "prompt_version": "project_analyzer.architecture.v1",
                "title": "Architecture baseline",
                "description": "Default project architecture interpretation prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "project_analyzer",
                "prompt_family": "project_analyzer.architecture",
                "prompt_version": "project_analyzer.architecture.v2",
                "title": "Architecture mentor",
                "description": "Adds onboarding path and module ownership reading order.",
                "system_suffix": "请额外输出新成员阅读顺序、模块职责边界、最可能误解的点，以及治理建议的证据来源。",
                "is_active": False,
            },
            {
                "agent": "code_reviewer",
                "prompt_family": "code_reviewer.suggestions",
                "prompt_version": "code_reviewer.suggestions.v1",
                "title": "Review suggestions baseline",
                "description": "Default code review remediation suggestions prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "code_reviewer",
                "prompt_family": "code_reviewer.suggestions",
                "prompt_version": "code_reviewer.suggestions.v2",
                "title": "Test-bound suggestions",
                "description": "Binds remediation suggestions to tests and governance actions.",
                "system_suffix": "每条建议都要尽量绑定具体 finding、推荐测试用例、优先级和人工审核条件。",
                "is_active": False,
            },
            {
                "agent": "file_reviewer",
                "prompt_family": "file_reviewer.semantic",
                "prompt_version": "file_reviewer.semantic.v1",
                "title": "Semantic file review baseline",
                "description": "Default hybrid semantic file review prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "file_reviewer",
                "prompt_family": "file_reviewer.semantic",
                "prompt_version": "file_reviewer.semantic.v2",
                "title": "Call-chain risk review",
                "description": "Emphasizes call-chain impact, testability, and dependency risk.",
                "system_suffix": "请优先分析调用链影响、隐含依赖、可测试性缺口、失败传播路径和治理优先级。",
                "is_active": False,
            },
            {
                "agent": "task_qa",
                "prompt_family": "task_qa",
                "prompt_version": "task_qa.v1",
                "title": "Task Q&A baseline",
                "description": "Default task context Q&A prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "task_qa",
                "prompt_family": "task_qa",
                "prompt_version": "task_qa.v2",
                "title": "Evidence-first Q&A",
                "description": "Answers with explicit source and uncertainty handling.",
                "system_suffix": "回答时请先说明依据来自报告、事件、知识库还是 fallback；信息不足时明确缺口。",
                "is_active": False,
            },
            {
                "agent": "learning_coach",
                "prompt_family": "learning_coach.reply",
                "prompt_version": "learning_coach.reply.v1",
                "title": "Learning reply baseline",
                "description": "Default learning coach reply prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "learning_coach",
                "prompt_family": "learning_coach.reply",
                "prompt_version": "learning_coach.reply.v2",
                "title": "Socratic learning reply",
                "description": "Makes the coach ask more adaptive follow-up questions.",
                "system_suffix": "请用苏格拉底式追问推进理解，避免直接给标准答案；每次只推进一个认知台阶。",
                "is_active": False,
            },
            {
                "agent": "learning_coach",
                "prompt_family": "learning_coach.questions",
                "prompt_version": "learning_coach.questions.v1",
                "title": "Learning questions baseline",
                "description": "Default next-question generation prompt.",
                "system_suffix": "",
                "is_active": True,
            },
            {
                "agent": "learning_coach",
                "prompt_family": "learning_coach.questions",
                "prompt_version": "learning_coach.questions.v2",
                "title": "Stage-aware questions",
                "description": "Generates questions tied to the current learning plan stage.",
                "system_suffix": "请根据当前 day/theme 生成递进问题，问题之间要体现从事实、机制到迁移应用的层次。",
                "is_active": False,
            },
            {
                "agent": "memory_extractor",
                "prompt_family": "memory_extractor",
                "prompt_version": "memory_extractor.v1",
                "title": "Governed long-term memory extraction",
                "description": "Extracts only durable, confirmation-required memory candidates from user messages.",
                "system_suffix": "Only emit concise JSON candidates. Never extract secrets, one-off questions, or instructions that do not represent durable memory.",
                "is_active": True,
            },
        ]

    @property
    def model(self) -> str:
        return self._config()["model"]

    @property
    def enabled(self) -> bool:
        return bool(self._config()["api_key"])

    @contextmanager
    def user_config_scope(self, config: dict[str, Any] | None):
        token = self._user_config_context.set(config)
        try:
            yield
        finally:
            self._user_config_context.reset(token)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        agent: str = "unknown",
        prompt_version: str = "v1",
    ) -> str:
        return self.generate_with_status(
            system_prompt,
            user_prompt,
            fallback,
            agent=agent,
            prompt_version=prompt_version,
        )["text"]

    def generate_with_status(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        agent: str = "unknown",
        prompt_version: str = "v1",
        use_active_prompt: bool = True,
        model_override: str | None = None,
        user_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system_prompt, prompt_version = self._resolve_prompt(agent, prompt_version, system_prompt, use_active_prompt=use_active_prompt)
        config = self._apply_user_config(self._config(agent), user_config or self._user_config_context.get())
        if model_override:
            config = {**config, "model": model_override}
        trace_id = f"llm_{uuid4().hex}"
        started = time.perf_counter()
        trace_input = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "fallback": fallback,
        }

        if not config["api_key"]:
            latency_ms = self._elapsed_ms(started)
            self._save_trace(
                trace_id=trace_id,
                agent=agent,
                prompt_version=prompt_version,
                model=None,
                input_payload=trace_input,
                output_text=fallback,
                fallback_used=True,
                error_message="OPENAI_API_KEY is not configured",
                latency_ms=latency_ms,
                token_usage={},
            )
            return {
                "text": fallback,
                "answer_source": "fallback",
                "fallback_used": True,
                "model": None,
                "trace_id": trace_id,
                "latency_ms": latency_ms,
            }

        try:
            if config.get("wire_api") == "responses":
                raw_response = self._invoke_responses_http(config, system_prompt, user_prompt)
                output_text = self._vision_response_text(raw_response)
                token_usage = raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {}
            else:
                from langchain_openai import ChatOpenAI

                llm = self._build_chat_openai(ChatOpenAI, config)
                response = llm.invoke(
                    [
                        ("system", system_prompt),
                        ("user", user_prompt),
                    ]
                )
                output_text = str(response.content)
                token_usage = self._extract_token_usage(response)
            if not output_text:
                raise ValueError("LLM provider returned no message content")
            latency_ms = self._elapsed_ms(started)
            self._save_trace(
                trace_id=trace_id,
                agent=agent,
                prompt_version=prompt_version,
                model=config["model"],
                input_payload=trace_input,
                output_text=output_text,
                fallback_used=False,
                error_message=None,
                latency_ms=latency_ms,
                token_usage=token_usage,
            )
            return {
                "text": output_text,
                "answer_source": "llm",
                "fallback_used": False,
                "model": config["model"],
                "trace_id": trace_id,
                "latency_ms": latency_ms,
                "token_usage": token_usage,
            }
        except Exception as exc:
            latency_ms = self._elapsed_ms(started)
            self._save_trace(
                trace_id=trace_id,
                agent=agent,
                prompt_version=prompt_version,
                model=config["model"],
                input_payload=trace_input,
                output_text=fallback,
                fallback_used=True,
                error_message=str(exc),
                latency_ms=latency_ms,
                token_usage={},
            )
            return {
                "text": fallback,
                "answer_source": "fallback",
                "fallback_used": True,
                "model": config["model"],
                "trace_id": trace_id,
                "latency_ms": latency_ms,
                "error_message": str(exc),
            }

    def _invoke_responses_http(
        self,
        config: dict[str, str],
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "model": config["model"],
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                ],
                "temperature": 0.2,
                "max_output_tokens": 2000,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        errors = []
        for endpoint in self._vision_endpoints(config.get("base_url", ""), "responses"):
            request = Request(
                endpoint,
                data=payload,
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "ValuSee/0.1 agents",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=60) as response:
                    body = response.read(4 * 1024 * 1024)
                parsed = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict) and (
                    isinstance(parsed.get("output"), list)
                    or isinstance(parsed.get("output_text"), str)
                ):
                    return parsed
                errors.append(f"{endpoint}: invalid response")
            except HTTPError as exc:
                detail = exc.read(500).decode("utf-8", errors="replace")
                errors.append(f"{endpoint}: HTTP {exc.code} {detail[:160]}")
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                errors.append(f"{endpoint}: {type(exc).__name__}")
        raise RuntimeError("; ".join(errors)[:800] or "Responses provider unavailable")

    def analyze_image_with_status(
        self,
        system_prompt: str,
        user_prompt: str,
        image_content: bytes,
        content_type: str,
        fallback: str = "",
        *,
        agent: str = "product_vision",
        prompt_version: str = "product_vision.v1",
        user_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = self._apply_user_config(self._config(agent), user_config or self._user_config_context.get())
        vision_models = self._vision_models(config)
        trace_id = f"llm_{uuid4().hex}"
        started = time.perf_counter()
        trace_input = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "image": {"content_type": content_type, "size_bytes": len(image_content)},
        }
        if not config["api_key"]:
            return self._image_fallback(
                trace_id, agent, prompt_version, trace_input, fallback, started, None,
                "OPENAI_API_KEY is not configured", "not_configured",
            )
        encoded = base64.b64encode(image_content).decode("ascii")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}", "detail": "high"}},
            ]},
        ]
        provider_configs = [{**config, "model": model} for model in vision_models]
        fallback_config = None if config.get("source") == "user_config" else self._vision_fallback_config()
        if fallback_config and all(
            (fallback_config["base_url"], fallback_config["model"], fallback_config["wire_api"])
            != (item["base_url"], item["model"], item["wire_api"])
            for item in provider_configs
        ):
            provider_configs.append(fallback_config)
        errors = []
        try:
            for index, provider_config in enumerate(provider_configs):
                try:
                    response = self._invoke_vision_http(provider_config, messages)
                    output_text = self._vision_response_text(response)
                    if not output_text:
                        raise ValueError("vision provider returned no message content")
                    latency_ms = self._elapsed_ms(started)
                    token_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
                    if index == 0:
                        provider_name = "primary"
                    elif provider_config.get("source") == "vision_fallback":
                        provider_name = "fallback_provider"
                    else:
                        provider_name = f"primary_candidate_{index + 1}"
                    self._save_trace(
                        trace_id=trace_id, agent=agent, prompt_version=prompt_version, model=provider_config["model"],
                        input_payload=trace_input, output_text=output_text, fallback_used=False,
                        error_message=None, latency_ms=latency_ms, token_usage=token_usage,
                    )
                    return {
                        "text": output_text, "answer_source": "llm", "fallback_used": False,
                        "model": provider_config["model"], "provider_name": provider_name,
                        "trace_id": trace_id, "latency_ms": latency_ms, "token_usage": token_usage,
                    }
                except Exception as exc:
                    error_message = str(exc)
                    errors.append(self._classify_provider_error(error_message))
            error_code = errors[-1] if errors else "provider_unavailable"
            if len(provider_configs) > 1:
                error_code = "all_providers_failed"
            return self._image_fallback(
                trace_id, agent, prompt_version, trace_input, fallback, started, provider_configs[0]["model"],
                "; ".join(errors), error_code,
            )
        except Exception as exc:
            error_message = str(exc)
            return self._image_fallback(
                trace_id, agent, prompt_version, trace_input, fallback, started, config["model"],
                error_message, self._classify_provider_error(error_message),
            )

    @staticmethod
    def _apply_user_config(config: dict[str, str], user_config: dict[str, Any] | None) -> dict[str, str]:
        if not user_config or not user_config.get("enabled") or not user_config.get("api_key"):
            return config
        return {
            **config,
            "api_key": str(user_config["api_key"]),
            "base_url": str(user_config.get("base_url") or ""),
            "model": str(user_config.get("model") or config["model"]),
            "wire_api": str(user_config.get("wire_api") or config["wire_api"]).lower(),
            "source": "user_config",
            "vision_model": str(user_config.get("vision_model") or user_config.get("model") or config["model"]),
        }

    def _vision_models(self, config: dict[str, str]) -> list[str]:
        if config.get("source") == "user_config" and config.get("vision_model"):
            return [str(config["vision_model"])]
        configured = os.getenv("VALUSee_VISION_MODELS", "").strip()
        primary = str(config.get("vision_model") or os.getenv("VALUSee_VISION_MODEL", "")).strip()
        values = [item.strip() for item in configured.split(",") if item.strip()]
        if primary:
            values.insert(0, primary)
        if not values:
            values.append(config["model"])
        return list(dict.fromkeys(values))

    def _vision_fallback_config(self) -> dict[str, str] | None:
        env_file = self._read_env_file()

        def value(name: str) -> str:
            return self._read_env_value(name, env_file).strip()

        api_key = self._normalize_api_key(value("OPENAI_VISION_FALLBACK_API_KEY"))
        base_url = value("OPENAI_VISION_FALLBACK_BASE_URL")
        if not api_key or not base_url:
            return None
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": value("OPENAI_VISION_FALLBACK_MODEL") or "gpt-5.5",
            "wire_api": value("OPENAI_VISION_FALLBACK_WIRE_API") or "chat_completions",
            "source": "vision_fallback",
        }

    def _invoke_vision_http(self, config: dict[str, str], messages: list[dict[str, Any]]) -> dict[str, Any]:
        wire_api = config.get("wire_api", "chat_completions")
        if wire_api == "responses":
            payload_object = {
                "model": config["model"],
                "input": self._responses_input(messages),
                "temperature": 0.1,
                "max_output_tokens": 1400,
            }
        else:
            payload_object = {
                "model": config["model"], "messages": messages,
                "temperature": 0.1, "max_tokens": 1400,
            }
        payload = json.dumps(payload_object, ensure_ascii=False).encode("utf-8")
        errors = []
        for endpoint in self._vision_endpoints(config.get("base_url", ""), wire_api):
            request = Request(
                endpoint,
                data=payload,
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "ValuSee/0.1 product-vision",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=45) as response:
                    body = response.read(4 * 1024 * 1024)
                parsed = json.loads(body.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict) and (
                    isinstance(parsed.get("choices"), list)
                    or isinstance(parsed.get("output"), list)
                    or isinstance(parsed.get("output_text"), str)
                ):
                    return parsed
                errors.append(f"{endpoint}: invalid response")
            except HTTPError as exc:
                detail = exc.read(500).decode("utf-8", errors="replace")
                errors.append(f"{endpoint}: HTTP {exc.code} {detail[:160]}")
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                errors.append(f"{endpoint}: {type(exc).__name__}")
        raise RuntimeError("; ".join(errors)[:800] or "vision provider unavailable")

    def _vision_endpoints(self, base_url: str, wire_api: str = "chat_completions") -> list[str]:
        base = base_url.strip().rstrip("/")
        suffix = "responses" if wire_api == "responses" else "chat/completions"
        if not base:
            return [f"https://api.openai.com/v1/{suffix}"]
        if base.endswith(f"/{suffix}"):
            return [base]
        if base.endswith("/v1"):
            return [f"{base}/{suffix}"]
        return [f"{base}/v1/{suffix}", f"{base}/{suffix}"]

    def _responses_input(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = message.get("content", "")
            if isinstance(content, str):
                items = [{"type": "input_text", "text": content}]
            else:
                items = []
                for item in content if isinstance(content, list) else []:
                    if isinstance(item, str):
                        items.append({"type": "input_text", "text": item})
                    elif isinstance(item, dict) and item.get("type") == "text":
                        items.append({"type": "input_text", "text": str(item.get("text") or "")})
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        image_url = item.get("image_url") if isinstance(item.get("image_url"), dict) else {}
                        items.append({
                            "type": "input_image",
                            "image_url": str(image_url.get("url") or ""),
                            "detail": str(image_url.get("detail") or "high"),
                        })
            converted.append({"role": role, "content": items})
        return converted

    def _vision_response_text(self, response: dict[str, Any]) -> str:
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        output = response.get("output")
        if isinstance(output, list):
            values = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            values.append(part["text"])
            if values:
                return "\n".join(values)
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        return self._message_text(message.get("content", "") if isinstance(message, dict) else "")

    def _image_fallback(
        self,
        trace_id: str,
        agent: str,
        prompt_version: str,
        trace_input: dict[str, Any],
        fallback: str,
        started: float,
        model: str | None,
        error_message: str,
        error_code: str = "provider_unavailable",
    ) -> dict[str, Any]:
        latency_ms = self._elapsed_ms(started)
        self._save_trace(
            trace_id=trace_id, agent=agent, prompt_version=prompt_version, model=model,
            input_payload=trace_input, output_text=fallback, fallback_used=True,
            error_message=error_message, latency_ms=latency_ms, token_usage={},
        )
        return {
            "text": fallback, "answer_source": "fallback", "fallback_used": True,
            "model": model, "trace_id": trace_id, "latency_ms": latency_ms,
            "error_message": error_message, "error_code": error_code,
        }

    @staticmethod
    def _classify_provider_error(error_message: str) -> str:
        """Turn provider errors into actionable, non-secret UI categories."""
        message = error_message.lower()
        if "http 401" in message or "http 403" in message or "invalid_api_key" in message:
            return "auth_failed"
        if "model" in message and (
            "not found" in message
            or "unsupported" in message
            or "not supported" in message
            or "does not exist" in message
        ):
            return "model_unsupported"
        if "invalid response" in message or "no message content" in message:
            return "invalid_response"
        if "timed out" in message or "timeout" in message or "urlerror" in message:
            return "network_error"
        return "provider_unavailable"

    def _message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            values = []
            for item in content:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    values.append(item["text"])
            return "\n".join(values)
        return str(content or "")

    def plan_steps(self, goal: str, context: dict[str, Any], fallback_steps: list[str]) -> list[str]:
        fallback = "\n".join(f"- {item}" for item in fallback_steps)
        text = self.generate(
            "你是 ValuSee 的任务规划器。请把用户目标拆成清晰、可执行、短句化的步骤。",
            f"目标：{goal}\n上下文：{context}",
            fallback,
            agent="planner",
            prompt_version="planner.v1",
        )
        steps = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        return steps or fallback_steps

    def write_report(self, goal: str, facts: dict[str, Any], fallback: str) -> str:
        return self.generate(
            "你是 ValuSee 的报告生成器。请基于事实生成结构清晰、可行动的中文 Markdown 报告，不要编造事实。",
            f"目标：{goal}\n事实：{facts}",
            fallback,
            agent="reporter",
            prompt_version="reporter.v1",
        )

    def status(self) -> dict[str, Any]:
        config = self._config()
        vision_models = self._vision_models(config)
        return {
            "enabled": bool(config["api_key"]),
            "model": config["model"],
            "vision_enabled": bool(config["api_key"]),
            "vision_model": vision_models[0],
            "vision_models": vision_models,
            "base_url": config["base_url"] or None,
            "wire_api": config["wire_api"],
            "env_path": str(self.env_path),
            "source": config["source"],
            "agent_models": {agent: self._config(agent)["model"] for agent in self.known_agents},
            "active_prompts": self.active_prompt_map(),
        }

    def list_prompt_versions(self, agent: str | None = None) -> list[dict[str, Any]]:
        self._ensure_prompt_versions()
        return task_store.list_prompt_versions(agent)

    def set_active_prompt_version(self, agent: str, prompt_version: str) -> dict[str, Any] | None:
        self._ensure_prompt_versions()
        return task_store.set_active_prompt_version(agent, prompt_version)

    def save_prompt_version(self, prompt: dict[str, Any]) -> dict[str, Any]:
        self._ensure_prompt_versions()
        return task_store.upsert_prompt_version(prompt)

    def run_prompt_ab_test(
        self,
        *,
        agent: str,
        prompt_a: str,
        prompt_b: str,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
    ) -> dict[str, Any]:
        self._ensure_prompt_versions()
        result_a = self.generate_with_status(
            system_prompt,
            user_prompt,
            fallback,
            agent=agent,
            prompt_version=prompt_a,
            use_active_prompt=False,
        )
        result_b = self.generate_with_status(
            system_prompt,
            user_prompt,
            fallback,
            agent=agent,
            prompt_version=prompt_b,
            use_active_prompt=False,
        )
        comparison = {
            "winner": self._pick_ab_winner(result_a, result_b),
            "criteria": [
                "fallback 优先级最低",
                "结构化程度越高越好",
                "回答越具体、长度适中越好",
                "token 与 latency 越低越好",
            ],
        }
        return {
            "agent": agent,
            "prompt_a": self._ab_result(prompt_a, result_a),
            "prompt_b": self._ab_result(prompt_b, result_b),
            "comparison": comparison,
        }

    def active_prompt_map(self) -> dict[str, str]:
        self._ensure_prompt_versions()
        active: dict[str, str] = {}
        for item in task_store.list_prompt_versions():
            if item.get("is_active"):
                key = f"{item.get('agent')}:{item.get('prompt_family')}"
                active[key] = str(item.get("prompt_version"))
        return active

    def usage_dashboard(self, limit: int = 500, agent: str | None = None) -> dict[str, Any]:
        traces = task_store.list_llm_traces(limit=limit, agent=agent)
        summary = self._aggregate_usage(traces)
        pricing = self._model_pricing()
        self._apply_costs(summary, pricing)
        return {
            **summary,
            "pricing": pricing,
            "sample_size": len(traces),
            "currency": "USD",
            "cost_basis": "estimated_from_configured_price_per_1m_tokens",
        }

    def _config(self, agent: str | None = None) -> dict[str, str]:
        env_file = self._read_env_file()
        api_key_from_process = os.getenv("OPENAI_API_KEY", "")
        base_url_from_process = os.getenv("OPENAI_BASE_URL", "")
        default_model = self._read_env_value("DEV_AGENT_LLM_MODEL", env_file, self.default_model)
        agent_model = self._agent_model(agent or "", env_file, default_model)
        return {
            "api_key": self._normalize_api_key(api_key_from_process or env_file.get("OPENAI_API_KEY", "")),
            "model": agent_model,
            "base_url": base_url_from_process or env_file.get("OPENAI_BASE_URL", ""),
            "wire_api": (
                os.getenv("OPENAI_WIRE_API", "")
                or env_file.get("OPENAI_WIRE_API", "")
                or "chat_completions"
            ).strip().lower(),
            "source": "process_env" if api_key_from_process else ".env" if env_file.get("OPENAI_API_KEY") else "fallback",
        }

    @staticmethod
    def _normalize_api_key(value: str) -> str:
        """Accept pasted keys without allowing a duplicated Bearer prefix."""
        normalized = str(value or "").strip().strip('"').strip("'").strip()
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        return normalized

    def _read_env_file(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in self.env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
        return values

    def _read_env_value(self, key: str, env_file: dict[str, str], default: str = "") -> str:
        return os.getenv(key, "") or env_file.get(key, default)

    def _agent_model(self, agent: str, env_file: dict[str, str], default_model: str) -> str:
        if not agent:
            return default_model
        direct_key = f"DEV_AGENT_LLM_MODEL_{self._agent_env_key(agent)}"
        direct_value = self._read_env_value(direct_key, env_file)
        if direct_value:
            return direct_value
        model_map = self._read_env_value("DEV_AGENT_LLM_AGENT_MODELS", env_file)
        for item in model_map.split(","):
            if ":" not in item:
                continue
            name, model = item.split(":", 1)
            if name.strip().lower() == agent.strip().lower() and model.strip():
                return model.strip()
        return default_model

    def _agent_env_key(self, agent: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in agent.upper()).strip("_")

    def _prompt_family(self, prompt_version: str) -> str:
        parts = prompt_version.split(".")
        if len(parts) > 1 and parts[-1].startswith("v") and parts[-1][1:].isdigit():
            return ".".join(parts[:-1])
        return prompt_version

    def _resolve_prompt(self, agent: str, prompt_version: str, system_prompt: str, *, use_active_prompt: bool = True) -> tuple[str, str]:
        self._ensure_prompt_versions()
        prompt_family = self._prompt_family(prompt_version)
        env_file = self._read_env_file()
        env_key = f"DEV_AGENT_PROMPT_{self._agent_env_key(prompt_family)}"
        configured_version = self._read_env_value(env_key, env_file)
        active = None
        if use_active_prompt and configured_version:
            active = task_store.get_prompt_version(agent, configured_version)
        if use_active_prompt and not active:
            active = task_store.get_active_prompt_version(agent, prompt_family)
        if not use_active_prompt:
            active = task_store.get_prompt_version(agent, prompt_version)
        if not active:
            return system_prompt, prompt_version
        suffix = str(active.get("system_suffix") or "").strip()
        resolved_version = str(active.get("prompt_version") or prompt_version)
        if suffix:
            system_prompt = f"{system_prompt}\n\nPrompt version instruction ({resolved_version}):\n{suffix}"
        return system_prompt, resolved_version

    def _ensure_prompt_versions(self) -> None:
        existing = {
            (item.get("agent"), item.get("prompt_version"))
            for item in task_store.list_prompt_versions()
        }
        for prompt in self.prompt_versions:
            key = (prompt["agent"], prompt["prompt_version"])
            if key not in existing:
                task_store.upsert_prompt_version(prompt)

    def _ab_result(self, prompt_version: str, result: dict[str, Any]) -> dict[str, Any]:
        token_usage = result.get("token_usage") if isinstance(result.get("token_usage"), dict) else {}
        input_tokens, output_tokens, total_tokens = self._token_counts(token_usage)
        if total_tokens <= 0:
            text = str(result.get("text") or "")
            input_tokens = max(1, len(text) // 8) if text else 0
            output_tokens = max(1, len(text) // 4) if text else 0
            total_tokens = input_tokens + output_tokens
        return {
            "prompt_version": prompt_version,
            "text": result.get("text") or "",
            "answer_source": result.get("answer_source") or "unknown",
            "fallback_used": bool(result.get("fallback_used")),
            "model": result.get("model"),
            "trace_id": result.get("trace_id"),
            "latency_ms": int(result.get("latency_ms") or 0),
            "token_usage": token_usage,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "quality_score": self._prompt_quality_score(str(result.get("text") or ""), bool(result.get("fallback_used")), total_tokens, int(result.get("latency_ms") or 0)),
            "error_message": result.get("error_message"),
        }

    def _pick_ab_winner(self, result_a: dict[str, Any], result_b: dict[str, Any]) -> str:
        a = self._ab_result("A", result_a)
        b = self._ab_result("B", result_b)
        if a["quality_score"] == b["quality_score"]:
            if a["total_tokens"] == b["total_tokens"]:
                return "tie"
            return "A" if a["total_tokens"] < b["total_tokens"] else "B"
        return "A" if a["quality_score"] > b["quality_score"] else "B"

    def _prompt_quality_score(self, text: str, fallback_used: bool, total_tokens: int, latency_ms: int) -> int:
        if fallback_used:
            return 35
        stripped = text.strip()
        if not stripped:
            return 20
        score = 52
        if len(stripped) >= 120:
            score += 12
        if any(marker in stripped for marker in ["1.", "2.", "-", "•", "：", ":"]):
            score += 10
        if any(word in stripped for word in ["风险", "建议", "步骤", "依据", "测试", "治理", "下一步"]):
            score += 12
        if 120 <= total_tokens <= 1200:
            score += 8
        if latency_ms and latency_ms < 15000:
            score += 6
        return max(0, min(100, score))

    def _model_pricing(self) -> dict[str, dict[str, float]]:
        env_file = self._read_env_file()
        pricing: dict[str, dict[str, float]] = {}
        models = {self.default_model, self._config()["model"]}
        for agent in self.known_agents:
            models.add(self._config(agent)["model"])
        for model in models:
            key = self._agent_env_key(model)
            input_price = self._read_env_value(f"DEV_AGENT_LLM_PRICE_{key}_INPUT_PER_1M", env_file)
            output_price = self._read_env_value(f"DEV_AGENT_LLM_PRICE_{key}_OUTPUT_PER_1M", env_file)
            pricing[model] = {
                "input_per_1m": self._float_or_zero(input_price),
                "output_per_1m": self._float_or_zero(output_price),
            }
        return pricing

    def _float_or_zero(self, value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _build_chat_openai(self, chat_openai: Any, config: dict[str, str]) -> Any:
        kwargs: dict[str, Any] = {
            "model": config["model"],
            "temperature": 0.2,
            "api_key": config["api_key"],
        }
        if config["base_url"]:
            kwargs["base_url"] = config["base_url"]
        try:
            return chat_openai(**kwargs)
        except TypeError:
            legacy_kwargs = dict(kwargs)
            legacy_kwargs["openai_api_key"] = legacy_kwargs.pop("api_key")
            if "base_url" in legacy_kwargs:
                legacy_kwargs["openai_api_base"] = legacy_kwargs.pop("base_url")
            return chat_openai(**legacy_kwargs)

    def _extract_token_usage(self, response: Any) -> dict[str, Any]:
        usage_metadata = getattr(response, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            return usage_metadata
        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
            if isinstance(token_usage, dict):
                return token_usage
        return {}

    def _aggregate_usage(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        total = self._usage_bucket("all")
        by_agent: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        by_prompt: dict[str, dict[str, Any]] = {}
        for trace in traces:
            usage = trace.get("token_usage") if isinstance(trace.get("token_usage"), dict) else {}
            input_tokens, output_tokens, total_tokens = self._token_counts(usage)
            fallback_used = bool(trace.get("fallback_used"))
            latency_ms = int(trace.get("latency_ms") or 0)
            agent = str(trace.get("agent") or "unknown")
            model = str(trace.get("model") or "fallback")
            prompt_version = str(trace.get("prompt_version") or "v1")
            prompt_key = f"{agent}:{prompt_version}"
            self._add_usage(total, model, input_tokens, output_tokens, total_tokens, latency_ms, fallback_used)
            self._add_usage(
                by_agent.setdefault(agent, self._usage_bucket(agent)),
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                latency_ms,
                fallback_used,
            )
            self._add_usage(
                by_model.setdefault(model, self._usage_bucket(model)),
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                latency_ms,
                fallback_used,
            )
            self._add_usage(
                by_prompt.setdefault(prompt_key, self._usage_bucket(prompt_key)),
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                latency_ms,
                fallback_used,
            )
        return {
            "total": self._finalize_usage(total),
            "by_agent": [self._finalize_usage(item) for item in by_agent.values()],
            "by_model": [self._finalize_usage(item) for item in by_model.values()],
            "by_prompt": [self._finalize_usage(item) for item in by_prompt.values()],
        }

    def _usage_bucket(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "calls": 0,
            "fallback_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
            "cost_by_model": {},
        }

    def _add_usage(
        self,
        bucket: dict[str, Any],
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        latency_ms: int,
        fallback_used: bool,
    ) -> None:
        bucket["calls"] += 1
        bucket["fallback_calls"] += 1 if fallback_used else 0
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_tokens"] += total_tokens
        bucket["latency_ms"] += latency_ms
        model_tokens = bucket["cost_by_model"].setdefault(model, {"input_tokens": 0, "output_tokens": 0})
        model_tokens["input_tokens"] += input_tokens
        model_tokens["output_tokens"] += output_tokens

    def _finalize_usage(self, bucket: dict[str, Any]) -> dict[str, Any]:
        calls = int(bucket["calls"] or 0)
        return {
            **bucket,
            "avg_latency_ms": int(bucket["latency_ms"] / calls) if calls else 0,
            "fallback_rate": round(float(bucket["fallback_calls"]) / calls, 4) if calls else 0,
        }

    def _token_counts(self, usage: dict[str, Any]) -> tuple[int, int, int]:
        input_tokens = int(
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or usage.get("input_token_count")
            or 0
        )
        output_tokens = int(
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or usage.get("output_token_count")
            or 0
        )
        total_tokens = int(usage.get("total_tokens") or usage.get("total_token_count") or input_tokens + output_tokens)
        return input_tokens, output_tokens, total_tokens

    def _apply_costs(self, summary: dict[str, Any], pricing: dict[str, dict[str, float]]) -> None:
        for section in ["total", "by_agent", "by_model", "by_prompt"]:
            value = summary.get(section)
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, dict):
                    item["estimated_cost_usd"] = self._estimated_cost(item, pricing)

    def _estimated_cost(self, item: dict[str, Any], pricing: dict[str, dict[str, float]]) -> float:
        total = 0.0
        by_model = item.get("cost_by_model") if isinstance(item.get("cost_by_model"), dict) else {}
        for model, tokens in by_model.items():
            price = pricing.get(str(model), {})
            input_tokens = float(tokens.get("input_tokens") or 0)
            output_tokens = float(tokens.get("output_tokens") or 0)
            total += (input_tokens / 1_000_000) * float(price.get("input_per_1m") or 0)
            total += (output_tokens / 1_000_000) * float(price.get("output_per_1m") or 0)
        return round(total, 6)

    def _save_trace(
        self,
        *,
        trace_id: str,
        agent: str,
        prompt_version: str,
        model: str | None,
        input_payload: dict[str, Any],
        output_text: str,
        fallback_used: bool,
        error_message: str | None,
        latency_ms: int,
        token_usage: dict[str, Any],
    ) -> None:
        try:
            task_store.save_llm_trace(
                {
                    "trace_id": trace_id,
                    "agent": agent,
                    "prompt_version": prompt_version,
                    "model": model,
                    "input": input_payload,
                    "output": output_text,
                    "fallback_used": fallback_used,
                    "error_message": error_message,
                    "latency_ms": latency_ms,
                    "token_usage": token_usage,
                    "created_at": utc_now_iso(),
                }
            )
        except Exception:
            pass

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))


llm_provider = LLMProvider()
