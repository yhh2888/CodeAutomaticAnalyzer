import ast


def select_function(tree, func_name, class_name=None):
    """Find a function in an AST and return its node and qualified scope."""
    if tree is None:
        raise ValueError("Cannot select a function from an empty syntax tree")

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    matches = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue

        ancestors = []
        parent = parents.get(node)
        while parent is not None:
            ancestors.append(parent)
            parent = parents.get(parent)

        enclosing_class = next(
            (ancestor for ancestor in ancestors if isinstance(ancestor, ast.ClassDef)),
            None,
        )
        if class_name is not None and (
            enclosing_class is None or enclosing_class.name != class_name
        ):
            continue

        scope_parts = [
            ancestor.name
            for ancestor in reversed(ancestors)
            if isinstance(ancestor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        scope_parts.append(f"{node.name}()")
        scope = ".".join(scope_parts)

        enclosing_function = next(
            (
                ancestor
                for ancestor in ancestors
                if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        object_name = (
            enclosing_class.name
            if enclosing_class is not None
            else enclosing_function.name if enclosing_function is not None else "module"
        )
        matches.append({
            "node": node,
            "scope": scope,
            "class_name": enclosing_class.name if enclosing_class is not None else None,
            "object_name": object_name,
        })

    if not matches:
        qualifier = f" in class '{class_name}'" if class_name else ""
        raise ValueError(f"Function '{func_name}'{qualifier} was not found")
    if len(matches) > 1:
        raise ValueError(
            f"Function '{func_name}' is ambiguous; provide class_name to select one"
        )

    return matches[0]


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

def find_class_of_function(func_node):
    parent = getattr(func_node, "parent", None)

    while parent is not None:
        if isinstance(parent, ast.ClassDef):
            return parent.name
        parent = getattr(parent, "parent", None)

    return None