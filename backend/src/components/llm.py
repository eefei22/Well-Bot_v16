import json
import httpx
from typing import Dict, Iterable, Generator, List, Optional

class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat", timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> Generator[str, None, None]:
        """
        Yields token chunks as they arrive (OpenAI-compatible streaming).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if kwargs:
            payload.update(kwargs)

        url = f"{self.base_url}/v1/chat/completions"
        with httpx.stream("POST", url, headers=self._headers(), json=payload, timeout=self.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="ignore")
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    chunk = delta.get("content")
                    if chunk:
                        yield chunk
                except Exception:
                    # swallow malformed SSE fragments
                    continue

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Non-streaming convenience.
        """
        payload = {
            "model": self.model,
            "messages": messages
        }
        if kwargs:
            payload.update(kwargs)

        url = f"{self.base_url}/v1/chat/completions"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
