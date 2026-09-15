import ast

def unwrap_ast(node):
    # exec: body(list) -> Expr -> 실제 노드
    if isinstance(node, list):
        if not node:
            return None
        node = node[0]

    if isinstance(node, ast.Expr):
        node = node.value

    if isinstance(node, ast.Expression):
        node = node.body

    return node

def normalize_called_method(s: str) -> str:
    # 양끝 ' 제거
    s = s.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1]

    # 마지막 '].' 찾기
    idx = s.rfind("].")
    if idx == -1:
        return s

    # '[receiver].method()' 형태인지 확인
    if s.startswith("["):
        return s[1:idx] + "." + s[idx + 2:]

    return s

def extract_parameter_names(values):
    params = set()

    for key in values.keys():
        if key.startswith("parameter '"):
            name = key[len("parameter '"):-1]   # 마지막 ' 제거
            if name != "self":
                params.add(name)

    return params