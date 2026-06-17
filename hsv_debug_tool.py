
"""
HSV 调试工具 - Phase 2
专门用于调试 POE2 紫色高亮识别
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import numpy as np
import cv2
from PIL import Image, ImageTk
from typing import Optional, Dict
import threading
import time
import mss
import pyautogui

# 导入独立的HSV检测器模块
from hsv_detector import detect_items, draw_detection_result


class HSVDebugTool:
    def __init__(self, root):
        self.root = root
        self.root.title("POE2 HSV 调试工具")
        self.root.geometry("1100x800")  # 更合理的初始大小
        self.root.minsize(900, 700)  # 最小尺寸限制
        
        # 状态
        self.running = False
        self.detection_region = None  # (x1, y1, x2, y2) 屏幕坐标
        self.current_img = None
        self.auto_click_enabled = False
        self.last_clicked_pos = None  # 记录上次点击位置，避免重复
        
        # 格子相关
        self.grid_region = None  # (x1, y1, x2, y2) 格子区域
        self.grid_cols = 12
        self.grid_rows = 5
        
        # 背包监控相关
        self.inventory_region = None  # 背包监控区域
        self.target_cells = []  # 目标格子列表 [{name, x1, y1, x2, y2}]
        self.inventory_config_path = "inventory_config.json"
        
        # Hash监控相关
        self.hash_config_path = "inventory_hash_config.json"
        self.hash_cells = []  # Hash格子列表 [{name, region, baseline_hash}]
        self.hash_config = {
            "hash_type": "dhash",
            "hash_size": 8,
            "threshold": 10,
            "check_interval": 0.3,
            "max_retries": 3,
            "retry_delay": 0.2,
            "wait_after_stash": 0.3,
            "cells": []
        }
        
        # 仓库位置（F5回城后点击打开仓库的位置）
        self.stash_open_pos = [900, 380]
        
        # 尝试加载 good.json 配置
        self.hsv_config = {
            "h_min": 105,
            "h_max": 180,
            "s_min": 70,
            "s_max": 255,
            "v_min": 70,
            "v_max": 255
        }
        self.try_load_good_config()
        self.try_load_inventory_config()
        self.try_load_hash_config()
        
        # 用加载的配置设置变量
        self.h_min_var = tk.IntVar(value=self.hsv_config["h_min"])
        self.h_max_var = tk.IntVar(value=self.hsv_config["h_max"])
        self.s_min_var = tk.IntVar(value=self.hsv_config["s_min"])
        self.s_max_var = tk.IntVar(value=self.hsv_config["s_max"])
        self.v_min_var = tk.IntVar(value=self.hsv_config["v_min"])
        self.v_max_var = tk.IntVar(value=self.hsv_config["v_max"])
        
        self.create_ui()
        
        # 创建 UI 之后，更新 region_label（如果加载了 ROI）
        if self.detection_region:
            x1, y1, x2, y2 = self.detection_region
            self.region_label.config(
                text=f"区域: ({x1},{y1})-({x2},{y2})",
                foreground="green"
            )
        if self.grid_region:
            x1, y1, x2, y2 = self.grid_region
            self.grid_label.config(
                text=f"格子: ({x1},{y1})-({x2},{y2}) {self.grid_cols}x{self.grid_rows}",
                foreground="green"
            )
        if self.inventory_region:
            self.inventory_label.config(
                text=f"背包: {self.inventory_region} {len(self.target_cells)}格",
                foreground="green"
            )
        if self.hash_cells:
            self.hash_label.config(
                text=f"Hash: {len(self.hash_cells)}格",
                foreground="green"
            )
        # 更新仓库位置标签
        self.stash_label.config(
            text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})",
            foreground="green" if self.stash_open_pos != [900, 380] else "gray"
        )
        
    def try_load_good_config(self):
        """尝试加载 auto_buy_config.json 配置，如果不存在则尝试 good.json"""
        try:
            import os
            # 先尝试加载 auto_buy_config.json
            filepath = os.path.join(os.path.dirname(__file__), "auto_buy_config.json")
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 从 auto_buy_config.json 中提取 hsv 部分
                    if "hsv" in config:
                        self.hsv_config.update(config["hsv"])
                    # 同时尝试加载 ROI
                    if "roi" in config and config["roi"]:
                        roi = config["roi"]
                        self.detection_region = (
                            int(roi["LEFT"]),
                            int(roi["TOP"]),
                            int(roi["RIGHT"]),
                            int(roi["BOTTOM"])
                        )
                        self.grid_region = (
                            int(config["roi"]["LEFT"]),
                            int(config["roi"]["TOP"]),
                            int(config["roi"]["RIGHT"]),
                            int(config["roi"]["BOTTOM"]))
                    if "cells_map" in config and len(config["cells_map"]) > 0:
                        # 从 cells_map 计算列数和行数
                        cols = set()
                        rows = set()
                        for cell in config["cells_map"]:
                            if isinstance(cell, dict):
                                cols.add(cell.get("col_index", 0))
                                rows.add(cell.get("row_index", 0))
                        # 如果有有效的列数和行数，使用它们；否则使用默认值
                        if len(cols) > 0 and len(rows) > 0:
                            self.grid_cols = len(cols)
                            self.grid_rows = len(rows)
                        else:
                            self.grid_cols = 12
                            self.grid_rows = 5
                    
                    # 加载仓库位置
                    if "stash_open_pos" in config and len(config["stash_open_pos"]) == 2:
                        self.stash_open_pos = config["stash_open_pos"]
                    
                    print("✓ 已自动加载 auto_buy_config.json 配置")
                return
            
            # 如果 auto_buy_config.json 不存在，尝试加载 good.json
            filepath = os.path.join(os.path.dirname(__file__), "good.json")
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.hsv_config.update(config)
                print("✓ 已自动加载 good.json 配置")
        except Exception as e:
            print(f"加载配置文件失败: {e}")
    
    def try_load_inventory_config(self):
        """尝试加载背包监控配置"""
        import os
        try:
            filepath = os.path.join(os.path.dirname(__file__), self.inventory_config_path)
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if "monitor_region" in config:
                        self.inventory_region = config["monitor_region"]
                    if "target_cells" in config:
                        self.target_cells = config["target_cells"]
                print("✓ 已加载背包监控配置")
        except Exception as e:
            print(f"加载背包配置失败: {e}")
    
    def save_inventory_config(self):
        """保存背包监控配置"""
        import os
        try:
            filepath = os.path.join(os.path.dirname(__file__), self.inventory_config_path)
            config = {
                "monitor_region": self.inventory_region,
                "target_cells": self.target_cells,
                "similarity_threshold": 0.85,
                "check_interval": 0.5,
                "target_dir": "target"
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print("✓ 背包配置已保存")
            return True
        except Exception as e:
            print(f"保存背包配置失败: {e}")
            return False
    
    def try_load_hash_config(self):
        """加载Hash监控配置"""
        import os
        try:
            filepath = os.path.join(os.path.dirname(__file__), self.hash_config_path)
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.hash_config.update(config)
                    self.hash_cells = config.get("cells", [])
                print("✓ 已加载Hash监控配置")
        except Exception as e:
            print(f"加载Hash配置失败: {e}")
    
    def save_hash_config(self):
        """保存Hash监控配置"""
        import os
        try:
            filepath = os.path.join(os.path.dirname(__file__), self.hash_config_path)
            config_to_save = self.hash_config.copy()
            config_to_save["cells"] = self.hash_cells
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
            print("✓ Hash配置已保存")
            self.hash_label.config(
                text=f"Hash: {len(self.hash_cells)}格",
                foreground="green"
            )
            return True
        except Exception as e:
            print(f"保存Hash配置失败: {e}")
            return False
    
    def select_hash_cell(self):
        """选择Hash监控格子"""
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        # 绘制已有的格子
        for idx, cell in enumerate(self.hash_cells):
            x1, y1, x2, y2 = cell["region"]
            canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2)
            canvas.create_text((x1+x2)//2, (y1+y2)//2, text=cell["name"], fill="red")
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="拖动选择仓库格子，点击确认或ESC取消", 
                          fill="#00ffff", font=("Arial", 20, "bold"))
        
        # 底部按钮和输入框
        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        ttk.Label(btn_frame, text="格子名称:").pack(side=tk.LEFT, padx=5)
        cell_name_var = tk.StringVar(value=f"格子{len(self.hash_cells)+1}")
        ttk.Entry(btn_frame, textvariable=cell_name_var, width=15).pack(side=tk.LEFT, padx=5)
        
        selection = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "rect": None}
        
        def on_mouse_down(event):
            selection["x1"] = event.x
            selection["y1"] = event.y
        
        def on_mouse_drag(event):
            selection["x2"] = event.x
            selection["y2"] = event.y
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["rect"] = canvas.create_rectangle(
                selection["x1"], selection["y1"], 
                selection["x2"], selection["y2"], 
                outline="cyan", width=3)
        
        def on_confirm():
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])
            
            if x2 - x1 < 10 or y2 - y1 < 10:
                messagebox.showerror("错误", "选择区域太小，请重新选择")
                return
            
            cell_name = cell_name_var.get().strip()
            if not cell_name:
                cell_name = f"格子{len(self.hash_cells)+1}"
            
            self.hash_cells.append({
                "name": cell_name,
                "region": [x1, y1, x2, y2],
                "baseline_hash": None
            })
            
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        ttk.Button(btn_frame, text="✅ 确认添加", command=on_confirm, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)
        
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()
        
        canvas.bg_photo = bg_photo
    
    def record_baseline_hash(self):
        """记录空仓基准Hash"""
        if not self.hash_cells:
            messagebox.showwarning("警告", "请先添加格子！")
            return
        
        # 导入Hash函数
        import sys
        from inventory_hash_monitor import InventoryHashMonitor
        
        monitor = InventoryHashMonitor()
        monitor.cells = []
        for cell_data in self.hash_cells:
            from inventory_hash_monitor import InventoryCell
            cell = InventoryCell(
                name=cell_data["name"],
                region=tuple(cell_data["region"]),
                baseline_hash=cell_data.get("baseline_hash")
            )
            monitor.cells.append(cell)
        
        print("\n正在记录基准Hash...")
        monitor.capture_baseline()
        
        # 更新self.hash_cells的baseline_hash
        for i, cell in enumerate(monitor.cells):
            self.hash_cells[i]["baseline_hash"] = cell.baseline_hash
        
        self.save_hash_config()
        messagebox.showinfo("成功", "基准Hash记录完成！")
    
    def clear_hash_cells(self):
        """清空Hash格子配置"""
        if messagebox.askyesno("确认", "确定要清空所有Hash格子配置吗？"):
            self.hash_cells = []
            self.save_hash_config()
    
    def select_stash_position(self):
        """选择仓库位置（F5回城后点击打开仓库的位置）"""
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="点击选择仓库位置（回城后要点击的位置），按ESC取消", 
                          fill="green", font=("Arial", 20, "bold"))
        
        # 显示当前位置
        canvas.create_text(screenshot.width // 2, 60, 
                          text=f"当前位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})", 
                          fill="white", font=("Arial", 14))
        
        def on_click(event):
            self.stash_open_pos = [event.x, event.y]
            self.stash_label.config(
                text=f"仓库位置: ({event.x}, {event.y})",
                foreground="green"
            )
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        canvas.bind("<Button-1>", on_click)
        calib_window.bind("<Escape>", on_cancel)
        canvas.focus_force()
        
        canvas.bg_photo = bg_photo
    
    def toggle_auto_click(self):
        """切换自动点击开关"""
        self.auto_click_enabled = self.auto_click_var.get()
        if self.auto_click_enabled:
            print("✓ 自动点击测试已启用")
        else:
            print("自动点击测试已禁用")
            self.last_clicked_pos = None
        
    def create_ui(self):
        """创建界面"""
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # ===== 顶部控制栏 - 第一行：核心功能 =====
        control_frame1 = ttk.Frame(main_frame)
        control_frame1.pack(fill=tk.X, pady=2)
        
        ttk.Button(control_frame1, text="🎯 选择检测区域", command=self.select_region).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame1, text="📐 选择格子区域", command=self.select_grid_region).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame1, text="▶ 开始/停止", command=self.toggle_capture).pack(side=tk.LEFT, padx=3)
        
        ttk.Separator(control_frame1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        
        self.auto_click_var = tk.BooleanVar(value=False)
        self.auto_click_check = ttk.Checkbutton(
            control_frame1, 
            text="🔘 自动点击", 
            variable=self.auto_click_var,
            command=self.toggle_auto_click
        )
        self.auto_click_check.pack(side=tk.LEFT, padx=3)
        
        ttk.Separator(control_frame1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        
        self.status_label = ttk.Label(control_frame1, text="状态: 未开始", foreground="gray")
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        self.region_label = ttk.Label(control_frame1, text="区域: 未选择", foreground="gray")
        self.region_label.pack(side=tk.LEFT, padx=8)
        
        self.grid_label = ttk.Label(control_frame1, text="格子: 未选择", foreground="gray")
        self.grid_label.pack(side=tk.LEFT, padx=8)
        
        # ===== 顶部控制栏 - 第二行：配置管理 =====
        control_frame2 = ttk.Frame(main_frame)
        control_frame2.pack(fill=tk.X, pady=2)
        
        ttk.Button(control_frame2, text="📂 加载配置", command=self.load_config).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame2, text="💾 保存配置", command=self.save_config).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame2, text="⭐ 保存到自动购买", command=self.save_to_auto_buy_config, style="Accent.TButton").pack(side=tk.LEFT, padx=3)
        
        # ===== 顶部控制栏 - 第三行：背包格子监控 =====
        control_frame3 = ttk.LabelFrame(main_frame, text="背包格子监控", padding=5)
        control_frame3.pack(fill=tk.X, pady=2)
        
        ttk.Button(control_frame3, text="🎒 选择背包区域", command=self.select_inventory_region).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame3, text="📐 设置行列数", command=self.show_grid_settings).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame3, text="💾 保存背包配置", command=self.save_inventory_config).pack(side=tk.LEFT, padx=3)
        
        self.inventory_label = ttk.Label(control_frame3, text="背包: 未选择", foreground="gray")
        self.inventory_label.pack(side=tk.LEFT, padx=10)
        
        # ===== 顶部控制栏 - 第四行：仓库格子监控 (推荐) =====
        control_frame4 = ttk.LabelFrame(main_frame, text="仓库格子监控 (推荐)", padding=5)
        control_frame4.pack(fill=tk.X, pady=2)
        
        ttk.Button(control_frame4, text="📌 添加格子", command=self.select_hash_cell).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame4, text="🔵 记录基准Hash", command=self.record_baseline_hash).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame4, text="💾 保存Hash配置", command=self.save_hash_config).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_frame4, text="🗑️ 清空", command=self.clear_hash_cells).pack(side=tk.LEFT, padx=3)
        
        self.hash_label = ttk.Label(control_frame4, text=f"Hash: {len(self.hash_cells)}格", foreground="gray")
        self.hash_label.pack(side=tk.LEFT, padx=10)
        
        # ===== 顶部控制栏 - 第五行：仓库位置设置 =====
        control_frame5 = ttk.LabelFrame(main_frame, text="仓库位置 (F5回城后点击)", padding=5)
        control_frame5.pack(fill=tk.X, pady=2)
        
        ttk.Button(control_frame5, text="📍 选择仓库位置", command=self.select_stash_position).pack(side=tk.LEFT, padx=3)
        self.stash_label = ttk.Label(control_frame5, text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})", foreground="gray")
        self.stash_label.pack(side=tk.LEFT, padx=10)
        
        # ===== 主体 - 左边显示区域 =====
        display_frame = ttk.Frame(main_frame)
        display_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 原始图像
        orig_frame = ttk.LabelFrame(display_frame, text="原始图像")
        orig_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
        
        self.orig_canvas = tk.Canvas(orig_frame, bg="black")
        self.orig_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Mask
        mask_frame = ttk.LabelFrame(display_frame, text="HSV Mask")
        mask_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
        
        self.mask_canvas = tk.Canvas(mask_frame, bg="black")
        self.mask_canvas.pack(fill=tk.BOTH, expand=True)
        
        # ===== 右边 - 控制面板 =====
        control_right = ttk.LabelFrame(display_frame, text="HSV 参数")
        control_right.pack(side=tk.RIGHT, fill=tk.Y, padx=3)
        
        # HSV 滑块
        self.create_hsv_sliders(control_right)
        
        # ===== 底部 - 检测结果 =====
        result_frame = ttk.LabelFrame(main_frame, text="检测结果预览", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.result_canvas = tk.Canvas(result_frame, bg="black")
        self.result_canvas.pack(fill=tk.BOTH, expand=True)
        
    def create_hsv_sliders(self, parent):
        """创建HSV滑块"""
        # H
        ttk.Label(parent, text="Hue (H):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Scale(frame, from_=0, to=180, variable=self.h_min_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Entry(frame, textvariable=self.h_min_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(frame, text="-").pack(side=tk.LEFT)
        ttk.Entry(frame, textvariable=self.h_max_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Scale(frame, from_=0, to=180, variable=self.h_max_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # S
        ttk.Label(parent, text="Saturation (S):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Scale(frame, from_=0, to=255, variable=self.s_min_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Entry(frame, textvariable=self.s_min_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(frame, text="-").pack(side=tk.LEFT)
        ttk.Entry(frame, textvariable=self.s_max_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Scale(frame, from_=0, to=255, variable=self.s_max_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # V
        ttk.Label(parent, text="Value (V):", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Scale(frame, from_=0, to=255, variable=self.v_min_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Entry(frame, textvariable=self.v_min_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(frame, text="-").pack(side=tk.LEFT)
        ttk.Entry(frame, textvariable=self.v_max_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Scale(frame, from_=0, to=255, variable=self.v_max_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        # 预设按钮
        ttk.Label(parent, text="预设颜色预设:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        preset_frame = ttk.Frame(parent)
        preset_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(preset_frame, text="紫色", command=lambda: self.apply_preset("purple")).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(preset_frame, text="洋红", command=lambda: self.apply_preset("magenta")).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(preset_frame, text="红色", command=lambda: self.apply_preset("red")).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(preset_frame, text="绿色", command=lambda: self.apply_preset("green")).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        # 快速调节
        ttk.Label(parent, text="快速调节:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        quick_frame = ttk.Frame(parent)
        quick_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(quick_frame, text="扩大范围", command=self.widen_range).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        ttk.Button(quick_frame, text="缩小范围", command=self.narrow_range).pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        # 格子配置
        ttk.Label(parent, text="格子配置:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        grid_frame = ttk.Frame(parent)
        grid_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(grid_frame, text="列数:").pack(side=tk.LEFT)
        self.grid_cols_var = tk.IntVar(value=self.grid_cols)
        ttk.Entry(grid_frame, textvariable=self.grid_cols_var, width=5).pack(side=tk.LEFT, padx=2)
        
        ttk.Label(grid_frame, text="行数:").pack(side=tk.LEFT, padx=10)
        self.grid_rows_var = tk.IntVar(value=self.grid_rows)
        ttk.Entry(grid_frame, textvariable=self.grid_rows_var, width=5).pack(side=tk.LEFT, padx=2)
        
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=15)
        
        ttk.Label(parent, text="当前配置:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)
        
        self.config_text = tk.Text(parent, height=12)
        self.config_text.pack(fill=tk.X)
        self.update_config_text()
        
    def select_region(self):
        """选择检测区域"""
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="拖动选择检测区域，点击确认或ESC取消", 
                          fill="cyan", font=("Arial", 20, "bold"))
        
        # 底部按钮
        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        selection = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "rect": None}
        
        def on_mouse_down(event):
            selection["x1"] = event.x
            selection["y1"] = event.y
        
        def on_mouse_drag(event):
            selection["x2"] = event.x
            selection["y2"] = event.y
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["rect"] = canvas.create_rectangle(
                selection["x1"], selection["y1"], 
                selection["x2"], selection["y2"], 
                outline="cyan", width=4)
        
        def on_confirm():
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])
            
            if x2 - x1 < 50 or y2 - y1 < 50:
                messagebox.showerror("错误", "选择区域太小，请重新选择")
                return
            
            self.detection_region = (x1, y1, x2, y2)
            self.region_label.config(text=f"区域: ({x1},{y1})-({x2},{y2})", foreground="green")
            
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        ttk.Button(btn_frame, text="✅ 确认", command=on_confirm, width=20).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 取消", command=on_cancel, width=20).pack(side=tk.LEFT, padx=10)
        
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()
        
        # 保持引用
        canvas.bg_photo = bg_photo

    def select_grid_region(self):
        """选择格子区域"""
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="拖动选择格子区域，点击确认或ESC取消", 
                          fill="yellow", font=("Arial", 20, "bold"))
        
        # 底部按钮
        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        selection = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "rect": None}
        
        def on_mouse_down(event):
            selection["x1"] = event.x
            selection["y1"] = event.y
        
        def on_mouse_drag(event):
            selection["x2"] = event.x
            selection["y2"] = event.y
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["rect"] = canvas.create_rectangle(
                selection["x1"], selection["y1"], 
                selection["x2"], selection["y2"], 
                outline="yellow", width=4)
        
        def on_confirm():
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])
            
            if x2 - x1 < 50 or y2 - y1 < 50:
                messagebox.showerror("错误", "选择区域太小，请重新选择")
                return
            
            self.grid_region = (x1, y1, x2, y2)
            # 更新行数和列数
            self.grid_cols = self.grid_cols_var.get()
            self.grid_rows = self.grid_rows_var.get()
            self.grid_label.config(text=f"格子: ({x1},{y1})-({x2},{y2}) {self.grid_cols}x{self.grid_rows}", foreground="green")
            
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        ttk.Button(btn_frame, text="✅ 确认", command=on_confirm, width=20).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 取消", command=on_cancel, width=20).pack(side=tk.LEFT, padx=10)
        
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()
        
        # 保持引用
        canvas.bg_photo = bg_photo
    
    def select_inventory_region(self):
        """选择背包监控区域"""
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="拖动选择背包监控区域，点击确认或ESC取消", 
                          fill="orange", font=("Arial", 20, "bold"))
        
        # 底部按钮
        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        selection = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "rect": None}
        
        def on_mouse_down(event):
            selection["x1"] = event.x
            selection["y1"] = event.y
        
        def on_mouse_drag(event):
            selection["x2"] = event.x
            selection["y2"] = event.y
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["rect"] = canvas.create_rectangle(
                selection["x1"], selection["y1"], 
                selection["x2"], selection["y2"], 
                outline="orange", width=4)
        
        def on_confirm():
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])
            
            if x2 - x1 < 50 or y2 - y1 < 50:
                messagebox.showerror("错误", "选择区域太小，请重新选择")
                return
            
            self.inventory_region = (x1, y1, x2, y2)
            
            # 自动生成所有格子
            self.generate_grid_cells()
            
            self.inventory_label.config(text=f"背包: ({x1},{y1})-({x2},{y2}) {self.grid_cols}x{self.grid_rows}={len(self.target_cells)}格", foreground="green")
            
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        ttk.Button(btn_frame, text="✅ 确认", command=on_confirm, width=20).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 取消", command=on_cancel, width=20).pack(side=tk.LEFT, padx=10)
        
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()
        
        # 保持引用
        canvas.bg_photo = bg_photo
    
    def select_target_cell(self):
        """选择目标格子"""
        if not self.inventory_region:
            messagebox.showwarning("警告", "请先选择背包区域")
            return
        
        self.root.withdraw()
        time.sleep(0.1)
        
        # 全屏选择窗口
        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()
        
        # 截全屏做背景
        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[0])
            bg_image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            bg_photo = ImageTk.PhotoImage(bg_image)
        
        canvas = tk.Canvas(calib_window, cursor="cross")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)
        
        # 画背包区域
        ix1, iy1, ix2, iy2 = self.inventory_region
        canvas.create_rectangle(ix1, iy1, ix2, iy2, outline="orange", width=2)
        
        # 画已有的目标格子
        for idx, cell in enumerate(self.target_cells):
            canvas.create_rectangle(
                cell["x1"], cell["y1"], cell["x2"], cell["y2"],
                outline="red", width=2, fill="", tags=f"cell_{idx}"
            )
            canvas.create_text(
                (cell["x1"] + cell["x2"]) // 2, (cell["y1"] + cell["y2"]) // 2,
                text=cell["name"], fill="red", font=("Arial", 10, "bold")
            )
        
        canvas.create_text(screenshot.width // 2, 30, 
                          text="拖动选择目标格子，点击确认或ESC取消", 
                          fill="red", font=("Arial", 20, "bold"))
        
        # 底部按钮和输入框
        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        ttk.Label(btn_frame, text="格子名称:").pack(side=tk.LEFT, padx=5)
        cell_name_var = tk.StringVar(value=f"格子{len(self.target_cells) + 1}")
        ttk.Entry(btn_frame, textvariable=cell_name_var, width=15).pack(side=tk.LEFT, padx=5)
        
        selection = {"x1": 0, "y1": 0, "x2": 0, "y2": 0, "rect": None}
        
        def on_mouse_down(event):
            selection["x1"] = event.x
            selection["y1"] = event.y
        
        def on_mouse_drag(event):
            selection["x2"] = event.x
            selection["y2"] = event.y
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["rect"] = canvas.create_rectangle(
                selection["x1"], selection["y1"], 
                selection["x2"], selection["y2"], 
                outline="red", width=3)
        
        def on_confirm():
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])
            
            if x2 - x1 < 10 or y2 - y1 < 10:
                messagebox.showerror("错误", "选择格子太小，请重新选择")
                return
            
            cell_name = cell_name_var.get().strip()
            if not cell_name:
                cell_name = f"格子{len(self.target_cells) + 1}"
            
            self.target_cells.append({
                "name": cell_name,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2
            })
            
            self.inventory_label.config(text=f"背包: {self.inventory_region} {len(self.target_cells)}格", foreground="green")
            
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()
        
        ttk.Button(btn_frame, text="✅ 确认添加", command=on_confirm, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="❌ 取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)
        
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()
        
        # 保持引用
        canvas.bg_photo = bg_photo
        
    def get_current_hsv(self) -> Dict:
        """获取当前HSV配置"""
        return {
            "h_min": self.h_min_var.get(),
            "h_max": self.h_max_var.get(),
            "s_min": self.s_min_var.get(),
            "s_max": self.s_max_var.get(),
            "v_min": self.v_min_var.get(),
            "v_max": self.v_max_var.get()
        }
    
    def generate_grid_cells(self):
        """根据背包区域和行列数自动生成所有格子"""
        if not self.inventory_region:
            return
        
        x1, y1, x2, y2 = self.inventory_region
        width = x2 - x1
        height = y2 - y1
        
        # 计算每个格子的大小
        cell_width = width // self.grid_cols
        cell_height = height // self.grid_rows
        
        # 清空旧的格子
        self.target_cells = []
        
        # 生成所有格子
        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                cell_x1 = x1 + col * cell_width
                cell_y1 = y1 + row * cell_height
                cell_x2 = cell_x1 + cell_width
                cell_y2 = cell_y1 + cell_height
                
                self.target_cells.append({
                    "name": f"格子{row * self.grid_cols + col + 1}",
                    "x1": cell_x1,
                    "y1": cell_y1,
                    "x2": cell_x2,
                    "y2": cell_y2
                })
        
        print(f"✓ 自动生成 {self.grid_cols}x{self.grid_rows}={len(self.target_cells)} 个格子")
    
    def show_grid_settings(self):
        """显示设置行列数的窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置行列数")
        settings_window.geometry("300x150")
        settings_window.resizable(False, False)
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        frame = ttk.Frame(settings_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="列数:").pack(side=tk.LEFT, padx=5)
        cols_entry = ttk.Entry(frame, width=10)
        cols_entry.pack(side=tk.LEFT, padx=5)
        cols_entry.insert(0, str(self.grid_cols))
        
        ttk.Label(frame, text="行数:").pack(side=tk.LEFT, padx=10)
        rows_entry = ttk.Entry(frame, width=10)
        rows_entry.pack(side=tk.LEFT, padx=5)
        rows_entry.insert(0, str(self.grid_rows))
        
        def on_ok():
            try:
                cols = int(cols_entry.get())
                rows = int(rows_entry.get())
                if cols < 1 or rows < 1:
                    messagebox.showerror("错误", "行列数必须大于0")
                    return
                self.grid_cols = cols
                self.grid_rows = rows
                self.grid_cols_var.set(cols)
                self.grid_rows_var.set(rows)
                
                # 如果已经选择了背包区域，重新生成格子
                if self.inventory_region:
                    self.generate_grid_cells()
                    self.inventory_label.config(
                        text=f"背包: {self.inventory_region} {self.grid_cols}x{self.grid_rows}={len(self.target_cells)}格",
                        foreground="green"
                    )
                
                settings_window.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")
        
        def on_cancel():
            settings_window.destroy()
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=15)
        
        ttk.Button(btn_frame, text="确定", command=on_ok, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)
        
        cols_entry.focus_set()
        
    def update_config_text(self):
        """更新配置文本显示"""
        config = self.get_current_hsv()
        text = json.dumps(config, indent=2)
        self.config_text.delete(1.0, tk.END)
        self.config_text.insert(tk.END, text)
        
    def apply_preset(self, preset_name: str):
        """应用颜色预设"""
        presets = {
            "purple": {"h_min": 105, "h_max": 180, "s_min": 70, "s_max": 255, "v_min": 70, "v_max": 255},
            "magenta": {"h_min": 140, "h_max": 180, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
            "red": {"h_min": 0, "h_max": 20, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
            "green": {"h_min": 35, "h_max": 85, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
        }
        
        if preset_name in presets:
            p = presets[preset_name]
            self.h_min_var.set(p["h_min"])
            self.h_max_var.set(p["h_max"])
            self.s_min_var.set(p["s_min"])
            self.s_max_var.set(p["s_max"])
            self.v_min_var.set(p["v_min"])
            self.v_max_var.set(p["v_max"])
            self.update_config_text()
            
    def widen_range(self):
        """扩大检测范围"""
        self.h_min_var.set(max(0, self.h_min_var.get() - 15))
        self.h_max_var.set(min(180, self.h_max_var.get() + 15))
        self.s_min_var.set(max(0, self.s_min_var.get() - 40))
        self.s_max_var.set(min(255, self.s_max_var.get() + 40))
        self.v_min_var.set(max(0, self.v_min_var.get() - 40))
        self.v_max_var.set(min(255, self.v_max_var.get() + 40))
        self.update_config_text()
        
    def narrow_range(self):
        """缩小检测范围"""
        h_center = (self.h_min_var.get() + self.h_max_var.get()) // 2
        s_center = (self.s_min_var.get() + self.s_max_var.get()) // 2
        v_center = (self.v_min_var.get() + self.v_max_var.get()) // 2
        
        self.h_min_var.set(max(0, h_center - 20))
        self.h_max_var.set(min(180, h_center + 20))
        self.s_min_var.set(max(0, s_center - 30))
        self.s_max_var.set(min(255, s_center + 30))
        self.v_min_var.set(max(0, v_center - 30))
        self.v_max_var.set(min(255, v_center + 30))
        self.update_config_text()
        
    def save_config(self):
        """保存配置到文件"""
        config = self.get_current_hsv()
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            messagebox.showinfo("成功", f"配置已保存到: {filepath}")

    def save_to_auto_buy_config(self):
        """保存配置到 auto_buy_config.json"""
        import os
        try:
            # 构建 auto_buy_config.json 的路径
            auto_buy_config_path = os.path.join(os.path.dirname(__file__), "auto_buy_config.json")
            
            # 加载现有的配置
            if os.path.exists(auto_buy_config_path):
                with open(auto_buy_config_path, 'r', encoding='utf-8') as f:
                    auto_buy_config = json.load(f)
            else:
                # 如果文件不存在，创建一个基本的结构
                auto_buy_config = {
                    "hsv": {},
                    "roi": {},
                    "cells_map": [],
                    "detection": {
                        "threshold": 8,
                        "border_thickness": 8
                    },
                    "delays": {
                        "ctrl_hold": 0.1,
                        "wait_after_buy": 3.0,
                        "scan_interval": 0.5
                    }
                }
            
            # 更新 HSV 配置
            auto_buy_config["hsv"] = self.get_current_hsv()
            
            # 使用检测区域作为主 ROI（HSV检测区域）
            if self.detection_region:
                x1, y1, x2, y2 = self.detection_region
                auto_buy_config["roi"] = {
                    "TOP": y1,
                    "LEFT": x1,
                    "BOTTOM": y2,
                    "RIGHT": x2
                }
            
            # 仍然使用格子区域生成 cells_map（保持原有的格子信息）
            if self.grid_region:
                x1, y1, x2, y2 = self.grid_region
                # 生成 cells_map
                cols = self.grid_cols_var.get()
                rows = self.grid_rows_var.get()
                cell_width = (x2 - x1) / cols
                cell_height = (y2 - y1) / rows
                
                auto_buy_config["cells_map"] = []
                for row in range(rows):
                    for col in range(cols):
                        cell_x1 = int(x1 + col * cell_width)
                        cell_y1 = int(y1 + row * cell_height)
                        cell_x2 = int(x1 + (col + 1) * cell_width)
                        cell_y2 = int(y1 + (row + 1) * cell_height)
                        center_x = int(x1 + col * cell_width + cell_width / 2)
                        center_y = int(y1 + row * cell_height + cell_height / 2)
                        auto_buy_config["cells_map"].append([
                            [cell_x1, cell_y1],
                            [cell_x2, cell_y2]
                        ])
            
            # 保存仓库位置
            auto_buy_config["stash_open_pos"] = self.stash_open_pos
            
            # 保存配置
            with open(auto_buy_config_path, 'w', encoding='utf-8') as f:
                json.dump(auto_buy_config, f, indent=2)
            
            messagebox.showinfo("成功", f"配置已保存到: {auto_buy_config_path}")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")
            
    def load_config(self):
        """从文件加载配置"""
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.h_min_var.set(config.get("h_min", 0))
                    self.h_max_var.set(config.get("h_max", 180))
                    self.s_min_var.set(config.get("s_min", 0))
                    self.s_max_var.set(config.get("s_max", 255))
                    self.v_min_var.set(config.get("v_min", 0))
                    self.v_max_var.set(config.get("v_max", 255))
                    self.update_config_text()
                messagebox.showinfo("成功", "配置已加载")
            except Exception as e:
                messagebox.showerror("错误", f"加载配置失败: {e}")
                
    def toggle_capture(self):
        """开始/停止捕获"""
        if self.running:
            self.stop_capture()
        else:
            self.start_capture()
            
    def start_capture(self):
        """开始捕获"""
        if not self.detection_region:
            messagebox.showerror("错误", "请先选择检测区域")
            return
            
        self.running = True
        self.status_label.config(text="状态: 捕获中", foreground="green")
        self.worker_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.worker_thread.start()
        
    def stop_capture(self):
        """停止捕获"""
        self.running = False
        self.status_label.config(text="状态: 已停止", foreground="gray")
        
    def process_image(self, img):
        """处理图像并显示（使用独立的HSV检测器）"""
        hsv_config = self.get_current_hsv()
        
        # 使用独立的HSV检测器（img是RGB格式，来自PIL）
        detected_items, mask = detect_items(img, hsv_config, min_area=500, input_format="RGB")
        
        # 使用独立的绘制函数（img是RGB格式）
        result_img = draw_detection_result(img, detected_items, input_format="RGB")
                
        return mask, result_img, detected_items
        
    def update_display(self, img, mask, result_img):
        """更新显示"""
        # 原始图像
        self._update_canvas(self.orig_canvas, img)
        
        # Mask
        mask_rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
        self._update_canvas(self.mask_canvas, mask_rgb)
        
        # 结果
        self._update_canvas(self.result_canvas, result_img)
        
        # 更新配置文本
        self.update_config_text()
        
    def _update_canvas(self, canvas, img):
        """更新单个Canvas"""
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            
            if w <= 1 or h <= 1:
                return
                
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            
            # 等比例缩放
            pil_img.thumbnail((w, h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            
            canvas.delete("all")
            canvas.create_image(w // 2, h // 2, image=tk_img, anchor=tk.CENTER)
            canvas.image = tk_img
            
        except Exception:
            pass
        
    def capture_loop(self):
        """主捕获循环"""
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            
            while self.running:
                try:
                    # 截全屏
                    screenshot = sct.grab(monitor)
                    img_full = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                    img_full_np = np.array(img_full)
                    
                    # 裁剪区域
                    x1, y1, x2, y2 = self.detection_region
                    img = img_full_np[y1:y2, x1:x2].copy()
                    
                    self.current_img = img
                    
                    # 处理
                    mask, result_img, items = self.process_image(img)
                    
                    # 自动点击逻辑
                    if self.auto_click_enabled and items:
                        # 取第一个检测到的物品
                        first_item = items[0]
                        rx, ry, rw, rh = first_item["bbox"]
                        cx, cy = first_item["center"]
                        # 转换为屏幕绝对坐标
                        screen_x = x1 + rx + rw // 2
                        screen_y = y1 + ry + rh // 2
                        
                        # 检查是否重复点击同一个位置
                        current_pos = (screen_x, screen_y)
                        if self.last_clicked_pos != current_pos:
                            # 执行点击
                            print(f"检测到物品，点击位置: ({screen_x}, {screen_y})")
                            pyautogui.moveTo(screen_x, screen_y, duration=0.1)
                            pyautogui.click()
                            self.last_clicked_pos = current_pos
                            # 点击后暂停一段时间，避免连续点击
                            time.sleep(0.5)
                    
                    # 在全屏图上画区域框
                    display_img = img_full_np.copy()
                    cv2.rectangle(display_img, (x1, y1), (x2, y2), (0, 255, 255), 3)
                    
                    # 绘制格子
                    if self.grid_region:
                        gx1, gy1, gx2, gy2 = self.grid_region
                        cv2.rectangle(display_img, (gx1, gy1), (gx2, gy2), (255, 255, 0), 2)
                        
                        cols = self.grid_cols_var.get()
                        rows = self.grid_rows_var.get()
                        cell_width = (gx2 - gx1) / cols
                        cell_height = (gy2 - gy1) / rows
                        
                        # 绘制垂直线
                        for i in range(1, cols):
                            x = int(gx1 + i * cell_width)
                            cv2.line(display_img, (x, gy1), (x, gy2), (255, 255, 0), 1)
                        
                        # 绘制水平线
                        for i in range(1, rows):
                            y = int(gy1 + i * cell_height)
                            cv2.line(display_img, (gx1, y), (gx2, y), (255, 255, 0), 1)
                    
                    # 绘制背包监控区域
                    if self.inventory_region:
                        ix1, iy1, ix2, iy2 = self.inventory_region
                        cv2.rectangle(display_img, (ix1, iy1), (ix2, iy2), (0, 165, 255), 3)
                        
                        # 绘制目标格子
                        for cell in self.target_cells:
                            cx1, cy1, cx2, cy2 = cell["x1"], cell["y1"], cell["x2"], cell["y2"]
                            cv2.rectangle(display_img, (cx1, cy1), (cx2, cy2), (0, 0, 255), 2)
                            # 绘制格子名称
                            cv2.putText(display_img, cell["name"], (cx1, cy1 - 5), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    
                    # 绘制Hash格子
                    if self.hash_cells:
                        for cell in self.hash_cells:
                            cx1, cy1, cx2, cy2 = cell["region"]
                            has_baseline = cell.get("baseline_hash") is not None
                            color = (0, 255, 255) if has_baseline else (255, 0, 255)
                            cv2.rectangle(display_img, (cx1, cy1), (cx2, cy2), color, 2)
                            # 绘制格子名称
                            cv2.putText(display_img, cell["name"], (cx1, cy1 - 5), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                    
                    # 把结果也画上去
                    for item in items:
                        rx, ry, rw, rh = item["bbox"]
                        cx, cy = item["center"]
                        cv2.rectangle(display_img, (x1+rx, y1+ry), (x1+rx+rw, y1+ry+rh), (0, 255, 0), 3)
                        cv2.circle(display_img, (x1+cx, y1+cy), 8, (0, 0, 255), -1)
                    
                    # 更新显示
                    self.root.after(0, lambda i=display_img, m=mask, r=result_img: self.update_display(i, m, r))
                    
                    time.sleep(1 / 30)
                    
                except Exception as e:
                    print(f"捕获错误: {e}")
                    time.sleep(0.1)
                    
        print("捕获循环结束")
        

if __name__ == "__main__":
    root = tk.Tk()
    app = HSVDebugTool(root)
    root.mainloop()

