#!/usr/bin/env python3
"""
AutoBuy 游戏自动化助手 - 图形界面版
版本: 2.0.0
功能：图形界面启动游戏 + 自动购买 + 存仓
"""

import os
import sys
import time
import json
import cv2
import numpy as np
import mss
import pyautogui
import psutil
import ctypes
import threading
import logging
import traceback
import subprocess
from datetime import datetime
from ctypes import wintypes
from tkinter import Tk, Label, Entry, Button, Frame, Radiobutton, StringVar, messagebox, filedialog, ttk, scrolledtext

# ==================== GUI 相关代码 ====================
VERSION = "2.0.0"
MIN_WIDTH = 700
MIN_HEIGHT = 550
LOG_MAX_SIZE = 5 * 1024 * 1024
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "AutoBuyLogs")

# 日志配置
def setup_logging():
    """设置日志系统"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y%m%d')}.log")
    
    if os.path.exists(log_file) and os.path.getsize(log_file) > LOG_MAX_SIZE:
        backup_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y%m%d')}_backup.log")
        if os.path.exists(backup_file):
            os.remove(backup_file)
        os.rename(log_file, backup_file)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def log_info(message):
    logging.info(message)

def log_error(message):
    logging.error(message)

def log_exception(exc):
    logging.error(f"异常: {exc}\n{traceback.format_exc()}")

# ==================== 自动化相关代码 ====================
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# 全局变量
game_window = None
stash_cells = []
has_purchased = False
just_purchased = False
running = False
automation_thread = None
topmost_enabled = True  # 窗口置顶功能开关

def log(message):
    """带时间戳的日志输出"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

class LogAggregator:
    """日志聚合器"""
    def __init__(self):
        self.last_messages = {}
        self.agg_counts = {}
        self.throttle_interval = 5.0
    
    def log_throttled(self, message, key=None, force=False):
        if key is None:
            key = message
        current_time = time.time()
        if force or key not in self.last_messages or \
           (current_time - self.last_messages[key]) >= self.throttle_interval:
            if key in self.agg_counts and self.agg_counts[key] > 0:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message} (已聚合 {self.agg_counts[key]} 次)")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")
            self.last_messages[key] = current_time
            self.agg_counts[key] = 0
        else:
            self.agg_counts[key] = self.agg_counts.get(key, 0) + 1
    
    def log_critical(self, message):
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

