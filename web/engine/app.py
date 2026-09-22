import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, render_template, request

from web.engine.analyzer_registry import ANALYZER_LIBRARY, compile_expression

app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent))


@app.route("/", methods=["GET"])
def index():
    analyzer_key = request.args.get("analyzer", "func_refactor")
    mode = request.args.get("mode", "together")
    compiled = compile_expression(analyzer_key, mode=mode)
    return render_template(
        "home.html",
        analyzers=ANALYZER_LIBRARY,
        selected_analyzer=analyzer_key,
        mode=mode,
        compiled=compiled,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
