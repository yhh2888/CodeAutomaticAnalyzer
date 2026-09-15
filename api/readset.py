import sys, ast, re
from pathlib import Path
import builtins
from utils import unwrap_ast

BUILTIN_FUNCTIONS = set(dir(builtins))

STATIC_OBJECTS = {} # 프로젝트에서 임포트한 클래스/모듈 이름 임시변수

sys.path.insert(0, str(Path(__file__).parent.parent))

from funcElementAnatomy import *

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

# ast로 보는 걸 elementanatomy와 취합해서 통합해보기 
# 일반 변수 not In인거 해결하기

def extract_nested_data(node):
    node = unwrap_ast(node)

    # obj["key"]
    if isinstance(node, ast.Subscript):
        path = []

        current = node
        while isinstance(current, ast.Subscript):
            key = current.slice
            if isinstance(key, ast.Constant):
                path.insert(0, key.value)
            current = current.value

        return {
            "root": ast.unparse(current),   # self.data
            "path": path                    # ["x"] 또는 ["links","id"]
        }

    # obj.get("key")
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    ):
        key = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
        return {
            "root": ast.unparse(node.func.value),  # self.data
            "path": [key]
        }

    return None

def is_r3(node):
    node = unwrap_ast(node)

    # 객체 참조 변수: dst, src, main_win, conn ...
    if isinstance(node, ast.Name):
        if node.id not in {"self", "True", "False", "None"}:
            return True
        return False

    # 객체 필드: dst.data, conn.rel_type ...
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            return False
        return True

    return False

def is_r5(node):
    node = unwrap_ast(node)

    if not isinstance(node, ast.Call):
        return False

    if not isinstance(node.func, ast.Attribute):
        return False

    # self.xxx()
    if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
        return False

    # obj.get() 은 R4
    if node.func.attr == "get":
        return False

    return True

def is_r6(node, imported_functions=None):
    node = unwrap_ast(node)

    # 모든 일반 함수 호출: sum(), get_new_node_data(), my_func() ...
    if isinstance(node, ast.Call):
        # func()
        if isinstance(node.func, ast.Name):
            return True

        # Static/Class 메서드: QInputDialog.getText()
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in STATIC_OBJECTS
        ):
            return True

    # Static 상수: Qt.UserRole
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in STATIC_OBJECTS
    ):
        return True

    return False

def classify_read(node):
    codeInfo = node.split(' ')
    typeInfo = codeInfo[0]
    structInfo = ' '.join(codeInfo[1:])
    structInfo = normalize_called_method(structInfo)
    print('\n', node, structInfo)


    if typeInfo in ['controlFlow', 'imports', 'functions']:
        return 'AlienType'

    elif is_parameter(typeInfo):
        return "R1"

    elif is_self_reference(structInfo):
        return "R2"

    elif is_nested_data(structInfo):      # obj[key], obj.get()
        return "R4"

    elif is_object_method(structInfo):    # obj.method()
        return "R5"

    elif is_object_field(structInfo):     # obj.attr
        return "R3"

    elif is_global_or_static(structInfo):
        return "R6"

    elif is_return(structInfo):
        return "is_return"

    return 'Not In R'

def is_parameter(typeInfo):
    if typeInfo == 'parameter':
        return True
    else:
        return False

def is_self_reference(structInfo):
    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)

    if isinstance(astForm, ast.Attribute):
        return (
            isinstance(astForm.value, ast.Name)
            and astForm.value.id == "self"
        )

    if isinstance(astForm, ast.Call):
        return (
            isinstance(astForm.func, ast.Attribute)
            and isinstance(astForm.func.value, ast.Name)
            and astForm.func.value.id == "self"
            and astForm.func.attr != "get"
        )

    return False

def is_nested_data(structInfo):
    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)
    return extract_nested_data(astForm) is not None


def is_object_method(structInfo):
    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)
    return is_r5(astForm)


def is_object_field(structInfo):
    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)
    return is_r3(astForm)


def is_global_or_static(structInfo):
    astForm = unwrap_ast(ast.parse(structInfo, mode="exec").body)
    return is_r6(astForm)

def is_return(node):
    node = unwrap_ast(node)

    return isinstance(node, ast.Return)

def categorize_test(file_target):
    analyzer = ModuleCodeAnalyzer(file_target)

    classified_dict = {"R1":[], "R2":[], "R3":[], "R4":[], "R5":[], "R6":[], "Not In R":[], "AlienType":[], "is_return":[]}
    
    for values in analyzer.summary_data.values():
        for dicts in values:
            classified_to = classify_read(dicts)
            classified_dict[classified_to].append(dicts)
            print("type: " + classified_to)

    print('\n')

    for key in classified_dict:
        print(f"{key}:", len(classified_dict[key]))



"""
Rn - 자동화 시 수행 작업

R1 - 매개변수 유지·추가·삭제 여부 결정.(is_shift)

R2 - self 참조를 새 객체 참조로 치환.(new_object_form)

R3 - 객체를 전달할지 필드만 전달할지 결정.(reference_form)

R4 - 필요한 키/인덱스만 추출하거나 컨테이너 유지.()

R5 - Getter/Action 구분 후 함께 이동 또는 호출 유지.

R6 - 전역 함수·Static·import 유지 및 namespace 확인.

"""

def R1_is_shift():
    pass

if __name__ == "__main__":
    from pprint import pprint

    # file_target = r"E:\autoconstruction\components\NodeEdit.py"
    file_target = r"C:\Users\hyunhoyang\Desktop\yhh\python\pjt\autoconstruction\components\NodeEdit.py"
    categorize_test(file_target)