class WindowLocator:
    """游戏窗口定位器"""
    def __init__(self):
        self._window = None
        self._process_name = "Path of Exile"
    
    def find_window(self):
        """查找游戏窗口"""
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        
        result = {}
        def callback(hwnd, extra):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value
                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, 256)
                if "Path of Exile" in title or "Exile" in title:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    result['hwnd'] = hwnd
                    result['title'] = title
                    result['left'] = rect.left
                    result['top'] = rect.top
                    result['width'] = rect.right - rect.left
                    result['height'] = rect.bottom - rect.top
                    return False
            return True
        
        user32.EnumWindows(EnumWindowsProc(callback), 0)
        self._window = result if result else None
        return self._window
    
    def is_active(self):
        """检测窗口是否在前台激活"""
        if self._window is None:
            return False
        try:
            user32 = ctypes.windll.user32
            hwnd = self._window.get("hwnd", 0)
            if hwnd == 0:
                return False
            foreground_hwnd = user32.GetForegroundWindow()
            return hwnd == foreground_hwnd
        except:
            return False
    
    def to_screen(self, x, y):
        """相对坐标转屏幕绝对坐标"""
        if self._window:
            return x + self._window["left"], y + self._window["top"]
        return x, y
    
    def to_screen_monitor(self, x, y):
        """相对坐标转MSS屏幕坐标"""
        if self._window:
            return x + self._window["left"], y + self._window["top"]
        return x, y
    
    def set_always_on_top(self, enable=True):
        """设置窗口置顶（始终在最前面）
        
        Args:
            enable: True=置顶, False=取消置顶
        
        Windows 使用 SetWindowPos + HWND_TOPMOST
        """
        if self._window is None:
            return False
        
        try:
            user32 = ctypes.windll.user32
            
            HWND_NOTOPMOST = -2
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            
            hwnd = self._window.get("hwnd", 0)
            if hwnd == 0:
                return False
            
            if enable:
                # 设置为置顶窗口
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )
                log(f"[置顶] ✓ 游戏窗口已置顶")
            else:
                # 取消置顶
                user32.SetWindowPos(
                    hwnd,
                    HWND_NOTOPMOST,
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                )
                log(f"[置顶] 游戏窗口已取消置顶")
            
            return True
        except Exception as e:
            log(f"[置顶] 设置置顶失败: {e}")
            return False
    
    def is_always_on_top(self):
        """检测窗口是否已置顶"""
        if self._window is None:
            return False
        
        try:
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            
            hwnd = self._window.get("hwnd", 0)
            if hwnd == 0:
                return False
            
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            return (ex_style & WS_EX_TOPMOST) != 0
        except:
            return False
    
    def bring_to_front(self):
        """将窗口带到前台"""
        if self._window is None:
            return False
        
        try:
            user32 = ctypes.windll.user32
            hwnd = self._window.get("hwnd", 0)
            
            if hwnd == 0:
                return False
            
            # 如果窗口最小化，先恢复
            SW_SHOWMINIMIZED = 2
            user32.ShowWindow(hwnd, SW_SHOWMINIMIZED)
            time.sleep(0.1)
            
            # 设置为前台窗口
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            
            # 激活窗口
            user32.SetActiveWindow(hwnd)
            
            return True
        except Exception as e:
            log(f"[置顶] 窗口前置失败: {e}")
            return False
    
    def ensure_topmost(self):
        """确保窗口置顶，如果被其他窗口覆盖则恢复置顶"""
        global topmost_enabled
        
        if self._window is None:
            return False
        
        # 如果置顶功能未启用，只检测窗口是否为活动窗口
        if not topmost_enabled:
            if not self.is_active():
                return self.bring_to_front()
            return True
        
        # 检查是否已置顶
        if not self.is_always_on_top():
            return self.set_always_on_top(True)
        
        # 检查是否为活动窗口
        if not self.is_active():
            return self.bring_to_front()
        
        return True

locator = WindowLocator()

# ==================== 模板匹配函数 ====================
def template_match_on_screen(template_path, threshold=0.7):
    """在整个屏幕上进行模板匹配"""
    if not os.path.exists(template_path):
        return False, 0, 0, 0
    
    template = cv2.imread(template_path)
    if template is None:
        return False, 0, 0, 0
    
    with mss.mss() as sct:
        screenshot = sct.grab(sct.monitors[1])
        screen = np.array(screenshot)
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        
        result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= threshold:
            h, w = template_gray.shape
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            return True, center_x, center_y, max_val
    
    return False, 0, 0, 0

