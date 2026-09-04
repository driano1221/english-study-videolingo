import json
import os
import time
from datetime import datetime, timezone
from threading import Lock

import json_repair
from openai import OpenAI
from rich import print as rprint

from core.utils.config_utils import load_key


LOCK = Lock()
GPT_LOG_FOLDER = "output/gpt_log"
USAGE_LOG_FILE = os.path.join(GPT_LOG_FOLDER, "usage.jsonl")
USAGE_SUMMARY_FILE = os.path.join(GPT_LOG_FOLDER, "usage_summary.json")


def _config(key, default):
    try:
        return load_key(key)
    except (KeyError, TypeError):
        return default


def _load_json_list(path):
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _save_cache(model, prompt, resp_content, resp_type, resp, message=None, log_title="default", usage=None):
    with LOCK:
        file = os.path.join(GPT_LOG_FOLDER, f"{log_title}.json")
        os.makedirs(os.path.dirname(file), exist_ok=True)
        logs = _load_json_list(file)
        logs.append(
            {
                "model": model,
                "prompt": prompt,
                "resp_content": resp_content,
                "resp_type": resp_type,
                "resp": resp,
                "message": message,
                "usage": usage or {},
            }
        )
        with open(file, "w", encoding="utf-8") as handle:
            json.dump(logs, handle, ensure_ascii=False, indent=2)


def _load_cache(prompt, resp_type, log_title, model):
    with LOCK:
        file = os.path.join(GPT_LOG_FOLDER, f"{log_title}.json")
        for item in _load_json_list(file):
            if (
                item.get("prompt") == prompt
                and item.get("resp_type") == resp_type
                and item.get("model", model) == model
            ):
                return item.get("resp")
    return None


def _field(value, name, default=0):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_dict(raw_usage):
    if raw_usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "reasoning_tokens": 0,
        }
    details = _field(raw_usage, "completion_tokens_details", {}) or {}
    return {
        "prompt_tokens": int(_field(raw_usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(_field(raw_usage, "completion_tokens", 0) or 0),
        "total_tokens": int(_field(raw_usage, "total_tokens", 0) or 0),
        "prompt_cache_hit_tokens": int(_field(raw_usage, "prompt_cache_hit_tokens", 0) or 0),
        "prompt_cache_miss_tokens": int(_field(raw_usage, "prompt_cache_miss_tokens", 0) or 0),
        "reasoning_tokens": int(_field(details, "reasoning_tokens", 0) or 0),
    }


def _is_deepseek_peak(now=None):
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)


def _pricing(model, base_url, now=None):
    """Return configurable USD prices per million tokens.

    Defaults are only supplied for the configured official DeepSeek V4 Flash
    endpoint. Unknown providers default to zero rather than reporting a false
    cost; users can provide explicit prices in config.yaml.
    """
    is_v4_flash = "deepseek.com" in base_url.lower() and model == "deepseek-v4-flash"
    peak = _is_deepseek_peak(now)
    defaults = ((0.014, 0.44, 1.32) if peak else (0.007, 0.22, 0.66)) if is_v4_flash else (0.0, 0.0, 0.0)
    suffix = "peak" if peak else "off_peak"

    def price(name, legacy, default):
        try:
            return float(load_key(f"api.{name}_{suffix}"))
        except (KeyError, TypeError):
            return float(_config(f"api.{legacy}", default))

    return {
        "cache_hit": price("cached_input_cost_per_million", "cached_input_cost_per_million", defaults[0]),
        "cache_miss": price("input_cost_per_million", "input_cost_per_million", defaults[1]),
        "output": price("output_cost_per_million", "output_cost_per_million", defaults[2]),
        "tier": suffix,
    }


def _estimate_cost(usage, prices):
    hit = usage["prompt_cache_hit_tokens"]
    miss = usage["prompt_cache_miss_tokens"]
    # Providers that omit the breakdown still report prompt_tokens.
    if hit == 0 and miss == 0:
        miss = usage["prompt_tokens"]
    return (
        hit * prices["cache_hit"]
        + miss * prices["cache_miss"]
        + usage["completion_tokens"] * prices["output"]
    ) / 1_000_000


def _read_usage_summary_unlocked():
    if not os.path.isfile(USAGE_SUMMARY_FILE):
        return {}
    try:
        with open(USAGE_SUMMARY_FILE, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_usage(event):
    with LOCK:
        os.makedirs(GPT_LOG_FOLDER, exist_ok=True)
        with open(USAGE_LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        summary = _read_usage_summary_unlocked()
        summary.setdefault("api_calls", 0)
        summary.setdefault("local_cache_hits", 0)
        summary.setdefault("failed_calls", 0)
        summary.setdefault("prompt_tokens", 0)
        summary.setdefault("completion_tokens", 0)
        summary.setdefault("reasoning_tokens", 0)
        summary.setdefault("prompt_cache_hit_tokens", 0)
        summary.setdefault("prompt_cache_miss_tokens", 0)
        summary.setdefault("estimated_cost_usd", 0.0)

        if event["source"] == "local_cache":
            summary["local_cache_hits"] += 1
        else:
            summary["api_calls"] += 1
            if event["status"] != "success":
                summary["failed_calls"] += 1
            usage = event.get("usage", {})
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens",
            ):
                summary[key] += int(usage.get(key, 0) or 0)
            summary["estimated_cost_usd"] += float(event.get("estimated_cost_usd", 0) or 0)

        summary["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp = USAGE_SUMMARY_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
        os.replace(temp, USAGE_SUMMARY_FILE)
        return summary


def _current_estimated_cost():
    with LOCK:
        return float(_read_usage_summary_unlocked().get("estimated_cost_usd", 0) or 0)


def _is_retryable(exc):
    status = getattr(exc, "status_code", None)
    if status in (408, 409, 429) or (isinstance(status, int) and status >= 500):
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "ratelimit", "internalserver"))


def _event(log_title, model, source, status, elapsed, usage=None, cost=0.0, error=None):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": log_title,
        "model": model,
        "source": source,
        "status": status,
        "elapsed_seconds": round(elapsed, 3),
        "usage": usage or _usage_dict(None),
        "estimated_cost_usd": round(float(cost), 10),
        "error": error,
    }


