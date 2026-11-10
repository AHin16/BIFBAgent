import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_PATH = ROOT / "config.local.json"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
INPUT_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | {".csv"}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    yolo_model_path: str = str(ROOT / "models" / "3900.pt")
    yolo_device: str = "auto"
    confidence: float = Field(default=0.25, ge=0.01, le=1)
    mm_per_pixel: float | None = Field(default=None, gt=0)
    max_tool_rounds: int = Field(default=12, ge=2, le=24)

    @field_validator("llm_base_url")
    @classmethod
    def validate_base_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("请填写有效的 HTTP(S) API 地址，例如 https://example.com/v1")
        return value

    @property
    def llm_ready(self):
        return bool(self.llm_model.strip() and self.llm_base_url)

    def public(self):
        result = self.model_dump(exclude={"llm_api_key"})
        result["has_api_key"] = bool(self.llm_api_key)
        result["llm_ready"] = self.llm_ready
        result["model_exists"] = local_path(self.yolo_model_path).is_file()
        return result


def local_path(value):
    path = Path(value.strip().strip('"')).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def load_settings():
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, value = line.split("=", 1)
                values[name.strip().lower()] = value.strip().strip('"').strip("'")
    if CONFIG_PATH.exists():
        values.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    for name in Settings.model_fields:
        if name.upper() in os.environ:
            values[name] = os.environ[name.upper()]
    values = {name: value for name, value in values.items() if name in Settings.model_fields}
    return Settings(**values)


def save_settings(settings):
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(CONFIG_PATH)
