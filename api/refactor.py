from readset import readSetCategorizeTest
from writeset import writeSetCategorizeTest

def getRefactorSet(file_target):
    readSet = readSetCategorizeTest(file_target)
    writeSet = writeSetCategorizeTest(file_target)

    return [readSet, writeSet]

if __name__ == "__main__":
    from pprint import pprint

    file_target = r"E:\autoconstruction\components\NodeEdit.py"
    pprint(getRefactorSet(file_target))