def ask_gpt(
    prompt,
    resp_type=None,
    valid_def=None,
    log_title="default",
    use_cache=True,
    validation_retries_override=None,
    temperature_override=None,
):
    api_key = load_key("api.key")
    if not api_key:
        raise ValueError("API key is not set")

    model = load_key("api.model")
    base_url = load_key("api.base_url")
    if "ark" in base_url:
        base_url = "https://ark.cn-beijing.volces.com/api/v3"
    elif "v1" not in base_url:
        base_url = base_url.rstrip("/") + "/v1"

    if use_cache:
        cached = _load_cache(prompt, resp_type, log_title, model)
        if cached is not None:
            rprint("[green]Using local cached LLM response.[/green]")
            _record_usage(_event(log_title, model, "local_cache", "success", 0.0))
            return cached

    max_cost = float(_config("api.max_cost_usd", 0.10))
    if max_cost > 0 and _current_estimated_cost() >= max_cost:
        raise RuntimeError(f"LLM cost limit reached for this job (${max_cost:.4f})")

    response_format = None
    if resp_type == "json" and bool(_config("api.llm_support_json", False)):
        response_format = {"type": "json_object"}

    params = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": int(_config("api.timeout_seconds", 180)),
        "max_tokens": int(_config("api.max_output_tokens", 4096)),
    }
    if response_format is not None:
        params["response_format"] = response_format
    temperature = (
        _config("api.temperature", None)
        if temperature_override is None
        else temperature_override
    )
    if temperature is not None:
        params["temperature"] = float(temperature)
    if "deepseek.com" in base_url.lower() and model.startswith("deepseek-"):
        thinking = "enabled" if bool(_config("api.thinking", False)) else "disabled"
        params["extra_body"] = {"thinking": {"type": thinking}}

    client = OpenAI(api_key=api_key, base_url=base_url)
    network_retries = max(0, int(_config("api.max_retries", 2)))
    validation_retries = max(0, int(
        _config("api.validation_retries", 1)
        if validation_retries_override is None
        else validation_retries_override
    ))
    network_attempt = 0
    validation_attempt = 0

    while True:
        started = time.perf_counter()
        try:
            resp_raw = client.chat.completions.create(**params)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            _record_usage(
                _event(log_title, model, "api", "error", elapsed, error=f"{type(exc).__name__}: {exc}")
            )
            if _is_retryable(exc) and network_attempt < network_retries:
                delay = min(2**network_attempt, 8)
                network_attempt += 1
                rprint(f"[yellow]Transient LLM error; retry {network_attempt}/{network_retries} in {delay}s.[/yellow]")
                time.sleep(delay)
                continue
            raise

        elapsed = time.perf_counter() - started
        usage = _usage_dict(getattr(resp_raw, "usage", None))
        prices = _pricing(model, base_url)
        cost = _estimate_cost(usage, prices)
        resp_content = resp_raw.choices[0].message.content or ""

        try:
            resp = json_repair.loads(resp_content) if resp_type == "json" else resp_content
            if valid_def:
                validation = valid_def(resp)
                if validation.get("status") != "success":
                    raise ValueError(validation.get("message", "Invalid API response"))
        except Exception as exc:
            _save_cache(
                model,
                prompt,
                resp_content,
                resp_type,
                None,
                log_title="error",
                message=str(exc),
                usage=usage,
            )
            _record_usage(
                _event(log_title, model, "api", "invalid_response", elapsed, usage, cost, str(exc))
            )
            if validation_attempt < validation_retries:
                validation_attempt += 1
                rprint(f"[yellow]Invalid LLM response; validation retry {validation_attempt}/{validation_retries}.[/yellow]")
                continue
            raise ValueError(f"API response validation failed: {exc}") from exc

        _save_cache(model, prompt, resp_content, resp_type, resp, log_title=log_title, usage=usage)
        summary = _record_usage(_event(log_title, model, "api", "success", elapsed, usage, cost))
        rprint(
            f"[cyan]LLM usage [{log_title}]: {usage['total_tokens']} tokens, "
            f"{elapsed:.2f}s, estimated ${cost:.6f}; job total ${summary['estimated_cost_usd']:.6f}.[/cyan]"
        )
        return resp


if __name__ == "__main__":
    result = ask_gpt(
        'Respond only as JSON: {"code": 200, "message": "success"}',
        resp_type="json",
    )
    rprint(result)
