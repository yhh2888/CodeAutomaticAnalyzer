import ast
import sys
from pathlib import Path

try:
    from api.utils import normalize_called_method
except ImportError:
    from utils import normalize_called_method

ROOT_DIR = Path(__file__).resolve().parent.parent
API_DIR = Path(__file__).resolve().parent
for path in (str(ROOT_DIR), str(API_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from api.readset import classify_read
    from api.writeset import classify_write
    from api.readset import readSetCategorizeTest
    from api.writeset import writeSetCategorizeTest
except ImportError:
    from readset import classify_read
    from writeset import classify_write
    from readset import readSetCategorizeTest
    from writeset import writeSetCategorizeTest


class FuncRefactor:
    def __init__(self):
        self.file_target = None
        self.selectedFunc = None
        self.objectName = None
        self.refactorSet = []

    def _find_function_object_name(self, analyzer, func_name):
        for node in ast.walk(analyzer.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                parent = getattr(node, "parent", None)
                while parent is not None:
                    if isinstance(parent, ast.ClassDef):
                        return parent.name
                    parent = getattr(parent, "parent", None)
                return None
        return None

    def _find_function_scope(self, analyzer, func_name):
        for node in ast.walk(analyzer.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                return analyzer._get_node_scope(node, include_self=True)
        return None

    def _categorize_function_only(self, file_target, func_name):
        from funcElementAnatomy import ModuleCodeAnalyzer

        analyzer = ModuleCodeAnalyzer(file_target)
        func_scope = self._find_function_scope(analyzer, func_name)
        if not func_scope:
            raise ValueError(f"Function '{func_name}' was not found in {file_target}")

        self.objectName = self._find_function_object_name(analyzer, func_name)

        selected_items = analyzer.summary_data.get(func_scope, {})
        parameter_names = set()
        for item_name in selected_items:
            if item_name.startswith("parameter '") and item_name.endswith("'"):
                parameter_names.add(item_name[len("parameter '"):-1])

        readSet = {
            "R1": [], "R2": [], "R3": [], "R4": [], "R5": [],
            "R6": [], "Not In R": [], "AlienType": [], "is_return": []
        }
        writeSet = {
            "W1": [], "W2": [], "W3": [], "W4": [], "W5": [],
            "W6": [], "Not In W": [], "AlienType": [], "is_return": []
        }

        for item_name in selected_items:
            codeInfo = item_name.split(' ')
            typeInfo = codeInfo[0]
            structInfo = ' '.join(codeInfo[1:])
            structInfo = normalize_called_method(" ".join(codeInfo[1:]))
            read_type = classify_read(item_name)
            readSet.setdefault(read_type, []).append([typeInfo, structInfo])

            write_type = classify_write(item_name, parameter_names)
            writeSet.setdefault(write_type, []).append([typeInfo, structInfo])

        return readSet, writeSet

    def getRefactorSet(self, file_target, func_name=None):
        self.file_target = str(Path(file_target).resolve())
        self.objectName = None
        if func_name is not None:
            self.selectedFunc = func_name

        if self.selectedFunc:
            readSet, writeSet = self._categorize_function_only(self.file_target, self.selectedFunc)
        else:
            readSet = readSetCategorizeTest(self.file_target)
            writeSet = writeSetCategorizeTest(self.file_target)

        del readSet['AlienType']
        del writeSet['AlienType']

        self.refactorSet = [readSet, writeSet]
        return self.refactorSet

    def selectFunc(self, func_name, file_target=None):
        if file_target is None:
            file_target = self.file_target
        if not file_target:
            raise ValueError("file_target must be provided")

        self.file_target = str(Path(file_target).resolve())
        self.selectedFunc = func_name
        self.objectName = None
        self.getRefactorSet(self.file_target, self.selectedFunc)

        return {
            "selectedFunc": self.selectedFunc,
            "objectName": self.objectName,
            "file_target": self.file_target,
            "refactorSet": self.refactorSet,
        }

    def docMaker(self, isMethod = False):
        if not self.selectedFunc:
            raise ValueError("selectFunc() must be called before docMaker()")


        if isMethod:
            methodStart = 'self'
        else:
            methodStart = ''

        R1 = [parameter[1] for parameter in self.refactorSet[0]['R1'] if parameter[1] != 'self']
        R1Phrase = methodStart + ''.join([param + ', ' for param in R1])
        R1Syntax = f'def {self.selectedFunc}(' + R1Phrase[:-2] + '):'
        print(R1Syntax)

        R2 = [parameter[1] for parameter in self.refactorSet[0]['R2']]
        # 다른 객체, 같은 메소드명을 구별할 수 있어야 함.
        R2Syntax = '\n    new_self_class = ' + self.objectName + \
                    ''.join(['\n    # ' + param for param in R2])
        print(R2Syntax)

        R3 = [parameter[1] for parameter in self.refactorSet[0]['R3']]
        R3Syntax = '\n    # variables' + \
                    ''.join(['\n    ' + param + ' = None' for param in R3])
        print(R3Syntax)

        R4 = [parameter[1] for parameter in self.refactorSet[0]['R4']]
        R4Syntax = '\n    # peeking data shape' + \
                    ''.join(['\n    # ' + param for param in R4])
        print(R4Syntax)

        R5 = [parameter[1] for parameter in self.refactorSet[0]['R5']]
        R5Syntax = '\n    # objects and methods' + \
                    ''.join(['\n    # ' + param for param in R5])
        print(R5Syntax)

        R6 = [parameter[1] for parameter in self.refactorSet[0]['R6']]
        R6Syntax = '\n    # Used functions' + \
                    ''.join(['\n    ' + param + ' = None' for param in R6])
        print(R6Syntax)


if __name__ == "__main__":
    from pprint import pprint

    file_target = r"E:\autoconstruction\components\NodeBlock.py"
    refactor = FuncRefactor()
    pprint(refactor.selectFunc("apply_update_from_box", file_target))
    refactor.docMaker()