from src.shared.typings import XYCoordinate
from .input_manager import input_manager


def drag(x1y1: XYCoordinate, x2y2: XYCoordinate):
    input_manager.drag(int(x1y1[0]), int(x1y1[1]), int(x2y2[0]), int(x2y2[1]))


def leftClick(windowCoordinate: XYCoordinate = None):
    if windowCoordinate is None:
        input_manager.left_click()
    else:
        input_manager.left_click(int(windowCoordinate[0]), int(windowCoordinate[1]))


def moveTo(windowCoordinate: XYCoordinate):
    input_manager.move_to(int(windowCoordinate[0]), int(windowCoordinate[1]))


def rightClick(windowCoordinate: XYCoordinate = None):
    if windowCoordinate is None:
        input_manager.right_click()
    else:
        input_manager.right_click(int(windowCoordinate[0]), int(windowCoordinate[1]))


def scroll(clicks: int):
    input_manager.scroll(clicks)
