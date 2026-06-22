"""
HSV检测调试脚本 - 帮助排查物品检测问题
"""
import os
import sys
import cv2
import numpy as np
import mss

sys.path.insert(0, '.')
from window_locator import locator
from hsv_detector import detect_items, apply_hsv_mask

def main():
    print("=" * 60)
    print("HSV检测调试工具")
    print("=" * 60)
    
    # 1. 检测游戏窗口
    if not locator.detect("china"):
        print("❌ 未检测到游戏窗口")
        return
    
    win = locator.window
    print(f"游戏窗口: {win['width']}x{win['height']} @ ({win['left']}, {win['top']})")
    
    # 2. 读取当前HSV配置
    import json
    hsv_config = {
        "h_min": 133,
        "h_max": 138,
        "s_min": 131,
        "s_max": 152,
        "v_min": 137,
        "v_max": 246
    }
    if os.path.exists("auto_buy_config.json"):
        with open("auto_buy_config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
            if "hsv" in config:
                hsv_config.update(config["hsv"])
    
    print(f"\n当前HSV配置:")
    print(f"  H: {hsv_config['h_min']} - {hsv_config['h_max']}")
    print(f"  S: {hsv_config['s_min']} - {hsv_config['s_max']}")
    print(f"  V: {hsv_config['v_min']} - {hsv_config['v_max']}")
    
    # 3. 截取检测区域
    rel_left, rel_top, rel_right, rel_bottom = 80, 285, 857, 1057
    screen_left = win['left'] + rel_left
    screen_top = win['top'] + rel_top
    screen_width = rel_right - rel_left
    screen_height = rel_bottom - rel_top
    
    print(f"\n检测区域:")
    print(f"  相对窗口: ({rel_left}, {rel_top}) - ({rel_right}, {rel_bottom})")
    print(f"  屏幕坐标: ({screen_left}, {screen_top})")
    print(f"  尺寸: {screen_width}x{screen_height}")
    
    # 截图
    with mss.mss() as sct:
        monitor = {
            "top": screen_top,
            "left": screen_left,
            "width": screen_width,
            "height": screen_height
        }
        screenshot = sct.grab(monitor)
        img = np.array(screenshot)[:, :, :3]  # BGRA -> BGR
    
    # 保存原始截图
    os.makedirs("detect_debug", exist_ok=True)
    cv2.imwrite("detect_debug/raw_screenshot.png", img)
    print("\n✅ 原始截图已保存: detect_debug/raw_screenshot.png")
    
    # 4. 应用HSV过滤
    mask = apply_hsv_mask(img, hsv_config)
    cv2.imwrite("detect_debug/hsv_mask.png", mask)
    print("✅ HSV掩码已保存: detect_debug/hsv_mask.png")
    
    # 5. 检测物品
    items, mask = detect_items(img, hsv_config, min_area=500, input_format="BGR")
    print(f"\n检测结果: 找到 {len(items)} 个物品")
    
    # 6. 绘制检测结果
    result_img = img.copy()
    for i, item in enumerate(items):
        x, y, w, h = item["bbox"]
        cv2.rectangle(result_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(result_img, f"#{i+1}", (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    cv2.imwrite("detect_debug/detection_result.png", result_img)
    print("✅ 检测结果已保存: detect_debug/detection_result.png")
    
    # 7. 显示HSV范围建议
    print("\n" + "=" * 60)
    print("HSV范围调整建议:")
    print("=" * 60)
    print("如果检测不到物品，尝试放宽HSV范围:")
    print(f"  H: {hsv_config['h_min']-10} - {hsv_config['h_max']+10}")
    print(f"  S: {max(0, hsv_config['s_min']-30)} - {min(255, hsv_config['s_max']+30)}")
    print(f"  V: {max(0, hsv_config['v_min']-30)} - {min(255, hsv_config['v_max']+30)}")
    print("\n如果检测到太多噪音，尝试缩小范围或增大 min_area")
    print("\n建议步骤:")
    print("1. 打开 detect_debug/raw_screenshot.png 确认截图包含物品")
    print("2. 打开 detect_debug/hsv_mask.png 查看HSV过滤效果")
    print("3. 如果mask中看不到物品，调整HSV配置")
    print("4. 如果mask中有物品但检测不到，减小min_area")

if __name__ == "__main__":
    main()
