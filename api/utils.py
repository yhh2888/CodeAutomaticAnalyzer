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