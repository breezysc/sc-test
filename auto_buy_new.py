"""
AutoBuy 自动购买工具 - 超时存仓版
功能：购买1次 → F5回城 → 持续检测 → 5分钟无动作触发存仓
使用模板匹配定位仓库位置
支持测试模式：直接执行存仓流程
"""

import time
import json
import cv2
import numpy as np
import mss
import pyautogui
import os
import psutil
import ctypes
import sys
import argparse
import threading
from ctypes import wintypes

from hsv_detector import detect_items

# 禁用 PyAutoGUI 安全保护（鼠标移到屏幕角落不会触发异常）
pyautogui.FAILSAFE = False
# 设置操作间隔为0，加快执行速度
pyautogui.PAUSE = 0


def log(message):
    """带时间戳的日志输出"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


# 日志聚合管理
class LogAggregator:
    """日志聚合器：避免重复日志连续输出"""
    def __init__(self):
        self.last_messages = {}  # {message_key: last_output_time}
        self.agg_counts = {}     # {message_key: count}
        self.throttle_interval = 5.0  # 同一消息聚合间隔（秒）
    
    def log_throttled(self, message, key=None, force=False):
        """节流日志输出
        
        Args:
            message: 日志内容
            key: 聚合键（默认使用message）
            force: 强制输出（忽略节流）
        """
        if key is None:
            key = message
        
        current_time = time.time()
        
        if force or key not in self.last_messages or \
           (current_time - self.last_messages[key]) >= self.throttle_interval:
            
            # 输出聚合信息
            if key in self.agg_counts and self.agg_counts[key] > 0:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message} (已聚合 {self.agg_counts[key]} 次)")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
            
            self.last_messages[key] = current_time
            self.agg_counts[key] = 0
        else:
            # 增加计数
            self.agg_counts[key] = self.agg_counts.get(key, 0) + 1
    
    def log_critical(self, message):
        """关键日志：始终输出（如存仓成功）"""
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")


# 创建全局日志聚合器
log_agg = LogAggregator()


CONFIG_PATH = "auto_buy_config.json"
GOOD_CONFIG_PATH = "good.json"
HASH_CONFIG_PATH = "inventory_hash_config.json"
INVENTORY_CONFIG_PATH = "inventory_config.json"

# 全局变量
game_window = None  # {"left": x, "top": y, "width": w, "height": h}
template_img = None  # 仓库模板图片
empty_cell_template = None  # 空格子参考模板（cc.png）
EMPTY_CELL_THRESHOLD = 0.85  # 空格子置信度阈值（降低识别敏感度）

# 优先级状态管理
class ActionState:
    """动作状态管理 - 实现优先级控制"""
    PURCHASE_ACTIVE = "purchase_active"      # 购买动作进行中（最高优先级）
    PURCHASE_PENDING = "purchase_pending"    # 购买动作待执行
    STORAGE_ACTIVE = "storage_active"        # 存仓动作进行中
    STORAGE_PENDING = "storage_pending"      # 存仓动作待执行
    IDLE = "idle"                            # 空闲状态

# 当前动作状态（全局状态机）
current_action_state = ActionState.IDLE
purchase_lock = threading.Lock()  # 购买动作锁

# 优先级定义（数值越小优先级越高）
ACTION_PRIORITY = {
    ActionState.PURCHASE_ACTIVE: 0,    # 最高优先级
    ActionState.PURCHASE_PENDING: 1,
    ActionState.STORAGE_ACTIVE: 2,
    ActionState.STORAGE_PENDING: 3,
    ActionState.IDLE: 4,               # 最低优先级
}


def _find_window(window_name):
    """通过窗口名查找窗口，返回窗口矩形"""
    user32 = ctypes.windll.user32
    
    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p
    )
    
    windows = []
    
    def enum_callback(hwnd, lParam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        if window_name.lower() in title.lower():
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            windows.append({
                "hwnd": hwnd,
                "title": title,
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top
            })
        return True
    
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return windows


def detect_game_window(server="global"):
    """识别游戏窗口 - 优先搜索国服，其次国际服，排除浏览器窗口"""
    global game_window
    
    # 需要排除的浏览器关键词（防止把浏览器标签页误识别为游戏窗口）
    browser_keywords = ["chrome", "firefox", "edge", "iexplore", "safari", "opera", "brave", "浏览器"]
    
    # 同时搜索国服和国际服
    all_windows = []
    search_terms = []
    
    if server == "china":
        search_terms = ["流放之路"]
    elif server == "global":
        search_terms = ["Path of Exile 2", "Path of Exile"]
    else:
        search_terms = ["流放之路", "Path of Exile 2", "Path of Exile"]
    
    for term in search_terms:
        found = _find_window(term)
        for w in found:
            all_windows.append(w)
    
    # 排除浏览器窗口（关键：如果排除后为空，返回 False，让主程序尝试其他服务器）
    game_windows = [w for w in all_windows if not any(bk in w["title"].lower() for bk in browser_keywords)]
    
    if not game_windows:
        log(f"[窗口] 未找到匹配的游戏窗口（搜索了: {', '.join(search_terms)}，排除了浏览器窗口）")
        return False
    
    # 如果有多个匹配，优先选非浏览器且标题更短的（游戏窗口标题通常更简洁）
    if len(game_windows) == 1:
        game_window = game_windows[0]
    else:
        # 优先选非浏览器窗口，再按标题长度排序（游戏窗口标题更简洁）
        game_windows.sort(key=lambda w: len(w["title"]))
        game_window = game_windows[0]
        log(f"[窗口] 找到 {len(game_windows)} 个候选窗口，选择最可能的游戏窗口")
    
    log(f"[窗口] 已识别: {game_window['title']} 位置:({game_window['left']},{game_window['top']}) 大小:{game_window['width']}x{game_window['height']}")
    return True


def load_template():
    """从配置文件加载仓库模板，并加载空格子模板"""
    global template_img, empty_cell_template
    
    # 从配置文件加载仓库模板
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if "stash_template" in config:
                template_data = config["stash_template"]
                template_img = np.array(template_data, dtype=np.uint8)
                log(f"[模板] 已加载仓库模板，大小: {template_img.shape[1]}x{template_img.shape[0]}")
        except Exception as e:
            log(f"[模板] 加载失败: {e}")
    
    # 加载空格子模板（cc.png）
    if os.path.exists("cc.png"):
        empty_cell_template = cv2.imread("cc.png")
        if empty_cell_template is not None:
            log(f"[模板] 已加载空格子模板，大小: {empty_cell_template.shape[1]}x{empty_cell_template.shape[0]}")
        else:
            log("[警告] 未能加载空格子模板 cc.png")
    else:
        log("[警告] 未找到空格子模板 cc.png")
    
    return template_img is not None


def check_cell_confidence(cell_region, cell_idx=0):
    """检查单个格子的置信度（是否为空格子）
    
    Args:
        cell_region: 格子区域 [x1, y1, x2, y2]
        cell_idx: 格子序号（用于唯一标识）
    
    Returns:
        confidence: 置信度（0-1），高于 EMPTY_CELL_THRESHOLD 认为是空格子
    """
    global empty_cell_template, game_window
    
    if empty_cell_template is None:
        # 如果没有空格子模板，默认认为是空格子
        return 1.0
    
    if game_window is None:
        return 0.0
    
    try:
        x1, y1, x2, y2 = cell_region
        
        # cells_map 中的坐标已经是屏幕绝对坐标，不需要再加游戏窗口偏移
        # 截取格子区域（直接使用绝对坐标）
        with mss.mss() as sct:
            monitor = {
                "top": int(y1),
                "left": int(x1),
                "width": int(x2 - x1),
                "height": int(y2 - y1)
            }
            screenshot = sct.grab(monitor)
            cell_img = np.array(screenshot)[:, :, :3]
        
        # 检查图像质量
        if cell_img.size == 0:
            log(f"[格子置信度] 格子{cell_idx}截图为空")
            return 0.0
        
        # 计算与空格子模板的匹配度
        confidence = _get_template_confidence(cell_img, empty_cell_template)
        
        # 置信度验证：确保在合理范围内
        if confidence < 0.0 or confidence > 1.0:
            log(f"[格子置信度] 格子{cell_idx}异常值: {confidence}, 修正为0.0")
            confidence = 0.0
        
        # 保存调试图像（覆盖模式）
        debug_save_path = "stash_debug"
        if not os.path.exists(debug_save_path):
            os.makedirs(debug_save_path)
        
        # 使用格子序号作为文件名，确保唯一性（1-60）
        cell_index = f"{cell_idx:02d}"
        
        # 计算格子中心坐标（用于日志和验证）
        center_x = int((x1 + x2) // 2)
        center_y = int((y1 + y2) // 2)
        
        # 判断是否为有物品的格子（置信度低于阈值）
        is_occupied = confidence < EMPTY_CELL_THRESHOLD
        
        # 保存截图（覆盖模式）
        # 1. 所有格子都保存基础截图（便于对比）
        base_file = os.path.join(debug_save_path, f"cell_{cell_index}.png")
        cv2.imwrite(base_file, cell_img)
        
        # 2. 有物品的格子额外保存标注版本（置信度 < 阈值）
        if is_occupied:
            # 在图像上标注置信度和坐标
            annotated_img = cell_img.copy()
            text = f"Conf: {confidence:.2f} (ITEM)"
            text2 = f"({center_x}, {center_y})"
            cv2.putText(annotated_img, text, (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.putText(annotated_img, text2, (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            annotated_file = os.path.join(debug_save_path, f"cell_{cell_index}_item.png")
            cv2.imwrite(annotated_file, annotated_img)
        
        # 3. 边界格子（置信度接近阈值）保存特殊标注
        if abs(confidence - EMPTY_CELL_THRESHOLD) < 0.1:
            borderline_img = cell_img.copy()
            text = f"Conf: {confidence:.2f} (BORDER)"
            cv2.putText(borderline_img, text, (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
            borderline_file = os.path.join(debug_save_path, f"cell_{cell_index}_border.png")
            cv2.imwrite(borderline_file, borderline_img)
        
        return confidence
        
    except Exception as e:
        log(f"[格子置信度] 格子{cell_idx}检测失败: {e}")
        return 0.0


def perform_stash_with_confidence(stash_cells):
    """基于置信度的智能存仓操作
    
    流程：
    1. 遍历每个格子
    2. 检查格子置信度（是否为空格子）
    3. 如果置信度高（空格子），跳过
    4. 如果置信度低（有物品），执行存仓
    """
    global game_window, EMPTY_CELL_THRESHOLD
    
    if not stash_cells:
        log("[存仓] 未配置仓库格子，跳过存仓")
        return
    
    num_cells = len(stash_cells)
    log(f"[存仓] 开始智能存仓，共 {num_cells} 个格子")
    log(f"[存仓] 空格子阈值: {EMPTY_CELL_THRESHOLD:.2f}（高于此值跳过）")
    
    # 保存原始设置
    original_pause = pyautogui.PAUSE
    original_min_duration = pyautogui.MINIMUM_DURATION
    original_min_sleep = pyautogui.MINIMUM_SLEEP
    
    # 关闭所有延迟
    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    
    start_time = time.time()
    stashed_count = 0
    skipped_count = 0
    
    try:
        pyautogui.keyDown('ctrl')
        time.sleep(0.05)
        
        for idx, cell in enumerate(stash_cells, 1):
            # 支持两种格式
            if isinstance(cell, list) and len(cell) == 2:
                # 格式1: cells_map [[[x1,y1],[x2,y2]], ...]
                p1, p2 = cell
                if isinstance(p1, list) and len(p1) >= 2 and isinstance(p2, list) and len(p2) >= 2:
                    x1, y1 = p1[0], p1[1]
                    x2, y2 = p2[0], p2[1]
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    cell_region = [x1, y1, x2, y2]
            elif isinstance(cell, dict) and "region" in cell:
                # 格式2: cells [{"region":[x1,y1,x2,y2]}, ...]
                region = cell.get("region", [])
                if len(region) >= 4:
                    x1, y1, x2, y2 = region
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    cell_region = region
            else:
                log(f"[存仓] 跳过无效格子 {idx}")
                continue
            
            # 检查格子置信度（传入格子序号确保截图文件名唯一）
            confidence = check_cell_confidence(cell_region, idx)
            
            # cells_map 中的坐标已经是屏幕绝对坐标，cx/cy 直接就是屏幕坐标
            screen_cx = cx
            screen_cy = cy
            
            # 调试：仅输出存仓相关的关键日志
            if confidence < EMPTY_CELL_THRESHOLD:
                # 识别到存仓的物品 - 关键日志，始终输出
                stashed_count += 1
                pyautogui.click(screen_cx, screen_cy)
                log_agg.log_critical(f"[存仓] 识别到存仓的物品 - 格子 {idx}/{num_cells} - 置信度: {confidence:.3f} - 坐标: ({screen_cx}, {screen_cy})")
            else:
                # 跳过空格子 - 不输出日志（避免冗余）
                skipped_count += 1
                # 日志已禁用：高频空格子日志会污染输出
                # log_agg.log_throttled(
                #     f"[存仓] 跳过空格子 {idx} - 置信度: {confidence:.3f}",
                #     key=f"skip_cell_{idx}"
                # )
            
            # 每30毫秒处理一个格子
            time.sleep(0.03)
        
        pyautogui.keyUp('ctrl')
        
        elapsed = time.time() - start_time
        log(f"[存仓] ✓ 存仓完成！")
        log(f"[存仓] 总格子: {num_cells} | 存仓: {stashed_count} | 跳过: {skipped_count}")
        log(f"[存仓] 耗时: {elapsed:.2f}秒 | 速度: {num_cells/elapsed:.1f}格子/秒")
        
    except Exception as e:
        log(f"[存仓] 出错: {e}")
        try:
            pyautogui.keyUp('ctrl')
        except:
            pass
    finally:
        pyautogui.PAUSE = original_pause
        pyautogui.MINIMUM_DURATION = original_min_duration
        pyautogui.MINIMUM_SLEEP = original_min_sleep


def match_stash_template():
    """在游戏窗口内使用模板匹配找到仓库位置"""
    global game_window, template_img
    
    if game_window is None:
        log("[模板匹配] 错误: 未识别游戏窗口")
        return None
    
    if template_img is None:
        log("[模板匹配] 错误: 未加载仓库模板")
        return None
    
    try:
        win = game_window
        template_w, template_h = template_img.shape[1], template_img.shape[0]
        
        # 截取游戏窗口区域
        with mss.mss() as sct:
            monitor = {
                "top": win["top"],
                "left": win["left"],
                "width": win["width"],
                "height": win["height"]
            }
            search_img = sct.grab(monitor)
            search_img = np.array(search_img)[:, :, :3]
        
        # 模板匹配
        gray_template = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
        gray_search = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
        
        result = cv2.matchTemplate(gray_search, gray_template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        log(f"[模板匹配] 匹配度: {max_val:.3f}, 阈值: 0.5")
        
        if max_val >= 0.5:
            center_x = win["left"] + max_loc[0] + template_w // 2
            center_y = win["top"] + max_loc[1] + template_h // 2
            log(f"[模板匹配] 找到匹配！坐标: ({center_x}, {center_y})")
            return (center_x, center_y)
        else:
            log(f"[模板匹配] 匹配度太低: {max_val:.3f}")
            return None
            
    except Exception as e:
        log(f"[模板匹配] 失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def _get_template_confidence(search_img, template_img):
    """计算模板匹配置信度（优化版）
    
    使用多种匹配方法和多尺度匹配来提高置信度准确性
    """
    try:
        template_h, template_w = template_img.shape[:2]
        screen_h, screen_w = search_img.shape[:2]
        
        # 尺寸检查
        if screen_h < template_h or screen_w < template_w:
            return 0.0
        
        # 图像预处理：转为灰度并进行高斯模糊
        gray_template = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
        gray_search = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
        
        # 高斯模糊减少噪声
        gray_template = cv2.GaussianBlur(gray_template, (3, 3), 0)
        gray_search = cv2.GaussianBlur(gray_search, (3, 3), 0)
        
        # 使用多种匹配方法取最佳值
        methods = [
            cv2.TM_CCOEFF_NORMED,
            cv2.TM_CCORR_NORMED,
            cv2.TM_SQDIFF_NORMED  # 这个方法是越小越好
        ]
        
        max_confidence = 0.0
        
        for method in methods:
            try:
                result = cv2.matchTemplate(gray_search, gray_template, method)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                
                # TM_SQDIFF_NORMED 需要取反（越小越好）
                if method == cv2.TM_SQDIFF_NORMED:
                    val = 1.0 - max_val
                else:
                    val = max_val
                
                if val > max_confidence:
                    max_confidence = val
            except:
                continue
        
        return max_confidence
        
    except Exception as e:
        log(f"[置信度计算] 错误: {e}")
        return 0.0


def _check_stash_open():
    """检测仓库是否打开（返回：(仓库置信度, 背包置信度)）"""
    global game_window
    
    if game_window is None:
        return (0.0, 0.0)
    
    try:
        with mss.mss() as sct:
            monitor = {
                "top": game_window["top"],
                "left": game_window["left"],
                "width": game_window["width"],
                "height": game_window["height"]
            }
            screenshot = sct.grab(monitor)
            screen_img = np.array(screenshot)[:, :, :3]
        
        # 读取配置中的置信度检测区域
        stash_conf_region = None
        inventory_conf_region = None
        stash_conf_template = None
        inventory_conf_template = None
        
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if "stash_confidence_region" in config:
                        stash_conf_region = config["stash_confidence_region"]
                    if "inventory_confidence_region" in config:
                        inventory_conf_region = config["inventory_confidence_region"]
                    if "stash_confidence_template" in config:
                        stash_conf_template = np.array(config["stash_confidence_template"], dtype=np.uint8)
                    if "inventory_confidence_template" in config:
                        inventory_conf_template = np.array(config["inventory_confidence_template"], dtype=np.uint8)
            except Exception as e:
                log(f"[置信度检测] 读取配置失败: {e}")
        
        # 仓库置信度
        if stash_conf_template is not None and stash_conf_region:
            sx1, sy1, sx2, sy2 = stash_conf_region
            current_region = screen_img[sy1:sy2, sx1:sx2].copy()
            stash_conf = _get_template_confidence(current_region, stash_conf_template)
        elif template_img is not None:
            stash_conf = _get_template_confidence(screen_img, template_img)
        else:
            stash_conf = 0.0
        
        # 背包置信度（HSV检测物品覆盖率）
        if inventory_conf_region:
            ix1, iy1, ix2, iy2 = inventory_conf_region
            current_inv_region = screen_img[iy1:iy2, ix1:ix2].copy()
            
            if inventory_conf_template is not None:
                inv_conf = _get_template_confidence(current_inv_region, inventory_conf_template)
            else:
                # 使用HSV检测
                hsv_cfg = load_config()["hsv_config"]
                items, _ = detect_items(current_inv_region, hsv_cfg, min_area=500, input_format="BGR")
                region_area = (ix2 - ix1) * (iy2 - iy1)
                item_area = sum(item["area"] for item in items)
                inv_conf = item_area / region_area if region_area > 0 else 0.0
        else:
            inv_conf = 0.0
        
        return (stash_conf, inv_conf)
    
    except Exception as e:
        log(f"[置信度检测] 错误: {e}")
        return (0.0, 0.0)


def click_stash_with_check():
    """点击仓库并检测是否成功打开"""
    global template_img
    
    STASH_OPEN_THRESHOLD = 0.8
    INVENTORY_FULL_THRESHOLD = 0.2
    
    # 1. 模板匹配找到仓库位置
    pos = match_stash_template()
    if not pos:
        log("[仓库] 未找到仓库位置")
        return False
    
    x, y = pos
    log(f"[仓库] 点击仓库位置: ({x}, {y})")
    
    # 2. 点击仓库
    pyautogui.moveTo(x, y, duration=0.1)
    time.sleep(0.3)
    pyautogui.click()
    time.sleep(1)
    pyautogui.click()
    
    # 3. 等待并检测仓库是否打开
    log("[仓库] 等待仓库打开...")
    max_wait = 20
    wait_count = 0
    
    while wait_count < max_wait:
        stash_conf, inv_conf = _check_stash_open()
        log(f"[仓库] 置信度检测 - 仓库: {stash_conf:.3f}, 背包: {inv_conf:.3f}")
        
        if stash_conf >= STASH_OPEN_THRESHOLD:
            log("[仓库] ✓ 仓库已打开")
            # 判断背包是否满
            if inv_conf < INVENTORY_FULL_THRESHOLD:
                log("[仓库] ✓ 背包已满，执行存仓")
                return True
            else:
                log("[仓库] 背包未满，跳过存仓")
                return False
        
        wait_count += 1
        time.sleep(1)
    
    log("[仓库] 等待超时，未检测到仓库打开")
    return False

def load_stash_detection_config():
    """加载仓库检测区域配置（来自 auto_buy_debug_tool.py 的"选择仓库检测区域"）
    
    Returns:
        dict: {
            "region": (x1, y1, x2, y2) 或 None,
            "template": np.ndarray 或 None,
            "threshold": float
        }
    """
    detection_config = {
        "region": None,
        "template": None,
        "threshold": 0.7  # 仓库检测置信度阈值（不低于0.7）
    }
    
    # 从配置文件加载
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 读取仓库检测区域（auto_buy_debug_tool.py 保存的字段）
            stash_det_region = config.get("stash_confidence_region")
            if stash_det_region and len(stash_det_region) == 4:
                detection_config["region"] = tuple(stash_det_region)
                log(f"[仓库检测] 已加载检测区域: {stash_det_region}")
            
            # 读取仓库检测模板
            stash_det_template = config.get("stash_confidence_template")
            if stash_det_template is not None:
                template = np.array(stash_det_template, dtype=np.uint8)
                if template.size > 0:
                    detection_config["template"] = template
                    log(f"[仓库检测] 已加载检测模板: {template.shape}")
            
            # 读取自定义阈值
            threshold = config.get("stash_confidence_threshold")
            if threshold is not None and threshold >= 0.7:
                detection_config["threshold"] = threshold
                
        except Exception as e:
            log(f"[仓库检测] 加载配置失败: {e}")
    
    return detection_config


def verify_stash_opened(detection_config, max_retry=10, retry_interval=0.5):
    """验证仓库是否已打开（通过检测区域特征识别）
    
    修复：使用 numpy 数组切片（相对坐标），与调试工具一致；
          缺少检测区域/模板时回退到基础模板匹配。
    
    Args:
        detection_config: 仓库检测配置
        max_retry: 最大重试次数
        retry_interval: 重试间隔（秒）
    
    Returns:
        tuple: (is_opened, confidence)
    """
    global game_window, template_img
    
    if game_window is None:
        log("[仓库检测] 错误: 未识别游戏窗口，无法验证")
        return False, 0.0
    
    threshold = detection_config["threshold"]
    use_detection_config = (
        detection_config["region"] is not None and
        detection_config["template"] is not None
    )
    
    if use_detection_config:
        x1, y1, x2, y2 = detection_config["region"]
        template = detection_config["template"]
        log(f"[仓库检测] 使用检测区域验证 - 区域:({x1},{y1})-({x2},{y2}) 阈值:{threshold}")
    else:
        if template_img is None:
            log("[仓库检测] ⚠ 警告: 缺少检测区域/模板且无基础模板 - 跳过验证直接执行存仓")
            return True, 1.0
        x1, y1, x2, y2 = 0, 0, game_window["width"], game_window["height"]
        template = template_img
        log(f"[仓库检测] 回退: 使用基础仓库模板匹配整个游戏窗口 阈值:{threshold}")
    
    for retry in range(max_retry):
        try:
            # 先截取游戏窗口，再用 numpy 数组切片取区域（相对坐标，与调试工具一致）
            with mss.mss() as sct:
                monitor = {
                    "top": game_window["top"],
                    "left": game_window["left"],
                    "width": game_window["width"],
                    "height": game_window["height"]
                }
                screenshot = sct.grab(monitor)
                screen_img = np.array(screenshot)[:, :, :3]
            
            current_region = screen_img[y1:y2, x1:x2].copy()
            confidence = _get_template_confidence(current_region, template)
            
            if confidence >= threshold:
                log(f"[仓库检测] ✓ 仓库已打开 - 置信度: {confidence:.3f} (阈值: {threshold})")
                return True, confidence
            else:
                if retry == 0 or retry == max_retry - 1:
                    log(f"[仓库检测] 等待仓库打开 - 置信度: {confidence:.3f} (阈值: {threshold}) 重试 {retry+1}/{max_retry}")
        except Exception as e:
            log(f"[仓库检测] 检测异常: {e}")
        
        time.sleep(retry_interval)
    
    log(f"[仓库检测] [警告] 存仓操作被阻止 - 未识别到有效仓库特征 (阈值: {threshold})")
    return False, 0.0


def load_config():
    hsv_config = {
        "h_min": 105,
        "h_max": 180,
        "s_min": 70,
        "s_max": 255,
        "v_min": 70,
        "v_max": 255
    }
    roi = {"LEFT": 80, "TOP": 285, "RIGHT": 857, "BOTTOM": 1057}
    stash_open_pos = [900, 380]  # 默认仓库位置
    
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if "hsv" in config:
                    hsv_config.update(config["hsv"])
                if "roi" in config and config["roi"]:
                    roi = config["roi"]
                if "stash_open_pos" in config and len(config["stash_open_pos"]) == 2:
                    stash_open_pos = config["stash_open_pos"]
        elif os.path.exists(GOOD_CONFIG_PATH):
            with open(GOOD_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                hsv_config.update(config)
    except Exception as e:
        pass
    
    return {
        "left": roi["LEFT"],
        "top": roi["TOP"],
        "right": roi["RIGHT"],
        "bottom": roi["BOTTOM"],
        "hsv_config": hsv_config,
        "stash_open_pos": stash_open_pos
    }


def load_stash_cells():
    """从 auto_buy_config.json 加载仓库格子（与 stash_debugger.py 共享配置）
    
    支持两种格式:
    1. cells_map: [[[x1,y1],[x2,y2]], ...]  - stash_debugger.py 保存的格式（60格）
    2. cells: [{"region":[x1,y1,x2,y2]}, ...]  - 旧格式兼容
    """
    
    # 优先从 auto_buy_config.json 读取 cells_map（stash_debugger.py 保存的格式）
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            cells_map = config.get("cells_map", [])
            if cells_map:
                result = []
                for cell in cells_map:
                    # 格式: [[x1,y1],[x2,y2]]
                    if isinstance(cell, list) and len(cell) == 2:
                        p1, p2 = cell
                        if isinstance(p1, list) and len(p1) >= 2 and isinstance(p2, list) and len(p2) >= 2:
                            x1, y1 = int(p1[0]), int(p1[1])
                            x2, y2 = int(p2[0]), int(p2[1])
                            result.append({"region": [x1, y1, x2, y2]})
                log(f"✓ 从 {CONFIG_PATH} 加载 {len(result)} 个仓库格子 (cells_map)")
                return result
        except Exception as e:
            log(f"从 {CONFIG_PATH} 加载 cells_map 失败: {e}")
    
    # 兼容格式1: inventory_config.json -> target_cells
    if os.path.exists(INVENTORY_CONFIG_PATH):
        try:
            with open(INVENTORY_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            cells = config.get("target_cells", [])
            if cells:
                result = []
                for cell in cells:
                    if "x1" in cell and "y1" in cell and "x2" in cell and "y2" in cell:
                        result.append({"region": [cell["x1"], cell["y1"], cell["x2"], cell["y2"]]})
                log(f"✓ 从 {INVENTORY_CONFIG_PATH} 加载 {len(result)} 个仓库格子 (target_cells)")
                return result
        except Exception as e:
            log(f"从 {INVENTORY_CONFIG_PATH} 加载失败: {e}")
    
    # 兼容格式2: inventory_hash_config.json -> cells
    if os.path.exists(HASH_CONFIG_PATH):
        try:
            with open(HASH_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            cells = config.get("cells", [])
            log(f"✓ 从 {HASH_CONFIG_PATH} 加载 {len(cells)} 个仓库格子")
            return cells
        except Exception as e:
            log(f"加载仓库配置失败: {e}")
    
    log(f"⚠ 未找到任何有效的仓库格子配置")
    return []


def detect_highlights(left, top, right, bottom, hsv_config):
    """检测高亮物品
    
    参数:
        left, top, right, bottom: 屏幕绝对坐标
    """
    with mss.mss() as sct:
        # 直接截取ROI区域（使用屏幕绝对坐标）
        monitor = {"top": int(top), "left": int(left), "width": int(right - left), "height": int(bottom - top)}
        
        # 调试：输出截图区域（使用节流）
        log_agg.log_throttled(
            f"[检测] 截图区域: top={top}, left={left}, width={right-left}, height={bottom-top}",
            key="detect_region"
        )
        
        screenshot = sct.grab(monitor)
        # mss返回BGRA格式，直接转换为BGR用于OpenCV处理
        img = np.array(screenshot)[:, :, :3]  # BGRA -> BGR
        
        # 保存调试截图
        debug_dir = "detect_debug"
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
        cv2.imwrite(os.path.join(debug_dir, "detect_region.png"), img)
        
        items, mask = detect_items(img, hsv_config, min_area=500, input_format="BGR")
        
        # 调试：输出检测结果（使用节流）
        if len(items) > 0:
            # 检测到物品 - 关键日志
            log_agg.log_critical(f"[检测] 识别到存仓的物品 - 检测到 {len(items)} 个物品")
        else:
            # 未检测到物品 - 节流输出
            log_agg.log_throttled(
                f"[检测] 检测到 0 个物品",
                key="detect_zero_items"
            )
        
        # 保存 mask 调试图
        cv2.imwrite(os.path.join(debug_dir, "detect_mask.png"), mask)
        
        return items


def dynamic_warehouse_recognition(duration=7.0):
    """动态仓库识别（受优先级控制）
    
    在指定时间内持续扫描仓库区域：
    1. 识别到高亮物品 → 立即购买（最高优先级）
    2. 识别到仓库位置 → 点击打开仓库（低优先级，可被购买中断）
    3. 每150ms扫描一次
    
    Args:
        duration: 识别持续时间（秒）
    
    Returns:
        recognized_items: 识别并处理的物品列表
    """
    global empty_cell_template, game_window, current_action_state
    
    recognized_items = []
    storage_attempted = False
    start_time = time.time()
    check_interval = 0.15  # 150ms 检测一次
    
    log(f"[动态识别] 启动 {duration}秒 仓库识别（最高优先级）")
    
    # 获取 ROI 配置
    if not os.path.exists(CONFIG_PATH):
        log("[动态识别] 配置文件不存在")
        return []
    
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        roi = config.get("roi", {})
        if not roi:
            log("[动态识别] 未配置 roi 区域")
            return []
        
        # ROI 坐标（屏幕绝对坐标）
        roi_left = int(roi.get("LEFT", 0))
        roi_top = int(roi.get("TOP", 0))
        roi_right = int(roi.get("RIGHT", 0))
        roi_bottom = int(roi.get("BOTTOM", 0))
        
        if roi_right <= roi_left or roi_bottom <= roi_top:
            log("[动态识别] ROI 坐标无效")
            return []
        
        # 获取 HSV 配置
        hsv_config = config.get("hsv", {})
        if not hsv_config:
            log("[动态识别] 未配置 HSV 参数")
            return []
        
    except Exception as e:
        log(f"[动态识别] 加载配置失败: {e}")
        return []
    
    # 持续识别循环
    iteration = 0
    while True:
        # 检查是否超时
        elapsed = time.time() - start_time
        if elapsed >= duration:
            log(f"[动态识别] 达到 {duration}秒 限制，退出识别")
            break
        
        iteration += 1
        remaining = duration - elapsed
        
        # 优先级检查：如果购买动作激活，立即跳过一次扫描
        if current_action_state == ActionState.PURCHASE_ACTIVE:
            if iteration % 10 == 0:  # 每1.5秒提示一次
                log(f"[动态识别] 购买动作进行中（最高优先级），暂停仓库识别")
            time.sleep(check_interval)
            continue
        
        try:
            # 截取 ROI 区域
            with mss.mss() as sct:
                monitor = {
                    "top": roi_top,
                    "left": roi_left,
                    "width": roi_right - roi_left,
                    "height": roi_bottom - roi_top
                }
                screenshot = sct.grab(monitor)
                img = np.array(screenshot)[:, :, :3]  # BGRA -> BGR
            
            # 1. 高优先级：检测高亮物品（购买目标）
            items, mask = detect_items(img, hsv_config, min_area=500, input_format="BGR")
            
            if items and len(items) > 0:
                # 识别到物品 - 最高优先级
                log(f"[动态识别] ⚡ 识别到 {len(items)} 个高亮物品 - 立即购买（剩余 {remaining:.1f}秒）")
                
                # 设置购买状态（最高优先级）
                current_action_state = ActionState.PURCHASE_ACTIVE
                
                for item in items[:5]:
                    cx, cy = item["center"]
                    screen_x = roi_left + cx
                    screen_y = roi_top + cy
                    
                    try:
                        pyautogui.keyDown('ctrl')
                        time.sleep(0.05)
                        pyautogui.click(screen_x, screen_y)
                        time.sleep(0.05)
                        pyautogui.keyUp('ctrl')
                        
                        recognized_items.append({
                            "type": "item_purchase",
                            "screen_x": screen_x,
                            "screen_y": screen_y,
                            "area": item.get("area", 0)
                        })
                        log(f"[动态识别] ✓ 已购买物品: ({screen_x}, {screen_y})")
                    except Exception as e:
                        log(f"[动态识别] 购买失败: {e}")
                
                # 重置状态
                current_action_state = ActionState.IDLE
                time.sleep(0.5)
                # 不执行 continue，继续检测仓库位置
                
            # 2. 低优先级：检测仓库位置（在购买后也继续检测）
            if template_img is not None:
                # 检查是否应该尝试存仓（购买不在激活/挂起状态）
                if current_action_state in [ActionState.IDLE]:
                    stash_pos = _try_detect_stash_in_roi(img, roi_left, roi_top)
                    if stash_pos:
                        # 找到仓库 - 设置存仓状态
                        current_action_state = ActionState.STORAGE_ACTIVE
                        
                        log(f"[动态识别] 📦 找到仓库位置: {stash_pos} - 准备打开")
                        
                        try:
                            pyautogui.click(stash_pos[0], stash_pos[1])
                            log(f"[动态识别] ✓ 已点击仓库: {stash_pos}")
                            
                            # 检查是否已经记录过这个仓库位置（避免重复）
                            has_stash_open = any(item.get("type") == "stash_open" for item in recognized_items)
                            if not has_stash_open:
                                recognized_items.append({
                                    "type": "stash_open",
                                    "screen_x": stash_pos[0],
                                    "screen_y": stash_pos[1]
                                })
                        except Exception as e:
                            log(f"[动态识别] 点击仓库失败: {e}")
                        finally:
                            current_action_state = ActionState.IDLE
            
            # 状态输出
            if iteration % 20 == 0:
                log(f"[动态识别] 监控中... 已扫描 {iteration} 次，剩余 {remaining:.1f}秒")
            
            time.sleep(check_interval)
            
        except Exception as e:
            log(f"[动态识别] 检测异常: {e}")
            time.sleep(check_interval)
            continue
    
    total_time = time.time() - start_time
    log(f"[动态识别] 完成 - 总耗时 {total_time:.1f}秒 | 处理 {len(recognized_items)} 个动作")
    
    return recognized_items


def _try_detect_stash_in_roi(img, roi_left, roi_top):
    """在 ROI 区域内检测仓库位置
    
    Args:
        img: ROI 区域图像
        roi_left, roi_top: ROI 左上角屏幕坐标
    
    Returns:
        (x, y) 仓库屏幕绝对坐标，未找到返回 None
    """
    if template_img is None:
        return None
    
    try:
        # 在 ROI 图像中匹配仓库模板
        result = cv2.matchTemplate(img, template_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= 0.7:  # 置信度阈值
            # max_loc 是 ROI 内的相对坐标
            template_h, template_w = template_img.shape[:2]
            stash_center_x = roi_left + max_loc[0] + template_w // 2
            stash_center_y = roi_top + max_loc[1] + template_h // 2
            return (stash_center_x, stash_center_y)
    except Exception as e:
        log(f"[仓库检测] 异常: {e}")
    
    return None


def can_execute_storage():
    """检查是否可以执行存仓操作（购买不在激活/挂起状态时）"""
    global current_action_state
    return current_action_state in [ActionState.IDLE, ActionState.STORAGE_PENDING]


def set_purchase_state(state):
    """设置购买状态（线程安全）"""
    global current_action_state
    with purchase_lock:
        current_action_state = state


def set_storage_state(state):
    """设置存仓状态（线程安全）"""
    global current_action_state
    # 存仓不能打断购买
    if current_action_state in [ActionState.PURCHASE_ACTIVE, ActionState.PURCHASE_PENDING]:
        log(f"[优先级] 购买动作进行中，存仓状态变更被拒绝")
        return False
    current_action_state = state
    return True


def ctrl_click(x, y):
    """执行Ctrl+左键点击购买"""
    try:
        # 方法1：使用hotkey更稳定
        pyautogui.moveTo(x, y, duration=0.05)
        time.sleep(0.1)
        pyautogui.keyDown('ctrl')
        time.sleep(0.1)
        pyautogui.click(x, y)
        time.sleep(0.1)
        pyautogui.keyUp('ctrl')
    except Exception as e:
        log(f"[购买] 点击失败: {e}")


def perform_stash(stash_cells):
    """执行存仓操作，遍历所有格子（高速版）"""
    if not stash_cells:
        log("[存仓] 未配置仓库格子，跳过存仓")
        return
    
    num_cells = len(stash_cells)
    
    # 计算优化前后耗时对比
    old_time = num_cells * 0.45  # 原来每个格子约0.45秒 (0.1移动+0.05*3ctrl+0.3等待)
    new_time = num_cells * 0.01  # 优化后每个格子约0.01秒
    log(f"[存仓] 开始存仓，共 {num_cells} 个格子")
    log(f"[存仓] 【优化对比】优化前预计: {old_time:.1f}秒 | 优化后预计: {new_time:.1f}秒 | 提升: {(old_time-new_time)/old_time*100:.1f}%")
    
    # 保存原始设置
    original_pause = pyautogui.PAUSE
    original_min_duration = pyautogui.MINIMUM_DURATION
    original_min_sleep = pyautogui.MINIMUM_SLEEP
    
    # 关闭所有延迟
    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    
    start_time = time.time()
    
    try:
        # 只按下一次 Ctrl
        pyautogui.keyDown('ctrl')
        time.sleep(0.02)  # 确保 Ctrl 键按下
        
        # 遍历所有格子，只执行点击
        for idx, cell in enumerate(stash_cells, 1):
            region = cell.get("region", [])
            if len(region) >= 4:
                x1, y1, x2, y2 = region
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                
                # cells_map 中的坐标已经是屏幕绝对坐标，直接使用
                screen_cx = cx
                screen_cy = cy
                
                # 直接点击，不需要 moveTo 动画
                pyautogui.click(screen_cx, screen_cy)
                
                # 每处理10个格子输出一次进度
                if idx % 10 == 0 or idx == num_cells:
                    elapsed = time.time() - start_time
                    progress = idx / num_cells * 100
                    log(f"[存仓] 进度: {idx}/{num_cells} ({progress:.0f}%)")
                
                # 最小延迟
                time.sleep(0.01)
            else:
                log(f"[存仓] 跳过无效格子 {idx}")
        
        # 释放 Ctrl 键
        pyautogui.keyUp('ctrl')
        
        elapsed_time = time.time() - start_time
        log(f"[存仓] ✓ 存仓完成！实际耗时: {elapsed_time:.2f}秒 | 速度: {num_cells/elapsed_time:.1f}格子/秒")
        
    except Exception as e:
        log(f"[存仓] 存仓过程出错: {e}")
        try:
            pyautogui.keyUp('ctrl')
        except:
            pass
    finally:
        # 恢复 PyAutoGUI 设置
        pyautogui.PAUSE = original_pause
        pyautogui.MINIMUM_DURATION = original_min_duration
        pyautogui.MINIMUM_SLEEP = original_min_sleep


def perform_stash_fast(stash_cells):
    """快速存仓操作 - 与 auto_buy_debug_tool.py 的 _execute_stash 一致
    
    支持两种格式:
    1. cells_map: [[[x1,y1],[x2,y2]], ...] - stash_debugger.py 保存的格式
    2. cells: [{"region":[x1,y1,x2,y2]}, ...] - 旧格式兼容
    """
    if not stash_cells:
        log("[存仓] 未配置仓库格子，跳过存仓")
        return
    
    num_cells = len(stash_cells)
    log(f"[存仓] 开始快速存仓，共 {num_cells} 个格子")
    
    # 保存原始设置
    original_pause = pyautogui.PAUSE
    original_min_duration = pyautogui.MINIMUM_DURATION
    original_min_sleep = pyautogui.MINIMUM_SLEEP
    
    # 关闭所有延迟
    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    
    start_time = time.time()
    
    try:
        pyautogui.keyDown('ctrl')
        time.sleep(0.05)
        
        for idx, cell in enumerate(stash_cells, 1):
            # 支持两种格式
            if isinstance(cell, list) and len(cell) == 2:
                # 格式1: cells_map [[[x1,y1],[x2,y2]], ...]
                p1, p2 = cell
                if isinstance(p1, list) and len(p1) >= 2 and isinstance(p2, list) and len(p2) >= 2:
                    x1, y1 = p1[0], p1[1]
                    x2, y2 = p2[0], p2[1]
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    # cells_map 中的坐标已经是屏幕绝对坐标，直接使用
                    screen_cx = cx
                    screen_cy = cy
                    pyautogui.click(screen_cx, screen_cy)
            elif isinstance(cell, dict) and "region" in cell:
                # 格式2: cells [{"region":[x1,y1,x2,y2]}, ...]
                region = cell.get("region", [])
                if len(region) >= 4:
                    x1, y1, x2, y2 = region
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    # cells_map 中的坐标已经是屏幕绝对坐标，直接使用
                    screen_cx = cx
                    screen_cy = cy
                    pyautogui.click(screen_cx, screen_cy)
            
            # 每30毫秒遍历一个格子（与 debug_tool.py 一致）
            time.sleep(0.03)
        
        pyautogui.keyUp('ctrl')
        elapsed = time.time() - start_time
        log(f"[存仓] 存仓完成！耗时: {elapsed:.2f}秒 | 速度: {num_cells/elapsed:.1f}格子/秒")
        
    except Exception as e:
        log(f"[存仓] 出错: {e}")
        try:
            pyautogui.keyUp('ctrl')
        except:
            pass
    finally:
        pyautogui.PAUSE = original_pause
        pyautogui.MINIMUM_DURATION = original_min_duration
        pyautogui.MINIMUM_SLEEP = original_min_sleep


def main():
    log("========== AutoBuy 自动购买工具 (智能存仓版) ==========")
    log("存仓条件：每次购买后F5回城自动执行存仓")
    
    # 初始化：自动识别游戏窗口（优先国际服，其次国服）
    log("[初始化] 正在识别游戏窗口...")
    if detect_game_window("global"):
        server = "global"
    else:
        log("[初始化] 未找到国际服，尝试检测国服...")
        if detect_game_window("china"):
            server = "china"
        else:
            log("[错误] 无法识别游戏窗口，退出")
            return
    
    # 初始化：加载仓库模板
    log("[初始化] 正在加载仓库模板...")
    if not load_template():
        log("[警告] 未找到仓库模板，请使用 stash_debugger.py 保存模板")
    
    cfg = load_config()
    left, top, right, bottom = cfg["left"], cfg["top"], cfg["right"], cfg["bottom"]
    hsv_config = cfg["hsv_config"]
    
    # 调试：输出实际加载的配置
    log(f"[调试] 加载的检测区域: LEFT={left}, TOP={top}, RIGHT={right}, BOTTOM={bottom}")
    log(f"[调试] 加载的HSV配置: H={hsv_config['h_min']}-{hsv_config['h_max']}, S={hsv_config['s_min']}-{hsv_config['s_max']}, V={hsv_config['v_min']}-{hsv_config['v_max']}")
    
    stash_cells = load_stash_cells()
    
    log(f"检测区域: {right-left}x{bottom-top}")
    log("存仓条件: 每次购买后F5回城自动执行存仓")
    log("扫描频率: 10次/秒")
    log("等待2秒后开始运行...")
    time.sleep(2)
    
    total_buy = 0
    loop_count = 0
    last_buy_pos = None
    
    # 日志节流
    last_no_item_log_time = 0
    last_duplicate_log_time = 0
    last_cpu_log_time = 0
    NO_ITEM_LOG_INTERVAL = 3
    DUPLICATE_LOG_INTERVAL = 3
    CPU_LOG_INTERVAL = 5
    
    log("开始主循环...")
    
    while True:
        loop_count += 1
        current_time = time.time()
        
        # CPU监控：每5秒输出一次
        if current_time - last_cpu_log_time > CPU_LOG_INTERVAL:
            cpu_percent = psutil.cpu_percent(interval=None)
            log(f"【CPU】当前使用率: {cpu_percent}%")
            last_cpu_log_time = current_time
        
        # 检测物品
        try:
            items = detect_highlights(left, top, right, bottom, hsv_config)
        except Exception as e:
            log(f"【循环 #{loop_count}】检测失败: {e}")
            time.sleep(0.1)
            continue
        
        if not items:
            if current_time - last_no_item_log_time > NO_ITEM_LOG_INTERVAL:
                log(f"【循环 #{loop_count}】未识别到物品")
                last_no_item_log_time = current_time
            time.sleep(0.1)
            continue
        
        # 找到最大的物品
        max_item = max(items, key=lambda x: x["area"])
        rx, ry, rw, rh = max_item["bbox"]
        screen_x = left + rx + rw // 2
        screen_y = top + ry + rh // 2
        current_pos = (screen_x, screen_y)
        
        # 跳过重复位置
        if last_buy_pos == current_pos:
            if current_time - last_duplicate_log_time > DUPLICATE_LOG_INTERVAL:
                log(f"【循环 #{loop_count}】识别到物品 | 坐标=({screen_x}, {screen_y}) | 跳过重复位置")
                last_duplicate_log_time = current_time
            time.sleep(0.1)
            continue
        
        # ========== 正常购买流程 ==========
        log(f"【循环 #{loop_count}】识别到物品 | 坐标=({screen_x}, {screen_y})")
        log(f"  -> 执行Ctrl+左键购买...")
        pyautogui.moveTo(screen_x, screen_y, duration=0.1)
        ctrl_click(screen_x, screen_y)
        
        total_buy += 1
        last_buy_pos = current_pos
        
        log(f"  -> 成功购买！累计购买: {total_buy}")
        
        # 移动鼠标到安全位置
        pyautogui.moveTo(907, 591)
        log(f"  -> 鼠标移至安全位置 (907, 591)")
        
        time.sleep(0.3)
        
        # 执行F5回城
        log("执行F5刷新（回城）")
        pyautogui.press("f5")
        
        # ========== 10秒持续监控：反复检测并点击仓库 ==========
        stash_opened = False
        monitor_start = time.time()
        monitor_timeout = 10.0  # 监控10秒
        
        if can_execute_storage():
            log(f"[存仓] 开始10秒持续监控，检测仓库位置并尝试打开...")
            
            while time.time() - monitor_start < monitor_timeout:
                # 尝试检测仓库
                pos = match_stash_template()
                
                if pos:
                    x, y = pos
                    log(f"[存仓] 检测到仓库: ({x}, {y})，点击打开...")
                    
                    # 点击仓库（双击更保险）
                    pyautogui.moveTo(x, y, duration=0.1)
                    time.sleep(0.3)
                    pyautogui.click()
                    time.sleep(1)
                    pyautogui.click()
                    
                    # 验证仓库是否真的打开
                    stash_det_config = load_stash_detection_config()
                    is_opened, conf = verify_stash_opened(
                        stash_det_config, max_retry=5, retry_interval=0.5
                    )
                    
                    if is_opened:
                        log(f"[存仓] ✓ 仓库已打开 - 置信度: {conf:.3f}")
                        stash_opened = True
                        break
                    else:
                        log(f"[存仓] 点击后未打开，继续检测（已用 {time.time() - monitor_start:.1f}秒）")
                else:
                    # 未检测到，等待0.5秒再试
                    elapsed = time.time() - monitor_start
                    if int(elapsed) % 3 == 0 and elapsed < monitor_timeout - 0.5:
                        log(f"[存仓] 监控中... 尚未检测到仓库（已用 {elapsed:.1f}秒，剩余 {monitor_timeout - elapsed:.1f}秒）")
                    time.sleep(0.5)
            
            # 监控结束
            if stash_opened:
                log(f"[存仓] 仓库已打开，用时 {time.time() - monitor_start:.1f}秒，开始存仓...")
                perform_stash_with_confidence(stash_cells)
                log("[存仓] 存仓完成")
            else:
                log(f"[存仓] ✗ 10秒内未成功检测到或打开仓库，跳过本次存仓")
        else:
            log("[存仓] 当前动作状态不允许存仓，跳过")
        
        log("等待2秒后继续检测下一个物品...")
        time.sleep(2)
        last_buy_pos = None


def test_stash_flow():
    """测试存仓流程 - 直接执行存仓操作（不等待超时）"""
    print("========== 测试存仓流程 ==========", flush=True)
    print("此模式将直接执行存仓操作，用于测试存仓功能是否正常", flush=True)
    
    # 初始化：自动识别游戏窗口
    print("[测试] 正在识别游戏窗口...", flush=True)
    if not detect_game_window("global"):
        print("[测试] 未找到国际服，尝试检测国服...", flush=True)
        if not detect_game_window("china"):
            print("[错误] 无法识别游戏窗口，退出", flush=True)
            return
    
    # 加载仓库模板
    print("[测试] 正在加载仓库模板...", flush=True)
    if not load_template():
        print("[警告] 未找到仓库模板", flush=True)
    
    # 加载仓库格子配置
    stash_cells = load_stash_cells()
    print(f"[测试] 加载到 {len(stash_cells)} 个仓库格子", flush=True)
    if not stash_cells:
        print("[错误] 未配置仓库格子，退出", flush=True)
        return
    
    # 执行F5回城
    print("[测试] 执行F5刷新（回城）", flush=True)
    pyautogui.press("f5")
    
    # 等待7秒确保到达藏身处
    print("[测试] 等待7秒让藏身处加载...", flush=True)
    time.sleep(7)
    
    # 简化版：直接点击仓库（不进行置信度检测）
    print("[测试] 使用模板匹配查找仓库...", flush=True)
    pos = match_stash_template()
    if pos:
        x, y = pos
        print(f"[测试] 找到仓库位置: ({x}, {y})", flush=True)
        
        # 点击仓库
        print("[测试] 点击仓库...", flush=True)
        pyautogui.moveTo(x, y, duration=0.1)
        time.sleep(0.3)
        pyautogui.click()
        time.sleep(1)
        pyautogui.click()
        
        # 等待2秒让仓库打开
        print("[测试] 等待2秒让仓库打开...", flush=True)
        time.sleep(2)
        
        # 执行智能存仓（基于置信度）
        print("[测试] 开始执行智能存仓（基于置信度）...", flush=True)
        perform_stash_with_confidence(stash_cells)
        print("[测试] ✓ 存仓测试完成！", flush=True)
    else:
        print("[测试] ✗ 未能找到仓库位置", flush=True)


if __name__ == "__main__":
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="AutoBuy 自动购买工具")
    parser.add_argument(
        "-t", "--test-stash", 
        action="store_true", 
        help="测试存仓流程（直接执行存仓操作，不等待超时）"
    )
    args = parser.parse_args()
    
    # 如果是测试模式，直接执行存仓测试
    if args.test_stash:
        test_stash_flow()
    else:
        main()
