"""
Action Layer 测试脚本

功能:
1. Inventory: 随机点击 5 个格子
2. Stash: 随机点击 5 个格子
3. 输出点击日志 + 调试截图

不修改 Locator，不新增识别，只做坐标转换+鼠标操作
"""
import os
import sys
import time
import random
import json
import numpy as np
import cv2
import mss
from datetime import datetime

from window_locator import locator
from template_locator import TemplateLocator

DEBUG_DIR = "template_debug"
SERVER = 'china'
# Inventory: 12列 x 5行 = 60格; Stash: 12列 x 12行 = 144格
GRID_CONFIG = {
    "inventory": {"cols": 12, "rows": 5},
    "stash": {"cols": 12, "rows": 12},
}

def write_log(lines, path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"  ✅ 日志: {path}")


def test_grid(tloc, tag, test_cells, cols, rows):
    """测试指定 Grid 的点击操作。"""
    print(f"\n{'='*60}")
    print(f"测试 {tag.upper()} Grid")
    print(f"{'='*60}")
    
    # 生成 Grid 坐标
    if tag == "inventory":
        cells_result = tloc.generate_inventory_cells()
    else:
        cells_result = tloc.generate_stash_cells()
    
    if not cells_result["success"]:
        print(f"  ❌ 失败: {cells_result['message']}")
        return [], None
    
    cells_map = cells_result["cells_map"]
    cells_screen = cells_result["cells_screen_map"]
    roi_rel = cells_result["roi_rel"]
    
    print(f"  ROI (相对窗口): {roi_rel}")
    print(f"  每格尺寸: {cells_result['cell_size'][0]:.1f}x{cells_result['cell_size'][1]:.1f} 像素")
    print(f"  总格子数: {len(cells_map)}")
    
    # 执行点击操作 + 记录日志
    log_lines = []
    log_lines.append("=" * 60)
    log_lines.append(f"{tag.upper()} Grid 点击测试报告")
    log_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_lines.append(f"游戏窗口: {tloc.locator.window['width']}x{tloc.locator.window['height']} @ "
                      f"({tloc.locator.window['left']}, {tloc.locator.window['top']})")
    log_lines.append(f"ROI (相对窗口): ({roi_rel[0]}, {roi_rel[1]})-({roi_rel[2]}, {roi_rel[3]})")
    log_lines.append(f"Grid: {cols}列 x {rows}行")
    log_lines.append(f"每格尺寸: {cells_result['cell_size'][0]:.1f}x{cells_result['cell_size'][1]:.1f} 像素")
    log_lines.append("=" * 60)
    log_lines.append("")
    
    click_points = []  # 用于截图标记点
    
    for i, (col, row) in enumerate(test_cells):
        cell_index = row * cols + col
        
        # 获取格子坐标
        cell_screen = cells_screen[cell_index]
        cell_rel = cells_map[cell_index]
        sx1, sy1 = cell_screen[0]
        sx2, sy2 = cell_screen[1]
        cx = (sx1 + sx2) // 2
        cy = (sy1 + sy2) // 2
        
        # 记录信息
        center_dist_left = cx - sx1
        center_dist_right = sx2 - cx
        center_dist_top = cy - sy1
        center_dist_bottom = sy2 - cy
        cell_width = sx2 - sx1
        cell_height = sy2 - sy1
        
        info = (
            f"[格子 {i+1}] 行列=({col},{row}), 索引={cell_index}\n"
            f"  相对窗口: ({cell_rel[0][0]},{cell_rel[0][1]})-({cell_rel[1][0]},{cell_rel[1][1]})\n"
            f"  屏幕坐标: ({sx1},{sy1})-({sx2},{sy2})\n"
            f"  中心点: ({cx},{cy})\n"
            f"  格子尺寸: {cell_width}x{cell_height} 像素\n"
            f"  距边界: 左={center_dist_left}px, 右={center_dist_right}px, 上={center_dist_top}px, 下={center_dist_bottom}px"
        )
        
        print(f"\n  格子 {i+1}: ({col},{row}) idx={cell_index}")
        print(f"    相对窗口: ({cell_rel[0][0]},{cell_rel[0][1]})-({cell_rel[1][0]},{cell_rel[1][1]})")
        print(f"    屏幕中心: ({cx},{cy})")
        
        # 执行鼠标移动（悬停
        if tag == "inventory":
            r = tloc.move_to_inventory_cell(col, row, cols, rows)
        else:
            r = tloc.move_to_stash_cell(col, row, cols, rows)
        
        if not r["success"]:
            print(f"    ⚠️  跳过: {r['message']}")
            log_lines.append(info + f"\n  ⚠️  跳过: {r['message']}")
            continue
        
        time.sleep(0.5)  # 可视化停顿
        log_lines.append(info + f"\n  ✅ 点击成功: 屏幕坐标 ({cx},{cy})")
        click_points.append((col, row, cx, cy, cell_index))
    
    log_lines.append("")
    log_lines.append("=" * 60)
    log_lines.append(f"总计: {len(click_points)}/{len(test_cells)} 个格子点击成功")
    log_lines.append("=" * 60)
    
    # 保存日志
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(DEBUG_DIR, f"{tag}_action_log_{timestamp}.txt")
    write_log(log_lines, log_path)
    
    # 截图并标记
    print(f"\n  调试截图准备中...")
    debug_img = take_and_mark_screenshot(tloc, tag, click_points, roi_rel)
    screenshot_path = os.path.join(DEBUG_DIR, f"{tag}_action_debug_{timestamp}.png")
    cv2.imwrite(screenshot_path, debug_img)
    print(f"  ✅ 调试截图: {screenshot_path}")
    
    return click_points, log_path


