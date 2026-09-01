import sys, ast
from pathlib import Path
import builtins

BUILTIN_FUNCTIONS = set(dir(builtins))

STATIC_OBJECTS = {} # 프로젝트에서 임포트한 클래스/모듈 이름 임시변수

sys.path.insert(0, str(Path(__file__).parent.parent))

from funcElementAnatomy import *

# is_xx(info) -> is_xx(info) 등으로 중첩되는 함수구조 해결
# ast로 보는 걸 elementanatomy와 취합해서 통합해보기 

def extract_nested_data(node):
    """Nested Data의 루트 객체와 접근 경로 추출"""

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
    """Object Field 읽기"""

    if not isinstance(node, ast.Attribute):
        return False

    # self.xxx 는 R2
    if isinstance(node.value, ast.Name) and node.value.id == "self":
        return False

    # obj.method() 형태는 R5에서 처리
    return True

def is_r5(node):
    """External/Object Method인지 판별"""

    # 함수 호출이 아니면 제외
    if not isinstance(node, ast.Call):
        return False

    # obj.method() 형태가 아니면 제외 (예: len(), sum())
    if not isinstance(node.func, ast.Attribute):
        return False

    # self.method() 는 R2
    if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
        return False

    return True

def is_r6(node, imported_functions=None):
    """Global / Static / Builtin"""

    imported_functions = imported_functions or set()

    # len(), sum(), enumerate(), hasattr() ...
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in BUILTIN_FUNCTIONS:
            return True
        if node.func.id in imported_functions:
            return True

    # QInputDialog.getText()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id in STATIC_OBJECTS
        ):
            return True

    # Qt.UserRole
    if isinstance(node, ast.Attribute):
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in STATIC_OBJECTS
        ):
            return True

    return False

def classify_read(node):
    codeInfo = node.key().split(' ')
    typeInfo = codeInfo[0]
    structInfo = codeInfo[1]

    if is_parameter(typeInfo):
        return "R1"

    if is_self_reference(structInfo):
        return "R2"

    if is_nested_data(node):      # obj[key], obj.get()
        return "R4"

    if is_object_method(node):    # obj.method()
        return "R5"

    if is_object_field(node):     # obj.attr
        return "R3"

    if is_global_or_static(node):
        return "R6"

def is_parameter(typeInfo):
    if typeInfo == 'parameter':
        return True
    else:
        return False
    
def is_self_reference(structInfo):
    structs = structInfo.split('].')
    if structs[0][1:] == "self" and not is_nested_data(structInfo):
        pass

def is_nested_data(structInfo):
    astForm = ast.parse(structInfo, mode="eval").body
    if extract_nested_data(astForm):
        return True
    else:
        return False

def is_object_method(structInfo):
    astForm = ast.parse(structInfo, mode="eval").body
    if is_r5(astForm) and not extract_nested_data(astForm):
        return True
    else:
        return False

def is_object_field(structInfo):
    astForm = ast.parse(structInfo, mode="eval").body
    if is_r3(astForm):
        return True
    else:
        return False

def is_global_or_static(structInfo):
    astForm = ast.parse(structInfo, mode="eval").body
    if is_r6(astForm):
        return True
    else:
        return False

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
    file_target = r"E:\autoconstruction\components\NodeEdit.py"
    analyzer = ModuleCodeAnalyzer(file_target)
    analyzer.scope_centric_summary()

    from pprint import pprint

    for values in analyzer.element_data.values():
        for key, units in values.items():
            pprint(f"key : {key.split(' ')[-1]}")
            pprint(f"units : {units}")

