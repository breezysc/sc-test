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
from window_locator import locator
from template_locator_integrator import (
    init_template_locator,
    get_stash_cells,
)

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
EMPTY_CELL_THRESHOLD = 0.9  # 空格子置信度阈值（高于此值为空格子，低于此值才存仓）
screenshot_btn_template = None  # 截图按钮模板
just_purchased = False  # 全局：是否刚刚购买（用于控制购买-存仓流程）

# 命令行参数
GAME_PATH = None  # 游戏可执行文件路径
SERVER_TYPE = "china"  # 服务器类型: china 或 global

# 自有仓库容量管理
own_stash_cells = None  # 自有仓库 12x12 格子（相对坐标）
current_stash_tab = 1  # 当前使用的仓库标签页编号
STASH_FULL_THRESHOLD = 0.8  # 仓库满仓阈值（80%）
OWN_STASH_C1_TEMPLATE = None  # 仓库标签页模板 c1.png

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


class WindowTracker:
    """动态窗口位置追踪器 - 实时监控窗口移动并自动校准坐标系统
    
    核心功能：
    1. 基于 GetWindowRect 快速检测窗口位置变化 (微秒级)
    2. 维护基准坐标 (reference_left=78, reference_top=78) 与实际窗口的偏移量
    3. 自动同步位置到 locator 和 game_window, 确保 to_screen() 转换准确
    4. 支持窗口移动、大小调整、多显示器环境的实时追踪
    
    性能：单次 check() 耗时 < 1ms，满足 500ms 自适应调整要求
    """
    
    def __init__(self):
        # 基准窗口位置 (用户测量格子坐标时的窗口位置, 相对坐标 = 屏幕坐标 - 此基准)
        self.reference_left = 78
        self.reference_top = 78
        self._hwnd = None
        self.last_left = 0
        self.last_top = 0
        self.last_width = 0
        self.last_height = 0
        self.offset_x = 0   # 当前窗口相对基准的 X 偏移
        self.offset_y = 0   # 当前窗口相对基准的 Y 偏移
        self.move_count = 0
        self.last_check_time = 0.0
        self._initialized = False
    
    def init(self, hwnd, left, top, width, height):
        """初始化追踪器，绑定到指定窗口
        
        Args:
            hwnd: 窗口句柄
            left, top: 当前窗口左上角屏幕坐标
            width, height: 当前窗口尺寸
        """
        self._hwnd = hwnd
        self.last_left = left
        self.last_top = top
        self.last_width = width
        self.last_height = height
        self.offset_x = left - self.reference_left
        self.offset_y = top - self.reference_top
        self.last_check_time = time.time()
        self._initialized = True
        log(f"[窗口追踪] 初始化完成 - 基准:({self.reference_left},{self.reference_top}) "
            f"当前:({left},{top}) 偏移:({self.offset_x},{self.offset_y}) "
            f"尺寸:{width}x{height}")
    
    def check(self):
        """快速检查窗口是否移动（使用 GetWindowRect 直接获取，微秒级性能）
        
        Returns:
            (moved, delta_x, delta_y, new_left, new_top, new_width, new_height)
            moved: 是否发生移动
            delta_x, delta_y: 移动偏移量（像素）
            new_*: 当前窗口最新位置和尺寸
        """
        if not self._initialized or self._hwnd is None:
            return (False, 0, 0, 0, 0, 0, 0)
        
        try:
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(self._hwnd, ctypes.byref(rect))
            current_left = rect.left
            current_top = rect.top
            current_width = rect.right - rect.left
            current_height = rect.bottom - rect.top
            
            self.last_check_time = time.time()
            
            if (current_left != self.last_left or current_top != self.last_top or
                current_width != self.last_width or current_height != self.last_height):
                
                delta_x = current_left - self.last_left
                delta_y = current_top - self.last_top
                
                self.last_left = current_left
                self.last_top = current_top
                self.last_width = current_width
                self.last_height = current_height
                self.offset_x = current_left - self.reference_left
                self.offset_y = current_top - self.reference_top
                self.move_count += 1
                
                log(f"[窗口追踪] 检测到窗口移动 #{self.move_count}: "
                    f"delta=({delta_x:+d},{delta_y:+d}) "
                    f"新位置:({current_left},{current_top}) "
                    f"偏移:({self.offset_x},{self.offset_y})")
                
                return (True, delta_x, delta_y, current_left, current_top, 
                        current_width, current_height)
            
            return (False, 0, 0, current_left, current_top, current_width, current_height)
        except Exception as e:
            return (False, 0, 0, 0, 0, 0, 0)
    
    def sync_to_locator(self):
        """将当前追踪到的窗口位置同步到 locator 和 game_window 全局变量
        
        这是坐标校准的关键步骤：当窗口移动后，必须同步更新 locator._window 
        的位置字段，否则 locator.to_screen() 会返回错误的屏幕坐标。
        
        Returns:
            bool: 是否同步成功
        """
        global game_window
        if not self._initialized or self._hwnd is None:
            return False
        
        try:
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(self._hwnd, ctypes.byref(rect))
            
            new_data = {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            }
            
            # 更新 locator._window（保留 title 和 hwnd 不变）
            if locator._window is not None:
                for key in new_data:
                    locator._window[key] = new_data[key]
            
            # 更新 game_window 全局变量（game_window 和 locator._window 是同一对象）
            if game_window is not None and game_window is not locator._window:
                for key in new_data:
                    game_window[key] = new_data[key]
            
            self.last_left = rect.left
            self.last_top = rect.top
            self.last_width = rect.right - rect.left
            self.last_height = rect.bottom - rect.top
            self.offset_x = rect.left - self.reference_left
            self.offset_y = rect.top - self.reference_top
            return True
        except Exception as e:
            log(f"[窗口追踪] 同步失败: {e}")
            return False
    
    @property
    def is_initialized(self):
        return self._initialized


# 全局窗口追踪器实例
window_tracker = WindowTracker()


def detect_game_window(server="global", silent=False):
    """识别游戏窗口 - 使用 window_locator 模块（排除浏览器窗口）

    坐标转换说明：
      配置中的所有坐标都是「相对于游戏窗口的」。
      运行时调用 locator.to_screen(rel_x, rel_y) 转换为屏幕绝对坐标。

    Args:
        server: "global"(国际服) 或 "china"(国服)
        silent: 是否静默检测（不输出日志）

    Returns:
        bool: 是否检测成功。检测成功后 game_window 全局变量会被设置。
    """
    global game_window

    # 使用 locator 统一检测
    if not locator.detect(server):
        if not silent:
            log(f"[窗口] 未找到匹配的游戏窗口（服务器: {server}）")
        return False

    game_window = locator.window
    # 初始化窗口追踪器
    if game_window and "hwnd" in game_window:
        window_tracker.init(
            game_window["hwnd"],
            game_window["left"], game_window["top"],
            game_window["width"], game_window["height"]
        )
    if not silent:
        log(f"[窗口] 已识别: {game_window['title']} 位置:({game_window['left']},{game_window['top']}) 大小:{game_window['width']}x{game_window['height']}")
    return True


def load_template():
    """从配置文件加载仓库模板，并加载空格子模板"""
    global template_img, empty_cell_template
    
    template_loaded = False
    
    # 从配置文件加载仓库模板（优先）
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if "stash_template" in config:
                template_data = config["stash_template"]
                if isinstance(template_data, list) and len(template_data) > 0:
                    template_img = np.array(template_data, dtype=np.uint8)
                    if template_img.ndim == 3 and template_img.shape[2] == 3:
                        log(f"[模板] 已从配置文件加载仓库模板，大小: {template_img.shape[1]}x{template_img.shape[0]}")
                        template_loaded = True
                    else:
                        template_img = None
                        log(f"[模板] 配置中的仓库模板数据格式无效")
        except Exception as e:
            log(f"[模板] 从配置文件加载仓库模板失败: {e}")
    
    # 从文件加载仓库模板（备选）
    if not template_loaded:
        # 优先尝试 a2.png（用户指定的仓库模板）
        stash_template_path = "templates/stash/a2.png"
        if os.path.exists(stash_template_path):
            template_img = cv2.imread(stash_template_path)
            if template_img is not None:
                log(f"[模板] 已从文件加载仓库模板: {stash_template_path}，大小: {template_img.shape[1]}x{template_img.shape[0]}")
                template_loaded = True
            else:
                log(f"[警告] 无法读取仓库模板文件: {stash_template_path}")
        
        # 如果 a2.png 不存在或加载失败，尝试 anchor.png
        if not template_loaded:
            stash_template_path = "templates/stash/anchor.png"
            if os.path.exists(stash_template_path):
                template_img = cv2.imread(stash_template_path)
                if template_img is not None:
                    log(f"[模板] 已从文件加载仓库模板: {stash_template_path}，大小: {template_img.shape[1]}x{template_img.shape[0]}")
                    template_loaded = True
                else:
                    log(f"[警告] 无法读取仓库模板文件: {stash_template_path}")
            else:
                log(f"[警告] 未找到仓库模板文件: {stash_template_path}")
    
    # 加载空格子模板（cc.png）
    empty_cell_template = None
    if os.path.exists("cc.png"):
        empty_cell_template = cv2.imread("cc.png")
        if empty_cell_template is not None:
            log(f"[模板] 已加载空格子模板，大小: {empty_cell_template.shape[1]}x{empty_cell_template.shape[0]}")
        else:
            log("[警告] 未能加载空格子模板 cc.png")
    else:
        log("[警告] 未找到空格子模板 cc.png，将使用像素统计方法")
    
    # 确保 empty_cell_template 在全局可用
    if 'empty_cell_template' not in globals():
        globals()['empty_cell_template'] = empty_cell_template
    
    # 加载截图按钮模板
    load_screenshot_btn_template()
    
    return template_img is not None


