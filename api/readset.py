import funcElementAnatomy

def classify_read(node):

    if is_parameter(node):
        return "R1"

    if is_self_reference(node):
        return "R2"

    if is_nested_data(node):      # obj[key], obj.get()
        return "R4"

    if is_object_method(node):    # obj.method()
        return "R5"

    if is_object_field(node):     # obj.attr
        return "R3"

    if is_global_or_static(node):
        return "R6"

def is_parameter():
    pass
def is_self_reference():
    pass
def is_nested_data():
    pass
def is_object_method():
    pass
def is_object_field():
    pass
def is_global_or_static():
    pass

"""
Rn - 자동화 시 수행 작업

R1 - 매개변수 유지·추가·삭제 여부 결정.

R2 - self 참조를 새 객체 참조로 치환.

R3 - 객체를 전달할지 필드만 전달할지 결정.

R4 - 필요한 키/인덱스만 추출하거나 컨테이너 유지.

R5 - Getter/Action 구분 후 함께 이동 또는 호출 유지.

R6 - 전역 함수·Static·import 유지 및 namespace 확인.

"""