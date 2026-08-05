import ast
from collections import defaultdict
from pathlib import Path


class ImportTracker:
    """지정한 디렉토리 하위의 모든 .py 파일을 전수 조사하여,

    특정 모듈/함수/클래스/변수 등의 요소가 어디에 Import되고 사용되었는지 추적하는 클래스
    """

    def __init__(self, target_dir: str):
        """:param target_dir: 검색 대상 루트 디렉토리 경로"""
        self.target_dir = Path(target_dir)
        # 검색 결과 구조: { target_element: [ { "file": ..., "line": ..., ... }, ... ] }
        self.usage_map = defaultdict(list)
        # 분석 실패(인코딩/문법 에러) 파일 목록
        self.failed_files = []

    def _get_all_python_files(self):
        """대상 디렉토리 하위의 모든 .py 파일 경로 수집"""
        if not self.target_dir.exists():
            print(f"❌ 경로를 찾을 수 없습니다: {self.target_dir}")
            return []
        return list(self.target_dir.rglob("*.py"))

    def print_all_py_files(self):
        """대상 디렉토리 하위의 모든 .py 파일 목록 출력"""
        py_files = self._get_all_python_files()

        print(
            "\n================================================================================"
        )
        print(
            f" 📂 [Python Files Found] Directory: {self.target_dir} ({len(py_files)}개)"
        )
        print(
            "================================================================================"
        )

        if not py_files:
            print("  ⚠️ 지정한 경로에 .py 파일이 존재하지 않습니다.")
        else:
            for idx, file_path in enumerate(py_files, start=1):
                print(f"  {idx:3d}. {file_path}")

        print(
            "================================================================================"
        )
        return py_files

    def track_element_imports(
        self, target_module_name: str, target_elements: list = None
    ):
        """특정 모듈(파일명) 및 그 안의 요소들(함수/클래스명)이 하위 .py 파일들에서 Import 및
        사용되었는지 추적

        :param target_module_name: 추적할 모듈 이름 (예: 'Edit',
        'funcElementAnatomy')
        :param target_elements: 추적할 모듈 내 요소 이름 목록 (예:
        ['ModuleCodeAnalyzer', 'update_settings'])
        """
        # .py 확장자가 입력된 경우 자동 제거
        if target_module_name.endswith(".py"):
            target_module_name = target_module_name[:-3]

        py_files = self._get_all_python_files()
        target_elements = set(target_elements) if target_elements else set()

        # 기존 상태 초기화
        self.usage_map.clear()
        self.failed_files.clear()

        for file_path in py_files:
            content = None
            # 인코딩 순차 시도 (UTF-8, UTF-8-SIG, CP949, EUC-KR)
            for enc in ["utf-8", "utf-8-sig", "cp949", "euc-kr"]:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        content = f.read()
                        break
                except Exception:
                    continue

            if content is None:
                self.failed_files.append((str(file_path), "인코딩 오류"))
                continue

            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError as e:
                self.failed_files.append(
                    (str(file_path), f"SyntaxError (Line {e.lineno})")
                )
                continue
            except Exception as e:
                self.failed_files.append((str(file_path), f"파싱 에러: {e}"))
                continue

            self._scan_ast_for_imports(
                tree, file_path, target_module_name, target_elements
            )

        return self.usage_map

    def _scan_ast_for_imports(
        self,
        tree: ast.AST,
        file_path: Path,
        target_module: str,
        target_elements: set,
    ):
        """단일 파일의 AST를 순회하며 Import 패턴 및 사용처 분석"""

        imported_aliases = {}  # { imported_alias: original_element_name }
        module_aliases = (
            set()
        )  # 모듈 자체(Edit)를 direct import 하거나 package에서 가져온 경우의 별칭

        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)

            # -------------------------------------------------------------
            # [CASE 1] ImportFrom (from ... import ...)
            # -------------------------------------------------------------
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""

                # Pattern A: from Edit import update_settings (모듈 내부의 요소를 가져올 때)
                if mod == target_module or mod.endswith(f".{target_module}"):
                    for alias in node.names:
                        imported_name = alias.name
                        as_name = alias.asname or imported_name

                        if (
                            not target_elements
                            or imported_name in target_elements
                        ):
                            imported_aliases[as_name] = imported_name
                            self.usage_map[imported_name].append({
                                "file": str(file_path),
                                "line": lineno,
                                "import_type": "From-Import (Element)",
                                "imported_as": as_name,
                                "raw_statement": f"from {mod} import {imported_name}",
                            })

                # Pattern B: from components import Edit (상위 패키지에서 모듈 자체를 가져올 때) 👈 [핵심 해결 지점]
                for alias in node.names:
                    imported_name = alias.name
                    as_name = alias.asname or imported_name

                    if (
                        imported_name == target_module
                    ):  # import 하려는 게 바로 찾던 target_module('Edit')인 경우
                        module_aliases.add(as_name)
                        self.usage_map[target_module].append({
                            "file": str(file_path),
                            "line": lineno,
                            "import_type": "From-Import (Module)",
                            "imported_as": as_name,
                            "raw_statement": f"from {mod} import {imported_name}",
                        })

            # -------------------------------------------------------------
            # [CASE 2] Import (import Edit / import components.Edit)
            # -------------------------------------------------------------
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod_name = alias.name
                    as_name = alias.asname or mod_name.split(".")[-1]

                    if mod_name == target_module or mod_name.endswith(
                        f".{target_module}"
                    ):
                        module_aliases.add(as_name)
                        self.usage_map[target_module].append({
                            "file": str(file_path),
                            "line": lineno,
                            "import_type": "Direct-Import",
                            "imported_as": as_name,
                            "raw_statement": f"import {mod_name}",
                        })

        # -----------------------------------------------------------------
        # [CASE 3 & 4] 실사용 추적
        # -----------------------------------------------------------------
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)

            # A. from Edit import update_settings -> update_settings() 형태 사용
            if isinstance(node, ast.Name) and node.id in imported_aliases:
                if not isinstance(getattr(node, "ctx", None), ast.Store):
                    original_name = imported_aliases[node.id]
                    self.usage_map[f"{original_name} (Used)"].append({
                        "file": str(file_path),
                        "line": lineno,
                        "context": f"코드 내부에서 '{node.id}' 변수/함수로 사용됨",
                    })

            # B. from components import Edit / import Edit -> Edit.update_settings() 형태 사용
            elif isinstance(node, ast.Attribute) and isinstance(
                node.value, ast.Name
            ):
                if node.value.id in module_aliases:
                    attr_name = node.attr
                    if not target_elements or attr_name in target_elements:
                        self.usage_map[f"{attr_name} (Used)"].append({
                            "file": str(file_path),
                            "line": lineno,
                            "context": f"모듈 별칭을 통해 '{node.value.id}.{attr_name}' 형태로 사용됨",
                        })

    def print_import_summary(self):
        """Import 추적 결과를 가독성 있게 출력"""
        print(
            "\n================================================================================"
        )
        print(" 🔍 [ImportTracker Directory Scan Results]")
        print(
            "================================================================================"
        )

        if not self.usage_map:
            print(
                "  ✨ 지정한 디렉토리 내에서 해당 요소/모듈을 Import한 파일이 없습니다."
            )
        else:
            for element_name, usages in self.usage_map.items():
                print(f"\n🔹 대상 요소/모듈: [{element_name}]")

                # 파일별 그룹화
                grouped_by_file = defaultdict(list)
                for usage in usages:
                    grouped_by_file[usage["file"]].append(usage)

                for file_path, items in grouped_by_file.items():
                    print(f"  📄 File: {file_path}")
                    for item in items:
                        line = item.get("line", "?")
                        if "import_type" in item:
                            print(
                                f"     • Line {line}: [{item['import_type']}] {item['raw_statement']} (as: {item['imported_as']})"
                            )
                        else:
                            print(
                                f"     • Line {line}: [실사용] {item['context']}"
                            )

        # 분석 실패 파일이 있는 경우 정보 출력
        if self.failed_files:
            print(
                "\n================================================================================"
            )
            print(" ⚠️ [Skipped Files Notification]")
            print(
                "================================================================================"
            )
            for fpath, reason in self.failed_files:
                print(f"  ❌ {fpath} -> 이유: {reason}")

        print(
            "================================================================================"
        )


if __name__ == "__main__":
    # 1. 탐색할 루트 디렉토리
    target_directory = r"E:\autoconstruction"

    tracker = ImportTracker(target_directory)

    # (선택 사항) 대상 디렉토리의 모든 파이썬 파일 출력
    # tracker.print_all_py_files()

    # 2. 추적할 모듈명 및 내부 요소를 지정
    # 예: 'Edit' 모듈 내부의 'ModuleCodeAnalyzer', 'update_settings' 요소 추적
    tracker.track_element_imports(
        target_module_name="controlHandler",
        target_elements=["ModuleCodeAnalyzer", "update_settings"],
    )

    # 3. 결과 요약 출력
    tracker.print_import_summary()
