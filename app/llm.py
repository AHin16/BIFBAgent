import httpx

from app.storage import ToolError


class LLMClient:
    def __init__(self, settings):
        self.settings = settings

    async def complete(self, messages, tools=None):
        if not self.settings.llm_ready:
            raise ToolError("尚未配置语言模型。请点击右上角「运行设置」，填写 API 地址、模型名称和 API Key，然后测试连接。")
        endpoint = self.settings.llm_base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = "Bearer " + self.settings.llm_api_key
        payload = {"model": self.settings.llm_model, "messages": messages, "stream": False}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            if response.status_code >= 400:
                reason = {401: "API Key 无效或未填写", 403: "无权访问此模型", 404: "API 地址或模型名称不存在",
                          429: "额度不足或请求过于频繁"}.get(response.status_code, "服务暂不可用，或不支持标准 Tool Calling")
                raise ToolError(f"LLM API 返回 {response.status_code}：{reason}。请检查运行设置。")
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or not (message.get("content") or message.get("tool_calls")):
                raise ToolError("模型返回空内容，请使用支持 OpenAI-compatible Tool Calling 的模型。")
            if choice.get("finish_reason") == "length":
                raise ToolError("模型输出达到长度限制，请缩小任务范围或调整服务端输出额度。")
            return {"role": "assistant", "content": message.get("content"),
                    **({"reasoning_content": message["reasoning_content"]} if isinstance(message.get("reasoning_content"), str) else {}),
                    **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {})}
        except httpx.TimeoutException as error:
            raise ToolError("LLM 请求超时（120 秒），请稍后重试或检查服务。") from error
        except httpx.RequestError as error:
            raise ToolError("无法连接 LLM 服务，请检查 API 地址、网络和代理设置。") from error
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ToolError("LLM 响应格式不兼容，需要标准 /chat/completions 和 tool_calls。") from error

    async def test_connection(self):
        tool = {"type": "function", "function": {"name": "connection_check",
                "description": "验证工具调用协议", "parameters": {"type": "object", "properties": {}, "required": []}}}
        response = await self.complete([{"role": "user", "content": "请调用 connection_check 工具验证工具调用功能。"}], [tool])
        calls = response.get("tool_calls", [])
        supported = any(call.get("function", {}).get("name") == "connection_check" for call in calls)
        return {"status": "success" if supported else "warning", "tool_calling": supported,
                "message": "连接成功，已收到真实 Tool Call。" if supported else "API 可连接，但模型未调用测试工具，请确认支持 Tool Calling。"}
