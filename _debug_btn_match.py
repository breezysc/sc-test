"""调试：截图按钮模板匹配对比"""
import os, cv2, numpy as np, mss
import auto_buy_new

# 检测窗口
auto_buy_new.detect_game_window("china")
gw = auto_buy_new.game_window
if gw is None:
    print("❌ 未检测到游戏窗口")
    exit(1)

print(f"游戏窗口: ({gw['left']}, {gw['top']})")

# 加载模板
auto_buy_new.load_screenshot_btn_template()
bt = auto_buy_new.screenshot_btn_template
if bt is None:
    print("❌ 未加载模板")
    exit(1)

# 游戏相对坐标（扩大10px搜索）
rel_x1, rel_y1, rel_x2, rel_y2 = 598, 512, 674, 532
margin = 10
sx1 = gw["left"] + max(0, rel_x1 - margin)
sy1 = gw["top"] + max(0, rel_y1 - margin)
sx2 = gw["left"] + min(gw["width"], rel_x2 + margin)
sy2 = gw["top"] + min(gw["height"], rel_y2 + margin)

# 截图（更大的区域）
with mss.mss() as sct:
    mon = {"top": sy1, "left": sx1, "width": sx2-sx1, "height": sy2-sy1}
    img = np.array(sct.grab(mon))[:, :, :3]

# 模板匹配
gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
gray_tpl = cv2.cvtColor(bt, cv2.COLOR_BGR2GRAY)

# 确保模板 <= 搜索图
if gray_tpl.shape[0] <= gray_img.shape[0] and gray_tpl.shape[1] <= gray_img.shape[1]:
    result = cv2.matchTemplate(gray_img, gray_tpl, cv2.TM_CCOEFF_NORMED)
    _, conf, _, max_loc = cv2.minMaxLoc(result)
    
    # 在搜索图上标出最佳匹配位置
    h, w = gray_tpl.shape
    result_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    cv2.rectangle(result_img, max_loc, (max_loc[0]+w, max_loc[1]+h), (0, 0, 255), 2)
    cv2.putText(result_img, f"Best match", (max_loc[0], max_loc[1]-5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
else:
    conf = 0.0
    result_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

# 保存对比图
current_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
tpl_rgb = cv2.cvtColor(bt, cv2.COLOR_BGR2RGB)

scale = 3
cur_big = cv2.resize(current_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
tpl_big = cv2.resize(tpl_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

# 三张图拼接：搜索图+匹配结果 | 模板
result_big = cv2.resize(result_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
# 统一高度
max_h = max(result_big.shape[0], tpl_big.shape[0])
r_canvas = np.zeros((max_h, result_big.shape[1], 3), dtype=np.uint8)
r_canvas[:result_big.shape[0]] = result_big
t_canvas = np.zeros((max_h, tpl_big.shape[1], 3), dtype=np.uint8)
t_canvas[:tpl_big.shape[0]] = tpl_big
compare = np.hstack([r_canvas, t_canvas])
h_c, w_c = compare.shape[:2]
cv2.putText(compare, f"Search + Match Result ({img.shape[1]}x{img.shape[0]})", (5, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
cv2.putText(compare, f"Template ({bt.shape[1]}x{bt.shape[0]})", (result_big.shape[1]+5, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
cv2.putText(compare, f"Match: {conf:.4f}", (5, h_c-5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1)

os.makedirs("detect_debug", exist_ok=True)
cv2.imwrite("detect_debug/btn_compare_debug.png", compare)
print(f"✅ 对比图保存: detect_debug/btn_compare_debug.png")
print(f"   置信度: {conf:.4f}")
print(f"   搜索区域(屏幕): ({sx1},{sy1})-({sx2},{sy2})")
print(f"   搜索区域(相对): ({rel_x1-margin},{rel_y1-margin})-({rel_x2+margin},{rel_y2+margin})")
