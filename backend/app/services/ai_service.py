"""Multi-provider AI service supporting OpenAI, Anthropic, and Google Gemini."""
import json
import logging
from typing import Tuple
import re

def _extract_json_from_text(text: str) -> str:
    """Attempt to extract a single JSON object from arbitrary text.

    Strategy:
    1. Try parsing the whole text as JSON.
    2. If that fails, look for ```json fenced blocks, then generic ``` blocks.
    3. If still failing, find the first balanced JSON object by scanning braces.
    Returns the JSON substring (str) or raises ValueError.
    """
    if not text:
        raise ValueError("Empty response from AI provider")

    # 1) direct parse
    try:
        json.loads(text)
        return text
    except Exception:
        pass

    # 2) fenced code blocks
    if "```json" in text:
        try:
            return text.split("```json", 1)[1].split("```", 1)[0]
        except Exception:
            pass
    if "```" in text:
        try:
            return text.split("```", 1)[1].split("```", 1)[0]
        except Exception:
            pass

    # 3) find balanced brace JSON object
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in AI response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                # final check
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    break
    # fallback: try to regex-match a {} block (greedy) as last resort
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        candidate = m.group(1)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass
    raise ValueError("Failed to extract valid JSON from AI response")


def _try_repair_truncated_json(text: str) -> str:
    """Best-effort repair of truncated JSON from AI providers.

    When the AI hits max_tokens the JSON is cut mid-string/mid-object.
    Strategy: strip markdown fencing, close any open quoted string, then
    close open braces/brackets so json.loads can succeed.
    """
    # Strip markdown fencing if present
    if "```json" in text:
        text = text.split("```json", 1)[1]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]

    # Find the opening brace
    start = text.find("{")
    if start == -1:
        return text  # nothing to repair

    fragment = text[start:].rstrip()

    # Close any unterminated string value
    in_string = False
    escape = False
    for ch in fragment:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        fragment += '"'

    # Close open brackets / braces
    opens = []
    in_str = False
    esc = False
    for ch in fragment:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in ("{", "["):
            opens.append(ch)
        elif ch == "}" and opens and opens[-1] == "{":
            opens.pop()
        elif ch == "]" and opens and opens[-1] == "[":
            opens.pop()

    for bracket in reversed(opens):
        fragment += "]" if bracket == "[" else "}"

    return fragment


from app.models.ai_config import AIProviderConfig

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are an expert SRE AI Agent. When given an infrastructure alert, you must:

1. Analyze the alert details (name, severity, instance, description).
2. Determine the root cause based on the information and any logs provided.
3. Provide a confidence score (0.0-1.0) of your diagnosis.
4. Create a detailed action plan with specific commands.
5. Suggest prevention steps.
6. Assess the risk level (Low/Medium/High/Critical).

Always respond with valid JSON in this exact format:
{
  "root_cause": "string describing the root cause",
  "confidence_score": 0.85,
  "action_plan": ["step 1", "step 2"],
  "prevention_steps": "string describing prevention",
  "risk_level": "Low|Medium|High|Critical"
}"""


async def analyze_with_ai(provider_config: AIProviderConfig, prompt: str, system_prompt: str | None = None) -> dict:
    """Run analysis using the configured AI provider and optional agent system prompt."""
    provider = provider_config.provider.lower()
    resolved_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    if provider == "openai":
        return await _call_openai(provider_config, prompt, resolved_prompt)
    elif provider == "anthropic":
        return await _call_anthropic(provider_config, prompt, resolved_prompt)
    elif provider == "google":
        return await _call_google(provider_config, prompt, resolved_prompt)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")


async def _call_openai(config: AIProviderConfig, prompt: str, system_prompt: str) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url or None)
    response = await client.chat.completions.create(
        model=config.model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    try:
        extracted = _extract_json_from_text(content)
        return json.loads(extracted.strip())
    except Exception as e:
        logger.error("Failed to parse OpenAI response JSON: %s; content=%s", e, content[:1000])
        raise


async def _call_anthropic(config: AIProviderConfig, prompt: str, system_prompt: str) -> dict:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.api_key)
    response = await client.messages.create(
        model=config.model_name,
        max_tokens=config.max_tokens,
        system=system_prompt + "\n\nRespond ONLY with the JSON object, no other text.",
        messages=[{"role": "user", "content": prompt}],
    )

    # Detect truncated response — Anthropic sets stop_reason="max_tokens" when output is cut off
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason == "max_tokens":
        logger.warning(
            "Anthropic response truncated (stop_reason=max_tokens, max_tokens=%s). "
            "Response will likely contain incomplete JSON.",
            config.max_tokens,
        )

    # Anthropic response shapes vary; coerce to text then extract JSON robustly
    try:
        # try common shapes
        if hasattr(response, "content") and isinstance(response.content, (list, tuple)) and len(response.content) > 0:
            content = getattr(response.content[0], "text", None) or str(response.content[0])
        else:
            content = getattr(response, "text", None) or str(response)

        # If truncated, attempt to repair the JSON by closing open strings/braces
        if stop_reason == "max_tokens":
            content = _try_repair_truncated_json(content)

        extracted = _extract_json_from_text(content)
        return json.loads(extracted.strip())
    except Exception as e:
        logger.error("Failed to parse Anthropic response JSON: %s; raw=%s", e, str(response)[:2000])
        return {"error": "anthropic_parse_failed", "exception": str(e), "raw": str(response)[:2000]}


async def _call_google(config: AIProviderConfig, prompt: str, system_prompt: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=config.api_key)
    model = genai.GenerativeModel(config.model_name)
    response = await model.generate_content_async(
        f"{system_prompt}\n\n{prompt}\n\nRespond ONLY with the JSON object.",
        generation_config=genai.GenerationConfig(
            max_output_tokens=config.max_tokens,
            temperature=config.temperature,
        ),
    )
    content = response.text

    # Detect truncation via finish_reason
    finish_reason = None
    try:
        finish_reason = response.candidates[0].finish_reason.name if response.candidates else None
    except Exception:
        pass
    if finish_reason == "MAX_TOKENS":
        logger.warning("Google response truncated (finish_reason=MAX_TOKENS, max_tokens=%s)", config.max_tokens)
        content = _try_repair_truncated_json(content)

    try:
        extracted = _extract_json_from_text(content)
        return json.loads(extracted.strip())
    except Exception as e:
        logger.error("Failed to parse Google Generative response JSON: %s; content=%s", e, content[:2000])
        return {"error": "google_parse_failed", "exception": str(e), "raw": content[:2000]}


async def generate_raw_json(provider_config: AIProviderConfig, prompt: str, system_prompt: str) -> dict:
    """Call the AI provider and return the parsed JSON response.

    Same as analyze_with_ai but accepts an explicit system_prompt (required)
    and is intended for auxiliary calls like SQL generation.
    """
    return await analyze_with_ai(provider_config, prompt, system_prompt=system_prompt)


async def test_ai_provider(config: AIProviderConfig) -> Tuple[bool, str]:
    """Test connectivity to an AI provider."""
    try:
        result = await analyze_with_ai(config, "Test alert: HighCPU on test-server-01. Severity: warning. Summary: CPU usage above 80%.")
        if "root_cause" in result:
            return True, "Connection successful. AI responded with valid analysis."
        return False, "AI responded but output format is invalid."
    except Exception as e:
        return False, f"Connection failed: {str(e)}"
