import argparse
import os

import uvicorn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BIFB 智能科研助手 · Windows 本地 Demo")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    os.environ.setdefault("PYTHONUTF8", "1")
    uvicorn.run("app.main:app", host="127.0.0.1", port=arguments.port, log_level="info")
