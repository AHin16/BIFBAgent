import inspect
import logging
from dataclasses import dataclass
from typing import get_type_hints

from pydantic import ConfigDict, ValidationError, create_model

from app.storage import ToolError


logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    schema: type
    callable: object

    def definition(self):
        return {"type": "function", "function": {"name": self.name,
                "description": self.description, "parameters": self.schema.model_json_schema()}}


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, description):
        def decorator(function):
            hints = get_type_hints(function)
            fields = {}
            for name, parameter in inspect.signature(function).parameters.items():
                if name != "context":
                    fields[name] = (hints[name], ... if parameter.default is inspect.Parameter.empty else parameter.default)
            schema = create_model(function.__name__ + "Arguments", __config__=ConfigDict(extra="forbid", allow_inf_nan=False), **fields)
            self.tools[function.__name__] = Tool(function.__name__, description, schema, function)
            return function
        return decorator

    def definitions(self):
        return [tool.definition() for tool in self.tools.values()]

    def execute(self, name, arguments, context):
        try:
            if name not in self.tools:
                raise ToolError(f"未注册工具：{name}")
            if not isinstance(arguments, dict):
                raise ToolError("工具参数必须是 JSON 对象。")
            tool = self.tools[name]
            validated = tool.schema.model_validate(arguments)
            result = tool.callable(context, **validated.model_dump())
            result.setdefault("status", "success")
            return context.store(name, result)
        except ValidationError as error:
            fields = [".".join(map(str, item["loc"])) + ": " + item["msg"] for item in error.errors()]
            return {"status": "error", "tool": name, "message": "工具参数不正确：" + "; ".join(fields)}
        except ToolError as error:
            return {"status": "error", "tool": name, "message": str(error)}
        except Exception:
            logger.exception("Tool execution failed: %s", name)
            return {"status": "error", "tool": name, "message": "工具执行失败，请检查输入格式、模型与运行日志 data/app.log。"}
