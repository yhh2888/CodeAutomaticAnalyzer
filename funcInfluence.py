import ast
import os
from pathlib import Path
from collections import defaultdict

# 사용자 모듈 import (실제 환경에 맞게 경로/이름 유지)
from funcElementAnatomy import ModuleCodeAnalyzer


class FuncInfluenceAnalyzer:
    """
    함수 내부의 파라미터, Global/Nonlocal, I/O 등이 외부 환경에 미치는 영향(Side Effects) 및
    참조 유출/타 함수 전달 등으로 인한 잠재적 변형 가능성(Potential Risks)을 정밀 추적하는 모듈
    """

    # 가변 객체의 상태를 직접 변경하는 대표적인 메서드 집합
    MUTATING_METHODS = {
        # List / Deque
        'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'reverse', 'sort',
        # Dict
        'update', 'setdefault', 'popitem',
        # Set
        'add', 'discard', 'difference_update', 'intersection_update', 'symmetric_difference_update'
    }

    # I/O 및 시스템 영향을 주는 대표 함수/메서드
    IO_FUNCTIONS = {'print', 'write', 'writelines', 'open', 'exit', 'close'}

    def __init__(self, tree: ast.AST):
        self.tree = tree
        self.influence_data = defaultdict(lambda: {
            # --- 1. 파라미터 상태 요약 ---
            "params_summary": {},            # 파라미터별 최종 상태 (Mutated vs Rebound vs Pure)
            
            # --- 2. 실제 발생한 영향 (Actual Side-Effects) ---
            "actual_param_mutations": [],    # 파라미터 메모리 내부 직접 수정 (Side Effect O)
            "param_rebindings": [],          # 파라미터 단순 재할당 (Side Effect X, 참조 변경)
            "actual_global_mutations": [],   # Global / Nonlocal 변수 바인딩 재할당
            "global_obj_mutations": [],     # Global 가변 객체 내부 수정
            "io_side_effects": [],          # I/O, 파일, 출력 등 외부 시스템 영향
            "returns": [],                   # 반환을 통한 데이터 유출
            
            # --- 3. 잠재적 변형 가능성 및 참조 유출 위험 (Potential Risks & Escaping) ---
            "mutable_default_args": [],      # 가변 기본 파라미터 선언 위험
            "escaped_params_to_calls": [],   # 외부 함수로 파라미터 전달 (타 함수에 의한 변형 가능성)
            "escaped_params_to_globals": [], # Global 변수로 참조 유출 (Alias 생성)
            "returned_param_aliases": [],    # Return을 통한 파라미터 참조 유출
            "shallow_copy_risks": []         # 얕은 복사로 인한 중첩 객체 변형 위험
        })

    def analyze(self):
        if not self.tree:
            return self.influence_data

        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_function(node)

        return self.influence_data

    def _analyze_function(self, func_node: ast.FunctionDef):
        func_name = func_node.name
        info = self.influence_data[func_name]

        # -------------------------------------------------------------
        # 1. 파라미터 데이터셋 구축 및 요약 정보 초기화
        # -------------------------------------------------------------
        params = set()
        for arg in func_node.args.args + func_node.args.kwonlyargs:
            params.add(arg.arg)
        if func_node.args.vararg:
            params.add(func_node.args.vararg.arg)
        if func_node.args.kwarg:
            params.add(func_node.args.kwarg.arg)

        for p in params:
            info["params_summary"][p] = {"mutated": False, "rebound": False}

        # -------------------------------------------------------------
        # [잠재 위험 1] 가변 객체 기본 파라미터 (Mutable Default Arguments)
        # -------------------------------------------------------------
        defaults = func_node.args.defaults + func_node.args.kw_defaults
        for default_node in defaults:
            if default_node and isinstance(default_node, (ast.List, ast.Dict, ast.Set)):
                info["mutable_default_args"].append({
                    "line": func_node.lineno,
                    "type": default_node.__class__.__name__,
                    "desc": "가변 객체가 기본값으로 선언됨 (함수 호출 간 공유 위험)"
                })

        # -------------------------------------------------------------
        # 2. Scope 전역 변수 선언 수집 (global / nonlocal)
        # -------------------------------------------------------------
        global_vars = set()
        nonlocal_vars = set()

        for child in ast.walk(func_node):
            if isinstance(child, ast.Global):
                global_vars.update(child.names)
            elif isinstance(child, ast.Nonlocal):
                nonlocal_vars.update(child.names)

        # -------------------------------------------------------------
        # 3. 함수 바디 AST 상세 탐색
        # -------------------------------------------------------------
        for child in ast.walk(func_node):
            lineno = getattr(child, 'lineno', None)

            # ---------------------------------------------------------
            # [CASE 1] 단순 변수 할당 (Assign: target = value)
            # ---------------------------------------------------------
            if isinstance(child, ast.Assign):
                val_names = self._extract_names(child.value)

                for target in child.targets:
                    # 1-A. param = x (파라미터 단순 재바인딩 -> 외부 영향 X)
                    if isinstance(target, ast.Name) and target.id in params:
                        info["param_rebindings"].append({
                            "line": lineno, "param": target.id,
                            "desc": f"파라미터 '{target.id}'의 참조 주소만 변경됨 (외부 영향 없음)"
                        })
                        info["params_summary"][target.id]["rebound"] = True

                    # 1-B. global_var = x / nonlocal_var = x (Global/Nonlocal 변수 재할당)
                    elif isinstance(target, ast.Name) and target.id in global_vars:
                        info["actual_global_mutations"].append({
                            "line": lineno, "var": target.id, "type": "Global Reassignment"
                        })
                    elif isinstance(target, ast.Name) and target.id in nonlocal_vars:
                        info["actual_global_mutations"].append({
                            "line": lineno, "var": target.id, "type": "Nonlocal Reassignment"
                        })

                    # [잠재 위험 2] global_var = param (Global 변수로 참조 유출)
                    if isinstance(target, ast.Name) and (target.id in global_vars or target.id in nonlocal_vars):
                        for p in val_names.intersection(params):
                            info["escaped_params_to_globals"].append({
                                "line": lineno, "param": p, "global_var": target.id,
                                "desc": f"파라미터 '{p}'의 참조가 스코프 변수 '{target.id}'로 유출됨"
                            })

                    # 1-C. param[key] = x 또는 param.attr = x (In-place Mutation)
                    elif isinstance(target, (ast.Subscript, ast.Attribute)):
                        root_name = self._get_root_name(target.value)
                        if root_name in params:
                            access_type = "속성(Attribute)" if isinstance(target, ast.Attribute) else "인덱스/키(Subscript)"
                            info["actual_param_mutations"].append({
                                "line": lineno, "param": root_name,
                                "type": f"{access_type} 변경",
                                "expr": ast.unparse(target) if hasattr(ast, 'unparse') else "target"
                            })
                            info["params_summary"][root_name]["mutated"] = True
                        elif root_name and root_name not in params:
                            # 모듈 레벨 가변 객체 수정 추적
                            info["global_obj_mutations"].append({
                                "line": lineno, "target": root_name,
                                "expr": ast.unparse(target) if hasattr(ast, 'unparse') else "target"
                            })

            # ---------------------------------------------------------
            # [CASE 2] 누적 할당 (AugAssign: target += value)
            # ---------------------------------------------------------
            elif isinstance(child, ast.AugAssign):
                if isinstance(child.target, ast.Name) and child.target.id in params:
                    info["actual_param_mutations"].append({
                        "line": lineno, "param": child.target.id,
                        "type": "Augmented Assignment (+=, -= 등)",
                        "expr": f"{child.target.id} {child.op.__class__.__name__}="
                    })
                    info["params_summary"][child.target.id]["mutated"] = True

            # ---------------------------------------------------------
            # [CASE 3] 메서드 호출 및 I/O Side Effect (Call)
            # ---------------------------------------------------------
            elif isinstance(child, ast.Call):
                # 3-A. obj.method() 형태의 호출
                if isinstance(child.func, ast.Attribute):
                    obj_name = self._get_root_name(child.func.value)
                    method_name = child.func.attr

                    # 파라미터 대상 Mutating Method 호출 (실제 변형)
                    if obj_name in params and method_name in self.MUTATING_METHODS:
                        info["actual_param_mutations"].append({
                            "line": lineno, "param": obj_name,
                            "type": f"In-place 메서드 호출 (.{method_name}())",
                            "expr": f"{obj_name}.{method_name}()"
                        })
                        info["params_summary"][obj_name]["mutated"] = True

                    # [잠재 위험 3] 얕은 복사 메서드 사용 추적 (.copy())
                    elif obj_name in params and method_name == 'copy':
                        info["shallow_copy_risks"].append({
                            "line": lineno, "param": obj_name,
                            "desc": f"'{obj_name}.copy()' 사용 - 중첩 객체의 경우 원본 변경 위험 잔존"
                        })

                    # I/O 메서드 호출 (e.g. f.write())
                    if method_name in self.IO_FUNCTIONS:
                        info["io_side_effects"].append({
                            "line": lineno, "type": "I/O Call", "func": f".{method_name}()"
                        })

                # 3-B. 일반 함수 호출 (e.g. print(), open())
                elif isinstance(child.func, ast.Name):
                    func_call_name = child.func.id
                    if func_call_name in self.IO_FUNCTIONS:
                        info["io_side_effects"].append({
                            "line": lineno, "type": "System/IO Call", "func": f"{func_call_name}()"
                        })

                # [잠재 위험 4] 파라미터가 타 함수 인자로 전달됨 (Escape Analysis)
                call_args_names = set()
                for arg in child.args:
                    call_args_names.update(self._extract_names(arg))

                passed_params = call_args_names.intersection(params)
                if passed_params:
                    func_str = ast.unparse(child.func) if hasattr(ast, 'unparse') else "function"
                    if func_str not in self.IO_FUNCTIONS:
                        for p in passed_params:
                            info["escaped_params_to_calls"].append({
                                "line": lineno, "param": p, "called_func": func_str,
                                "desc": f"파라미터 '{p}'가 외부 함수 '{func_str}()'로 전달됨 (호출 내부에서 변형 가능성 있음)"
                            })

            # ---------------------------------------------------------
            # [CASE 4] 반환문 (Return)
            # ---------------------------------------------------------
            elif isinstance(child, ast.Return):
                val_str = ast.unparse(child.value) if (child.value and hasattr(ast, 'unparse')) else "None"
                info["returns"].append({"line": lineno, "value": val_str})

                # [잠재 위험 5] Return을 통한 파라미터 참조 유출 (Alias 생성)
                if child.value:
                    ret_names = self._extract_names(child.value)
                    returned_params = ret_names.intersection(params)
                    for p in returned_params:
                        info["returned_param_aliases"].append({
                            "line": lineno, "param": p,
                            "desc": f"파라미터 '{p}' 참조가 그대로 반환됨 (Caller 스코프에서 참조를 통한 변형 가능성)"
                        })

    def _get_root_name(self, node: ast.AST) -> str:
        """체이닝된 객체(a.b.c[0])에서 최상위 변수 이름(a)을 추출"""
        curr = node
        while isinstance(curr, (ast.Attribute, ast.Subscript)):
            curr = curr.value
        if isinstance(curr, ast.Name):
            return curr.id
        return ""

    def _extract_names(self, node: ast.AST) -> set:
        """AST 노드 표현식 내부에 사용된 모든 식별자(Variable Name) 추출"""
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
        return names

    def print_influence_summary(self):
        """실제 영향과 잠재적 위험 요소를 종합 출력"""
        print("\n================================================================================")
        print(" 🌐 [FuncInfluence Comprehensive Side-Effect & Risk Analysis]")
        print("================================================================================")

        for func_name, info in self.influence_data.items():
            print(f"\n🔹 함수: [{func_name}()]")

            # 1. 파라미터 상태 요약 (Mutated vs Rebound vs Pure)
            if info["params_summary"]:
                print("  📌 파라미터 상태 요약:")
                for p_name, p_state in info["params_summary"].items():
                    status = []
                    if p_state["mutated"]:
                        status.append("⚠️ 외부 메모리 직접 수정됨 (Mutated)")
                    if p_state["rebound"]:
                        status.append("ℹ️ 내부 참조 재할당됨 (Rebound)")
                    if not status:
                        status.append("✅ 변경 없음 (Pure)")
                    print(f"     • {p_name}: {', '.join(status)}")

            # 2. 실제 변형 발생 항목 (Actual Side-Effects)
            if info["actual_param_mutations"]:
                print("  🔥 [실제 변형] 파라미터 In-place 직접 수정:")
                for item in info["actual_param_mutations"]:
                    print(f"     • Line {item['line']}: [{item['param']}] -> {item.get('type', 'Modification')} ({item['expr']})")

            if info["param_rebindings"]:
                print("  ℹ️ [참조 변경] 파라미터 재바인딩 (외부 영향 없음):")
                for item in info["param_rebindings"]:
                    print(f"     • Line {item['line']}: [{item['param']}] -> {item['desc']}")

            if info["actual_global_mutations"] or info["global_obj_mutations"]:
                print("  🌍 [Scope 변형] Global / Scope 바인딩 변경:")
                for item in info["actual_global_mutations"]:
                    print(f"     • Line {item['line']}: {item['type']} ('{item['var']}')")
                for item in info["global_obj_mutations"]:
                    print(f"     • Line {item['line']}: Global 객체 내부 수정 ({item['expr']})")

            if info["io_side_effects"]:
                print("  🖥️ [시스템 영향] I/O 및 외부 시스템 호출:")
                for item in info["io_side_effects"]:
                    print(f"     • Line {item['line']}: {item['type']} -> {item['func']}")

            # 3. 잠재적 변형 가능성 및 참조 유출 위험 (Potential Risks)
            has_potential = any([
                info["mutable_default_args"], info["escaped_params_to_calls"],
                info["escaped_params_to_globals"], info["returned_param_aliases"],
                info["shallow_copy_risks"]
            ])

            if has_potential:
                print("  ⚠️ [잠재적 위험] 외부 유출 및 변형 가능성 (Potential Side-Effects):")
                for item in info["mutable_default_args"]:
                    print(f"     • Line {item['line']}: [가변 기본값] {item['desc']}")
                for item in info["escaped_params_to_calls"]:
                    print(f"     • Line {item['line']}: [외부 함수 유출] 파라미터 '{item['param']}' -> '{item['called_func']}()' 인자로 전달됨")
                for item in info["escaped_params_to_globals"]:
                    print(f"     • Line {item['line']}: [Global 유출] 파라미터 '{item['param']}' -> global '{item['global_var']}'에 할당됨")
                for item in info["returned_param_aliases"]:
                    print(f"     • Line {item['line']}: [Return 유출] 파라미터 '{item['param']}' 참조가 그대로 반환됨")
                for item in info["shallow_copy_risks"]:
                    print(f"     • Line {item['line']}: [얕은 복사 위험] {item['desc']}")

            # 4. 반환 정보
            if info["returns"]:
                print("  📤 [반환 정보]:")
                for item in info["returns"]:
                    print(f"     • Line {item['line']}: return {item['value']}")

            if not info["actual_param_mutations"] and not info["actual_global_mutations"] and not info["io_side_effects"] and not has_potential:
                print("  ✅ 완전함 (변형 및 유출 위험 없는 Pure Function 형태).")

        print("================================================================================")

if __name__ == "__main__":
    file_target = r"E:\autoconstruction\components\NodeEdit.py"

    # 1. 이전 analyzer 실행
    analyzer = ModuleCodeAnalyzer(file_target)

    # 2. FuncInfluence 모듈 연결 실행
    if analyzer.tree:
        influence_analyzer = FuncInfluenceAnalyzer(analyzer.tree)
        influence_analyzer.analyze()
        influence_analyzer.print_influence_summary()
