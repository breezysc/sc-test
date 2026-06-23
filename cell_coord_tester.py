"""
格子坐标测试工具
功能:
  - 实时显示第一个格子和最后一个格子的屏幕坐标
  - 按键 1: 点击第一个格子
  - 按键 2: 点击最后一个格子
  - 按键 3: 点击指定格子 (输入编号 1-60)
  - 按键 R: 刷新窗口检测 (窗口移动后重新校准)
  - 按键 Q: 退出
  - 窗口移动时自动跟踪并校准坐标
"""

import time
import sys
import threading
import pyautogui
from window_locator import locator

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# ============ 格子坐标配置 ============
# 屏幕绝对坐标 (用户测量时窗口位于 (78,78))
ABS_FIRST_CENTER = (540, 452)   # 第一个格子中心
ABS_LAST_CENTER  = (862, 568)   # 最后一个格子中心
COLS = 12
ROWS = 5
CELL_SIZE = 30

# 用户测量坐标时的窗口位置
MEASURE_WINDOW_LEFT = 78
MEASURE_WINDOW_TOP = 78

# ============ 全局状态 ============
game_window = None
cells = []  # [(cx, cy), ...] 屏幕绝对坐标
rel_cells = []  # [(rx, ry), ...] 相对游戏窗口坐标
running = True
last_window_pos = None


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def detect_window():
    """检测游戏窗口"""
    global game_window
    if not locator.detect("global"):
        if not locator.detect("china"):
            return False
    game_window = locator.window
    return True


def calc_cells():
    """计算所有格子的屏幕绝对坐标和相对坐标
    
    逻辑:
    1. 用测量时的窗口位置计算相对坐标 (固定不变)
    2. 用 locator.to_screen() 将相对坐标转为当前屏幕坐标 (随窗口移动自适应)
    """
    global cells, rel_cells, game_window, last_window_pos
    
    if not game_window:
        return False
    
    win_left = game_window["left"]
    win_top = game_window["top"]
    current_pos = (win_left, win_top)
    
    # 第一步: 基于测量窗口位置计算相对坐标 (固定值, 不随窗口移动变化)
    rel_first_cx = ABS_FIRST_CENTER[0] - MEASURE_WINDOW_LEFT
    rel_first_cy = ABS_FIRST_CENTER[1] - MEASURE_WINDOW_TOP
    rel_last_cx = ABS_LAST_CENTER[0] - MEASURE_WINDOW_LEFT
    rel_last_cy = ABS_LAST_CENTER[1] - MEASURE_WINDOW_TOP
    
    col_spacing = (rel_last_cx - rel_first_cx) / (COLS - 1)
    row_spacing = (rel_last_cy - rel_first_cy) / (ROWS - 1)
    
    rel_cells = []
    cells = []
    for row in range(ROWS):
        for col in range(COLS):
            rx = int(rel_first_cx + col * col_spacing)
            ry = int(rel_first_cy + row * row_spacing)
            rel_cells.append((rx, ry))
            # 第二步: 用 locator 将相对坐标转为屏幕坐标
            sx, sy = locator.to_screen(rx, ry)
            cells.append((sx, sy))
    
    if current_pos != last_window_pos:
        if last_window_pos is not None:
            offset_x = win_left - last_window_pos[0]
            offset_y = win_top - last_window_pos[1]
            log(f"窗口移动: {last_window_pos} → {current_pos}  偏移:({offset_x},{offset_y})")
        last_window_pos = current_pos
    
    return True


