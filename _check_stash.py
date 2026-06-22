"""快速检测脚本：确认游戏窗口位置和 Stash ROI 相对坐标"""
import os
import json
import sys
from window_locator import locator

# 1. 检测游戏窗口
server = 'china' if '--china' in sys.argv else 'global'
if not locator.detect(server):
    print("[ERROR] 未检测到游戏窗口")
    sys.exit(1)

win = locator.window
print(f"[窗口] 位置: ({win['left']}, {win['top']}) 尺寸: {win['width']}x{win['height']}")

# 2. 从配置读取 Stash ROI（屏幕绝对坐标）
with open('auto_buy_config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)

# Stash ROI 屏幕绝对坐标
inv_region = cfg.get('inventory_region', None)
if inv_region:
    sx1, sy1, sx2, sy2 = inv_region
    print(f"\n[Stash ROI 屏幕坐标] ({sx1}, {sy1}) - ({sx2}, {sy2})")
    print(f"                 宽 x 高: {sx2 - sx1} x {sy2 - sy1}")

    # 转换为相对窗口坐标
    rx1 = sx1 - win['left']
    ry1 = sy1 - win['top']
    rx2 = sx2 - win['left']
    ry2 = sy2 - win['top']
    print(f"[Stash ROI 相对坐标] ({rx1}, {ry1}) - ({rx2}, {ry2})")
    print(f"                 宽 x 高: {rx2 - rx1} x {ry2 - ry1}")

    # 检查是否在窗口范围内
    print(f"\n[检查] rx1>=0: {rx1 >= 0}, ry1>=0: {ry1 >= 0}")
    print(f"       rx2<={win['width']}: {rx2 <= win['width']}")
    print(f"       ry2<={win['height']}: {ry2 <= win['height']}")

    # 每格尺寸估算
    cell_w = (rx2 - rx1) / 12
    cell_h = (ry2 - ry1) / 5
    print(f"\n[格子估算] 12列 x 5行 = 60格")
    print(f"         每格: {cell_w:.1f} x {cell_h:.1f} 像素")
else:
    print("\n[WARN] 未找到 inventory_region")

# 3. Inventory ROI（相对窗口坐标，用于验证）
inv_roi = cfg.get('roi', None)
if inv_roi:
    print(f"\n[Inventory ROI 相对坐标] ({inv_roi['LEFT']}, {inv_roi['TOP']}) - ({inv_roi['RIGHT']}, {inv_roi['BOTTOM']})")
    # 转换回屏幕坐标验证
    inv_sx1 = win['left'] + inv_roi['LEFT']
    inv_sy1 = win['top'] + inv_roi['TOP']
    inv_sx2 = win['left'] + inv_roi['RIGHT']
    inv_sy2 = win['top'] + inv_roi['BOTTOM']
    print(f"[Inventory ROI 屏幕坐标] ({inv_sx1}, {inv_sy1}) - ({inv_sx2}, {inv_sy2})")

# 4. Stash 打开按钮
stash_pos = cfg.get('stash_open_pos', None)
if stash_pos:
    print(f"\n[Stash Open 屏幕坐标] ({stash_pos[0]}, {stash_pos[1]})")
    srx = stash_pos[0] - win['left']
    sry = stash_pos[1] - win['top']
    print(f"[Stash Open 相对坐标] ({srx}, {sry})")
    print(f"       (在Stash ROI 相对坐标中的位置: ({srx - rx1}, {sry - ry1})")

print("\n=== 需要提供 ===")
print("Stash 锚点图需要手动截取:")
print("  1. 确保游戏中 Stash 界面已打开")
print("  2. 截取 Stash 标题栏作为锚点")
print("  3. 保存为: templates/stash/anchor.png")
print("Stash ROI 相对坐标（用于计算 offset）:")
print(f"  rx1={rx1}, ry1={ry1}, rx2={rx2}, ry2={ry2}")
