import sys, ast
from pathlib import Path
import builtins
from utils import unwrap_ast

BUILTIN_FUNCTIONS = set(dir(builtins))

STATIC_OBJECTS = {} # 프로젝트에서 임포트한 클래스/모듈 이름 임시변수

sys.path.insert(0, str(Path(__file__).parent.parent))

from funcElementAnatomy import *

MUTATION_METHODS = {
    "append", "remove", "update", "extend",
    "insert", "pop", "clear",
    "add", "discard",
    "put", "setdefault"
}

SIDE_EFFECT_METHODS = {
    "addItem", "removeItem", "save_state", "undo",
    "redo", "remove_connection", "update_path"
}

def is_w1(node):
    """
    W1 = Parameter 객체 수정 (휴리스틱 버전)

    dst.name = ...
    dst.data["id"] = ...
    dst.append(...)
    """

    node = unwrap_ast(node)

    # dst.name = ...
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target

        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id != "self"
        ):
            return True

        # dst.data["id"] = ...
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id != "self"
        ):
            return True

    # dst.append(...), dst.remove(...), dst.update(...)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id != "self"
        and node.func.attr in MUTATION_METHODS
    ):
        return True

    return False

def is_w2(node):
    node = unwrap_ast(node)

    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target

        # self.field = ...
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            return True

        # self.data["id"] = ...
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "self"
        ):
            return True

    return False

def is_w3(node):
    node = unwrap_ast(node)

    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target

        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id != "self"
        ):
            return True

    return False

def is_w4(node):
    node = unwrap_ast(node)

    # data["id"] = ...
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target

        if isinstance(target, ast.Subscript):
            return True

    # append(), remove(), update() ...
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATION_METHODS
        ):
            return True

    return False

def is_w5(node):
    node = unwrap_ast(node)

    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in SIDE_EFFECT_METHODS
        ):
            return True

    return False

def is_w6(node):
    node = unwrap_ast(node)

    codeInfo = node.split(' ')
    structInfo = ' '.join(codeInfo[1:])

    STATIC_OBJECTS = register_import(structInfo)

    # Qt.UserRole = ...
    if isinstance(node, ast.Assign):
        target = node.targets[0]

        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in STATIC_OBJECTS
        ):
            return True

        # GLOBAL_CACHE["id"] = ...
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id.isupper()
        ):
            return True

    # Static 메서드 호출
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in STATIC_OBJECTS
        ):
            return True

    return False

def classify_write(astForm):

    if is_w1(astForm):
        return "W1"

    if is_w2(astForm):
        return "W2"

    if is_w4(astForm):      # W4를 W3보다 먼저
        return "W4"

    if is_w3(astForm):
        return "W3"

    if is_w5(astForm):
        return "W5"

    if is_w6(astForm):
        return "W6"

    return "Not In W"

def register_import(structInfo):
    """
    from PyQt5.QtWidgets import QInputDialog
    import os
    import numpy as np
    """
    STATIC_OBJECTS = set()

    tree = ast.parse(structInfo, mode="exec").body[0]

    if isinstance(tree, ast.ImportFrom):
        for alias in tree.names:
            STATIC_OBJECTS.add(alias.asname or alias.name)

    elif isinstance(tree, ast.Import):
        for alias in tree.names:
            STATIC_OBJECTS.add(alias.asname or alias.name.split(".")[0])

    return STATIC_OBJECTS

def categorize_test(file_target):
    analyzer = ModuleCodeAnalyzer(file_target)

    classified_dict = {"W1":[], "W2":[], "W3":[], "W4":[], "W5":[], "W6":[], "Not In W":[], "AlienType":[], "is_return":[]}
    
    for values in analyzer.summary_data.values():
        for dicts in values:
            classified_to = classify_write(dicts)
            classified_dict[classified_to].append(dicts)
            print("type: " + classified_to)

    print('\n')

    for key in classified_dict:
        print(f"{key}:", len(classified_dict[key]))


if __name__ == "__main__":
    file_target = r"C:\Users\hyunhoyang\Desktop\yhh\python\pjt\autoconstruction\components\NodeEdit.py"
    categorize_test(file_target)