def show_info():
    """显示当前坐标信息"""
    if not game_window or not cells or not rel_cells:
        return
    
    win = game_window
    first = cells[0]
    last = cells[-1]
    rel_first = rel_cells[0]
    rel_last = rel_cells[-1]
    
    print()
    print("=" * 65)
    print(f"  游戏窗口: 左上({win['left']}, {win['top']})  右下({win['left']+win['width']}, {win['top']+win['height']})  大小:{win['width']}x{win['height']}")
    print(f"  测量基准窗口: ({MEASURE_WINDOW_LEFT}, {MEASURE_WINDOW_TOP})")
    print("-" * 65)
    print(f"  格子 1  相对({rel_first[0]}, {rel_first[1]})  屏幕({first[0]}, {first[1]})")
    print(f"  格子 60 相对({rel_last[0]}, {rel_last[1]})  屏幕({last[0]}, {last[1]})")
    print("-" * 65)
    print(f"  列间距: {(rel_last[0] - rel_first[0]) / 11:.1f}px  行间距: {(rel_last[1] - rel_first[1]) / 4:.1f}px  格子大小: {CELL_SIZE}x{CELL_SIZE}")
    print("=" * 65)
    print()
    print("  [1] 点击格子1   [2] 点击格子60   [3] 指定格子编号")
    print("  [R] 刷新窗口   [Q] 退出")
    print()


def click_cell(index):
    """点击指定格子 (1-based)"""
    if not cells or index < 1 or index > len(cells):
        log(f"无效格子编号: {index} (有效范围 1-{len(cells)})")
        return
    
    cx, cy = cells[index - 1]
    row = (index - 1) // COLS + 1
    col = (index - 1) % COLS + 1
    
    log(f"点击格子 {index} (第{row}行第{col}列) → 屏幕({cx}, {cy})")
    pyautogui.click(cx, cy)


def get_cell_index_input():
    """获取用户输入的格子编号"""
    try:
        s = input("  请输入格子编号 (1-60): ").strip()
        if s:
            idx = int(s)
            if 1 <= idx <= 60:
                return idx
            else:
                log(f"编号超出范围: {idx}")
    except ValueError:
        log(f"无效输入: {s}")
    return None


def monitor_loop():
    """后台监控窗口位置变化，同步更新 locator 并重算格子坐标"""
    global running, game_window
    while running:
        if game_window and locator.detected:
            hwnd = game_window.get("hwnd")
            if hwnd:
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    new_left = rect.left
                    new_top = rect.top
                    new_width = rect.right - rect.left
                    new_height = rect.bottom - rect.top
                    
                    if (new_left != game_window["left"] or 
                        new_top != game_window["top"] or
                        new_width != game_window["width"] or
                        new_height != game_window["height"]):
                        # 同步更新 locator 和 game_window
                        game_window["left"] = new_left
                        game_window["top"] = new_top
                        game_window["width"] = new_width
                        game_window["height"] = new_height
                        game_window["right"] = rect.right
                        game_window["bottom"] = rect.bottom
                        locator._window = game_window
                        calc_cells()
                        show_info()
                except Exception:
                    pass
        time.sleep(0.3)


def main():
    global running, game_window
    
    print()
    print("=" * 65)
    print("  格子坐标测试工具")
    print("=" * 65)
    
    # 检测窗口
    log("正在检测游戏窗口...")
    if not detect_window():
        log("未找到游戏窗口！请确保游戏已启动")
        log("按键 [R] 可重新检测")
    else:
        log(f"检测到窗口: {game_window['title']}")
        calc_cells()
    
    show_info()
    
    # 启动后台监控线程
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    
    # 主循环
    while running:
        try:
            cmd = input("> ").strip().lower()
            
            if cmd == 'q':
                running = False
                log("退出")
                break
            elif cmd == '1':
                if not cells:
                    log("请先检测到游戏窗口")
                else:
                    click_cell(1)
            elif cmd == '2':
                if not cells:
                    log("请先检测到游戏窗口")
                else:
                    click_cell(60)
            elif cmd == '3':
                if not cells:
                    log("请先检测到游戏窗口")
                else:
                    idx = get_cell_index_input()
                    if idx:
                        click_cell(idx)
            elif cmd == 'r':
                log("重新检测窗口...")
                if detect_window():
                    log(f"检测到窗口: {game_window['title']}")
                    calc_cells()
                    show_info()
                else:
                    log("未找到游戏窗口")
            elif cmd == '':
                continue
            else:
                log(f"未知命令: '{cmd}'")
                
        except KeyboardInterrupt:
            running = False
            log("退出")
            break
        except EOFError:
            running = False
            break
    
    print("工具已关闭")


if __name__ == "__main__":
    main()