# ==================== 游戏启动函数 ====================
def start_game_via_wegame(game_path=None):
    """通过WeGame启动游戏"""
    log("[启动] 开始启动游戏...")
    
    # 检查WeGame
    target_wegame_path = r"D:\Program Files\WeGame\wegame.exe"
    wegame_running = False
    
    for proc in psutil.process_iter(['name', 'exe']):
        try:
            if proc.name().lower() == 'wegame.exe':
                wegame_running = True
                log(f"[启动] 检测到WeGame已运行: {proc.exe()}")
                break
        except:
            pass
    
    # 如果WeGame未运行，启动它
    if not wegame_running:
        wegame_paths = [
            r"D:\Program Files\WeGame\wegame.exe",
            r"C:\Program Files (x86)\Tencent\WeGame\wegame.exe",
            r"D:\Program Files (x86)\Tencent\WeGame\wegame.exe",
        ]
        for path in wegame_paths:
            if os.path.exists(path):
                os.startfile(path)
                log(f"[启动] 已启动WeGame: {path}")
                time.sleep(5)
                break
    
    # 等待并激活WeGame窗口
    log("[启动] 激活WeGame窗口...")
    try:
        user32 = ctypes.windll.user32
        def find_wegame_window(hwnd, extra):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if "WeGame" in buffer.value or "wegame" in buffer.value.lower():
                    user32.ShowWindow(hwnd, 1)  # SW_RESTORE
                    time.sleep(0.2)
                    user32.SetForegroundWindow(hwnd)
                    time.sleep(0.3)
                    return False
            return True
        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(find_wegame_window), 0)
    except Exception as e:
        log(f"[启动] 激活WeGame失败: {e}")
    
    time.sleep(2)
    
    # 循环匹配 a5.png 和 a3.png
    log("[启动] 等待WeGame界面（循环匹配a5和a3）...")
    found_login = False
    found_game = False
    
    for _ in range(60):  # 最多等待60秒
        # 先尝试匹配登录按钮 (a5.png)
        if not found_login:
            found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a5.png", 0.7)
            if found:
                log(f"[启动] 找到登录按钮，点击登录...")
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.click()
                time.sleep(2)
                found_login = True
                log("[启动] 已登录，等待游戏图标...")
        
        # 尝试匹配游戏图标 (a3.png)
        if not found_game:
            found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a3.png", 0.7)
            if found:
                log(f"[启动] 找到游戏图标，点击启动...")
                pyautogui.moveTo(x, y, duration=0.2)
                pyautogui.click()
                time.sleep(2)
                found_game = True
        
        # 如果两个都找到了，跳出循环
        if found_login and found_game:
            break
        
        time.sleep(1)
    
    # 匹配启动按钮 (a4.png)
    log("[启动] 等待启动按钮...")
    for _ in range(60):
        found, x, y, conf = template_match_on_screen(r"f:\scgit\templates\stash\a4.png", 0.7)
        if found:
            log(f"[启动] 找到启动按钮，点击...")
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
            break
        time.sleep(1)
    
    # 等待游戏启动
    log("[启动] 等待游戏启动...")
    locator.find_window()
    start_time = time.time()
    while time.time() - start_time < 120:
        if locator._window:
            log(f"[启动] 游戏窗口已找到")
            time.sleep(3)
            
            # 设置游戏窗口置顶
            log("[启动] 设置游戏窗口置顶...")
            locator.set_always_on_top(True)
            time.sleep(1)
            
            # 按回车3次
            for i in range(3):
                pyautogui.press('enter')
                time.sleep(2)
            return True
        time.sleep(2)
    
    return False

# ==================== 自动化核心函数 ====================
def load_template():
    """加载仓库模板"""
    template_path = r"f:\scgit\templates\stash\a2.png"
    if os.path.exists(template_path):
        template = cv2.imread(template_path)
        if template is not None:
            return template
    return None

def detect_screenshot_button():
    """检测截图按钮"""
    if not locator._window:
        return False, 0, 0
    
    x1 = locator._window["left"] + 600
    y1 = locator._window["top"] + 800
    x2 = x1 + 200
    y2 = y1 + 150
    
    with mss.mss() as sct:
        screenshot = sct.grab((x1, y1, x2, y2))
        img = np.array(screenshot)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        white_ratio = np.sum(thresh == 255) / thresh.size
        
        if white_ratio > 0.3:
            center_x = locator._window["left"] + 700
            center_y = locator._window["top"] + 875
            return True, center_x, center_y
    
    return False, 0, 0

