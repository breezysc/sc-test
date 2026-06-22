"""调试脚本：截取截图按钮区域，分析置信度"""
import os
import sys
import cv2
import numpy as np
import mss
import traceback
import auto_buy_new

DEBUG_DIR = "detect_debug"
os.makedirs(DEBUG_DIR, exist_ok=True)

# 截图按钮游戏相对坐标
BTN_REL_REGION = (598, 512, 674, 532)

def debug_screenshot_button():
    """截取按钮区域并分析置信度"""
    
    # 检测游戏窗口
    result = auto_buy_new.detect_game_window("china")
    if not result or auto_buy_new.game_window is None:
        print("❌ 未检测到游戏窗口")
        return
    gw = auto_buy_new.game_window
    print(f"✅ 游戏窗口: ({gw['left']}, {gw['top']}) {gw['width']}x{gw['height']}")
    
    rel_x1, rel_y1, rel_x2, rel_y2 = BTN_REL_REGION
    screen_x1 = gw["left"] + rel_x1
    screen_y1 = gw["top"] + rel_y1
    screen_x2 = gw["left"] + rel_x2
    screen_y2 = gw["top"] + rel_y2
    width = screen_x2 - screen_x1
    height = screen_y2 - screen_y1
    
    print(f"=" * 60)
    print(f"截图按钮区域调试")
    print(f"=" * 60)
    print(f"游戏相对坐标: ({rel_x1}, {rel_y1}) -> ({rel_x2}, {rel_y2})")
    print(f"屏幕绝对坐标: ({screen_x1}, {screen_y1}) -> ({screen_x2}, {screen_y2})")
    print(f"按钮大小: {width}x{height}")
    print()
    
    # 截取按钮区域
    with mss.mss() as sct:
        monitor = {
            "top": screen_y1,
            "left": screen_x1,
            "width": width,
            "height": height
        }
        screenshot = sct.grab(monitor)
        btn_img = np.array(screenshot)[:, :, :3]
    
    if btn_img.size == 0:
        print("❌ 截图为空！")
        return
    
    # 保存原始截图
    cv2.imwrite(f"{DEBUG_DIR}/btn_raw.png", cv2.cvtColor(btn_img, cv2.COLOR_BGR2RGB))
    print(f"✅ 原始截图已保存: {DEBUG_DIR}/btn_raw.png")
    
    # 转换为灰度
    gray_img = cv2.cvtColor(btn_img, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(f"{DEBUG_DIR}/btn_gray.png", gray_img)
    print(f"✅ 灰度图已保存: {DEBUG_DIR}/btn_gray.png")
    
    # ========== 计算各项指标 ==========
    
    # 1. 非零像素比例
    non_zero_ratio = np.count_nonzero(gray_img) / gray_img.size
    print(f"\n📊 指标分析:")
    print(f"  非零像素比例: {non_zero_ratio:.4f}")
    
    # 2. 平均亮度
    mean_brightness = np.mean(gray_img) / 255.0
    print(f"  平均亮度: {mean_brightness:.4f}")
    
    # 3. Canny边缘检测
    for edge_thresh in [(30, 100), (50, 150), (80, 200)]:
        t1, t2 = edge_thresh
        edges = cv2.Canny(gray_img, t1, t2)
        edge_ratio = np.count_nonzero(edges) / edges.size
        print(f"  Canny({t1},{t2}) 边缘比例: {edge_ratio:.4f}")
        
        # 保存边缘检测结果
        cv2.imwrite(f"{DEBUG_DIR}/btn_edges_{t1}_{t2}.png", edges)
    
    # 4. 使用默认阈值(50,150)计算综合置信度
    edges = cv2.Canny(gray_img, 50, 150)
    edge_ratio = np.count_nonzero(edges) / edges.size
    combined_confidence = edge_ratio * 0.7 + non_zero_ratio * 0.3
    
    print(f"\n📊 综合置信度:")
    print(f"  综合置信度 = 边缘比例{edge_ratio:.4f}×0.7 + 非零比例{non_zero_ratio:.4f}×0.3")
    print(f"  = {combined_confidence:.4f}")
    print()
    
    # 5. 生成对比图: 原图 + 灰度 + 边缘检测
    h, w = gray_img.shape
    edges_colored = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    
    # 将按钮区域放大显示以便观察
    scale = 4
    btn_big = cv2.resize(btn_img, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    gray_big = cv2.resize(gray_img, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    gray_big_colored = cv2.cvtColor(gray_big, cv2.COLOR_GRAY2BGR)
    edges_big = cv2.resize(edges_colored, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    
    # 水平拼接: 原图 | 灰度 | 边缘
    comparison = np.hstack([btn_big, gray_big_colored, edges_big])
    
    # 添加标注文字
    cv2.putText(comparison, f"Raw", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(comparison, f"Gray", (w*scale + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(comparison, f"Edges(Canny)", (w*scale*2 + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    
    # 添加置信度信息
    info_text = f"Confidence: {combined_confidence:.4f}  |  Edge: {edge_ratio:.4f}  |  NonZero: {non_zero_ratio:.4f}"
    cv2.putText(comparison, info_text, (10, h*scale - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    
    compare_path = f"{DEBUG_DIR}/btn_comparison.png"
    cv2.imwrite(compare_path, comparison)
    print(f"✅ 对比图已保存: {compare_path}")
    print(f"   (原图 | 灰度图 | 边缘检测)")
    
    # 也保存放大后的原图
    cv2.imwrite(f"{DEBUG_DIR}/btn_raw_4x.png", btn_big)
    
    print(f"\n{'='*60}")
    print(f"判断: 综合置信度 {'>= 0.8 ✅' if combined_confidence >= 0.8 else '< 0.8 ❌'}")
    
    # 给出建议
    if combined_confidence < 0.8:
        print(f"\n💡 置信度不足建议:")
        print(f"  1. 检查按钮区域是否确实包含截图按钮")
        print(f"  2. 按钮可能有透明背景，边缘不够明显")
        print(f"  3. 尝试调整Canny阈值或改用其他检测方法")
        print(f"  4. 检查按钮区域坐标是否准确")
    
    print(f"\n打开 {compare_path} 查看对比分析")

if __name__ == "__main__":
    try:
        debug_screenshot_button()
    except Exception as e:
        print(f"❌ 错误: {e}")
        traceback.print_exc()
    
    input("\n按回车键退出...")