def take_and_mark_screenshot(tloc, tag, click_points, roi_rel):
    """截图并标记点击位置
    
    对于 Stash，面板可能延伸到游戏窗口外，所以需要扩展截图范围。
    """
    win_left = tloc.locator.window['left']
    win_top = tloc.locator.window['top']
    win_width = tloc.locator.window['width']
    win_height = tloc.locator.window['height']
    
    # 计算 ROI 的屏幕坐标范围
    roi_screen_x1 = win_left + roi_rel[0]
    roi_screen_y1 = win_top + roi_rel[1]
    roi_screen_x2 = win_left + roi_rel[2]
    roi_screen_y2 = win_top + roi_rel[3]
    
    # 决定截图区域：
    # - Inventory: 只截游戏窗口（ROI 完全在窗口内）
    # - Stash: 扩展截图范围以包含完整 Stash 面板（可能超出游戏窗口）
    if tag == "stash":
        # 扩展截图区域覆盖整个 Stash 面板
        capture_left = min(win_left, roi_screen_x1) - 20
        capture_top = min(win_top, roi_screen_y1) - 20
        capture_right = max(win_left + win_width, roi_screen_x2) + 20
        capture_bottom = max(win_top + win_height, roi_screen_y2) + 20
        capture_width = capture_right - capture_left
        capture_height = capture_bottom - capture_top
    else:
        capture_left = win_left
        capture_top = win_top
        capture_width = win_width
        capture_height = win_height
    
    with mss.mss() as sct:
        monitor = {
            'left': capture_left,
            'top': capture_top,
            'width': capture_width,
            'height': capture_height,
        }
        shot = sct.grab(monitor)
        img = np.array(shot, dtype=np.uint8)
        if img.shape[2] == 4:
            img = img[:, :, :3].copy()
    
    # 绘制 ROI 框（相对于截图左上角）
    rx1_s = roi_screen_x1 - capture_left
    ry1_s = roi_screen_y1 - capture_top
    rx2_s = roi_screen_x2 - capture_left
    ry2_s = roi_screen_y2 - capture_top
    cv2.rectangle(img, (int(rx1_s), int(ry1_s)), (int(rx2_s), int(ry2_s)), (0, 255, 0), 2)
    cv2.putText(img, f"{tag.upper()} ROI", (int(rx1_s), max(0, int(ry1_s - 10))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    # 绘制点击标记点（相对于截图左上角）
    for i, (col, row, cx, cy, idx) in enumerate(click_points):
        draw_cx = cx - capture_left
        draw_cy = cy - capture_top
        
        cross_size = 10
        cv2.line(img, (draw_cx - cross_size, draw_cy), (draw_cx + cross_size, draw_cy), (0, 0, 255), 2)
        cv2.line(img, (draw_cx, draw_cy - cross_size), (draw_cx, draw_cy + cross_size), (0, 0, 255), 2)
        cv2.circle(img, (draw_cx, draw_cy), 5, (0, 0, 255), -1)
        cv2.putText(img, f"#{i+1} ({col},{row})", (draw_cx + 8, draw_cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    
    return img


def generate_random_cells(n=5, cols=12, rows=5):
    """随机选择 n 个测试格子"""
    cells = []
    used = set()
    while len(cells) < n:
        col = random.randint(0, cols - 1)
        row = random.randint(0, rows - 1)
        if (col, row) not in used:
            used.add((col, row))
            cells.append((col, row))
    return cells


def main():
    print("=" * 60)
    print("Action Layer 测试 - Inventory & Stash")
    print("=" * 60)
    
    # 初始化
    if not locator.detect(SERVER):
        print("  ❌ 失败: 未检测到游戏窗口")
        return 1
    
    tloc = TemplateLocator(locator, debug=True)
    
    print(f"\n[INFO] 窗口: {locator.window['width']}x{locator.window['height']} @ "
          f"({locator.window['left']}, {locator.window['top']})")
    
    # 测试 Inventory 5 个随机格子 (12x5=60)
    inv_cfg = GRID_CONFIG["inventory"]
    inv_test_cells = generate_random_cells(5, inv_cfg["cols"], inv_cfg["rows"])
    test_grid(tloc, "inventory", inv_test_cells, inv_cfg["cols"], inv_cfg["rows"])
    
    time.sleep(1.0)
    
    # 测试 Stash 5 个随机格子 (12x12=144)
    stash_cfg = GRID_CONFIG["stash"]
    stash_test_cells = generate_random_cells(5, stash_cfg["cols"], stash_cfg["rows"])
    test_grid(tloc, "stash", stash_test_cells, stash_cfg["cols"], stash_cfg["rows"])
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())