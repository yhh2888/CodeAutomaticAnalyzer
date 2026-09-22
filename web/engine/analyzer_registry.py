import json
from typing import Any, Dict, List

ANALYZER_LIBRARY: Dict[str, Dict[str, str]] = {
    "module_anatomy": {
        "label": "ModuleCodeAnalyzer",
        "category": "Core",
        "description": "모듈 전체 AST와 scope/element 요약을 수집합니다.",
    },
    "func_origin": {
        "label": "FuncOrigin",
        "category": "Origin",
        "description": "변수/함수/메서드의 최초 정의 위치와 출처를 추적합니다.",
    },
    "func_influence": {
        "label": "FuncInfluenceAnalyzer",
        "category": "Influence",
        "description": "부작용, 전역 변경, 참조 유출, 위험성을 분석합니다.",
    },
    "func_refactor": {
        "label": "FuncRefactor",
        "category": "Refactor",
        "description": "R1~R6 분류를 기반으로 템플릿 코드와 변환 형태를 생성합니다.",
    },
}


def sample_refactor_payload() -> Dict[str, List[List[str]]]:
    return {
        "R1": [["parameter", "self"], ["parameter", "node"], ["parameter", "value"]],
        "R2": [["object", "self.parent"], ["object", "current_node"], ["object", "context"]],
        "R3": [["variable", "tmp_result"], ["variable", "buffer"], ["variable", "child_nodes"]],
        "R4": [["peek", "node.body"], ["peek", "target.scope"], ["peek", "current_data"]],
        "R5": [["method", "self.apply_update()"], ["method", "context.load()"], ["method", "node.walk()"]],
        "R6": [["function", "normalize_called_method()"], ["function", "classify_read()"], ["function", "classify_write()"]],
    }


def _build_segments(selected_func: str, object_name: str | None, is_method: bool, payload: Dict[str, List[List[str]]]) -> List[Dict[str, str]]:
    method_start = "self" if is_method else ""
    r1 = [item[1] for item in payload.get("R1", []) if item[1] != "self"]
    r2 = [item[1] for item in payload.get("R2", [])]
    r3 = [item[1] for item in payload.get("R3", [])]
    r4 = [item[1] for item in payload.get("R4", [])]
    r5 = [item[1] for item in payload.get("R5", [])]
    r6 = [item[1] for item in payload.get("R6", [])]

    blocks = []
    sig = ", ".join(r1)
    blocks.append({"label": "R1", "code": f"def {selected_func}({method_start}{sig}):"})

    if object_name and object_name != "module":
        blocks.append({"label": "R2", "code": "\n".join([
            f"    new_self_class = {object_name}",
            *[f"    # {item}" for item in r2],
        ])})
    else:
        blocks.append({"label": "R2", "code": "\n".join([f"    # {item}" for item in r2])})

    blocks.append({"label": "R3", "code": "\n".join([f"    {item} = None" for item in r3])})
    blocks.append({"label": "R4", "code": "\n".join([f"    # {item}" for item in r4])})
    blocks.append({"label": "R5", "code": "\n".join([f"    # {item}" for item in r5])})
    blocks.append({"label": "R6", "code": "\n".join([f"    {item} = None" for item in r6])})
    return blocks


def compile_expression(analyzer_key: str, mode: str = "together") -> Dict[str, Any]:
    analyzer = ANALYZER_LIBRARY.get(analyzer_key, ANALYZER_LIBRARY["func_refactor"])
    payload = sample_refactor_payload()

    if analyzer_key not in {"func_refactor", "func_refactor_method"}:
        return {
            "analyzer": analyzer["label"],
            "mode": mode,
            "description": analyzer["description"],
            "rendered": f"# {analyzer['label']}\n# {analyzer['description']}\n\nsummary = {{\n  'kind': '{analyzer['label']}',\n  'mode': '{mode}'\n}}",
            "segments": [{"label": "summary", "code": analyzer["description"]}],
        }

    selected_func = "apply_update_from_box"
    object_name = "NodeBlock"
    segments = _build_segments(selected_func, object_name, is_method=analyzer_key == "func_refactor_method", payload=payload)

    if mode == "dict":
        rendered = json.dumps({
            "analyzer": analyzer["label"],
            "selected_func": selected_func,
            "object_name": object_name,
            "segments": segments,
        }, ensure_ascii=False, indent=2)
    elif mode == "flat":
        rendered = "\n\n".join(f"{segment['label']}\n{segment['code']}" for segment in segments)
    else:
        rendered = "\n\n".join(segment["code"] for segment in segments)

    return {
        "analyzer": analyzer["label"],
        "mode": mode,
        "description": analyzer["description"],
        "selected_func": selected_func,
        "object_name": object_name,
        "segments": segments,
        "rendered": rendered,
    }
