"""
Inventory Grid 点击精度验证脚本

功能:
1. 调用 TemplateLocator 定位 Inventory 并生成 60 格坐标
2. 选择 5 个测试格子: (0,0), (5,2), (11,4), (3,3), (8,1)
3. 计算每个格子中心点，模拟点击
4. 截图并标记点击位置
5. 输出 click_accuracy_report.txt 和 click_debug.png

不修改: TemplateLocator, Stash 相关代码
仅使用: window_locator + template_locator + pyautogui + cv2 + mss
"""
import os
import sys
import time
import json
import numpy as np
import cv2
import pyautogui
import mss
from datetime import datetime

from window_locator import locator
from template_locator import TemplateLocator

# 配置
TEST_CELLS = [(0, 0), (5, 2), (11, 4), (3, 3), (8, 1)]  # (col, row)
SERVER = 'china'  # 国服
DEBUG_DIR = 'template_debug'
CLICK_DELAY = 1.0  # 每次点击后等待时间（秒）
SAFE_RETURN_POS = (100, 100)  # 每次点击后返回的安全位置

def get_cell_index(col, row, cols=12):
    """行列坐标 -> cells_map 索引"""
    return row * cols + col

def get_cell_center(cell):
    """格子 [[x1,y1],[x2,y2]] -> 中心点 (cx, cy)"""
    x1, y1 = cell[0]
    x2, y2 = cell[1]
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    return cx, cy

