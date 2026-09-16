import sys, ast
from pathlib import Path
import builtins
from utils import unwrap_ast, normalize_called_method, extract_parameter_names

BUILTIN_FUNCTIONS = set(dir(builtins))

STATIC_OBJECTS = {} # 프로젝트에서 임포트한 클래스/모듈 이름 임시변수

sys.path.insert(0, str(Path(__file__).parent.parent))

from funcElementAnatomy import *

def is_w1(node, parameter_names):
    node = unwrap_ast(node)

    # ------------------------
    # Assign / AugAssign
    # ------------------------
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target

        # dst.name = ...
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in parameter_names
        ):
            return True

        # dst.data["id"] = ...
        if isinstance(target, ast.Subscript):
            current = target
            while isinstance(current, ast.Subscript):
                current = current.value

            if (
                isinstance(current, ast.Attribute)
                and isinstance(current.value, ast.Name)
                and current.value.id in parameter_names
            ):
                return True

    # ------------------------
    # Mutation Method Call
    # ------------------------
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    ):
        receiver = node.func.value

        # dst.append(...)
        if (
            isinstance(receiver, ast.Name)
            and receiver.id in parameter_names
        ):
            return True

        # dst.data["links"].append(...)
        if isinstance(receiver, ast.Subscript):
            current = receiver
            while isinstance(current, ast.Subscript):
                current = current.value

            if (
                isinstance(current, ast.Attribute)
                and isinstance(current.value, ast.Name)
                and current.value.id in parameter_names
            ):
                return True

    return False

def is_w6(node):
    node = unwrap_ast(node)

    # Qt.UserRole = ...
    if isinstance(node, ast.Assign):
        target = node.targets[0]

        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id in STATIC_OBJECTS
        ):
            return True

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

def classify_write(node, parameter_names):
    codeInfo = node.split(" ")
    typeInfo = codeInfo[0].lower()
    structInfo = normalize_called_method(" ".join(codeInfo[1:]))
    # print('\n', node, structInfo)

    # Write Set 대상이 아닌 타입
    if typeInfo in {"functions", "function", "controlflow"}:
        return "AlienType"

    if typeInfo == "imports":
        register_import(structInfo)
        return "AlienType"

    if typeInfo == "return":
        return "W6"

    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)

    if is_w1(astForm, parameter_names):
        return "W1"
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

def writeSetCategorizeTest(file_target):
    analyzer = ModuleCodeAnalyzer(file_target)

    classified_dict = {"W1":[], "W2":[], "W3":[], "W4":[], "W5":[], "W6":[], "Not In W":[], "AlienType":[], "is_return":[]}
    
    for scope_name, values in analyzer.summary_data.items():

        parameter_names = extract_parameter_names(values)
        print(values)
        for item in values:
            classified_to = classify_write(item, parameter_names)
            classified_dict[classified_to].append(item)
            # print("type: " + classified_to)

    print('\n')

    for key in classified_dict:
        print(f"{key}:", len(classified_dict[key]))

    return classified_dict


if __name__ == "__main__":
    file_target = r"C:\Users\hyunhoyang\Desktop\yhh\python\pjt\autoconstruction\components\NodeEdit.py"
    file_target = r"E:\autoconstruction\components\NodeEdit.py"
    writeSetCategorizeTest(file_target)