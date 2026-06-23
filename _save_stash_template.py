"""
截图仓库NPC交互按钮，保存为模板并写入 auto_buy_config.json

用法：
  1. 站在仓库NPC旁边（能看到仓库交互按钮）
  2. 运行此脚本
  3. 调整截图区域，确认后保存
"""
import cv2
import numpy as np
import mss
import json
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from window_locator import locator

CONFIG_PATH = "auto_buy_config.json"

# 检测游戏窗口
server = "china"
if locator.detect("global"):
    server = "global"
elif not locator.detect("china"):
    print("[错误] 未检测到游戏窗口")
    sys.exit(1)

win = locator.window
print(f"[窗口] 已识别: {win['title']} 位置:({win['left']},{win['top']}) 大小:{win['width']}x{win['height']}")

# 提示：请确认仓库NPC交互按钮在视野内
input("请确保仓库NPC在游戏画面中可见，然后按 Enter 键截图...")

# 截图整个游戏窗口
with mss.mss() as sct:
    monitor = {"top": win["top"], "left": win["left"], "width": win["width"], "height": win["height"]}
    screenshot = sct.grab(monitor)
    win_img = np.array(screenshot)[:, :, :3]

# 显示并让用户框选区域
print("\n[提示] 请在弹出窗口中框选仓库交互按钮区域，按 Enter 或 Space 确认")
print("[提示] 如果窗口没显示，请检查是否被遮挡")

# 使用 OpenCV 选择 ROI
from cv2 import selectROI
roi = selectROI("框选仓库交互按钮区域，按 Enter 确认", win_img, showCrosshair=True)

if roi[2] == 0 or roi[3] == 0:
    print("[警告] 未选择区域，使用默认区域")
    # 使用默认区域（仓库交互按钮通常位于游戏画面左下角附近）
    x, y, w, h = 40, win["height"] - 160, 120, 131
    roi = (x, y, w, h)
else:
    x, y, w, h = roi

print(f"\n[信息] 选定区域: ({int(x)}, {int(y)}) 大小: {int(w)}x{int(h)}")

# 裁剪模板
template = win_img[int(y):int(y+h), int(x):int(x+w)]
cv2.imwrite("detect_debug/new_stash_template.png", template)
print(f"[保存] 模板已保存到 detect_debug/new_stash_template.png")

# 提示确认
print(f"\n模板大小: {template.shape[1]}x{template.shape[0]}")
confirm = input("是否确认保存到配置文件？(y/n): ")

if confirm.lower() == 'y':
    # 读取现有配置
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
    
    # 替换 stash_template
    config["stash_template"] = template.tolist()
    
    # 保存
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)
    
    print(f"[完成] 新仓库模板已保存到 {CONFIG_PATH}")
    print(f"  - 模板大小: {template.shape[1]}x{template.shape[0]}")
else:
    print("[取消] 未保存")
