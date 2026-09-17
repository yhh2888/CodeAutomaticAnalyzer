from pathlib import Path
import sys

sys.path.insert(0, r"e:\CodeAutomaticAnalyzer")

from api.refactor import FuncRefactor

p = Path(r"e:\CodeAutomaticAnalyzer\tmp_refactor_sample.py")
p.write_text(
    "def hello(x):\n"
    "    return x + 1\n\n"
    "def world(y):\n"
    "    return hello(y)\n",
    encoding="utf-8",
)

r = FuncRefactor()
result = r.selectFunc("hello", str(p))
print(result["selectedFunc"])
print(result["file_target"])
print(sorted(result["refactorSet"][0].keys()))
print(sorted(result["refactorSet"][1].keys()))
