import os, json, sys, numpy as np
from window_locator import locator

cv2 = None
try:
    import cv2
except ImportError:
    print("[ERROR] 未安装 cv2")
    sys.exit(1)

# 1. 检测游戏窗口
locator.detect('china')
w = locator.window
win_left = w['left']
win_top = w['top']
win_w = w['width']
win_h = w['height']
print(f'[窗口] {win_w}x{win_h} @ 屏幕 ({win_left}, {win_top})')

# 2. 用户给的屏幕坐标
screen_x1, screen_y1 = 457, 375
screen_x2, screen_y2 = 811, 523

# 转换为相对坐标
rel_x1 = screen_x1 - win_left
rel_y1 = screen_y1 - win_top
rel_x2 = screen_x2 - win_left
rel_y2 = screen_y2 - win_top
print(f'[ROI 相对] ({rel_x1}, {rel_y1}) - ({rel_x2}, {rel_y2})')
print(f'         宽 x 高: {rel_x2 - rel_x1} x {rel_y2 - rel_y1}')

# 3. 截图找锚点
window_img = locator.grab_window()
if window_img is None:
    print('[ERROR] grab_window 返回 None')
    sys.exit(1)

tpl_path = 'templates/inventory/anchor.png'
template = cv2.imread(tpl_path)
if template is None:
    print(f'[ERROR] 锚点模板不存在: {tpl_path}')
    sys.exit(1)

tpl_h, tpl_w = template.shape[:2]
print(f'[模板] {tpl_w}x{tpl_h}')

# 多尺度匹配
gray_win = cv2.cvtColor(window_img, cv2.COLOR_BGR2GRAY)
gray_tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

best_conf = 0
best_scale = 1.0
best_x = 0
best_y = 0
best_w = tpl_w
best_h = tpl_h

for s in np.arange(0.7, 2.01, 0.03):
    s = round(float(s), 2)
    new_w = max(1, int(tpl_w * s))
    new_h = max(1, int(tpl_h * s))
    if new_h >= gray_win.shape[0] or new_w >= gray_win.shape[1]:
        continue
    if s < 1.0:
        scaled = cv2.resize(gray_tpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        scaled = cv2.resize(gray_tpl, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    r = cv2.matchTemplate(gray_win, scaled, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _ml, ml = cv2.minMaxLoc(r)
    if mx > best_conf:
        best_conf = float(mx)
        best_scale = s
        best_x = int(ml[0])
        best_y = int(ml[1])
        best_w = new_w
        best_h = new_h

print(f'[锚点] 置信度={best_conf:.3f} 尺度={best_scale:.2f} 相对位置=({best_x}, {best_y}) 尺寸={best_w}x{best_h}')

# 4. 计算 offset
dx1 = rel_x1 - best_x
dy1 = rel_y1 - best_y
dx2 = rel_x2 - best_x
dy2 = rel_y2 - best_y
print(f'[offset] dx1={dx1}, dy1={dy1}, dx2={dx2}, dy2={dy2}')

# 5. 验证
calc_x1 = best_x + dx1
calc_y1 = best_y + dy1
calc_x2 = best_x + dx2
calc_y2 = best_y + dy2
print(f'[验证] 锚点+offset = ({calc_x1}, {calc_y1})-({calc_x2}, {calc_y2})')
print(f'       期望相对   = ({rel_x1}, {rel_y1})-({rel_x2}, {rel_y2})')

# 6. 输出配置
config = {
    "inventory": {
        "template_path": "templates/inventory/anchor.png",
        "threshold": 0.7,
        "scale_min": 0.7,
        "scale_max": 1.5,
        "scale_step": 0.05,
        "offset": {
            "dx1": int(dx1),
            "dy1": int(dy1),
            "dx2": int(dx2),
            "dy2": int(dy2),
        },
    }
}
print()
print('[输出配置] 写入 template_locator_config.json')
print(json.dumps(config, ensure_ascii=False, indent=2))

with open('template_locator_config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)
print('已保存')