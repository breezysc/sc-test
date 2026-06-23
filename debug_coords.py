import cv2
import numpy as np
import mss
from window_locator import locator

# 初始化 locator
locator.detect('china')

# 获取游戏窗口（属性，不是方法）
win = locator.window
print(f"游戏窗口对象: {win}")

if win:
    game_window = {
        "left": win["left"],
        "top": win["top"],
        "width": win["width"],
        "height": win["height"]
    }
    print(f"游戏窗口: {game_window}")
else:
    game_window = None
    print("游戏窗口未找到")

# 用户提供的绝对坐标
abs_first_center_x = 521
abs_first_center_y = 763

# 转换为相对坐标
if game_window:
    rel_first_center_x = abs_first_center_x - game_window["left"]
    rel_first_center_y = abs_first_center_y - game_window["top"]
    print(f"\n绝对坐标: ({abs_first_center_x}, {abs_first_center_y})")
    print(f"相对坐标: ({rel_first_center_x}, {rel_first_center_y})")
    
    # 再转换回绝对坐标
    back_abs_x, back_abs_y = locator.to_screen(rel_first_center_x, rel_first_center_y)
    print(f"转换回来: ({back_abs_x}, {back_abs_y})")
    print(f"是否一致: {abs_first_center_x == back_abs_x and abs_first_center_y == back_abs_y}")
    
    # 截图测试
    cell_width = 62
    cell_height = 62
    x1 = rel_first_center_x - cell_width // 2
    y1 = rel_first_center_y - cell_height // 2
    x2 = rel_first_center_x + cell_width // 2
    y2 = rel_first_center_y + cell_height // 2
    
    print(f"\n相对坐标区域: ({x1}, {y1}) - ({x2}, {y2})")
    
    # 使用相对坐标通过 locator 转换
    abs_x1, abs_y1 = locator.to_screen(x1, y1)
    abs_x2, abs_y2 = locator.to_screen(x2, y2)
    print(f"绝对坐标区域: ({abs_x1}, {abs_y1}) - ({abs_x2}, {abs_y2})")
    
    # 截图
    with mss.mss() as sct:
        monitor = {
            "top": int(abs_y1),
            "left": int(abs_x1),
            "width": int(abs_x2 - abs_x1),
            "height": int(abs_y2 - abs_y1)
        }
        screenshot = sct.grab(monitor)
        cell_img = np.array(screenshot)[:, :, :3]
    
    cv2.imwrite("debug_cell.png", cell_img)
    print(f"\n截图已保存: debug_cell.png (大小: {cell_img.shape[1]}×{cell_img.shape[0]})")
    
    # 计算与空格子模板的匹配度
    empty_cell_template = cv2.imread("cc.png")
    if empty_cell_template is not None:
        search_gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(empty_cell_template, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        print(f"匹配度: {max_val:.4f}")
        print(f"判断: {'空格子' if max_val > 0.5 else '有物品'}")
else:
    print("无法获取游戏窗口")
