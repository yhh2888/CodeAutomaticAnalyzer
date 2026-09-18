import ast
import re
from collections import defaultdict
from pathlib import Path


class FuncExport:

    def __init__(self, target_dir: str | Path):
        """
        :param target_dir: 분석할 최상위 디렉토리 경로
        """
        self.target_dir = Path(target_dir).resolve()
        self.python_files = self._get_all_python_files()

        self.ast_trees = {}
        self.module_names = {}

        # 폴더 내 모든 파일 파싱 및 스코프 부모 설정
        self._build_ast_trees()

    def _get_all_python_files(self):
        """대상 디렉토리 하위의 모든 .py 파일 경로 수집"""
        if not self.target_dir.exists():
            print(f"❌ 경로를 찾을 수 없습니다: {self.target_dir}")
            return []
        return list(self.target_dir.rglob("*.py"))

    def _build_ast_trees(self):
        """수집된 모든 .py 파일의 AST를 생성하고 Parent 참조 연결"""
        for file_path in self.python_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)
                tree.module_name = file_path.stem
                tree.file_path = file_path

                # Parent 참조 추가
                for parent in ast.walk(tree):
                    for child in ast.iter_child_nodes(parent):
                        child.parent = parent

                self.ast_trees[file_path] = tree
                self.module_names[file_path] = file_path.stem
            except Exception as e:
                print(f"⚠️ 파일 파싱 실패 ({file_path.name}): {e}")

    def _get_scope_path(self, node) -> str:
        """해당 노드가 위치한 스코프 경로 추적 (클래스 -> 함수 -> 메서드...)"""
        scopes = []
        curr = getattr(node, "parent", None)
        module_name = None

        while curr:
            if isinstance(curr, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(f"{curr.name}()")
            elif isinstance(curr, ast.ClassDef):
                scopes.append(curr.name)
            elif isinstance(curr, ast.Module):
                module_name = getattr(curr, "module_name", None)
            curr = getattr(curr, "parent", None)

        scope_str = " -> ".join(reversed(scopes)) if scopes else "(모듈 최상위)"
        if module_name:
            return f"{module_name}.py -> {scope_str}"
        return scope_str

    def _parse_address_target(self, target_name: str):
        """'C:/repo/x.py:128' 또는 'x.py:128' 같은 주소 형태 파싱"""
        if not isinstance(target_name, str):
            return None

        candidate = target_name.strip()
        if not candidate:
            return None

        match = re.match(r"^(?P<file>.+?\.py)(?::(?P<line>\d+))?(?::(?P<col>\d+))?$", candidate)
        if not match:
            return None

        file_part = match.group("file")
        line_no = int(match.group("line") or 0)

        return {
            "file": Path(file_part),
            "line": line_no,
        }

    def _pick_best_definition(self, call_info: dict, defined_locations: list[dict]) -> dict | None:
        """호출/참조 위치에 가장 잘 맞는 정의를 하나 고름.

        우선순위:
        1) 같은 파일이면 가장 우선
        2) 같은 스코프/클래스 경로나 마지막 스코프명이 겹치면 우선
        3) 같은 파일명이라면 다음 우선
        4) 그 외에는 라인 차이가 가장 작은 정의를 선택
        """
        if not defined_locations:
            return None

        def scope_tokens(scope: str):
            if not scope:
                return []
            return [part.strip().lower() for part in scope.split("->") if part.strip()]

        call_file = Path(call_info.get("file", "")).resolve()
        call_scope = str(call_info.get("scope", ""))
        call_scope_parts = scope_tokens(call_scope)

        best_match = None
        best_score = float("-inf")

        for defined in defined_locations:
            def_file = Path(defined.get("file", "")).resolve()
            def_scope = str(defined.get("scope", ""))
            def_scope_parts = scope_tokens(def_scope)

            score = 0

            if call_file == def_file:
                score += 200
            elif call_file.name == def_file.name:
                score += 50

            if call_scope and def_scope:
                if call_scope == def_scope:
                    score += 150
                else:
                    overlapping = len(set(call_scope_parts) & set(def_scope_parts))
                    score += overlapping * 25
                    if call_scope_parts and def_scope_parts and call_scope_parts[-1] == def_scope_parts[-1]:
                        score += 30

            if call_scope and def_scope:
                # 자동 추론이 가능한 범위에서 스코프 문자열이 비슷할수록 우선
                score += min(len(call_scope), len(def_scope)) * 0.1

            line_gap = abs(int(defined.get("line", 0)) - int(call_info.get("line", 0)))
            score -= min(line_gap, 10000) * 0.01

            if score > best_score:
                best_score = score
                best_match = defined

        return best_match

    def analyze_element(self, target_name: str) -> dict:
        """
        특정 대상(함수, 메서드, 어트리뷰트 등)이 폴더 내 전체 파일에서
        어떻게 속해있고, 외부/로컬에서 호출/참조되는지 검토
        """
        result = {
            "target_element": target_name,
            "1_defined_locations": [],  # 정의된 위치 목록
            "2_external_calls": [],     # 외부 파일에서의 호출 및 참조
            "3_local_calls": [],        # 동일 파일 내에서의 호출 및 참조
        }

        address_target = self._parse_address_target(target_name)
        target_lookup_name = target_name
        defined_files_map = set()  # (file_path) 저장

        # -------------------------------------------------------------
        # 1. 정의 및 선언 위치 검토
        # -------------------------------------------------------------
        for file_path, tree in self.ast_trees.items():
            for node in ast.walk(tree):
                is_target_def = False
                def_type = ""
                element_name = None

                # ① 함수/메서드 정의
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    element_name = node.name
                    def_type = "Function/Method"
                # ② 클래스 정의
                elif isinstance(node, ast.ClassDef):
                    element_name = node.name
                    def_type = "Class"
                # ③ 어트리뷰트/변수 할당
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            element_name = t.id
                            def_type = "Variable"
                            break
                        elif isinstance(t, ast.Attribute):
                            element_name = t.attr
                            def_type = "Attribute"
                            break

                # 주소 기반 검색인 경우 단순 이름 추출
                if address_target:
                    # 주소 지정 모드에서는 노드 위치(파일 및 라인) 일치 여부 검증
                    is_file_match = file_path.name == address_target["file"].name or file_path.resolve() == address_target["file"].resolve()
                    is_line_match = not address_target["line"] or getattr(node, "lineno", 0) == address_target["line"]
                    if is_file_match and is_line_match and element_name:
                        is_target_def = True
                        target_lookup_name = element_name
                else:
                    if element_name == target_name:
                        is_target_def = True

                if is_target_def:
                    scope_info = self._get_scope_path(node)
                    location_info = {
                        "file": str(file_path),
                        "line": getattr(node, "lineno", 0),
                        "type": def_type,
                        "scope": scope_info,
                        "element_name": element_name,
                    }
                    result["1_defined_locations"].append(location_info)
                    defined_files_map.add(file_path)

        # 주소 검색이었으나 대상을 찾지 못한 경우 반환
        if address_target and not result["1_defined_locations"]:
            return result

        # -------------------------------------------------------------
        # 2 & 3. 호출 및 참조 검토 (Call, AttributeAccess, Name)
        # -------------------------------------------------------------
        for file_path, tree in self.ast_trees.items():
            mod_name = self.module_names[file_path]

            for node in ast.walk(tree):
                accessed_name = None
                action_type = "Reference"

                # ① 함수/메서드 호출: target() 또는 obj.target()
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == target_lookup_name:
                        accessed_name = node.func.id
                        action_type = "Call"
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == target_lookup_name:
                        accessed_name = node.func.attr
                        action_type = "Method Call"

                # ② 어트리뷰트 접근: obj.target
                elif isinstance(node, ast.Attribute) and node.attr == target_lookup_name:
                    if not (isinstance(getattr(node, "parent", None), ast.Call) and node.parent.func == node):
                        accessed_name = node.attr
                        action_type = "Attribute Access"

                # ③ 일반 변수/함수 이름 참조
                elif isinstance(node, ast.Name) and node.id == target_lookup_name:
                    if isinstance(node.ctx, ast.Load) and not isinstance(getattr(node, "parent", None), ast.Call):
                        accessed_name = node.id
                        action_type = "Variable Reference"

                # 타깃 사용 지점 발견 시 정보 기록
                if accessed_name:
                    caller_scope = self._get_scope_path(node)
                    try:
                        snippet = ast.unparse(node)
                    except AttributeError:
                        snippet = target_lookup_name

                    call_info = {
                        "file": str(file_path),
                        "module": mod_name,
                        "line": getattr(node, "lineno", 0),
                        "scope": caller_scope,
                        "action": action_type,
                        "code_snippet": snippet,
                    }

                    # 정의된 파일과 동일한 파일 내의 참조면 로컬(3), 다르면 외부(2)
                    if file_path in defined_files_map:
                        result["3_local_calls"].append(call_info)
                    else:
                        result["2_external_calls"].append(call_info)

        for call_bucket in (result["2_external_calls"], result["3_local_calls"]):
            for call_info in call_bucket:
                call_info["element_from"] = self._pick_best_definition(call_info, result["1_defined_locations"])

        return result


if __name__ == "__main__":
    # 실행 테스트 예시
    import pprint

    # 분석할 디렉토리 경로
    target_directory = r"E:/autoconstruction"

    exporter = FuncExport(target_directory)

    # 1. 일반 심볼 이름으로 검색
    report = exporter.analyze_element("bulk_add_nodes")
    pprint.pprint(report)

    # 2. 특정 파일:라인 주소 형태로 검색 (예시)
    # report_addr = exporter.analyze_element("my_script.py:15")
    # pprint.pprint(report_addr)