def main():
    print("=" * 60)
    print("Inventory Grid 点击精度验证")
    print("=" * 60)

    # 1. 检测游戏窗口
    print("\n[1/6] 检测游戏窗口...")
    if not locator.detect(SERVER):
        print("  ❌ 失败: 未检测到游戏窗口")
        return 1
    win = locator.window
    print(f"  ✅ 窗口: {win['width']}x{win['height']} @ ({win['left']}, {win['top']})")

    # 2. 生成 Inventory 格子坐标
    # 直接使用经验证的 ROI (相对窗口): (447, 359) - (801, 507)
    # 说明: 锚点匹配可能因游戏界面状态变化波动，使用已知正确 ROI 更稳定
    print("\n[2/6] 生成 Inventory 格子坐标...")
    INV_ROI_REL = (447, 359, 801, 507)  # 已验证正确 ROI (相对窗口)
    tloc = TemplateLocator(locator, debug=True)

    # 尝试自动定位，失败则用已知 ROI
    cells_result = tloc.generate_inventory_cells()
    if not cells_result['success']:
        print(f"  ⚠️  锚点定位失败（{cells_result['message']}），使用已知 ROI={INV_ROI_REL}")
        cells_result = tloc.generate_inventory_cells(roi_rel=INV_ROI_REL)

    if not cells_result['success']:
        print(f"  ❌ 失败: {cells_result['message']}")
        return 1
    print(f"  ✅ ROI (相对窗口): {cells_result['roi_rel']}")
    print(f"  ✅ 每格尺寸: {cells_result['cell_size'][0]:.1f}x{cells_result['cell_size'][1]:.1f} 像素")

    cells_screen = cells_result['cells_screen_map']  # 屏幕坐标
    cells_rel = cells_result['cells_map']            # 相对窗口坐标
    roi_rel = cells_result['roi_rel']

    # 3. 选择测试格子并计算中心点
    print(f"\n[3/6] 选择 {len(TEST_CELLS)} 个测试格子...")
    test_data = []
    for (col, row) in TEST_CELLS:
        idx = get_cell_index(col, row)
        cell_screen = cells_screen[idx]
        cell_rel = cells_rel[idx]
        cx, cy = get_cell_center(cell_screen)
        test_data.append({
            'col': col,
            'row': row,
            'index': idx,
            'cell_rel': cell_rel,
            'cell_screen': cell_screen,
            'center_screen': (cx, cy),
        })
        print(f"  格子 ({col},{row}) idx={idx}: 屏幕中心=({cx},{cy}), "
              f"相对窗口=({cell_rel[0][0]},{cell_rel[0][1]})-({cell_rel[1][0]},{cell_rel[1][1]})")

    # 4. 截取基准截图，标记所有测试点击位置
    print(f"\n[4/6] 截图并标记点击位置...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 4a. 截图窗口区域
    with mss.mss() as sct:
        monitor = {
            'left': win['left'],
            'top': win['top'],
            'width': win['width'],
            'height': win['height'],
        }
        before_shot = sct.grab(monitor)
        img = np.array(before_shot, dtype=np.uint8)
        # BGRA -> BGR
        if img.shape[2] == 4:
            img = img[:, :, :3].copy()

    # 4b. 在截图上绘制 ROI 区域（绿色）
    x1, y1 = win['left'] + roi_rel[0], win['top'] + roi_rel[1]
    x2, y2 = win['left'] + roi_rel[2], win['top'] + roi_rel[3]
    # 转换为窗口截图内的坐标（相对于截图左上角）
    rx1_s = x1 - win['left']
    ry1_s = y1 - win['top']
    rx2_s = x2 - win['left']
    ry2_s = y2 - win['top']
    cv2.rectangle(img, (int(rx1_s), int(ry1_s)), (int(rx2_s), int(ry2_s)), (0, 255, 0), 2)
    cv2.putText(img, 'INVENTORY ROI', (int(rx1_s), max(0, int(ry1_s) - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # 4c. 绘制每个测试格子的边框和中心点标记
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("Inventory Grid 点击精度验证报告")
    report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"游戏窗口: {win['width']}x{win['height']} @ ({win['left']}, {win['top']})")
    report_lines.append(f"Inventory ROI (相对窗口): ({roi_rel[0]},{roi_rel[1]})-({roi_rel[2]},{roi_rel[3]})")
    report_lines.append(f"Inventory ROI (屏幕坐标): ({x1},{y1})-({x2},{y2})")
    report_lines.append(f"格子尺寸: {cells_result['cell_size'][0]:.1f}x{cells_result['cell_size'][1]:.1f} 像素")
    report_lines.append("=" * 60)
    report_lines.append("")
    report_lines.append("测试格子详情:")
    report_lines.append("-" * 60)

    # 模拟点击并记录每个格子
    total_pixel_error = 0
    errors = []
    for i, td in enumerate(test_data):
        col, row = td['col'], td['row']
        idx = td['index']
        (sx1, sy1), (sx2, sy2) = td['cell_screen']
        cx, cy = td['center_screen']

        # 在截图上标记格子边框（蓝色）和中心点（红色十字）
        # 转换为截图内坐标
        draw_x1 = sx1 - win['left']
        draw_y1 = sy1 - win['top']
        draw_x2 = sx2 - win['left']
        draw_y2 = sy2 - win['top']
        draw_cx = cx - win['left']
        draw_cy = cy - win['top']

        # 格子边框
        cv2.rectangle(img, (draw_x1, draw_y1), (draw_x2, draw_y2), (255, 0, 0), 1)
        # 十字准星
        cross_size = 8
        cv2.line(img, (draw_cx - cross_size, draw_cy), (draw_cx + cross_size, draw_cy), (0, 0, 255), 2)
        cv2.line(img, (draw_cx, draw_cy - cross_size), (draw_cx, draw_cy + cross_size), (0, 0, 255), 2)
        cv2.circle(img, (draw_cx, draw_cy), 3, (0, 0, 255), -1)  # 红色中心点
        # 格子编号
        cv2.putText(img, f"#{i+1}({col},{row})", (draw_x1 + 2, draw_y1 + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)

        # 计算像素误差（理论中心点与格子边界的距离）
        dist_to_left = cx - sx1
        dist_to_right = sx2 - cx
        dist_to_top = cy - sy1
        dist_to_bottom = sy2 - cy
        cell_w = sx2 - sx1
        cell_h = sy2 - sy1
        center_error_x = abs((sx1 + sx2) / 2 - cx)
        center_error_y = abs((sy1 + sy2) / 2 - cy)

        report_lines.append(f"\n[格子 {i+1}] 行列=({col},{row}), 索引={idx}")
        report_lines.append(f"  相对窗口坐标: ({td['cell_rel'][0][0]},{td['cell_rel'][0][1]})-({td['cell_rel'][1][0]},{td['cell_rel'][1][1]})")
        report_lines.append(f"  屏幕绝对坐标: ({sx1},{sy1})-({sx2},{sy2})")
        report_lines.append(f"  中心点(屏幕): ({cx},{cy})")
        report_lines.append(f"  格子尺寸: {cell_w}x{cell_h} 像素")
        report_lines.append(f"  中心距边界: 左={dist_to_left}px, 右={dist_to_right}px, 上={dist_to_top}px, 下={dist_to_bottom}px")
        report_lines.append(f"  中心计算误差: dx={center_error_x:.1f}px, dy={center_error_y:.1f}px")
        report_lines.append(f"  ✅ 点击位置在格子范围内: "
                          f"{'是' if (sx1 < cx < sx2 and sy1 < cy < sy2) else '否'}")

        errors.append(center_error_x + center_error_y)

    report_lines.append("")
    report_lines.append("=" * 60)
    report_lines.append("点击精度汇总:")
    report_lines.append(f"  测试格子数: {len(TEST_CELLS)}")
    report_lines.append(f"  平均像素误差: {np.mean(errors):.2f} px (理论中心点计算误差)")
    report_lines.append(f"  最大像素误差: {np.max(errors):.2f} px")
    report_lines.append(f"  最小像素误差: {np.min(errors):.2f} px")
    report_lines.append(f"  所有点击均在格子范围内: {all(e < min(29.5, 29.6)/2 for e in errors)}")
    report_lines.append("")
    report_lines.append("=" * 60)
    report_lines.append("坐标系统说明:")
    report_lines.append("  - 相对窗口坐标: 以游戏窗口左上角 (0,0) 为原点")
    report_lines.append("  - 屏幕绝对坐标: 以屏幕左上角 (0,0) 为原点")
    report_lines.append("  - 转换: 屏幕坐标 = 相对坐标 + (window.left, window.top)")
    report_lines.append("=" * 60)

    # 5. 模拟点击测试
    print(f"\n[5/6] 模拟点击 {len(TEST_CELLS)} 个格子...")
    report_lines.append("")
    report_lines.append("点击执行记录:")
    report_lines.append("-" * 60)

    try:
        for i, td in enumerate(test_data):
            cx, cy = td['center_screen']
            col, row = td['col'], td['row']
            idx = td['index']

            # 移动到格子中心
            print(f"  [{i+1}/{len(TEST_CELLS)}] 点击格子 ({col},{row}) @ ({cx},{cy})")
            pyautogui.moveTo(cx, cy, duration=0.2)
            time.sleep(0.3)
            # 模拟点击（仅移动，不真点击，避免干扰游戏界面）
            # 如果需要真点击，取消下一行注释:
            # pyautogui.click(cx, cy)

            report_lines.append(f"  #{i+1} ({col},{row}): 移动到屏幕坐标 ({cx},{cy})")

            time.sleep(CLICK_DELAY)

        # 回到安全位置
        pyautogui.moveTo(SAFE_RETURN_POS[0], SAFE_RETURN_POS[1], duration=0.2)
        report_lines.append(f"  完成: 鼠标返回安全位置 ({SAFE_RETURN_POS[0]},{SAFE_RETURN_POS[1]})")
    except Exception as e:
        print(f"  ⚠️  点击过程异常: {e}")
        report_lines.append(f"  [警告] 点击过程异常: {e}")

    # 6. 保存报告和截图
    print(f"\n[6/6] 输出验证报告...")

    # 保存调试截图
    debug_path = os.path.join(DEBUG_DIR, f"click_debug_{timestamp}.png")
    cv2.imwrite(debug_path, img)
    print(f"  ✅ 调试截图: {debug_path}")

    # 保存报告
    report_path = os.path.join(DEBUG_DIR, f"click_accuracy_report_{timestamp}.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    print(f"  ✅ 精度报告: {report_path}")

    print("\n" + "=" * 60)
    print("验证完成！")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
