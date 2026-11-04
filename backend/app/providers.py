"""OpenRouter integration; credentials remain server-side."""
import base64
import os
import httpx

class ProviderError(Exception):
    pass

class OpenRouter:
    def __init__(self):
        self.key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.text_model = os.getenv("OPENROUTER_TEXT_MODEL", "deepseek/deepseek-chat")
        self.image_model = os.getenv("OPENROUTER_IMAGE_MODEL", "openai/gpt-image-2")

    def _post(self, path, payload, timeout=90):
        if not self.key:
            raise ProviderError("未配置 OPENROUTER_API_KEY，请在本地 .env 文件中设置。")
        try:
            try:
                response = httpx.post("https://openrouter.ai/api/v1/" + path, headers={"Authorization": "Bearer " + self.key}, json=payload, timeout=timeout)
            except httpx.ConnectError:
                # A failed connection has not submitted the request; do not auto-retry timeouts.
                response = httpx.post("https://openrouter.ai/api/v1/" + path, headers={"Authorization": "Bearer " + self.key}, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("模型请求超时，请检查网络并重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"模型服务返回 HTTP {exc.response.status_code}，请检查额度、模型权限及配置。") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderError("模型服务不可用，请检查网络并重试。") from exc

    def chat(self, system, prompt):
        data = self._post("chat/completions", {"model": self.text_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": 0.5, "max_tokens": 650})
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("文本模型返回了无法识别的结果。") from exc

    def image(self, prompt, reference=None):
        payload = {"model": self.image_model, "prompt": prompt, "n": 1, "aspect_ratio": "1:1", "output_format": "png"}
        if reference:
            encoded = base64.b64encode(reference).decode("ascii")
            payload["input_references"] = [{"type":"image_url", "image_url":{"url":"data:image/png;base64," + encoded}}]
        data = self._post("images", payload, timeout=180)
        try:
            return base64.b64decode(data["data"][0]["b64_json"], validate=True)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderError("图片模型返回了无法识别的结果。") from exc