def load_screenshot_btn_template():
    """加载截图按钮模板"""
    global screenshot_btn_template
    btn_template_path = "template_screenshot_btn.png"
    if os.path.exists(btn_template_path):
        screenshot_btn_template = cv2.imread(btn_template_path)
        if screenshot_btn_template is not None:
            log(f"[模板] 已加载截图按钮模板，大小: {screenshot_btn_template.shape[1]}x{screenshot_btn_template.shape[0]}")
            return True
        else:
            log("[警告] 未能加载截图按钮模板")
    else:
        log("[警告] 未找到截图按钮模板文件")
    return False


def detect_screenshot_button():
    """检测截图按钮，使用模板匹配
    
    Returns:
        (found, confidence, screen_x, screen_y)
        found: 是否检测到按钮
        confidence: 置信度
        screen_x, screen_y: 按钮中心屏幕坐标（检测到时有效）
    """
    global game_window, screenshot_btn_template
    
    if game_window is None or screenshot_btn_template is None:
        return (False, 0.0, 0, 0)
    
    try:
        # 使用游戏相对坐标，转换为屏幕坐标（扩大10px确保搜索区域大于模板）
        rel_x1, rel_y1, rel_x2, rel_y2 = 598, 512, 674, 532
        margin = 10
        screen_x1 = game_window["left"] + max(0, rel_x1 - margin)
        screen_y1 = game_window["top"] + max(0, rel_y1 - margin)
        screen_x2 = game_window["left"] + min(game_window["width"], rel_x2 + margin)
        screen_y2 = game_window["top"] + min(game_window["height"], rel_y2 + margin)
        
        # 截取按钮区域
        with mss.mss() as sct:
            monitor = {
                "top": screen_y1,
                "left": screen_x1,
                "width": screen_x2 - screen_x1,
                "height": screen_y2 - screen_y1
            }
            screenshot = sct.grab(monitor)
            btn_img = np.array(screenshot)[:, :, :3]
        
        if btn_img.size == 0:
            return (False, 0.0, 0, 0)
        
        # 模板匹配
        gray_btn = cv2.cvtColor(btn_img, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.cvtColor(screenshot_btn_template, cv2.COLOR_BGR2GRAY)
        
        if gray_template.shape[0] <= gray_btn.shape[0] and gray_template.shape[1] <= gray_btn.shape[1]:
            result = cv2.matchTemplate(gray_btn, gray_template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
        else:
            h, w = gray_btn.shape
            template_resized = cv2.resize(gray_template, (w, h))
            result = cv2.matchTemplate(gray_btn, template_resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
        
        confidence = float(max_val)
        screen_cx = game_window["left"] + (rel_x1 + rel_x2) // 2
        screen_cy = game_window["top"] + (rel_y1 + rel_y2) // 2
        
        # 调试：保存当前截图和模板的对比（用于分析置信度高低）
        debug_dir = "detect_debug"
        os.makedirs(debug_dir, exist_ok=True)
        debug_current = cv2.cvtColor(btn_img, cv2.COLOR_BGR2RGB)
        debug_template = cv2.cvtColor(screenshot_btn_template, cv2.COLOR_BGR2RGB)
        cv2.imwrite(f"{debug_dir}/btn_current.png", debug_current)
        # 水平拼接：当前截图 | 模板
        h1, w1 = debug_current.shape[:2]
        h2, w2 = debug_template.shape[:2]
        h_max = max(h1, h2)
        canvas1 = np.zeros((h_max, w1, 3), dtype=np.uint8)
        canvas1[:h1] = debug_current
        canvas2 = np.zeros((h_max, w2, 3), dtype=np.uint8)
        canvas2[:h2] = debug_template
        compare = np.hstack([canvas1, canvas2])
        cv2.putText(compare, f"Current ({w1}x{h1})", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
        cv2.putText(compare, f"Template ({w2}x{h2})", (w1+5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
        cv2.putText(compare, f"Match: {confidence:.4f}", (5, h_max-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,255), 1)
        cv2.imwrite(f"{debug_dir}/btn_compare.png", compare)
        
        return (confidence > 0.8, confidence, screen_cx, screen_cy)
        
    except Exception as e:
        return (False, 0.0, 0, 0)


def check_cell_confidence(cell_region, cell_idx=0):
    """检查单个格子的置信度（是否为空格子）

    Args:
        cell_region: 格子区域 [x1, y1, x2, y2]（可能是相对坐标或绝对坐标）
        cell_idx: 格子序号（用于唯一标识）

    Returns:
        confidence: 置信度（0-1），高于 EMPTY_CELL_THRESHOLD 认为是空格子
    """
    global empty_cell_template, game_window

    if game_window is None:
        return 0.0

    try:
        x1, y1, x2, y2 = cell_region

        # 检查坐标是否已经是屏幕绝对坐标
        if game_window and (x1 > game_window["width"] or y1 > game_window["height"]):
            # 已经是绝对坐标，直接使用
            abs_x1, abs_y1, abs_x2, abs_y2 = x1, y1, x2, y2
            log(f"[格子置信度] 格子{cell_idx}坐标已为绝对坐标")
        else:
            # 是相对坐标，需要转换
            abs_x1, abs_y1 = locator.to_screen(x1, y1)
            abs_x2, abs_y2 = locator.to_screen(x2, y2)
        
        # 使用绝对坐标进行截图
        with mss.mss() as sct:
            monitor = {
                "top": int(abs_y1),
                "left": int(abs_x1),
                "width": int(abs_x2 - abs_x1),
                "height": int(abs_y2 - abs_y1)
            }
            screenshot = sct.grab(monitor)
            cell_img = np.array(screenshot)[:, :, :3]
        
        # 检查图像质量
        if cell_img.size == 0:
            log(f"[格子置信度] 格子{cell_idx}截图为空")
            return 0.0
        
        # 模板匹配：使用 cc.png（空格子模板）与当前格子截图进行匹配
        # 匹配度越高 → 越像空格子 → 置信度越高（跳过存仓）
        # 匹配度越低 → 越不像空格子 → 置信度越低（需要存仓）
        confidence = 0.0
        
        if empty_cell_template is not None:
            # 先将 cc.png 缩放到与格子截图一致的 30x30，再统一裁剪
            cell_h, cell_w = cell_img.shape[:2]
            template_resized = cv2.resize(empty_cell_template, (cell_w, cell_h))
            
            # 两侧都取中心 80% 区域，排除边缘干扰
            crop_ratio = 0.8
            crop_h = int(cell_h * crop_ratio)
            crop_w = int(cell_w * crop_ratio)
            cy, cx = cell_h // 2, cell_w // 2
            
            cropped_cell = cell_img[cy - crop_h // 2:cy + crop_h // 2,
                                    cx - crop_w // 2:cx + crop_w // 2]
            cropped_template = template_resized[cy - crop_h // 2:cy + crop_h // 2,
                                                 cx - crop_w // 2:cx + crop_w // 2]
            
            # 保存对比调试图
            debug_compare = np.hstack([cropped_cell, cropped_template])
            cv2.imwrite(f"stash_debug/compare_{cell_idx:02d}.png", debug_compare)
            
            # 像素差异法：直接计算两图像素差异，结果直观可靠
            # 1.0 = 完全相同  0.0 = 完全不同
            gray_cell = cv2.cvtColor(cropped_cell, cv2.COLOR_BGR2GRAY)
            gray_template = cv2.cvtColor(cropped_template, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray_cell, gray_template)
            confidence = 1.0 - float(np.mean(diff)) / 255.0
            
            # 置信度裁剪到 [0, 1]
            confidence = max(0.0, min(1.0, confidence))
            
            has_item = confidence < EMPTY_CELL_THRESHOLD
        
        if cell_idx <= 10 or confidence < 0.5:
            log(f"[格子置信度] 格子{cell_idx} - 模板匹配度:{confidence:.3f} {'[有物品]' if has_item else '[空格子]'}")
        
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
    global game_window, EMPTY_CELL_THRESHOLD, has_purchased, just_purchased
    
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
    
    # 创建本次存仓的专属调试截图文件夹（按时间戳）
    stash_screenshot_dir = os.path.join("stash_debug", "stashed",
        time.strftime("%Y%m%d_%H%M%S"))
    
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
            
            # 仅当格子有物品时才需要坐标转换（有物品才点击）
            if confidence < EMPTY_CELL_THRESHOLD:
                # 检查坐标是否已经是屏幕绝对坐标（通过阈值判断）
                # 用户坐标生成的是相对坐标，需要转换；配置文件中的可能是绝对坐标
                if game_window:
                    # 如果坐标值远大于窗口尺寸（超过2倍），认为是绝对坐标
                    if cx > game_window["width"] * 2 or cy > game_window["height"] * 2:
                        # 坐标已经是屏幕绝对坐标，直接使用
                        screen_cx, screen_cy = cx, cy
                    else:
                        # 坐标是相对窗口坐标，需要转换
                        screen_cx, screen_cy = locator.to_screen(cx, cy)
                else:
                    # 无法获取窗口位置，直接使用原始坐标
                    screen_cx, screen_cy = cx, cy
                
                # 识别到存仓的物品 - 关键日志，始终输出
                stashed_count += 1
                
                # 保存存仓格子截图到专属调试文件夹
                try:
                    os.makedirs(stash_screenshot_dir, exist_ok=True)
                    abs_x1, abs_y1 = locator.to_screen(x1, y1)
                    abs_x2, abs_y2 = locator.to_screen(x2, y2)
                    with mss.mss() as sct:
                        monitor = {
                            "top": int(abs_y1), "left": int(abs_x1),
                            "width": int(abs_x2 - abs_x1), "height": int(abs_y2 - abs_y1)
                        }
                        shot = np.array(sct.grab(monitor))[:, :, :3]
                    # 保存原始截图（无标注，用于与 cc.png 比对）
                    cv2.imwrite(os.path.join(stash_screenshot_dir, f"stashed_{idx:02d}_raw.png"), shot)
                    # 保存标注截图
                    annotated = shot.copy()
                    cv2.putText(annotated, f"Cell {idx} Conf:{confidence:.2f}", (3, 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    cv2.putText(annotated, f"({screen_cx},{screen_cy})", (3, 26),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    cv2.imwrite(os.path.join(stash_screenshot_dir, f"stashed_{idx:02d}.png"), annotated)
                    # 保存与 cc.png 模板的对比图
                    if empty_cell_template is not None:
                        shot_resized = cv2.resize(shot, (empty_cell_template.shape[1], empty_cell_template.shape[0]))
                        compare = np.hstack([shot_resized, empty_cell_template])
                        cv2.putText(compare, f"Cell {idx} (match:{confidence:.2f})", (3, 12),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                        cv2.putText(compare, "cc.png", (shot_resized.shape[1] + 3, 12),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
                        cv2.imwrite(os.path.join(stash_screenshot_dir, f"stashed_{idx:02d}_compare.png"), compare)
                except Exception:
                    pass
                
                pyautogui.click(screen_cx, screen_cy)
                log_agg.log_critical(f"[存仓] 识别到存仓的物品 - 格子 {idx}/{num_cells} - 置信度: {confidence:.3f} - 坐标: ({screen_cx}, {screen_cy})")
            else:
                # 跳过空格子 - 不输出日志（避免冗余）
                skipped_count += 1
            
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
        # 存仓完成后重置刚刚购买标志，等待下一次购买
        just_purchased = False
        log("[存仓] 已重置存仓标志，等待下一次购买...")


def template_match_on_screen(template_path, threshold=0.8):
    """在整个屏幕上进行模板匹配
    
    Args:
        template_path: 模板图片路径
        threshold: 匹配阈值
        
    Returns:
        tuple: (match_found, center_x, center_y, confidence)
    """
    try:
        # 加载模板
        template = cv2.imread(template_path)
        if template is None:
            log(f"[模板匹配] 无法加载模板: {template_path}")
            return (False, 0, 0, 0.0)
        
        template_h, template_w = template.shape[:2]
        
        # 截取整个屏幕
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # 主显示器
            screenshot = sct.grab(monitor)
            search_img = np.array(screenshot)[:, :, :3]
        
        # 模板匹配
        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        gray_search = cv2.cvtColor(search_img, cv2.COLOR_BGR2GRAY)
        
        result = cv2.matchTemplate(gray_search, gray_template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= threshold:
            center_x = max_loc[0] + template_w // 2
            center_y = max_loc[1] + template_h // 2
            log(f"[模板匹配] 找到匹配！模板: {os.path.basename(template_path)} 坐标: ({center_x}, {center_y}), 匹配度: {max_val:.3f}")
            return (True, center_x, center_y, max_val)
        else:
            log(f"[模板匹配] 未找到匹配，模板: {os.path.basename(template_path)} 匹配度: {max_val:.3f}")
            return (False, 0, 0, max_val)
    except Exception as e:
        log(f"[模板匹配] 错误: {e}")
        return (False, 0, 0, 0.0)


def restart_game_via_wegame():
    """通过 WeGame 或自定义路径重启游戏（国服）
    
    流程：
    1. 检查是否设置自定义游戏路径
    2. 如果设置了，直接启动游戏
    3. 否则，通过 WeGame 启动
    """
    log("========== 开始重启游戏流程 ==========")
    
    # 检查是否设置了自定义游戏路径
    if GAME_PATH and os.path.exists(GAME_PATH):
        log(f"[重启] 使用自定义游戏路径: {GAME_PATH}")
        
        # 检查游戏是否已经在运行
        game_running = False
        for proc in psutil.process_iter(['name']):
            try:
                if proc.name().lower() in ['pathofexile.exe', 'pathofexilechina.exe']:
                    game_running = True
                    log("[重启] 游戏已在运行")
                    break
            except:
                pass
        
        if not game_running:
            log("[重启] 启动游戏...")
            try:
                os.startfile(GAME_PATH)
                log(f"[重启] ✓ 已启动游戏: {GAME_PATH}")
                time.sleep(3)  # 等待游戏启动
            except Exception as e:
                log(f"[重启] 启动游戏失败: {e}")
                return False
        return True
    
    # 原有的 WeGame 启动逻辑
    log("[重启] 未设置自定义游戏路径，使用 WeGame 启动")
    
    # 检查游戏是否已运行
    game_running = False
    for proc in psutil.process_iter(['name']):
        try:
            if proc.name().lower() in ['pathofexile.exe', 'pathofexilechina.exe']:
                game_running = True
                log("[重启] 游戏已在运行")
                break
        except:
            pass
    
    if not game_running:
        log("[重启] 游戏未运行，尝试通过 WeGame 启动")
        
        # 检查 WeGame 是否运行，以及是否从正确路径启动
        target_wegame_path = r"D:\Program Files\WeGame\wegame.exe"
        wegame_running = False
        wegame_correct_path = False
        
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                if proc.name().lower() == 'wegame.exe':
                    wegame_running = True
                    exe_path = proc.exe()
                    log(f"[重启] 检测到 WeGame 已在运行: {exe_path}")
                    if exe_path.lower() == target_wegame_path.lower():
                        wegame_correct_path = True
                        log("[重启] ✓ WeGame 是从正确路径启动的")
                    else:
                        log(f"[重启] ⚠️ WeGame 不是从目标路径启动，将关闭并重新启动")
                        # 关闭错误的 WeGame
                        proc.kill()
                        log(f"[重启] 已关闭错误路径的 WeGame")
                        wegame_running = False
                    break
            except:
                pass
        
        # 如果 WeGame 未运行或路径不正确，启动它
        if not wegame_running or not wegame_correct_path:
            log("[重启] 启动 WeGame...")
            try:
                # 尝试常见的 WeGame 安装路径
                wegame_paths = [
                    r"D:\Program Files\WeGame\wegame.exe",
                    r"C:\Program Files (x86)\Tencent\WeGame\wegame.exe",
                    r"D:\Program Files (x86)\Tencent\WeGame\wegame.exe",
                    r"C:\WeGame\wegame.exe"
                ]
                wegame_exe = None
                log(f"[重启] 尝试以下路径启动 WeGame:")
                for path in wegame_paths:
                    exists = os.path.exists(path)
                    log(f"[重启]   {path} - {'存在' if exists else '不存在'}")
                    if exists and wegame_exe is None:
                        wegame_exe = path
                
                if wegame_exe:
                    os.startfile(wegame_exe)
                    log(f"[重启] ✓ 已启动 WeGame: {wegame_exe}")
                else:
                    log("[重启] 错误：未找到 WeGame 安装路径")
                    return False
            except Exception as e:
                log(f"[重启] 启动 WeGame 失败: {e}")
                return False
        
        # 激活 WeGame 窗口到前端
        log("[重启] 激活 WeGame 窗口...")
        try:
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            SW_SHOW = 5
            
            # 遍历窗口找到 WeGame
            def find_wegame_window(hwnd, extra):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    window_title = buffer.value
                    if "WeGame" in window_title or "wegame" in window_title.lower():
                        log(f"[重启] 找到 WeGame 窗口: {window_title}")
                        # 先确保窗口不是最小化
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        time.sleep(0.1)
                        # 设置为前台窗口
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.2)
                        # 再次确认激活
                        user32.SetActiveWindow(hwnd)
                        log(f"[重启] ✓ 已激活 WeGame 窗口到前端")
                        return False  # 停止遍历
                return True  # 继续遍历
            
            user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(find_wegame_window), 0)
        except Exception as e:
            log(f"[重启] 激活 WeGame 窗口失败: {e}")
        
        # 等待 WeGame 界面加载，先匹配登录按钮（a5.png），失败则匹配游戏图标（a3.png），循环直到成功
        log("[重启] 等待 WeGame 界面加载（a5/a3 交替识别循环）...")
        wait_time = 0
        login_success = False
        
        while wait_time < 30:
            # 第1步：尝试匹配 a5 登录按钮（阈值 0.7）
            found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a5.png", threshold=0.7)
            if found:
                log(f"[重启] 找到登录按钮，匹配度: {conf:.3f}，点击登录...")
                pyautogui.moveTo(x, y, duration=0.2)
                time.sleep(0.1)
                pyautogui.click()
                time.sleep(2)  # 等待登录完成
                login_success = True
                break
            
            # 第2步：a5 失败，尝试匹配 a3 游戏图标（阈值 0.7）
            found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a3.png", threshold=0.7)
            if found:
                log(f"[重启] 找到游戏图标，匹配度: {conf:.3f}（可能已登录），点击启动...")
                pyautogui.moveTo(x, y, duration=0.2)
                time.sleep(0.1)
                pyautogui.click()
                login_success = True
                break
            
            # 第3步：两者都失败，等待后继续循环
            wait_time += 1
            log(f"[重启] a5(登录) 和 a3(图标) 均未识别，等待重试... ({wait_time}/30)")
            time.sleep(1)
        
        if not login_success:
            log("[重启] 超时：a5/a3 交替识别循环 30 次均失败")
            return False
        
        # 等待启动按钮出现（a4.png），最多等待15秒
        log("[重启] 等待启动按钮...")
        wait_time = 0
        while wait_time < 15:
            found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a4.png", threshold=0.7)
            if found:
                log(f"[重启] 找到启动按钮，点击...")
                pyautogui.moveTo(x, y, duration=0.2)
                time.sleep(0.1)
                pyautogui.click()
                break
            
            time.sleep(1)
            wait_time += 1
        
        if wait_time >= 15:
            log("[重启] 超时：未找到启动按钮")
            return False
    
    # 等待游戏启动，最多等待120秒
    log("[重启] 等待游戏启动...")
    wait_time = 0
    while wait_time < 120:
        # 检测游戏窗口
        if detect_game_window("china", silent=True):
            log("[重启] ✓ 游戏窗口已启动")
            break
        
        time.sleep(2)
        wait_time += 2
    
    if wait_time >= 120:
        log("[重启] 超时：游戏未启动")
        return False
    
    # 激活游戏窗口并等待20秒
    log("[重启] 激活游戏窗口...")
    try:
        user32 = ctypes.windll.user32
        hwnd = locator.window["hwnd"]
        user32.SetForegroundWindow(hwnd)
        log("[重启] ✓ 游戏窗口已激活")
    except Exception as e:
        log(f"[重启] 激活窗口失败: {e}")
    
    log("[重启] 等待20秒让游戏加载...")
    time.sleep(20)
    
    # 按回车继续，总共3次，每2秒一次
    log("[重启] 按回车继续游戏...")
    for i in range(3):
        pyautogui.press('enter')
        log(f"[重启] 第 {i+1}/3 次按回车")
        if i < 2:
            time.sleep(2)
    
    log("========== 游戏重启流程完成 ==========")
    return True


def monitor_game_restart():
    """持续监控游戏状态，必要时重启"""
    while True:
        # 检测游戏窗口
        game_detected = detect_game_window("china", silent=True)
        
        if not game_detected:
            log("[监控] 游戏未运行，尝试重启...")
            restart_game_via_wegame()
        
        # 每30秒检查一次
        time.sleep(30)


def match_stash_template():
    """在游戏窗口内使用模板匹配找到仓库位置"""
    global game_window, template_img
    
    # 初始化时间戳（函数属性）
    if not hasattr(match_stash_template, 'last_match_time'):
        match_stash_template.last_match_time = 0.0
    
    if game_window is None:
        log("[仓库匹配] 错误: 未识别游戏窗口")
        return None
    
    if template_img is None:
        log("[仓库匹配] 错误: 未加载仓库模板")
        return None
    
    try:
        # 控制模板匹配频率，每2秒一次
        current_time = time.time()
        if current_time - match_stash_template.last_match_time < 2.0:
            return None
        match_stash_template.last_match_time = current_time
        
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
        
        # 调试：每次匹配都保存对比图
        try:
            debug_dir = "detect_debug"
            os.makedirs(debug_dir, exist_ok=True)
            # 标注最佳匹配位置
            debug_img = search_img.copy()
            cv2.rectangle(debug_img, max_loc, (max_loc[0]+template_w, max_loc[1]+template_h), (0,0,255), 2)
            cv2.putText(debug_img, f"Match: {max_val:.3f}", (max_loc[0], max_loc[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
            # 水平拼接：当前截图 | 模板
            h1, w1 = debug_img.shape[:2]
            h2, w2 = template_img.shape[:2]
            h_max = max(h1, h2)
            canvas1 = np.zeros((h_max, w1, 3), dtype=np.uint8)
            canvas1[:h1] = debug_img
            canvas2 = np.zeros((h_max, w2, 3), dtype=np.uint8)
            canvas2[:h2] = cv2.cvtColor(template_img, cv2.COLOR_BGR2RGB)
            compare = np.hstack([canvas1, canvas2])
            cv2.putText(compare, f"Search ({w1}x{h1})", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            cv2.putText(compare, f"Template ({w2}x{h2})", (w1+5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            cv2.imwrite(f"{debug_dir}/stash_compare.png", compare)
        except Exception:
            pass
        
        if max_val >= 0.5:
            center_x = win["left"] + max_loc[0] + template_w // 2
            center_y = win["top"] + max_loc[1] + template_h // 2
            log(f"[仓库匹配] 找到匹配！坐标: ({center_x}, {center_y}), 匹配度: {max_val:.3f}")
            return (center_x, center_y)
        else:
            log(f"[仓库匹配] 匹配度: {max_val:.3f} (阈值0.5)")
            return None
            
    except Exception as e:
        log(f"[仓库匹配] 失败: {e}")
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
        
        # 配置模板验证失败后，走回退检测
        # fall through to fallback below
    else:
        # 无配置模板时：用宝箱模板做反向验证
        # 原理：宝箱匹配度高 → 宝箱可见 → 仓库未打开
        #       宝箱匹配度低 → 宝箱被UI面板遮挡 → 仓库已打开
        log(f"[仓库检测] 无配置模板，使用反向验证：检测仓库宝箱是否被UI面板遮挡")
        # fall through to fallback below
    
    # ========== 回退检测：用仓库宝箱模板做反向验证 ==========
    # 原理：如果仓库已打开，UI面板会覆盖仓库宝箱，
    # 宝箱模板匹配度大幅下降 → 仓库已打开
    if template_img is not None:
        log(f"[仓库检测] 反向验证：检查仓库宝箱匹配度...")
        with mss.mss() as sct:
            monitor = {
                "top": game_window["top"],
                "left": game_window["left"],
                "width": game_window["width"],
                "height": game_window["height"]
            }
            screenshot = sct.grab(monitor)
            window_img = np.array(screenshot)[:, :, :3]
        
        if window_img.size > 0:
            try:
                gray_win = cv2.cvtColor(window_img, cv2.COLOR_BGR2GRAY)
                gray_tpl = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
                result = cv2.matchTemplate(gray_win, gray_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                
                # 宝箱匹配度大幅下降 → UI面板遮挡 → 仓库已打开
                # 阈值设为 0.5：点击前匹配度约 0.95，点击后如果降到 0.5 以下说明被遮挡
                if max_val < 0.5:
                    log(f"[仓库检测] ✓ 反向验证确认仓库已打开 - 宝箱匹配度降至 {max_val:.3f}（已被UI面板遮挡）")
                    return True, max_val
                else:
                    log(f"[仓库检测] 反向验证：宝箱仍可匹配(匹配度:{max_val:.3f})，仓库可能未打开")
                    log(f"[仓库检测] 提示：如果仓库实际上已打开，说明宝箱未被完全遮挡，需降低反向验证阈值")
            except Exception as e:
                log(f"[仓库检测] 反向验证异常: {e}")
    else:
        log(f"[仓库检测] 无宝箱模板，跳过验证直接执行存仓")
        return True, 1.0
    
    log(f"[仓库检测] [警告] 存仓操作被阻止 - 未识别到有效仓库特征 (阈值: {threshold})")
    return False, 0.0


def load_config():
    """加载配置 - 物品检测 ROI 从配置文件读取，格子坐标由 TemplateLocator 提供"""
    hsv_config = {
        "h_min": 105,
        "h_max": 180,
        "s_min": 70,
        "s_max": 255,
        "v_min": 70,
        "v_max": 255
    }
    roi = {"LEFT": 80, "TOP": 285, "RIGHT": 857, "BOTTOM": 1057}
    stash_open_pos = [900, 380]
    
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
            log("[配置] 从配置文件加载")
        elif os.path.exists(GOOD_CONFIG_PATH):
            with open(GOOD_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                hsv_config.update(config)
            log("[配置] 从 good.json 加载")
    except Exception as e:
        log(f"[配置] 加载失败，使用默认值: {e}")
    
    return {
        "left": roi["LEFT"],
        "top": roi["TOP"],
        "right": roi["RIGHT"],
        "bottom": roi["BOTTOM"],
        "hsv_config": hsv_config,
        "stash_open_pos": stash_open_pos
    }


def generate_stash_cells_from_user_coords():
    """基于用户提供的第一个和最后一个格子坐标生成所有格子 (严格相对坐标)
    
    用户提供 (屏幕绝对坐标, 测量时窗口位于 (78,78)):
    - 第一个格子区域: 左上(525,437) 右下(555,467) -> 中心(540,452), 大小 30x30
    - 最后一个格子中心: (862, 568)
    - 布局: 12列 x 5行 = 60个格子
    
    相对坐标 = 屏幕绝对坐标 - 测量时的窗口位置, 是固定值不随窗口移动变化.
    locator.to_screen(rel_x, rel_y) 自动叠加当前窗口偏移还原屏幕坐标.
    """
    global game_window
    
    # 用户指定的绝对屏幕坐标
    abs_first_center_x = 540
    abs_first_center_y = 452
    abs_last_center_x = 862
    abs_last_center_y = 568
    
    # 测量时的窗口位置 (固定值, 相对坐标以此为基准)
    MEASURE_WINDOW_LEFT = 78
    MEASURE_WINDOW_TOP = 78
    
    # 转换为相对游戏窗口的坐标 (固定值, 不随窗口移动变化)
    rel_first_center_x = abs_first_center_x - MEASURE_WINDOW_LEFT
    rel_first_center_y = abs_first_center_y - MEASURE_WINDOW_TOP
    rel_last_center_x = abs_last_center_x - MEASURE_WINDOW_LEFT
    rel_last_center_y = abs_last_center_y - MEASURE_WINDOW_TOP
    log(f"[存仓] 基准窗口({MEASURE_WINDOW_LEFT},{MEASURE_WINDOW_TOP}) "
        f"绝对({abs_first_center_x},{abs_first_center_y}) "
        f"相对({rel_first_center_x},{rel_first_center_y})")
    
    # 仓库布局
    cols = 12
    rows = 5
    
    # 计算格子间距（使用相对坐标）
    col_spacing = (rel_last_center_x - rel_first_center_x) / (cols - 1)
    row_spacing = (rel_last_center_y - rel_first_center_y) / (rows - 1)
    
    # 格子大小：实际格子 30x30，与 cc.png 模板大小一致
    cell_width = 30
    cell_height = 30
    
    result = []
    idx = 1
    for row in range(rows):
        for col in range(cols):
            center_x = int(rel_first_center_x + col * col_spacing)
            center_y = int(rel_first_center_y + row * row_spacing)
            x1 = center_x - cell_width // 2
            y1 = center_y - cell_height // 2
            x2 = center_x + cell_width // 2
            y2 = center_y + cell_height // 2
            result.append({"region": [x1, y1, x2, y2]})
            idx += 1
    
    log(f"✓ 使用用户坐标生成 {len(result)} 个仓库格子（相对坐标）")
    return result


# =====================================================================
# 自有仓库容量判断模块
# =====================================================================

def load_own_stash_c1_template():
    """加载仓库标签页模板 c1.png"""
    global OWN_STASH_C1_TEMPLATE
    c1_path = "templates/stash/c1.png"
    if os.path.exists(c1_path):
        OWN_STASH_C1_TEMPLATE = cv2.imread(c1_path)
        if OWN_STASH_C1_TEMPLATE is not None:
            log(f"[仓库标签] 已加载标签页模板: {c1_path}, 大小: {OWN_STASH_C1_TEMPLATE.shape[1]}x{OWN_STASH_C1_TEMPLATE.shape[0]}")
            return True
    log(f"[仓库标签] 未找到标签页模板: {c1_path}")
    return False


def generate_own_stash_cells():
    """生成自有仓库 12x12 格子坐标系统（相对游戏窗口坐标）
    
    用户指定的坐标（相对游戏窗口）:
    - 第一个格子: 中心(55, 178)
    - 最后一个格子: 中心(377, 499)
    - 布局: 12列 x 12行 = 144个格子
    
    生成的是相对游戏窗口坐标，通过 locator.to_screen() 转换为屏幕坐标，
    支持窗口移动后自动校准。"""
    global own_stash_cells
    
    # 相对坐标（固定值，不随窗口移动变化）
    # 用户指定: 第一个格子中心(55, 178), 最后一个格子中心(377, 499)
    # 游戏窗口有标题栏/边框偏移，OFFSET 用于微调
    X_OFFSET = -24  # X轴补偿：左移一个格子（左侧边框约29px）
    Y_OFFSET = -62  # Y轴补偿：上移两个格子（标题栏约58px）
    rel_first_cx = 55 + X_OFFSET
    rel_first_cy = 178 + Y_OFFSET
    rel_last_cx = 377 + X_OFFSET
    rel_last_cy = 499 + Y_OFFSET
    
    cols = 12
    rows = 12
    
    # 格子间距
    col_spacing = (rel_last_cx - rel_first_cx) / (cols - 1)
    row_spacing = (rel_last_cy - rel_first_cy) / (rows - 1)
    
    # 格子大小：与背包格子一致，30x30（与 cc.png 模板大小一致）
    # 实际格子间距约 29px，30px 贴近目标格子边缘，80% 中心裁剪排除干扰
    cell_size = 30
    
    result = []
    for row in range(rows):
        for col in range(cols):
            cx = int(rel_first_cx + col * col_spacing)
            cy = int(rel_first_cy + row * row_spacing)
            half = cell_size // 2
            x1 = cx - half
            y1 = cy - half
            x2 = cx + half
            y2 = cy + half
            result.append({
                "region": [x1, y1, x2, y2],
                "center": (cx, cy)
            })
    
    own_stash_cells = result
    log(f"[仓库容量] 生成自有仓库格子: {len(result)} 个 ({cols}x{rows}), "
        f"格子大小: {cell_size}px, 列间距: {col_spacing:.1f}, 行间距: {row_spacing:.1f}")
    return result


def detect_stash_tabs():
    """检测仓库标签页位置（使用 c1.png 模板匹配）
    
    标签页判定范围: 相对窗口坐标 (220, 268) 至 (469, 287)
    在这个范围内通过 c1.png 模板匹配，置信度 > 0.6 的区域判定为标签页。
    按从左到右顺序排列，返回所有检测到的标签页中心坐标。
    
    Returns:
        list of dict: [{"center": (cx, cy), "confidence": float, "index": int}, ...]
        按从左到右排序，index 为标签页编号（从1开始）
    """
    global OWN_STASH_C1_TEMPLATE, game_window
    
    if OWN_STASH_C1_TEMPLATE is None:
        if not load_own_stash_c1_template():
            return []
    
    if game_window is None:
        return []
    
    try:
        # 标签页区域相对坐标（固定值，不随窗口移动变化）
        # 用户指定屏幕坐标(92,144)-(331,161)，基于当前窗口位置(23,62)计算：
        # rel = screen - window = (92-23, 144-62) = (69, 82)
        REL_TAB_X1, REL_TAB_Y1 = 69, 82
        REL_TAB_X2, REL_TAB_Y2 = 308, 99
        
        # 调试：输出当前窗口位置和坐标转换
        if game_window:
            log(f"[仓库标签] 窗口位置: ({game_window['left']}, {game_window['top']})")
            log(f"[仓库标签] 相对坐标: ({REL_TAB_X1},{REL_TAB_Y1}) - ({REL_TAB_X2},{REL_TAB_Y2})")
        
        # 转换为当前屏幕坐标（支持窗口移动后自动校准）
        screen_tab_x1, screen_tab_y1 = locator.to_screen(REL_TAB_X1, REL_TAB_Y1)
        screen_tab_x2, screen_tab_y2 = locator.to_screen(REL_TAB_X2, REL_TAB_Y2)
        
        log(f"[仓库标签] 屏幕坐标: ({screen_tab_x1},{screen_tab_y1}) - ({screen_tab_x2},{screen_tab_y2})")
        
        with mss.mss() as sct:
            monitor = {
                "top": int(screen_tab_y1),
                "left": int(screen_tab_x1),
                "width": int(screen_tab_x2 - screen_tab_x1),
                "height": int(screen_tab_y2 - screen_tab_y1)
            }
            screenshot = sct.grab(monitor)
            tab_region = np.array(screenshot)[:, :, :3]
        
        if tab_region.size == 0:
            return []
        
        # 模板匹配
        gray_region = cv2.cvtColor(tab_region, cv2.COLOR_BGR2GRAY)
        gray_template = cv2.cvtColor(OWN_STASH_C1_TEMPLATE, cv2.COLOR_BGR2GRAY)
        
        th, tw = gray_template.shape
        rh, rw = gray_region.shape
        
        if th > rh or tw > rw:
            # 模板比区域大，缩放模板
            scale = min(rh / th, rw / tw)
            new_th = int(th * scale)
            new_tw = int(tw * scale)
            gray_template = cv2.resize(gray_template, (new_tw, new_th))
            th, tw = gray_template.shape
        
        result = cv2.matchTemplate(gray_region, gray_template, cv2.TM_CCOEFF_NORMED)
        
        # 找到所有匹配置信度 > 0.45 的位置
        matches = []
        threshold = 0.45
        h, w = result.shape
        
        # 使用非极大值抑制：找到所有峰值
        locations = np.where(result >= threshold)
        # 按置信度从高到低排序
        matched_pts = list(zip(locations[1], locations[0]))  # (x, y) in result coords
        matched_vals = [result[y, x] for x, y in matched_pts]
        
        # 非极大值抑制：合并重叠的匹配
        tab_centers = []
        min_distance = tw // 2  # 最小间距为模板宽度的一半
        
        sorted_indices = sorted(range(len(matched_vals)), key=lambda i: matched_vals[i], reverse=True)
        used = set()
        
        for idx in sorted_indices:
            if idx in used:
                continue
            px, py = matched_pts[idx]
            confidence = matched_vals[idx]
            # 屏幕坐标中心
            screen_cx = screen_tab_x1 + px + tw // 2
            screen_cy = screen_tab_y1 + py + th // 2
            tab_centers.append((screen_cx, screen_cy, confidence))
            # 抑制附近匹配
            for j in range(len(matched_pts)):
                if j in used:
                    continue
                if abs(matched_pts[j][0] - px) < min_distance:
                    used.add(j)
        
        # 按 X 坐标从左到右排序
        tab_centers.sort(key=lambda t: t[0])
        
        tabs = []
        for i, (cx, cy, conf) in enumerate(tab_centers):
            tabs.append({
                "center": (int(cx), int(cy)),
                "confidence": round(float(conf), 3),
                "index": i + 1
            })
        
        if tabs:
            tab_info = ", ".join([f"#{t['index']}(conf:{t['confidence']:.3f})" for t in tabs])
            log(f"[仓库标签] 检测到 {len(tabs)} 个标签页: {tab_info}")
            for t in tabs:
                log(f"          - 标签页{t['index']}: 中心({t['center'][0]},{t['center'][1]}) 置信度:{t['confidence']:.3f}")
        else:
            log(f"[仓库标签] 未检测到标签页 (最高置信度: {float(np.max(result)):.3f})")
        
        # 保存调试截图：标签页区域 + 模板对比
        _save_tab_debug_image(tab_region, gray_template, result, threshold, tabs, screen_tab_x1, screen_tab_y1)
        
        return tabs
        
    except Exception as e:
        log(f"[仓库标签] 检测失败: {e}")
        return []


def _save_tab_debug_image(tab_region, gray_template, match_result, threshold, tabs=None, screen_x1=0, screen_y1=0):
    """保存标签页检测调试截图
    
    生成三部分内容并拼接:
    - 左侧: 标签页区域截图（彩色原始图）+ 检测到的标签页标记
    - 中间: matchTemplate 热力图（越亮=置信度越高）
    - 右侧: c1.png 模板
    """
    try:
        debug_dir = "stash_debug"
        os.makedirs(debug_dir, exist_ok=True)
        
        # 1. 原始彩色区域截图 + 标记检测到的标签页
        debug_region = cv2.cvtColor(tab_region, cv2.COLOR_BGR2RGB)
        
        # 在截图上标记每个检测到的标签页（放大标记）
        if tabs:
            for t in tabs:
                # 标签页中心相对于截图的位置
                cx = t["center"][0] - screen_x1
                cy = t["center"][1] - screen_y1
                # 画大号红色圆点标记
                cv2.circle(debug_region, (int(cx), int(cy)), 8, (255, 0, 0), -1)
                cv2.circle(debug_region, (int(cx), int(cy)), 10, (0, 0, 255), 2)
                # 标注编号和置信度（大号）
                label = f"#{t['index']}({t['confidence']:.2f})"
                cv2.putText(debug_region, label, (int(cx) - 25, int(cy) - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        
        # 放大区域截图（2倍放大，让标签页更清晰）
        debug_region = cv2.resize(debug_region, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        
        # 2. matchTemplate 热力图（归一化到0-255显示）
        heatmap = ((match_result + 1) / 2 * 255).astype(np.uint8)
        heatmap_color = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)
        # 放大热力图（2倍）
        heatmap_color = cv2.resize(heatmap_color, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        cv2.putText(heatmap_color, f"Threshold:{threshold:.2f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        max_val = float(np.max(match_result))
        cv2.putText(heatmap_color, f"Max:{max_val:.3f}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        # 3. c1.png 模板（放大2倍）
        th, tw = gray_template.shape
        template_display = cv2.cvtColor(gray_template, cv2.COLOR_GRAY2RGB)
        template_display = cv2.resize(template_display, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
        
        # 拼接: 区域 | 热力图 | 模板
        h1, w1 = debug_region.shape[:2]
        h2, w2 = heatmap_color.shape[:2]
        h3, w3 = template_display.shape[:2]
        h_max = max(h1, h2, h3)
        
        canvas1 = np.zeros((h_max, w1, 3), dtype=np.uint8)
        canvas1[:h1] = debug_region
        canvas2 = np.zeros((h_max, w2, 3), dtype=np.uint8)
        canvas2[:h2] = heatmap_color
        canvas3 = np.zeros((h_max, w3, 3), dtype=np.uint8)
        canvas3[:h3] = template_display
        
        compare = np.hstack([canvas1, canvas2, canvas3])
        
        cv2.putText(compare, "Tab Region (Red=detected)", (10, h_max - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(compare, "Heatmap", (w1 + 10, h_max - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(compare, f"c1.png ({tw}x{th})", (w1 + w2 + 10, h_max - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        save_path = os.path.join(debug_dir, "tab_detect_debug.png")
        cv2.imwrite(save_path, cv2.cvtColor(compare, cv2.COLOR_RGB2BGR))
        log(f"[仓库标签] 调试截图已保存: {save_path}")
        
    except Exception as e:
        log(f"[仓库标签] 保存调试截图失败: {e}")


def switch_stash_tab(target_tab_index):
    """切换到指定仓库标签页
    
    Args:
        target_tab_index: 目标标签页编号（从1开始）
    
    Returns:
        bool: 是否切换成功
    """
    global current_stash_tab
    
    if target_tab_index == current_stash_tab:
        return True  # 已经在目标标签页
    
    # 检测所有标签页
    tabs = detect_stash_tabs()
    if not tabs:
        log(f"[仓库标签] 无法检测标签页，切换失败")
        return False
    
    if target_tab_index > len(tabs):
        log(f"[仓库标签] 目标标签页 {target_tab_index} 超出范围 (共 {len(tabs)} 个)")
        # 回退到第一个标签页
        target_tab_index = 1
    
    target_tab = tabs[target_tab_index - 1]
    cx, cy = target_tab["center"]
    
    log(f"[仓库标签] 切换至标签页 {target_tab_index} → 点击({cx}, {cy})")
    pyautogui.moveTo(cx, cy, duration=0.1)
    time.sleep(0.1)
    pyautogui.click()
    time.sleep(0.3)  # 等待标签页切换动画
    
    current_stash_tab = target_tab_index
    log(f"[仓库标签] ✓ 已切换到标签页 {current_stash_tab}")
    return True


def check_own_stash_capacity(silent=False):
    """检查自有仓库容量（截图 12x12 格子并判断占用率）
    
    流程:
    1. 生成自有仓库 12x12 格子坐标
    2. 遍历每个格子，检查置信度（是否为空格子）
    3. 计算已占用格子比例
    4. 超过 80% 则判定为满仓
    5. 生成可视化反馈截图 stash_debug/own_stash_overview.png
    
    Args:
        silent: 静默模式（不输出每个格子的详细日志）
    
    Returns:
        dict: {
            "total": 144,
            "occupied": 占用数,
            "empty": 空格子数,
            "ratio": 占用率,
            "is_full": 是否满仓 (>80%)
        }
    """
    global own_stash_cells, STASH_FULL_THRESHOLD, EMPTY_CELL_THRESHOLD, game_window
    
    if own_stash_cells is None:
        generate_own_stash_cells()
    
    if not own_stash_cells:
        log("[仓库容量] 未生成自有仓库格子，跳过容量检查")
        return None
    
    if game_window is None:
        log("[仓库容量] 未检测到游戏窗口，跳过容量检查")
        return None
    
    total = len(own_stash_cells)
    occupied = 0
    cell_results = []  # [(idx, confidence, is_occupied), ...]
    
    log(f"[仓库容量] 开始检查自有仓库容量 (共 {total} 个格子)...")
    
    # 第一步：遍历所有格子，记录置信度
    for idx, cell in enumerate(own_stash_cells, 1):
        region = cell["region"]
        confidence = check_cell_confidence(region, 1000 + idx)
        is_occupied = confidence < EMPTY_CELL_THRESHOLD
        if is_occupied:
            occupied += 1
        cell_results.append((idx, confidence, is_occupied))
    
    ratio = occupied / total
    is_full = ratio >= STASH_FULL_THRESHOLD
    
    log(f"[仓库容量] 自有仓库: {occupied}/{total} 已占用 ({ratio:.1%}), "
        f"满仓阈值: {STASH_FULL_THRESHOLD:.0%}, "
        f"{'[满仓]' if is_full else '[未满]'}")
    
    # 第二步：生成可视化反馈截图
    try:
        _generate_stash_overview_image(cell_results)
    except Exception as e:
        log(f"[仓库容量] 生成概览图失败: {e}")
    
    # 第三步：检测标签页并生成调试截图（便于调试）
    log(f"[仓库容量] 同时检测仓库标签页...")
    detect_stash_tabs()
    
    return {
        "total": total,
        "occupied": occupied,
        "empty": total - occupied,
        "ratio": ratio,
        "is_full": is_full
    }


def _generate_stash_overview_image(cell_results):
    """生成自有仓库容量可视化概览图
    
    截图整个仓库区域，在每个格子上绘制彩色边框：
    - 红色边框 = 有物品（已占用）
    - 绿色边框 = 空格子
    左上角显示已占用/总数统计
    
    Args:
        cell_results: [(idx, confidence, is_occupied), ...]
    """
    global own_stash_cells, game_window
    
    if not own_stash_cells or not game_window:
        return
    
    cols = 12
    rows = 12
    
    # 计算仓库区域范围（相对坐标）
    regions = [c["region"] for c in own_stash_cells]
    all_x1 = [r[0] for r in regions]
    all_y1 = [r[1] for r in regions]
    all_x2 = [r[2] for r in regions]
    all_y2 = [r[3] for r in regions]
    
    rel_x1 = min(all_x1) - 5
    rel_y1 = min(all_y1) - 5
    rel_x2 = max(all_x2) + 5
    rel_y2 = max(all_y2) + 5
    
    # 转换为屏幕坐标
    scr_x1, scr_y1 = locator.to_screen(rel_x1, rel_y1)
    scr_x2, scr_y2 = locator.to_screen(rel_x2, rel_y2)
    
    # 截图整个仓库区域
    with mss.mss() as sct:
        monitor = {
            "top": int(scr_y1),
            "left": int(scr_x1),
            "width": max(1, int(scr_x2 - scr_x1)),
            "height": max(1, int(scr_y2 - scr_y1))
        }
        screenshot = sct.grab(monitor)
        overview = np.array(screenshot)[:, :, :3].copy()
    
    if overview.size == 0:
        return
    
    # 在截图上绘制格子边框
    for idx, confidence, is_occupied in cell_results:
        region = own_stash_cells[idx - 1]["region"]
        # 转换为相对于截图的坐标
        local_x1 = int(region[0] - rel_x1)
        local_y1 = int(region[1] - rel_y1)
        local_x2 = int(region[2] - rel_x1)
        local_y2 = int(region[3] - rel_y1)
        
        color = (0, 0, 255) if is_occupied else (0, 255, 0)  # BGR: 红=占用, 绿=空格
        thickness = 1
        cv2.rectangle(overview, (local_x1, local_y1), (local_x2, local_y2), color, thickness)
    
    # 左上角标注统计信息
    occupied_count = sum(1 for _, _, occ in cell_results if occ)
    total_count = len(cell_results)
    ratio = occupied_count / total_count
    
    # 半透明背景
    overlay = overview.copy()
    cv2.rectangle(overlay, (0, 0), (280, 60), (0, 0, 0), -1)
    overview = cv2.addWeighted(overview, 0.6, overlay, 0.4, 0)
    
    text1 = f"Occupied: {occupied_count}/{total_count} ({ratio:.1%})"
    text2 = "RED=Occupied  GREEN=Empty"
    text3 = time.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(overview, text1, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(overview, text2, (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(overview, text3, (8, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
    
    # 保存
    debug_dir = "stash_debug"
    os.makedirs(debug_dir, exist_ok=True)
    save_path = os.path.join(debug_dir, "own_stash_overview.png")
    cv2.imwrite(save_path, overview)
    log(f"[仓库容量] 概览图已保存: {save_path}")


def load_stash_cells():
    """加载仓库格子 - 优先使用用户坐标生成，其次 TemplateLocator，最后配置文件
    
    支持的来源（优先级从高到低）:
    1. 用户坐标生成（硬编码的第一个和最后一个格子坐标）
    2. TemplateLocator 动态生成
    3. auto_buy_config.json -> cells_map
    4. inventory_config.json -> target_cells
    5. inventory_hash_config.json -> cells
    """
    
    # 优先使用用户坐标生成的格子
    user_cells = generate_stash_cells_from_user_coords()
    if user_cells:
        return user_cells
    
    # 其次使用 TemplateLocator 动态生成的格子
    locator_cells = get_stash_cells()
    if locator_cells:
        log(f"✓ 使用 TemplateLocator 动态生成的 {len(locator_cells)} 个仓库格子")
        return locator_cells
    
    # 回退到配置文件
    # 格式1: auto_buy_config.json -> cells_map
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            cells_map = config.get("cells_map", [])
            if cells_map:
                result = []
                for cell in cells_map:
                    # 支持两种格式:
                    # 格式1: [[x1,y1],[x2,y2]] - 数字数组
                    # 格式2: [["x1 y1"],["x2 y2"]] - 空格分隔的字符串（PowerShell处理后的格式）
                    if isinstance(cell, list) and len(cell) == 2:
                        p1, p2 = cell
                        # 尝试解析 p1
                        if isinstance(p1, list) and len(p1) >= 2:
                            # 格式1: 数字数组
                            x1, y1 = int(p1[0]), int(p1[1])
                        elif isinstance(p1, str):
                            # 格式2: 空格分隔的字符串
                            coords = p1.split()
                            if len(coords) >= 2:
                                x1, y1 = int(coords[0]), int(coords[1])
                            else:
                                continue
                        else:
                            continue
                        # 尝试解析 p2
                        if isinstance(p2, list) and len(p2) >= 2:
                            x2, y2 = int(p2[0]), int(p2[1])
                        elif isinstance(p2, str):
                            coords = p2.split()
                            if len(coords) >= 2:
                                x2, y2 = int(coords[0]), int(coords[1])
                            else:
                                continue
                        else:
                            continue
                        result.append({"region": [x1, y1, x2, y2]})
                log(f"✓ 从 {CONFIG_PATH} 加载 {len(result)} 个仓库格子 (cells_map)")
                return result
        except Exception as e:
            log(f"从 {CONFIG_PATH} 加载 cells_map 失败: {e}")
    
    # 格式2: inventory_config.json -> target_cells
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
    
    # 格式3: inventory_hash_config.json -> cells
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

    if game_window is None:
        log("[动态识别] 未识别游戏窗口")
        return []

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)

        roi = config.get("roi", {})
        if not roi:
            log("[动态识别] 未配置 roi 区域")
            return []

        # ROI 坐标现在是「相对游戏窗口的」，转换为屏幕绝对坐标
        rel_left = int(roi.get("LEFT", 0))
        rel_top = int(roi.get("TOP", 0))
        rel_right = int(roi.get("RIGHT", 0))
        rel_bottom = int(roi.get("BOTTOM", 0))
        roi_left = game_window["left"] + rel_left
        roi_top = game_window["top"] + rel_top
        roi_right = game_window["left"] + rel_right
        roi_bottom = game_window["top"] + rel_bottom
        
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
                
                # 购买完成后强制延迟2秒，再进入下一识别周期
                log(f"[动态识别] ⏳ 购买完成，等待 2 秒后继续识别...")
                time.sleep(2.0)
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
                
                # cx, cy 现在是相对游戏窗口的坐标 → 转换为屏幕绝对坐标
                screen_cx, screen_cy = locator.to_screen(cx, cy)

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
                # 格式1: cells_map [[[x1,y1],[x2,y2]], ...]  → 相对游戏窗口坐标
                p1, p2 = cell
                if isinstance(p1, list) and len(p1) >= 2 and isinstance(p2, list) and len(p2) >= 2:
                    x1, y1 = p1[0], p1[1]
                    x2, y2 = p2[0], p2[1]
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    screen_cx, screen_cy = locator.to_screen(cx, cy)
                    pyautogui.click(screen_cx, screen_cy)
            elif isinstance(cell, dict) and "region" in cell:
                # 格式2: cells [{"region":[x1,y1,x2,y2]}, ...]  → 相对游戏窗口坐标
                region = cell.get("region", [])
                if len(region) >= 4:
                    x1, y1, x2, y2 = region
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    screen_cx, screen_cy = locator.to_screen(cx, cy)
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
    global game_window, just_purchased
    log("========== AutoBuy 自动购买工具 (智能存仓版) ==========")
    log("存仓条件：每次购买后F5回城自动执行存仓")
    log("支持游戏闪退后自动重启（国服）")
    
    # 设置默认服务器为国服
    server = "china"
    
    # 初始化：尝试识别游戏窗口
    log("[初始化] 正在识别游戏窗口...")
    if not detect_game_window("china"):
        log("[初始化] 未找到游戏窗口，尝试重启游戏...")
        # 尝试通过 WeGame 重启游戏
        if not restart_game_via_wegame():
            log("[错误] 无法启动游戏，退出")
            return
    
    # 启动游戏监控线程
    log("[初始化] 启动游戏监控线程...")
    monitor_thread = threading.Thread(target=monitor_game_restart, daemon=True)
    monitor_thread.start()
    
    # 初始化：使用 TemplateLocator 自动定位 Inventory 和 Stash
    log(f"[初始化] 正在使用 TemplateLocator 定位 UI...")
    locator_result = init_template_locator(server)
    if locator_result["inventory_ok"]:
        log(f"[初始化] ✓ Inventory 定位成功")
    else:
        log(f"[初始化] ⚠️  Inventory 定位失败，将使用配置文件")
    if locator_result["stash_ok"]:
        log(f"[初始化] ✓ Stash 定位成功")
    else:
        log(f"[初始化] ⚠️  Stash 定位失败，将使用配置文件")
    
    # 初始化：加载仓库模板
    log("[初始化] 正在加载仓库模板...")
    if not load_template():
        log("[警告] 未找到仓库模板，请使用 stash_debugger.py 保存模板")
    
    # 初始化：加载仓库标签页模板
    load_own_stash_c1_template()
    # 初始化：生成自有仓库格子坐标
    generate_own_stash_cells()
    
    cfg = load_config()
    # config 中的坐标是「相对游戏窗口的」，运行时转换为屏幕绝对坐标
    rel_left, rel_top, rel_right, rel_bottom = cfg["left"], cfg["top"], cfg["right"], cfg["bottom"]
    left = game_window["left"] + rel_left
    top = game_window["top"] + rel_top
    right = game_window["left"] + rel_right
    bottom = game_window["top"] + rel_bottom
    hsv_config = cfg["hsv_config"]

    # 调试：输出实际加载的配置
    log(f"[调试] 加载的检测区域(相对): LEFT={rel_left}, TOP={rel_top}, RIGHT={rel_right}, BOTTOM={rel_bottom}")
    log(f"[调试] 游戏窗口位置: ({game_window['left']}, {game_window['top']})")
    log(f"[调试] 检测区域(屏幕): LEFT={left}, TOP={top}, RIGHT={right}, BOTTOM={bottom}")
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
    has_purchased = False  # 是否已购买过
    global just_purchased
    just_purchased = False  # 是否刚刚购买（用于控制一次完整的购买-存仓流程）
    
    # 日志节流
    last_duplicate_log_time = 0
    last_cpu_log_time = 0
    DUPLICATE_LOG_INTERVAL = 3
    CPU_LOG_INTERVAL = 5
    
    log("开始主循环...")
    
    while True:
        loop_count += 1
        current_time = time.time()
        
        # ===== 窗口位置实时追踪与坐标校准 =====
        # 使用 WindowTracker 快速检测窗口移动（GetWindowRect，微秒级）
        moved, delta_x, delta_y, wl, wt, ww, wh = window_tracker.check()
        if moved:
            # 窗口发生了移动，立即同步位置到 locator 和 game_window
            window_tracker.sync_to_locator()
            log(f"[坐标校准] 窗口移动 delta=({delta_x:+d},{delta_y:+d})，已自动校准坐标系统")
        
        # 兜底：每 300 轮（约30秒）通过完整窗口检测重新校准
        if loop_count % 300 == 0:
            try:
                detect_game_window("china", silent=True)
            except Exception:
                pass
        
        # CPU监控：每5秒输出一次
        if current_time - last_cpu_log_time > CPU_LOG_INTERVAL:
            cpu_percent = psutil.cpu_percent(interval=None)
            log(f"【CPU】当前使用率: {cpu_percent}%")
            last_cpu_log_time = current_time
        
        # ========== 持续检测模式：按优先级检测 ==========
        
        # 检测游戏窗口是否在前台激活
        window_is_active = locator.is_active()
        
        # 每轮使用最新 game_window 计算检测区域（窗口移动时自动跟随）
        if game_window and isinstance(game_window, dict):
            current_left = game_window["left"] + rel_left
            current_top = game_window["top"] + rel_top
            current_right = game_window["left"] + rel_right
            current_bottom = game_window["top"] + rel_bottom
        else:
            current_left, current_top, current_right, current_bottom = left, top, right, bottom
        
        # 1. 最高优先级：检测高亮物品
        items = None
        try:
            items = detect_highlights(current_left, current_top, current_right, current_bottom, hsv_config)
        except Exception as e:
            log(f"【循环 #{loop_count}】检测失败: {e}")
        
        # 2. 第二优先级：检测截图按钮（仅当没有检测到物品且窗口在前台激活时）
        screenshot_btn_found = False
        screenshot_confidence = 0.0
        screenshot_btn_screen_x = 0
        screenshot_btn_screen_y = 0
        if not items and window_is_active:
            try:
                screenshot_btn_found, screenshot_confidence, screenshot_btn_screen_x, screenshot_btn_screen_y = detect_screenshot_button()
            except Exception as e:
                log(f"【循环 #{loop_count}】截图按钮检测失败: {e}")
        
        # 3. 低优先级：检测仓库位置（仅当没有检测到物品和截图按钮，且刚刚购买过且窗口在前台激活时才检测）
        stash_pos = None
        if not items and not screenshot_btn_found and has_purchased and just_purchased and window_is_active:
            try:
                stash_pos = match_stash_template()
            except Exception as e:
                log(f"【循环 #{loop_count}】仓库检测失败: {e}")
        
        # 处理检测结果
        if items and len(items) > 0:
            # 检测到物品 - 最高优先级，立即购买
            max_item = max(items, key=lambda x: x["area"])
            rx, ry, rw, rh = max_item["bbox"]
            screen_x = current_left + rx + rw // 2
            screen_y = current_top + ry + rh // 2
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
            has_purchased = True  # 标记已购买
            just_purchased = True  # 标记刚刚购买，开始存仓流程
            
            log(f"  -> 成功购买！累计购买: {total_buy}")
            
            # 购买完成后按 ESC 关闭购买对话框
            time.sleep(0.15)
            pyautogui.press('esc')
            log(f"  -> 已按 ESC 关闭对话框")
            
            # 移动鼠标到游戏窗口中心（相对坐标转换为屏幕绝对坐标）
            safe_screen_x, safe_screen_y = locator.to_screen(game_window["width"] // 2, game_window["height"] // 2)
            pyautogui.moveTo(safe_screen_x, safe_screen_y)
            log(f"  -> 鼠标移至安全位置 ({safe_screen_x}, {safe_screen_y})")
            
            time.sleep(0.3)
            
            # ========== 购买完成后处理 ==========
            # 检测截图按钮替代F5回城（仅当窗口在前台激活时）
            if window_is_active:
                btn_found, btn_conf, btn_sx, btn_sy = detect_screenshot_button()
                log(f"点击截图按钮回城: 置信度={btn_conf:.4f}, 屏幕坐标=({btn_sx}, {btn_sy})")
                
                if btn_found:
                    pyautogui.moveTo(btn_sx, btn_sy, duration=0.1)
                    time.sleep(0.1)
                    pyautogui.click()
                else:
                    log(f"⚠️ 截图按钮置信度不足({btn_conf:.4f})，跳过点击")
                    # 置信度不足时不点击，等待主循环检测到后再处理
                
                # 购买完成后等待2秒，然后继续检测（最高优先级）
                log("等待2秒后继续检测...")
                time.sleep(2)
            else:
                log("⚠️ 窗口不在前台激活，等待窗口激活...")
                time.sleep(0.5)
            
            # 重置购买位置，允许购买下一个物品
            last_buy_pos = None
            
        elif screenshot_btn_found:
            # 检测到截图按钮 - 第二优先级（仅当窗口在前台激活时点击）
            if window_is_active:
                log(f"【循环 #{loop_count}】检测到截图按钮: 屏幕坐标=({screenshot_btn_screen_x}, {screenshot_btn_screen_y})，置信度: {screenshot_confidence:.4f}，点击...")
                
                pyautogui.moveTo(screenshot_btn_screen_x, screenshot_btn_screen_y, duration=0.1)
                time.sleep(0.1)
                pyautogui.click()
                
                log(f"【循环 #{loop_count}】✓ 已点击截图按钮")
            else:
                log(f"【循环 #{loop_count}】⚠️ 窗口未激活，等待...")
            
            # 继续下一轮检测
            time.sleep(0.5)
            
        elif stash_pos and can_execute_storage() and window_is_active:
            # 检测到仓库 - 执行存仓（低优先级，且窗口必须在前台激活）
            x, y = stash_pos
            log(f"【循环 #{loop_count}】检测到仓库宝箱: ({x}, {y})，准备点击打开...")
            
            # ===== 点击仓库（单次点击 + 等待UI打开）=====
            # 注：双击可能导致第一次触发了打开动画，第二次取消了它
            pyautogui.moveTo(x, y, duration=0.1)
            time.sleep(0.2)
            pyautogui.click()
            log(f"[仓库] 已点击仓库宝箱，等待UI面板打开...")
            
            # 等待仓库UI面板打开，最多等待3秒
            wait_start = time.time()
            while time.time() - wait_start < 3:
                # 每0.5秒检查一次窗口是否激活
                if locator.is_active():
                    time.sleep(0.5)  # 窗口激活，等待让UI完全打开
                    break
                log("[仓库] 窗口未激活，等待激活...")
                time.sleep(0.2)
            
            # 验证仓库是否真的打开
            stash_det_config = load_stash_detection_config()
            is_opened, conf = verify_stash_opened(
                stash_det_config, max_retry=3, retry_interval=0.5
            )
            
            if is_opened:
                log(f"[存仓] ✓ 仓库已打开 - 置信度: {conf:.3f}")
                
                # ===== 自有仓库容量检查 =====
                log(f"[存仓] [仓位标签页 {current_stash_tab}] 检查自有仓库容量...")
                capacity = check_own_stash_capacity()
                if capacity and capacity["is_full"]:
                    log(f"[存仓] [仓位标签页 {current_stash_tab}] 自有仓库已满 "
                        f"({capacity['occupied']}/{capacity['total']}={capacity['ratio']:.1%})，切换标签页...")
                    next_tab = current_stash_tab + 1
                    switch_stash_tab(next_tab)
                    log(f"[存仓] [仓位标签页 {current_stash_tab}] 切换完成，继续存仓...")
                
                log(f"[存仓] [仓位标签页 {current_stash_tab}] 开始存仓...")
                perform_stash_with_confidence(stash_cells)
                log(f"[存仓] [仓位标签页 {current_stash_tab}] 存仓完成")
                
                # ===== 存仓完成后：先基于高亮识别判断购买是否成功 =====
                # 优化逻辑：不再立即进行仓库检测，而是先检查是否有新的购买需求
                # 只有确认购买成功后，才在后续循环中触发仓库检测
                try:
                    # 使用当前窗口位置重新计算检测区域（确保窗口移动后坐标正确）
                    if game_window and isinstance(game_window, dict):
                        check_left = game_window["left"] + rel_left
                        check_top = game_window["top"] + rel_top
                        check_right = game_window["left"] + rel_right
                        check_bottom = game_window["top"] + rel_bottom
                    else:
                        check_left, check_top, check_right, check_bottom = left, top, right, bottom
                    
                    post_items = detect_highlights(check_left, check_top, check_right, check_bottom, hsv_config)
                    if post_items and len(post_items) > 0:
                        log(f"[流程优化] 存仓后检测到 {len(post_items)} 个高亮物品，购买成功确认，将触发仓库检测")
                        just_purchased = True
                    else:
                        log(f"[流程优化] 存仓后未检测到高亮物品，跳过仓库检测，等待下一次购买")
                except Exception as e:
                    log(f"[流程优化] 存仓后购买检测异常: {e}")
            else:
                log(f"[存仓] 点击后未打开")
            
            # 继续下一轮检测
            time.sleep(0.5)
            
        else:
            # 未检测到任何内容，等待后继续循环
            time.sleep(0.1)


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
        
        # ===== 自有仓库容量检查 =====
        print(f"[测试] [仓位标签页 {current_stash_tab}] 检查自有仓库容量...", flush=True)
        capacity = check_own_stash_capacity()
        if capacity and capacity["is_full"]:
            print(f"[测试] [仓位标签页 {current_stash_tab}] 自有仓库已满 "
                  f"({capacity['occupied']}/{capacity['total']}={capacity['ratio']:.1%})，切换标签页...", flush=True)
            next_tab = current_stash_tab + 1
            switch_stash_tab(next_tab)
            print(f"[测试] [仓位标签页 {current_stash_tab}] 切换完成，继续存仓...", flush=True)
        
        # 执行智能存仓（基于置信度）
        print(f"[测试] [仓位标签页 {current_stash_tab}] 开始执行智能存仓（基于置信度）...", flush=True)
        perform_stash_with_confidence(stash_cells)
        print(f"[测试] [仓位标签页 {current_stash_tab}] ✓ 存仓测试完成！", flush=True)
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
    parser.add_argument(
        "-s", "--server", 
        default="china",
        help="服务器类型: china 或 global (默认: china)"
    )
    parser.add_argument(
        "-g", "--game",
        default=None,
        help="游戏可执行文件路径"
    )
    args = parser.parse_args()
    
    # 存储游戏路径到全局变量
    if args.game:
        global GAME_PATH
        GAME_PATH = args.game
        log(f"[启动] 使用自定义游戏路径: {GAME_PATH}")
    
    # 存储服务器类型到全局变量
    if args.server:
        global SERVER_TYPE
        SERVER_TYPE = args.server
        log(f"[启动] 服务器类型: {SERVER_TYPE}")
    
    # 如果是测试模式，直接执行存仓测试
    if args.test_stash:
        test_stash_flow()
    else:
        main()
