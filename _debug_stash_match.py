"""调试脚本：仓库模板匹配对比分析"""
import os
import sys
import cv2
import numpy as np
import mss
import traceback
import json

DEBUG_DIR = "detect_debug"
os.makedirs(DEBUG_DIR, exist_ok=True)

# 加载配置和模板
def load_templates():
    config_path = "auto_buy_config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if "stash_template" in config:
            template_data = config["stash_template"]
            template_img = np.array(template_data, dtype=np.uint8)
            print(f"✅ 仓库模板加载成功: {template_img.shape[1]}x{template_img.shape[0]}")
            return template_img
    print("❌ 仓库模板加载失败")
    return None

def debug_stash_match():
    """调试仓库模板匹配"""
    print("=" * 60)
    print("仓库模板匹配调试")
    print("=" * 60)
    
    # 使用 auto_buy_new 检测窗口
    import auto_buy_new
    result = auto_buy_new.detect_game_window("china")
    if not result or auto_buy_new.game_window is None:
        print("❌ 未检测到游戏窗口")
        return
    
    game_window = auto_buy_new.game_window
    print(f"✅ 游戏窗口: ({game_window['left']}, {game_window['top']}) {game_window['width']}x{game_window['height']}")
    
    # 加载模板
    template_img = load_templates()
    if template_img is None:
        return
    
    # 截取游戏窗口
    with mss.mss() as sct:
        monitor = {
            "top": game_window["top"],
            "left": game_window["left"],
            "width": game_window["width"],
            "height": game_window["height"]
        }
        search_img = sct.grab(monitor)
        search_img = np.array(search_img)[:, :, :3]
    
    print(f"✅ 游戏截图: {search_img.shape[1]}x{search_img.shape[0]}")
    
    # 保存原始截图
    cv2.imwrite(f"{DEBUG_DIR}/stash_search_raw.png", cv2.cvtColor(search_img, cv2.COLOR_BGR2RGB))
    
    # 模板匹配
    gray_search = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
    gray_template = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
    
    result = cv2.matchTemplate(gray_search, gray_template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    
    print(f"\n📊 匹配结果:")
    print(f"  最高匹配度: {max_val:.4f}")
    print(f"  最低匹配度: {min_val:.4f}")
    print(f"  最佳位置: {max_loc}")
    print(f"  阈值: 0.5")
    print(f"  判断: {'✅ 匹配成功' if max_val >= 0.5 else '❌ 匹配失败'}")
    
    # 在截图中标出匹配位置
    h, w = gray_template.shape
    result_img = search_img.copy()
    
    # 画出最佳匹配位置
    cv2.rectangle(result_img, max_loc, (max_loc[0] + w, max_loc[1] + h), (0, 0, 255), 3)
    cv2.putText(result_img, f"Best: {max_val:.3f}", 
                (max_loc[0], max_loc[1] - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    # 调整模板大小以便显示
    scale = 4
    template_big = cv2.resize(template_img, (w*scale, h*scale), interpolation=cv2.INTER_NEAREST)
    
    # 保存结果
    cv2.imwrite(f"{DEBUG_DIR}/stash_match_result.png", cv2.cvtColor(result_img, cv2.COLOR_BGR2RGB))
    cv2.imwrite(f"{DEBUG_DIR}/stash_template_4x.png", cv2.cvtColor(template_big, cv2.COLOR_BGR2RGB))
    
    # 创建对比图：原图(缩小) | 模板(放大)
    scale_down = 0.3
    h_small = int(game_window["height"] * scale_down)
    w_small = int(game_window["width"] * scale_down)
    search_small = cv2.resize(search_img, (w_small, h_small))
    
    # 标注文字
    cv2.putText(search_small, "Game Screen", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(template_big, f"Stash Template ({w}x{h})", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # 水平拼接
    h1, w1 = search_small.shape[:2]
    h2, w2 = template_big.shape[:2]
    canvas_h = max(h1, h2)
    
    canvas1 = np.zeros((canvas_h, w1, 3), dtype=np.uint8)
    canvas1[:h1] = search_small
    canvas2 = np.zeros((canvas_h, w2, 3), dtype=np.uint8)
    canvas2[:h2] = template_big
    
    comparison = np.hstack([canvas1, canvas2])
    
    # 添加匹配信息
    info = f"Match: {max_val:.4f}  |  Threshold: 0.5  |  {'OK' if max_val >= 0.5 else 'TOO LOW'}"
    cv2.putText(comparison, info, (10, canvas_h - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    
    cv2.imwrite(f"{DEBUG_DIR}/stash_comparison.png", comparison)
    
    print(f"\n✅ 已保存调试文件:")
    print(f"  1. {DEBUG_DIR}/stash_search_raw.png      - 游戏窗口完整截图")
    print(f"  2. {DEBUG_DIR}/stash_template_4x.png      - 仓库模板(放大4x)")
    print(f"  3. {DEBUG_DIR}/stash_match_result.png     - 匹配结果(红框=最佳匹配)")
    print(f"  4. {DEBUG_DIR}/stash_comparison.png       - 对比图")
    print(f"\n💡 请查看对比图确认:")
    print(f"  1. 模板中的仓库图标是否出现在当前游戏画面中")
    print(f"  2. 如果不在 -> 当前不在仓库NPC附近，无需担心")
    print(f"  3. 如果在但匹配度低 -> 模板可能过时，需重新保存")

if __name__ == "__main__":
    try:
        debug_stash_match()
    except Exception as e:
        print(f"❌ 错误: {e}")
        traceback.print_exc()
    input("\n按回车键退出...")
