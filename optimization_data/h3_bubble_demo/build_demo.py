"""Build a self-contained HTML review demo from the four existing conditions."""

import json
from pathlib import Path

from .model import ROOT, BubbleDemo, load_measurements

TEMPLATE = Path(__file__).with_name("ui.html")
OUTPUT = ROOT / "data/variation_evaluation/h3_pl10/standalone_bubble_demo.html"


def render_demo_html(with_transport=False):
    demo = BubbleDemo(load_measurements())
    data = demo.ui_data()
    sources = dict.fromkeys(row["source"] for row in data["measurements"])
    display_names = {
        source: f"模拟污水实验批次 {index}" for index, source in enumerate(sources, 1)
    }
    for row in data["measurements"]:
        row["source"] = display_names[row["source"]]
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "__BUBBLE_DEMO_DATA__"
    if template.count(marker) != 1:
        raise ValueError("Expected one model data marker in the demo UI.")
    return template.replace(marker, payload).replace(
        "__H3_TRANSPORT_ENABLED__", "true" if with_transport else "false"
    )


def main():
    html = render_demo_html()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