def detect_highlights():
    """检测高亮物品"""
    if not locator._window:
        return None
    
    x1 = locator._window["left"] + 100
    y1 = locator._window["top"] + 500
    x2 = x1 + 400
    y2 = y1 + 400
    
    with mss.mss() as sct:
        screenshot = sct.grab((x1, y1, x2, y2))
        img = np.array(screenshot)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        lower_yellow = np.array([20, 100, 100])
        upper_yellow = np.array([30, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            if w > 15 and h > 15:
                center_x = locator._window["left"] + x1 + x + w // 2
                center_y = locator._window["top"] + y1 + y + h // 2
                return (center_x, center_y)
    
    return None

def match_stash_template():
    """匹配仓库模板"""
    template = load_template()
    if template is None:
        log("[仓库匹配] 错误: 未加载仓库模板")
        return False, 0, 0
    
    if not locator._window:
        return False, 0, 0
    
    with mss.mss() as sct:
        monitor = {
            "left": locator._window["left"],
            "top": locator._window["top"],
            "width": locator._window["width"],
            "height": locator._window["height"]
        }
        screenshot = sct.grab(monitor)
        screen = np.array(screenshot)
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        
        result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= 0.5:
            h, w = template_gray.shape
            screen_x = locator._window["left"] + max_loc[0] + w // 2
            screen_y = locator._window["top"] + max_loc[1] + h // 2
            return True, screen_x, screen_y
    
    return False, 0, 0

def verify_stash_opened():
    """验证仓库是否打开（反向验证）"""
    template = load_template()
    if template is None:
        return True
    
    with mss.mss() as sct:
        monitor = {
            "left": locator._window["left"],
            "top": locator._window["top"],
            "width": locator._window["width"],
            "height": locator._window["height"]
        }
        screenshot = sct.grab(monitor)
        screen = np.array(screenshot)
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        
        result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        log(f"[仓库检测] 宝箱匹配度: {max_val:.3f}")
        
        if max_val < 0.5:
            log(f"[仓库检测] ✓ 反向验证确认仓库已打开 - 宝箱匹配度降至 {max_val:.3f}")
            return True
    
    return False

def generate_stash_cells():
    """生成仓库格子坐标"""
    global stash_cells
    # 第一个格子中心: (467, 528)
    # 最后一个格子中心: (789, 644)
    first_x, first_y = 467, 528
    last_x, last_y = 789, 644
    cols, rows = 12, 5
    
    col_step = (last_x - first_x) / (cols - 1) if cols > 1 else 0
    row_step = (last_y - first_y) / (rows - 1) if rows > 1 else 0
    
    stash_cells = []
    for row in range(rows):
        for col in range(cols):
            cx = first_x + int(col * col_step)
            cy = first_y + int(row * row_step)
            # 转换为相对坐标
            rel_x = cx - locator._window["left"]
            rel_y = cy - locator._window["top"]
            stash_cells.append((rel_x, rel_y, cx, cy))

def check_cell_confidence(rel_x, rel_y):
    """检查格子是否有物品"""
    x1 = locator._window["left"] + rel_x - 31
    y1 = locator._window["top"] + rel_y - 31
    x2 = x1 + 62
    y2 = y1 + 62
    
    try:
        with mss.mss() as sct:
            screenshot = sct.grab((x1, y1, x2, y2))
            img = np.array(screenshot)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            mean_val = np.mean(gray)
            std_val = np.std(gray)
            
            if mean_val > 45 or std_val > 30:
                return 0.3
            else:
                return 0.6
    except:
        return 0.5

def perform_stash():
    """执行存仓操作"""
    global has_purchased, just_purchased
    
    log("[存仓] 开始存仓...")
    generate_stash_cells()
    
    stash_count = 0
    skip_count = 0
    
    for idx, (rel_x, rel_y, abs_x, abs_y) in enumerate(stash_cells, 1):
        confidence = check_cell_confidence(rel_x, rel_y)
        
        if confidence < 0.5:
            screen_x, screen_y = locator.to_screen(rel_x, rel_y)
            log(f"[存仓] 识别到存仓的物品 - 格子 {idx}/60 - 置信度: {confidence:.3f} - 坐标: ({screen_x}, {screen_y})")
            pyautogui.moveTo(screen_x, screen_y, duration=0.1)
            pyautogui.click()
            time.sleep(0.05)
            stash_count += 1
        else:
            skip_count += 1
    
    log(f"[存仓] ✓ 存仓完成！总格子: {len(stash_cells)} | 存仓: {stash_count} | 跳过: {skip_count}")
    
    has_purchased = False
    just_purchased = False

def run_automation():
    """运行自动化主循环"""
    global running, has_purchased, just_purchased
    
    log("[自动化] 开始运行...")
    purchase_count = 0
    
    while running:
        # 查找游戏窗口
        if locator._window is None:
            locator.find_window()
            time.sleep(1)
            continue
        
        # 确保窗口置顶（持续检测）
        locator.ensure_topmost()
        
        # 检测高亮物品（最高优先级，无视窗口状态）
        item_pos = detect_highlights()
        if item_pos:
            log(f"[自动化] 识别到物品 | 坐标={item_pos}")
            screen_x, screen_y = item_pos
            pyautogui.moveTo(screen_x, screen_y, duration=0.1)
            pyautogui.keyDown('ctrl')
            pyautogui.click()
            pyautogui.keyUp('ctrl')
            log(f"[自动化] -> 执行Ctrl+左键购买...")
            time.sleep(0.3)
            purchase_count += 1
            log(f"[自动化] -> 成功购买！累计购买: {purchase_count}")
            has_purchased = True
            just_purchased = True
            pyautogui.moveTo(467, 708)
            time.sleep(0.2)
        
        # 窗口激活检查
        if not locator.is_active():
            time.sleep(0.1)
            continue
        
        # 检测截图按钮
        found, btn_x, btn_y = detect_screenshot_button()
        if found:
            log(f"[自动化] 检测到截图按钮: 屏幕坐标=({btn_x}, {btn_y})")
            pyautogui.moveTo(btn_x, btn_y, duration=0.1)
            pyautogui.click()
            log(f"[自动化] ✓ 已点击截图按钮")
            time.sleep(1)
        
        # 仓库检测（仅刚购买后）
        if has_purchased and just_purchased:
            found, stash_x, stash_y = match_stash_template()
            if found:
                log(f"[自动化] 检测到仓库宝箱: ({stash_x}, {stash_y})，准备点击打开...")
                pyautogui.moveTo(stash_x, stash_y, duration=0.1)
                pyautogui.click()
                log(f"[自动化] 已点击仓库宝箱，等待3秒让UI面板打开...")
                time.sleep(3)
                
                # 等待窗口激活
                wait_start = time.time()
                while time.time() - wait_start < 3:
                    if locator.is_active():
                        time.sleep(0.5)
                        break
                    time.sleep(0.2)
                
                # 验证仓库打开
                if verify_stash_opened():
                    log(f"[自动化] ✓ 仓库已打开")
                    perform_stash()
                else:
                    log(f"[自动化] 存仓操作被阻止 - 未识别到有效仓库特征")
        
        time.sleep(0.1)
    
    log("[自动化] 已停止")

# ==================== GUI 主类 ====================
class AutoBuyApp:
    """AutoBuy主应用"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"AutoBuy 游戏自动化助手 v{VERSION}")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.resizable(True, True)
        
        self.center_window()
        
        self.game_path = StringVar()
        self.server_type = StringVar(value="china")
        self.status = StringVar(value="就绪")
        
        self.load_config()
        self.create_widgets()
        
        log_info(f"========== AutoBuy v{VERSION} 启动 ==========")
        log_info(f"操作系统: {sys.platform}")
        log_info(f"Python版本: {sys.version}")
    
    def center_window(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - MIN_WIDTH) // 2
        y = (screen_height - MIN_HEIGHT) // 2
        self.root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}+{x}+{y}")
    
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill="both", expand=True)
        
        # 标题
        title = ttk.Label(main_frame, text="AutoBuy 游戏自动化助手", font=('Arial', 14, 'bold'))
        title.pack(pady=(0, 15))
        
        # 游戏路径区
        path_frame = ttk.LabelFrame(main_frame, text="游戏路径", padding="10")
        path_frame.pack(fill="x", pady=(0, 10))
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.game_path, width=55)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ttk.Button(path_frame, text="浏览", command=self.browse_game_path).pack(side="right")
        
        # 服务器选择区
        server_frame = ttk.LabelFrame(main_frame, text="服务器", padding="10")
        server_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Radiobutton(server_frame, text="国服", variable=self.server_type, value="china").pack(side="left", padx=(0, 30))
        ttk.Radiobutton(server_frame, text="国际服", variable=self.server_type, value="global").pack(side="left")
        
        # 状态显示
        self.status_label = ttk.Label(main_frame, textvariable=self.status, font=('Arial', 10), foreground='green')
        self.status_label.pack(pady=(0, 10))
        
        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, font=('Consolas', 9))
        self.log_text.pack(fill="both", expand=True)
        
        # 按钮区
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x")
        
        self.start_btn = ttk.Button(btn_frame, text="启动游戏", command=self.start_game, style='Accent.TButton')
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.stop_btn = ttk.Button(btn_frame, text="停止", command=self.stop_automation, state='disabled')
        self.stop_btn.pack(side="right", fill="x", expand=True)
        
        # 重定向print到日志框
        sys.stdout = TextRedirector(self.log_text, 'stdout')
        sys.stderr = TextRedirector(self.log_text, 'stderr')
        
        style = ttk.Style()
        style.configure('Accent.TButton', font=('Arial', 11, 'bold'))
    
    def browse_game_path(self):
        file_path = filedialog.askopenfilename(title="选择游戏启动程序", filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if file_path:
            self.game_path.set(file_path)
            log_info(f"选择游戏路径: {file_path}")
    
    def validate_path(self):
        path = self.game_path.get().strip()
        if not path:
            self.status.set("请选择游戏路径")
            return False
        if not os.path.exists(path):
            self.status.set("错误: 文件不存在")
            return False
        if not path.lower().endswith('.exe'):
            self.status.set("错误: 不是可执行文件")
            return False
        self.status.set("路径有效")
        return True
    
    def start_game(self):
        if not self.validate_path():
            return
        
        global running, automation_thread
        
        self.status.set("正在启动游戏...")
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        
        running = True
        
        # 启动游戏
        success = start_game_via_wegame(self.game_path.get())
        
        if success:
            self.status.set("游戏已启动，自动化运行中...")
            log_info("[自动化] 游戏已启动，开始监控...")
            
            # 启动自动化线程
            automation_thread = threading.Thread(target=run_automation, daemon=True)
            automation_thread.start()
        else:
            self.status.set("游戏启动失败")
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
            running = False
    
    def stop_automation(self):
        global running
        running = False
        self.status.set("已停止")
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        log_info("[自动化] 已手动停止")
    
    def load_config(self):
        config_path = os.path.join(LOG_DIR, "config.ini")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('game_path='):
                            self.game_path.set(line.split('=', 1)[1])
                        elif line.startswith('server='):
                            self.server_type.set(line.split('=', 1)[1])
            except:
                pass
    
    def save_config(self):
        config_path = os.path.join(LOG_DIR, "config.ini")
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(f"game_path={self.game_path.get()}\n")
                f.write(f"server={self.server_type.get()}\n")
        except:
            pass

class TextRedirector:
    """重定向输出到文本框"""
    def __init__(self, text_widget, tag='stdout'):
        self.text_widget = text_widget
        self.tag = tag
    
    def write(self, string):
        self.text_widget.configure(state='normal')
        self.text_widget.insert('end', string, (self.tag,))
        self.text_widget.see('end')
        self.text_widget.configure(state='disabled')
    
    def flush(self):
        pass

def main():
    try:
        setup_logging()
        
        root = Tk()
        app = AutoBuyApp(root)
        root.protocol("WM_DELETE_WINDOW", lambda: (app.save_config(), root.destroy()))
        root.mainloop()
        
    except Exception as e:
        log_error(f"程序异常: {e}")
        log_exception(e)

if __name__ == "__main__":
    main()