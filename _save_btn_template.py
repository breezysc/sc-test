"""保存截图按钮模板 - 使用游戏相对坐标，自动适配窗口位置"""
import cv2
import numpy as np
import mss
import auto_buy_new

# 检测游戏窗口
result = auto_buy_new.detect_game_window("china")
if not result or auto_buy_new.game_window is None:
    print("❌ 未检测到游戏窗口")
    exit(1)

gw = auto_buy_new.game_window
print(f"✅ 游戏窗口: ({gw['left']}, {gw['top']}) {gw['width']}x{gw['height']}")

# 截图按钮游戏相对坐标
REL_X1, REL_Y1, REL_X2, REL_Y2 = 598, 512, 674, 532

# 转换为屏幕坐标
screen_x1 = gw["left"] + REL_X1
screen_y1 = gw["top"] + REL_Y1
screen_x2 = gw["left"] + REL_X2
screen_y2 = gw["top"] + REL_Y2

width = screen_x2 - screen_x1
height = screen_y2 - screen_y1

print(f"截取区域(屏幕): ({screen_x1}, {screen_y1}) -> ({screen_x2}, {screen_y2})")

with mss.mss() as sct:
    monitor = {"top": screen_y1, "left": screen_x1, "width": width, "height": height}
    screenshot = sct.grab(monitor)
    btn_img = np.array(screenshot)[:, :, :3]

if btn_img.size == 0 or btn_img.mean() < 1:
    print("❌ 截图区域为空或全黑，按钮可能不在该位置")
    exit(1)

# 保存模板
cv2.imwrite("template_screenshot_btn.png", cv2.cvtColor(btn_img, cv2.COLOR_BGR2RGB))
print(f"✅ 模板已保存: template_screenshot_btn.png ({width}x{height})")
print(f"   平均亮度: {btn_img.mean():.1f}")
