#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoBuy 统一调试工具
整合 HSV调试工具 和 仓库配置工具，用于配置 auto_buy_new.py 的所有参数
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import time
import mss
import numpy as np
import cv2
from PIL import Image, ImageTk
import threading
import pyautogui
import psutil
from ctypes import wintypes
import ctypes

from hsv_detector import detect_items, draw_detection_result
from window_locator import locator


class AutoBuyDebugTool:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoBuy 统一调试工具")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)

        self.config_path = "auto_buy_config.json"

        # HSV调试相关
        self.running = False
        self.detection_region = None
        self.current_img = None
        self.auto_click_test_mode = False
        self.auto_click_done = False  # 自动点击只执行一次
        self.hsv_config = {
            "h_min": 105,
            "h_max": 180,
            "s_min": 70,
            "s_max": 255,
            "v_min": 70,
            "v_max": 255
        }

        # 仓库相关
        self.game_window = None
        self.game_server = "global"  # 默认国际服
        self.template_img = None
        self.inventory_region = None
        self.grid_cols = 12
        self.grid_rows = 5
        self.stash_cells = []
        self.stash_open_pos = [900, 380]
        
        # 空格子模板（用于判断格子是否为空）
        self.empty_cell_template = None  # 空格子参考模板（cc.png）
        self.EMPTY_CELL_THRESHOLD = 0.7  # 空格子置信度阈值（高于此值认为是空格子）

        # 置信度检测区域
        self.stash_confidence_region = None  # 仓库检测区域 (x1,y1,x2,y2)
        self.inventory_confidence_region = None  # 背包检测区域 (x1,y1,x2,y2)
        
        # 置信度检测模板（截图）
        self.stash_confidence_template = None  # 仓库检测模板截图
        self.inventory_confidence_template = None  # 背包检测模板截图

        # 加载已有配置
        self.load_config()

        # HSV变量
        self.h_min_var = tk.IntVar(value=self.hsv_config["h_min"])
        self.h_max_var = tk.IntVar(value=self.hsv_config["h_max"])
        self.s_min_var = tk.IntVar(value=self.hsv_config["s_min"])
        self.s_max_var = tk.IntVar(value=self.hsv_config["s_max"])
        self.v_min_var = tk.IntVar(value=self.hsv_config["v_min"])
        self.v_max_var = tk.IntVar(value=self.hsv_config["v_max"])

        self.create_ui()

        # 更新已加载配置的显示
        if self.detection_region:
            x1, y1, x2, y2 = self.detection_region
            self.region_label.config(
                text=f"区域: ({x1},{y1})-({x2},{y2})",
                foreground="green"
            )
        self._update_window_label()
        self._refresh_stash_display()  # 刷新仓库配置显示
        
        # 加载空格子模板（cc.png）
        self._load_empty_cell_template()

    def _load_empty_cell_template(self):
        """加载空格子模板 cc.png"""
        if os.path.exists("cc.png"):
            self.empty_cell_template = cv2.imread("cc.png")
            if self.empty_cell_template is not None:
                print(f"[模板] 已加载空格子模板 cc.png，大小: {self.empty_cell_template.shape[1]}x{self.empty_cell_template.shape[0]}")
            else:
                print("[警告] 未能加载空格子模板 cc.png")
        else:
            print("[警告] 未找到空格子模板 cc.png")

    def _find_window(self, window_name):
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

    def load_config(self):
        """加载 auto_buy_config.json 配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                    # HSV配置
                    if "hsv" in config:
                        self.hsv_config.update(config["hsv"])

                    # 检测区域（可能是绝对或相对坐标）
                    if "roi" in config and config["roi"]:
                        roi = config["roi"]
                        self.detection_region = (
                            int(roi["LEFT"]),
                            int(roi["TOP"]),
                            int(roi["RIGHT"]),
                            int(roi["BOTTOM"])
                        )

                    # 仓库模板
                    if "stash_template" in config:
                        self.template_img = np.array(config["stash_template"], dtype=np.uint8)

                    # 仓库格子（可能是绝对或相对坐标）
                    if "cells_map" in config:
                        self.stash_cells = config["cells_map"]
                        if self.stash_cells:
                            self._guess_grid_size()

                    # 窗口信息：不保存，由运行时检测
                    # 兼容旧配置：如果存在，不再读取（会误导）

                    # 仓库位置（可能是绝对或相对坐标）
                    if "stash_open_pos" in config:
                        self.stash_open_pos = config["stash_open_pos"]

                    # 服务器类型
                    if "game_server" in config:
                        self.game_server = config["game_server"]

                    # 置信度检测区域和模板（已是相对坐标）
                    if "stash_confidence_region" in config:
                        scr = config["stash_confidence_region"]
                        self.stash_confidence_region = tuple(int(x) for x in scr)
                    if "stash_confidence_template" in config:
                        self.stash_confidence_template = np.array(config["stash_confidence_template"], dtype=np.uint8)
                    if "inventory_confidence_region" in config:
                        icr = config["inventory_confidence_region"]
                        self.inventory_confidence_region = tuple(int(x) for x in icr)
                    if "inventory_confidence_template" in config:
                        self.inventory_confidence_template = np.array(config["inventory_confidence_template"], dtype=np.uint8)

                    # 背包区域（相对坐标）
                    if "inventory_region" in config:
                        ir = config["inventory_region"]
                        self.inventory_region = tuple(int(x) for x in ir)

                    # 坐标体系标记
                    coord_sys = config.get("coord_system", "unknown")
                    coord_note = ""
                    if coord_sys == "relative":
                        coord_note = " [相对坐标]"
                    elif coord_sys == "absolute":
                        coord_note = " [绝对坐标-需迁移]"
                    else:
                        coord_note = " [检测:建议重新选择区域]"

                print(f"已加载配置: HSV区域 {self.detection_region}, {len(self.stash_cells)} 个仓库格子{coord_note}")
            except Exception as e:
                print(f"加载配置失败: {e}")

    def _guess_grid_size(self):
        """从cells_map猜测行列数"""
        if not self.stash_cells:
            return
        x_coords = set()
        for cell in self.stash_cells:
            if isinstance(cell, list) and len(cell) == 2:
                x_coords.add(cell[0][0])
        self.grid_cols = len(x_coords)
        self.grid_rows = len(self.stash_cells) // self.grid_cols if self.grid_cols > 0 else 5

    def save_config(self):
        """保存所有配置到 auto_buy_config.json"""
        try:
            config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            # HSV配置
            config["hsv"] = self.get_current_hsv()

            # 检测区域（相对坐标）
            if self.detection_region:
                x1, y1, x2, y2 = self.detection_region
                config["roi"] = {
                    "TOP": y1,
                    "LEFT": x1,
                    "BOTTOM": y2,
                    "RIGHT": x2
                }

            # 仓库位置（相对坐标）
            config["stash_open_pos"] = self.stash_open_pos

            # 仓库格子（相对坐标）
            config["cells_map"] = self.stash_cells

            # 不再保存 game_window - 由 window_locator 在运行时动态检测
            config.pop("game_window", None)

            # 服务器类型
            config["game_server"] = self.game_server

            # 坐标体系标记（关键：表示所有坐标都是相对游戏窗口的）
            config["coord_system"] = "relative"

            # 仓库模板
            if self.template_img is not None:
                config["stash_template"] = self.template_img.tolist()

            # 置信度检测区域和模板（已是相对坐标）
            if self.stash_confidence_region:
                config["stash_confidence_region"] = list(self.stash_confidence_region)
            if self.stash_confidence_template is not None:
                config["stash_confidence_template"] = self.stash_confidence_template.tolist()
            if self.inventory_confidence_region:
                config["inventory_confidence_region"] = list(self.inventory_confidence_region)
            if self.inventory_confidence_template is not None:
                config["inventory_confidence_template"] = self.inventory_confidence_template.tolist()

            # 背包区域（相对坐标）
            if self.inventory_region:
                config["inventory_region"] = list(self.inventory_region)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            messagebox.showinfo("成功", f"配置已保存到: {self.config_path} [相对坐标体系]")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def create_ui(self):
        """创建Tab界面"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # HSV调试页
        self.hsv_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.hsv_frame, text="HSV 调试")
        self._create_hsv_tab()

        # 仓库配置页
        self.stash_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stash_frame, text="仓库配置")
        self._create_stash_tab()

        # 状态栏
        self.status_bar = ttk.Label(self.root, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _create_hsv_tab(self):
        """创建HSV调试Tab页"""
        main_frame = ttk.Frame(self.hsv_frame, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== 第一行：核心功能 =====
        control_row1 = ttk.Frame(main_frame)
        control_row1.pack(fill=tk.X, pady=2)

        ttk.Button(control_row1, text="选择检测区域", command=self.select_region).pack(side=tk.LEFT, padx=3)
        ttk.Button(control_row1, text="开始/停止", command=self.toggle_capture).pack(side=tk.LEFT, padx=3)

        ttk.Separator(control_row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.auto_click_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            control_row1,
            text="自动点击",
            variable=self.auto_click_var
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(control_row1, text="测试自动点击", command=self.test_auto_click).pack(side=tk.LEFT, padx=3)

        ttk.Separator(control_row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.hsv_status_label = ttk.Label(control_row1, text="状态: 未开始", foreground="gray")
        self.hsv_status_label.pack(side=tk.LEFT, padx=10)

        self.region_label = ttk.Label(control_row1, text="区域: 未选择", foreground="gray")
        self.region_label.pack(side=tk.LEFT, padx=8)

        # ===== 第二行：配置管理 =====
        control_row2 = ttk.Frame(main_frame)
        control_row2.pack(fill=tk.X, pady=2)

        ttk.Button(control_row2, text="保存所有配置", command=self.save_config, style="Accent.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(control_row2, text="加载配置", command=self.load_config).pack(side=tk.LEFT, padx=3)

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

        # ===== 右边 - HSV参数 =====
        control_right = ttk.LabelFrame(display_frame, text="HSV 参数")
        control_right.pack(side=tk.RIGHT, fill=tk.Y, padx=3)

        self._create_hsv_sliders(control_right)

        # ===== 底部 - 检测结果 =====
        result_frame = ttk.LabelFrame(main_frame, text="检测结果预览", padding=5)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.hsv_result_canvas = tk.Canvas(result_frame, bg="black")
        self.hsv_result_canvas.pack(fill=tk.BOTH, expand=True)

    def _create_hsv_sliders(self, parent):
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

        ttk.Label(parent, text="当前配置:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)

        self.hsv_config_text = tk.Text(parent, height=10)
        self.hsv_config_text.pack(fill=tk.X)
        self._update_hsv_config_text()

    def _create_stash_tab(self):
        """创建仓库配置Tab页"""
        main_frame = ttk.Frame(self.stash_frame, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== 窗口识别 =====
        window_frame = ttk.LabelFrame(main_frame, text="游戏窗口", padding=10)
        window_frame.pack(fill=tk.X, pady=5)

        window_btn_frame = ttk.Frame(window_frame)
        window_btn_frame.pack(fill=tk.X)

        ttk.Button(window_btn_frame, text="识别窗口", command=self._detect_game_window).pack(side=tk.LEFT, padx=5)
        self.stash_window_label = ttk.Label(window_btn_frame, text="未识别窗口", foreground="gray")
        self.stash_window_label.pack(side=tk.LEFT, padx=10)

        # ===== 仓库模板 =====
        stash_pos_frame = ttk.LabelFrame(main_frame, text="仓库位置", padding=10)
        stash_pos_frame.pack(fill=tk.X, pady=5)

        stash_pos_btn_frame = ttk.Frame(stash_pos_frame)
        stash_pos_btn_frame.pack(fill=tk.X)

        ttk.Button(stash_pos_btn_frame, text="选择仓库位置", command=self.select_stash_position).pack(side=tk.LEFT, padx=5)
        ttk.Button(stash_pos_btn_frame, text="测试打开仓库", command=self.test_stash_click).pack(side=tk.LEFT, padx=5)
        self.stash_pos_label = ttk.Label(stash_pos_btn_frame, text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})")
        self.stash_pos_label.pack(side=tk.LEFT, padx=10)
        self.template_label = ttk.Label(stash_pos_btn_frame, text="模板: 未保存", foreground="gray")
        self.template_label.pack(side=tk.LEFT, padx=10)

        # ===== 置信度检测区域 =====
        conf_frame = ttk.LabelFrame(main_frame, text="置信度检测区域", padding=10)
        conf_frame.pack(fill=tk.X, pady=5)

        conf_btn_frame = ttk.Frame(conf_frame)
        conf_btn_frame.pack(fill=tk.X)

        ttk.Button(conf_btn_frame, text="选择仓库检测区域", command=self.select_stash_confidence_region).pack(side=tk.LEFT, padx=5)
        ttk.Button(conf_btn_frame, text="选择背包检测区域", command=self.select_inventory_confidence_region).pack(side=tk.LEFT, padx=5)

        conf_label_frame = ttk.Frame(conf_frame)
        conf_label_frame.pack(fill=tk.X, pady=5)

        self.stash_conf_region_label = ttk.Label(conf_label_frame, text="仓库检测区: 未选择")
        self.stash_conf_region_label.pack(side=tk.LEFT, padx=10)
        self.inventory_conf_region_label = ttk.Label(conf_label_frame, text="背包检测区: 未选择")
        self.inventory_conf_region_label.pack(side=tk.LEFT, padx=10)

        # ===== 背包格子 =====
        inv_frame = ttk.LabelFrame(main_frame, text="背包格子设置", padding=10)
        inv_frame.pack(fill=tk.X, pady=5)

        inv_btn_frame = ttk.Frame(inv_frame)
        inv_btn_frame.pack(fill=tk.X)

        ttk.Button(inv_btn_frame, text="选择背包区域", command=self.select_inventory_region).pack(side=tk.LEFT, padx=5)
        ttk.Button(inv_btn_frame, text="设置行列数", command=self.show_grid_settings).pack(side=tk.LEFT, padx=5)
        self.inventory_label = ttk.Label(inv_btn_frame, text=f"未选择 ({self.grid_cols}x{self.grid_rows})", foreground="gray")
        self.inventory_label.pack(side=tk.LEFT, padx=10)

        # ===== 存仓测试 =====
        test_frame = ttk.LabelFrame(main_frame, text="存仓测试", padding=10)
        test_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        test_btn_frame = ttk.Frame(test_frame)
        test_btn_frame.pack(fill=tk.X)

        ttk.Button(test_btn_frame, text="测试存仓", command=self.test_stash_operation).pack(side=tk.LEFT, padx=5)
        self.stash_stop_btn = ttk.Button(test_btn_frame, text="停止", command=self.stop_stash_test, state=tk.DISABLED)
        self.stash_stop_btn.pack(side=tk.LEFT, padx=5)

        # 置信度显示区域
        conf_frame = ttk.Frame(test_frame)
        conf_frame.pack(fill=tk.X, pady=5)

        self.stash_conf_label = ttk.Label(conf_frame, text="仓库置信度: --")
        self.stash_conf_label.pack(side=tk.LEFT, padx=10)

        self.inventory_conf_label = ttk.Label(conf_frame, text="背包置信度: --")
        self.inventory_conf_label.pack(side=tk.LEFT, padx=10)

        self.stash_status_label = ttk.Label(conf_frame, text="状态: 等待开始")
        self.stash_status_label.pack(side=tk.RIGHT, padx=10)

        # 实时画面显示
        display_inner_frame = ttk.Frame(test_frame)
        display_inner_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.stash_canvas = tk.Canvas(display_inner_frame, bg="black", width=400, height=300)
        self.stash_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ===== 保存按钮 =====
        save_frame = ttk.Frame(main_frame)
        save_frame.pack(fill=tk.X, pady=10)

        ttk.Button(save_frame, text="保存仓库配置", command=self.save_stash_config, style="Accent.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(save_frame, text="保存所有配置", command=self.save_config, style="Accent.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(save_frame, text="刷新配置", command=self._refresh_stash_display).pack(side=tk.LEFT, padx=5)

        # 更新模板显示
        if self.template_img is not None:
            self.template_label.config(text=f"模板: 已保存 {self.template_img.shape[1]}x{self.template_img.shape[0]}", foreground="green")

    def _detect_game_window(self):
        """识别游戏窗口 - 让用户选择国际服/国服"""
        sel_window = tk.Toplevel(self.root)
        sel_window.title("选择服务器")
        sel_window.geometry("280x160")
        sel_window.resizable(False, False)
        sel_window.transient(self.root)
        sel_window.grab_set()

        ttk.Label(sel_window, text="请选择游戏服务器：", font=("Arial", 12)).pack(pady=15)

        def select_server(server):
            sel_window.destroy()
            self._find_and_set_window(server)

        btn_frame = ttk.Frame(sel_window)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="国际服\nPath of Exile 2",
                  command=lambda: select_server("global"), width=16).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="国服\n流放之路：降临",
                  command=lambda: select_server("china"), width=16).pack(side=tk.LEFT, padx=10)

        self.root.wait_window(sel_window)

    def _find_and_set_window(self, server):
        """根据服务器类型查找窗口（使用 window_locator 模块）"""
        # 第一步：使用 locator 检测窗口
        if not locator.detect(server):
            # 兜底：尝试用旧方法直接枚举窗口
            if server == "global":
                windows = self._find_window("Path of Exile 2")
                if not windows:
                    windows = self._find_window("Path of Exile")
                if windows:
                    windows = [w for w in windows if not any(
                        kw in w["title"].lower() for kw in ["chrome", "firefox", "edge", "iexplore", "brave"])]
            else:
                windows = self._find_window("流放之路")
                windows = [w for w in windows if not any(
                    kw in w["title"].lower() for kw in ["chrome", "firefox", "edge", "iexplore", "brave"])]

            if not windows:
                messagebox.showerror("未找到窗口", "未找到游戏窗口，请确认游戏已启动")
                return

            if len(windows) == 1:
                self.game_window = windows[0]
                self.game_server = server
                self._update_window_label()
                return

            # 多个窗口：让用户选择
            choices = [f"{w['title']} ({w['width']}x{w['height']})" for w in windows]
            choice = tk.StringVar(value=choices[0])
            sel_window = tk.Toplevel(self.root)
            sel_window.title("选择窗口")
            sel_window.geometry("400x150")
            ttk.Label(sel_window, text="找到多个窗口，请选择：").pack(pady=10)
            ttk.Combobox(sel_window, textvariable=choice, values=choices, state="readonly").pack(pady=10)
            def on_select():
                idx = choices.index(choice.get())
                self.game_window = windows[idx]
                self.game_server = server
                sel_window.destroy()
                self._update_window_label()
            ttk.Button(sel_window, text="确认", command=on_select).pack(pady=10)
            sel_window.transient(self.root)
            sel_window.grab_set()
            self.root.wait_window(sel_window)
            return

        # locator 检测成功
        self.game_window = locator.window
        self.game_server = server
        self._update_window_label()

    def _update_window_label(self):
        """更新窗口信息显示"""
        if self.game_window:
            w = self.game_window
            server_text = "国际服" if getattr(self, 'game_server', 'global') == 'global' else "国服"
            self.stash_window_label.config(
                text=f"{server_text} {w['width']}x{w['height']}",
                foreground="green"
            )
            self.stash_pos_label.config(
                text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})",
                foreground="green"
            )
            print(f"[窗口] 已识别: {server_text} {w['title']} 位置:({w['left']},{w['top']}) 大小:{w['width']}x{w['height']}")
        else:
            self.stash_window_label.config(text="未识别窗口", foreground="gray")

    def _refresh_stash_display(self):
        """刷新仓库配置显示"""
        self.load_config()
        self._update_window_label()
        
        # 更新仓库位置标签
        self.stash_pos_label.config(text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})")
        
        # 更新背包区域标签
        if self.stash_cells:
            self.inventory_label.config(
                text=f"背包区域: {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)}格",
                foreground="green"
            )
        
        # 更新模板标签
        if self.template_img is not None:
            self.template_label.config(
                text=f"模板: 已保存 {self.template_img.shape[1]}x{self.template_img.shape[0]}",
                foreground="green"
            )
        
        # 更新仓库检测区域标签
        if self.stash_confidence_region:
            sx1, sy1, sx2, sy2 = self.stash_confidence_region
            template_size = ""
            if self.stash_confidence_template is not None:
                template_size = f" [{self.stash_confidence_template.shape[1]}x{self.stash_confidence_template.shape[0]}]"
            self.stash_conf_region_label.config(
                text=f"仓库检测区: ({sx1},{sy1})-({sx2},{sy2}){template_size}",
                foreground="green"
            )
        else:
            self.stash_conf_region_label.config(text="仓库检测区: 未选择", foreground="gray")
        
        # 更新背包检测区域标签
        if self.inventory_confidence_region:
            ix1, iy1, ix2, iy2 = self.inventory_confidence_region
            template_size = ""
            if self.inventory_confidence_template is not None:
                template_size = f" [{self.inventory_confidence_template.shape[1]}x{self.inventory_confidence_template.shape[0]}]"
            self.inventory_conf_region_label.config(
                text=f"背包检测区: ({ix1},{iy1})-({ix2},{iy2}){template_size}",
                foreground="green"
            )
        else:
            self.inventory_conf_region_label.config(text="背包检测区: 未选择", foreground="gray")
        
        self.status_bar.config(text="配置已刷新")

    # ==================== HSV调试功能 ====================

    def select_region(self):
        """选择检测区域"""
        self.root.withdraw()
        time.sleep(0.1)

        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()

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

            # 转换为相对游戏窗口的坐标
            if self.game_window:
                win_left = self.game_window["left"]
                win_top = self.game_window["top"]
            else:
                win_left = 0
                win_top = 0
            rel_x1 = x1 - win_left
            rel_y1 = y1 - win_top
            rel_x2 = x2 - win_left
            rel_y2 = y2 - win_top

            self.detection_region = (rel_x1, rel_y1, rel_x2, rel_y2)
            self.region_label.config(text=f"区域: ({rel_x1},{rel_y1})-({rel_x2},{rel_y2}) [相对]", foreground="green")

            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()

        def on_cancel():
            calib_window.destroy()
            self.root.deiconify()
            self.root.lift()

        ttk.Button(btn_frame, text="确认", command=on_confirm, width=20).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=20).pack(side=tk.LEFT, padx=10)

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", lambda e: on_confirm())
        calib_window.bind("<Escape>", lambda e: on_cancel())
        canvas.focus_force()

        canvas.bg_photo = bg_photo

    def get_current_hsv(self):
        """获取当前HSV配置"""
        return {
            "h_min": self.h_min_var.get(),
            "h_max": self.h_max_var.get(),
            "s_min": self.s_min_var.get(),
            "s_max": self.s_max_var.get(),
            "v_min": self.v_min_var.get(),
            "v_max": self.v_max_var.get()
        }

    def _update_hsv_config_text(self):
        """更新配置文本显示"""
        config = self.get_current_hsv()
        text = json.dumps(config, indent=2)
        self.hsv_config_text.delete(1.0, tk.END)
        self.hsv_config_text.insert(tk.END, text)

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
        self.auto_click_test_mode = False
        self.auto_click_done = False  # 重置点击标志
        self.hsv_status_label.config(text="状态: 捕获中", foreground="green")
        self.worker_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.worker_thread.start()

    def stop_capture(self):
        """停止捕获"""
        self.running = False
        self.hsv_status_label.config(text="状态: 已停止", foreground="gray")

    def test_auto_click(self):
        """测试自动点击 - 检测一次并点击一次"""
        if not self.detection_region:
            messagebox.showerror("错误", "请先选择检测区域")
            return

        if not self.auto_click_var.get():
            messagebox.showwarning("警告", "请先勾选'自动点击'选项")
            return

        if self.running:
            self.stop_capture()

        self.auto_click_test_mode = True
        self.auto_click_done = False  # 重置点击标志
        self.running = True
        self.hsv_status_label.config(text="状态: 测试中...", foreground="orange")

        self.worker_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.worker_thread.start()

    def process_image(self, img):
        """处理图像并显示"""
        hsv_config = self.get_current_hsv()
        detected_items, mask = detect_items(img, hsv_config, min_area=500, input_format="RGB")
        result_img = draw_detection_result(img, detected_items, input_format="RGB")
        return mask, result_img, detected_items

    def update_display(self, img, mask, result_img):
        """更新显示"""
        self._update_canvas(self.orig_canvas, img)
        mask_rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
        self._update_canvas(self.mask_canvas, mask_rgb)
        self._update_canvas(self.hsv_result_canvas, result_img)
        self._update_hsv_config_text()

    def _update_canvas(self, canvas, img):
        """更新单个Canvas"""
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()

            if w <= 1 or h <= 1:
                return

            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            pil_img.thumbnail((w, h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)

            canvas.delete("all")
            canvas.create_image(w // 2, h // 2, image=tk_img, anchor=tk.CENTER)
            canvas.image = tk_img
        except Exception:
            pass

    def _capture_loop(self):
        """主捕获循环"""
        has_clicked = False
        self.auto_click_done = False  # 重置点击标志

        with mss.mss() as sct:
            monitor = sct.monitors[0]

            while self.running:
                try:
                    screenshot = sct.grab(monitor)
                    img_full = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                    img_full_np = np.array(img_full)

                    x1, y1, x2, y2 = self.detection_region
                    img = img_full_np[y1:y2, x1:x2].copy()

                    self.current_img = img

                    mask, result_img, items = self.process_image(img)

                    # 测试模式下只点击一次
                    if self.auto_click_test_mode and not has_clicked and items and self.auto_click_var.get():
                        first_item = items[0]
                        rx, ry, rw, rh = first_item["bbox"]
                        cx, cy = first_item["center"]
                        screen_x = x1 + rx + rw // 2
                        screen_y = y1 + ry + rh // 2

                        print(f"测试模式: 检测到物品，点击位置: ({screen_x}, {screen_y})")
                        pyautogui.moveTo(screen_x, screen_y, duration=0.1)
                        pyautogui.click()
                        has_clicked = True

                        self.running = False
                        self.root.after(0, lambda: self.hsv_status_label.config(text="状态: 测试完成", foreground="green"))
                        break

                    # 正常捕获模式下也支持自动点击（但只执行一次）
                    if not self.auto_click_test_mode and self.auto_click_var.get() and items and not self.auto_click_done:
                        first_item = items[0]
                        rx, ry, rw, rh = first_item["bbox"]
                        cx, cy = first_item["center"]
                        screen_x = x1 + rx + rw // 2
                        screen_y = y1 + ry + rh // 2

                        print(f"检测到物品，点击位置: ({screen_x}, {screen_y})")
                        pyautogui.moveTo(screen_x, screen_y, duration=0.1)
                        pyautogui.click()
                        self.auto_click_done = True  # 标记已点击，不再继续
                        time.sleep(0.5)

                    # 在全屏图上画区域框
                    display_img = img_full_np.copy()
                    cv2.rectangle(display_img, (x1, y1), (x2, y2), (0, 255, 255), 3)

                    # 绘制检测结果
                    for item in items:
                        rx, ry, rw, rh = item["bbox"]
                        cx, cy = item["center"]
                        cv2.rectangle(display_img, (x1+rx, y1+ry), (x1+rx+rw, y1+ry+rh), (0, 255, 0), 3)
                        cv2.circle(display_img, (x1+cx, y1+cy), 8, (0, 0, 255), -1)

                    self.root.after(0, lambda i=display_img, m=mask, r=result_img: self.update_display(i, m, r))

                    time.sleep(1 / 30)

                except Exception as e:
                    print(f"捕获错误: {e}")
                    time.sleep(0.1)

            if not self.auto_click_test_mode:
                self.root.after(0, lambda: self.hsv_status_label.config(text="状态: 已停止", foreground="gray"))

            print("捕获循环结束")

    # ==================== 仓库配置功能 ====================

    def select_stash_position(self):
        """选择仓库模板截图"""
        if not self.game_window:
            messagebox.showwarning("未识别窗口", "请先点击'识别窗口'按钮")
            return

        win = self.game_window
        self.root.withdraw()
        time.sleep(0.1)

        with mss.mss() as sct:
            full_screenshot = sct.grab(sct.monitors[0])
            full_image = Image.frombytes("RGB", full_screenshot.size, full_screenshot.bgra, "raw", "BGRX")

        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()

        bg_photo = ImageTk.PhotoImage(full_image)
        canvas = tk.Canvas(calib_window, cursor="cross", bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)

        # 绘制窗口边框
        canvas.create_rectangle(win["left"], win["top"], win["right"], win["bottom"],
                               outline="red", width=3, dash=(10, 5))

        canvas.create_text(win["left"] + win["width"]//2, win["top"] + 30,
                          text="选择【仓库图标】(将作为模板)",
                          fill="yellow", font=("Arial", 20, "bold"), anchor=tk.CENTER)

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

        def on_confirm(event=None):
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])

            if x2 - x1 < 10 or y2 - y1 < 10:
                messagebox.showerror("错误", "模板区域太小")
                return

            # 转换为相对游戏窗口的坐标（保存中心点作为 stash_open_pos）
            rel_cx = (x1 + x2) // 2 - win["left"]
            rel_cy = (y1 + y2) // 2 - win["top"]
            self.stash_open_pos = [rel_cx, rel_cy]

            # 截取并保存模板图片（使用屏幕绝对坐标截图）
            with mss.mss() as sct:
                monitor = {"top": y1, "left": x1, "width": x2 - x1, "height": y2 - y1}
                template_screenshot = sct.grab(monitor)
                self.template_img = np.array(template_screenshot)[:, :, :3]

            calib_window.destroy()
            self.root.deiconify()

            print(f"[模板] 已保存仓库模板，大小: {x2-x1}x{y2-y1}，相对位置: ({rel_cx}, {rel_cy})")
            self.template_label.config(text=f"模板: 已保存 {x2-x1}x{y2-y1} [相对]", foreground="green")
            messagebox.showinfo("成功", "仓库模板已保存！点击'测试打开仓库'开始识别并点击")

        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()

        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        ttk.Button(btn_frame, text="确认", command=on_confirm, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", on_confirm)
        calib_window.bind("<Escape>", on_cancel)
        canvas.focus_force()
        canvas.bg_photo = bg_photo

    def select_stash_confidence_region(self):
        """选择仓库检测区域 - 用于判断仓库是否打开"""
        if not self.game_window:
            messagebox.showwarning("未识别窗口", "请先点击'识别窗口'按钮")
            return

        win = self.game_window
        self.root.withdraw()
        time.sleep(0.1)

        with mss.mss() as sct:
            full_screenshot = sct.grab(sct.monitors[0])
            full_image = Image.frombytes("RGB", full_screenshot.size, full_screenshot.bgra, "raw", "BGRX")

        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()

        bg_photo = ImageTk.PhotoImage(full_image)
        canvas = tk.Canvas(calib_window, cursor="cross", bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)

        canvas.create_rectangle(win["left"], win["top"], win["right"], win["bottom"],
                               outline="red", width=3, dash=(10, 5))

        canvas.create_text(win["left"] + win["width"]//2, win["top"] + 30,
                          text="拖动选择【仓库检测区域】(用于判断仓库是否打开)",
                          fill="yellow", font=("Arial", 20, "bold"), anchor=tk.CENTER)

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

        def on_confirm(event=None):
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])

            # 转换为相对游戏窗口的坐标
            rel_x1 = x1 - win["left"]
            rel_y1 = y1 - win["top"]
            rel_x2 = x2 - win["left"]
            rel_y2 = y2 - win["top"]
            
            self.stash_confidence_region = (rel_x1, rel_y1, rel_x2, rel_y2)
            
            # 截取游戏窗口内的该区域作为模板
            full_image_np = np.array(full_image)
            template_img = full_image_np[y1:y2, x1:x2].copy()
            self.stash_confidence_template = template_img
            
            self.stash_conf_region_label.config(
                text=f"仓库检测区: ({rel_x1},{rel_y1})-({rel_x2},{rel_y2}) [{template_img.shape[1]}x{template_img.shape[0]}]",
                foreground="green"
            )

            calib_window.destroy()
            self.root.deiconify()
            print(f"[仓库检测区] 已选择: 相对坐标 ({rel_x1},{rel_y1})-({rel_x2},{rel_y2})，模板大小: {template_img.shape[1]}x{template_img.shape[0]}")

        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()

        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        ttk.Button(btn_frame, text="确认", command=on_confirm, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", on_confirm)
        calib_window.bind("<Escape>", on_cancel)
        canvas.focus_force()
        canvas.bg_photo = bg_photo

    def select_inventory_confidence_region(self):
        """选择背包检测区域 - 用于判断背包是否满了"""
        if not self.game_window:
            messagebox.showwarning("未识别窗口", "请先点击'识别窗口'按钮")
            return

        win = self.game_window
        self.root.withdraw()
        time.sleep(0.1)

        with mss.mss() as sct:
            full_screenshot = sct.grab(sct.monitors[0])
            full_image = Image.frombytes("RGB", full_screenshot.size, full_screenshot.bgra, "raw", "BGRX")

        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()

        bg_photo = ImageTk.PhotoImage(full_image)
        canvas = tk.Canvas(calib_window, cursor="cross", bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)

        canvas.create_rectangle(win["left"], win["top"], win["right"], win["bottom"],
                               outline="red", width=3, dash=(10, 5))

        canvas.create_text(win["left"] + win["width"]//2, win["top"] + 30,
                          text="拖动选择【背包检测区域】(用于判断背包是否满了)",
                          fill="cyan", font=("Arial", 20, "bold"), anchor=tk.CENTER)

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

        def on_confirm(event=None):
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])

            # 转换为相对游戏窗口的坐标
            rel_x1 = x1 - win["left"]
            rel_y1 = y1 - win["top"]
            rel_x2 = x2 - win["left"]
            rel_y2 = y2 - win["top"]
            
            self.inventory_confidence_region = (rel_x1, rel_y1, rel_x2, rel_y2)
            
            # 截取游戏窗口内的该区域作为模板
            full_image_np = np.array(full_image)
            template_img = full_image_np[y1:y2, x1:x2].copy()
            self.inventory_confidence_template = template_img
            
            self.inventory_conf_region_label.config(
                text=f"背包检测区: ({rel_x1},{rel_y1})-({rel_x2},{rel_y2}) [{template_img.shape[1]}x{template_img.shape[0]}]",
                foreground="green"
            )

            calib_window.destroy()
            self.root.deiconify()
            print(f"[背包检测区] 已选择: 相对坐标 ({rel_x1},{rel_y1})-({rel_x2},{rel_y2})，模板大小: {template_img.shape[1]}x{template_img.shape[0]}")

        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()

        btn_frame = tk.Frame(calib_window, bg="white")
        btn_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        ttk.Button(btn_frame, text="确认", command=on_confirm, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel, width=15).pack(side=tk.LEFT, padx=10)

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", on_confirm)
        calib_window.bind("<Escape>", on_cancel)
        canvas.focus_force()
        canvas.bg_photo = bg_photo

    def _match_template_in_window(self, template_img, threshold=0.7):
        """在整个游戏窗口内使用模板匹配
        
        Args:
            template_img: 模板图像
            threshold: 匹配阈值（默认0.7，提高准确性）
        
        Returns:
            [center_x, center_y] 如果匹配成功，否则 None
        """
        try:
            win = self.game_window
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

            print(f"[模板匹配] 匹配度: {max_val:.3f}, 阈值: {threshold}")

            if max_val >= threshold:
                center_x = win["left"] + max_loc[0] + template_w // 2
                center_y = win["top"] + max_loc[1] + template_h // 2
                print(f"[模板匹配] 找到匹配！坐标: ({center_x}, {center_y})")
                return [center_x, center_y]
            else:
                print(f"[模板匹配] 匹配度太低: {max_val:.3f}，低于阈值 {threshold}")
                return None

        except Exception as e:
            print(f"[模板匹配] 失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def test_stash_click(self):
        """测试打开仓库 - 使用模板匹配"""
        if self.template_img is None:
            messagebox.showwarning("未保存模板", "请先点击'选择仓库位置'保存模板")
            return

        print("[测试] 开始模板匹配...")

        pos = self._match_template_in_window(self.template_img)

        if not pos:
            messagebox.showerror("匹配失败", "未在游戏窗口内找到仓库图标，请重试")
            return

        x, y = pos
        print(f"[测试] 匹配成功！坐标: ({x}, {y})，开始点击...")

        # 执行点击（与 auto_buy_new.py 一致）
        pyautogui.moveTo(x, y, duration=0.1)
        time.sleep(0.3)
        pyautogui.click()
        time.sleep(1)
        pyautogui.click()
        time.sleep(3)  # 第三次点击后减少延迟

        messagebox.showinfo("完成", f"已点击仓库 ({x}, {y})")
        self.stash_open_pos = pos
        self.stash_pos_label.config(text=f"仓库位置: ({pos[0]}, {pos[1]})", foreground="green")

    def select_inventory_region(self):
        """选择背包区域"""
        if not self.game_window:
            messagebox.showwarning("未识别窗口", "请先点击'识别窗口'按钮")
            return

        win = self.game_window
        self.root.withdraw()
        time.sleep(0.1)

        with mss.mss() as sct:
            full_screenshot = sct.grab(sct.monitors[0])
            full_image = Image.frombytes("RGB", full_screenshot.size, full_screenshot.bgra, "raw", "BGRX")

        calib_window = tk.Toplevel()
        calib_window.attributes("-fullscreen", True)
        calib_window.attributes("-alpha", 0.3)
        calib_window.focus_force()

        bg_photo = ImageTk.PhotoImage(full_image)
        canvas = tk.Canvas(calib_window, cursor="cross", bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        canvas.create_image(0, 0, image=bg_photo, anchor=tk.NW)

        # 绘制窗口边框
        canvas.create_rectangle(win["left"], win["top"], win["right"], win["bottom"],
                               outline="red", width=3, dash=(10, 5))

        canvas.create_text(win["left"] + win["width"]//2, win["top"] + 30,
                          text="拖动选择背包区域",
                          fill="cyan", font=("Arial", 20, "bold"), anchor=tk.CENTER)

        canvas.create_text(win["left"] + win["width"]//2, win["top"] + 60,
                          text=f"当前行列: {self.grid_cols}x{self.grid_rows}",
                          fill="white", font=("Arial", 14), anchor=tk.CENTER)

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

        def on_confirm(event=None):
            x1 = min(selection["x1"], selection["x2"])
            y1 = min(selection["y1"], selection["y2"])
            x2 = max(selection["x1"], selection["x2"])
            y2 = max(selection["y1"], selection["y2"])

            if x2 - x1 < 100 or y2 - y1 < 100:
                messagebox.showerror("错误", "选择区域太小")
                return

            # 转换为相对游戏窗口的坐标
            rel_x1 = x1 - win["left"]
            rel_y1 = y1 - win["top"]
            rel_x2 = x2 - win["left"]
            rel_y2 = y2 - win["top"]

            self.inventory_region = (rel_x1, rel_y1, rel_x2, rel_y2)
            self._generate_cells()

            self.inventory_label.config(
                text=f"背包区域: {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)}格 [相对]",
                foreground="green"
            )

            calib_window.destroy()
            self.root.deiconify()

        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        calib_window.bind("<Return>", on_confirm)
        calib_window.bind("<Escape>", on_cancel)
        canvas.focus_force()
        canvas.bg_photo = bg_photo

    def _generate_cells(self):
        """根据背包区域和行列数生成格子"""
        if not self.inventory_region:
            return

        x1, y1, x2, y2 = self.inventory_region
        width = x2 - x1
        height = y2 - y1

        cell_width = width / self.grid_cols
        cell_height = height / self.grid_rows

        self.stash_cells = []

        for row in range(self.grid_rows):
            for col in range(self.grid_cols):
                cell_x1 = int(x1 + col * cell_width)
                cell_y1 = int(y1 + row * cell_height)
                cell_x2 = int(x1 + (col + 1) * cell_width)
                cell_y2 = int(y1 + (row + 1) * cell_height)

                self.stash_cells.append([[cell_x1, cell_y1], [cell_x2, cell_y2]])

        print(f"已生成 {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)} 个格子")

    def show_grid_settings(self):
        """设置行列数"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置行列数")
        settings_window.geometry("300x130")
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

                if self.inventory_region:
                    self._generate_cells()
                    self.inventory_label.config(
                        text=f"背包区域: {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)}格",
                        foreground="green"
                    )

                settings_window.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=15)

        ttk.Button(btn_frame, text="确定", command=on_ok, width=12).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=settings_window.destroy, width=12).pack(side=tk.LEFT, padx=10)

        cols_entry.focus_set()

    def stop_stash_test(self):
        """停止存仓测试"""
        self.stash_test_running = False
        self.stash_status_label.config(text="状态: 已停止", foreground="red")
        self.stash_stop_btn.config(state=tk.DISABLED)
        print("[存仓] 测试已停止")

    def test_stash_operation(self):
        """测试存仓操作 - 带置信度判断"""
        if not self.stash_cells:
            messagebox.showwarning("警告", "未配置仓库格子，请先选择背包区域")
            return

        if self.template_img is None:
            messagebox.showwarning("未保存模板", "请先点击'选择仓库位置'保存模板")
            return

        if self.inventory_region is None:
            messagebox.showwarning("警告", "未配置背包区域，请先选择背包区域")
            return

        # 初始化
        self.stash_test_running = True
        self.stash_stop_btn.config(state=tk.NORMAL)
        self.stash_status_label.config(text="状态: 点击仓库中...", foreground="orange")
        self.stash_conf_label.config(text="仓库置信度: --")
        self.inventory_conf_label.config(text="背包置信度: --")

        num_cells = len(self.stash_cells)
        print(f"开始存仓测试，共 {num_cells} 个格子")

        # 1. 模板匹配找到仓库位置并点击
        print("[存仓] 步骤1: 模板匹配仓库...")
        pos = self._match_template_in_window(self.template_img)
        if not pos:
            messagebox.showerror("匹配失败", "未在游戏窗口内找到仓库图标，请重试")
            self.stash_stop_btn.config(state=tk.DISABLED)
            self.stash_status_label.config(text="状态: 匹配失败", foreground="red")
            return

        x, y = pos
        print(f"[存仓] 仓库位置: ({x}, {y})")

        # 2. 点击仓库
        print(f"[存仓] 步骤2: 点击仓库...")
        pyautogui.moveTo(x, y, duration=0.1)
        time.sleep(0.3)
        pyautogui.click()
        time.sleep(1)
        pyautogui.click()

        self.stash_status_label.config(text="状态: 等待仓库打开...", foreground="orange")

        # 3. 使用非阻塞方式等待仓库打开并检测
        print(f"[存仓] 步骤3: 检测仓库是否打开...")
        self.stash_wait_count = 0
        self.stash_max_wait = 20  # 最多等待20秒
        self._check_stash_open()

    def _check_stash_open(self):
        """非阻塞方式检测仓库是否打开"""
        if not self.stash_test_running:
            return

        STASH_OPEN_THRESHOLD = 0.8
        INVENTORY_FULL_THRESHOLD = 0.2

        self.stash_wait_count += 1

        # 检查是否超时
        if self.stash_wait_count > self.stash_max_wait:
            print("[存仓] 等待超时")
            self.stash_status_label.config(text="状态: 等待超时", foreground="red")
            self.stash_stop_btn.config(state=tk.DISABLED)
            return

        # 截取游戏窗口
        with mss.mss() as sct:
            monitor = {
                "top": self.game_window["top"],
                "left": self.game_window["left"],
                "width": self.game_window["width"],
                "height": self.game_window["height"]
            }
            screenshot = sct.grab(monitor)
            screen_img = np.array(screenshot)[:, :, :3]

        # 判断1: 仓库模板置信度（使用保存的检测区域模板进行匹配）
        if self.stash_confidence_template is not None:
            # 截取当前检测区域
            sx1, sy1, sx2, sy2 = self.stash_confidence_region
            current_region_img = screen_img[sy1:sy2, sx1:sx2].copy()
            stash_confidence = self._get_template_confidence(current_region_img, self.stash_confidence_template)
        else:
            # 使用原始模板匹配整个窗口
            stash_confidence = self._get_template_confidence(screen_img, self.template_img)

        # 判断2: 背包区域置信度（使用保存的模板进行匹配）
        items = []  # 默认空列表
        if self.inventory_confidence_template is not None:
            ix1, iy1, ix2, iy2 = self.inventory_confidence_region
            inv_x1, inv_y1, inv_x2, inv_y2 = ix1, iy1, ix2, iy2
            current_inv_img = screen_img[iy1:iy2, ix1:ix2].copy()
            inv_confidence = self._get_template_confidence(current_inv_img, self.inventory_confidence_template)
        else:
            # 使用HSV检测
            if self.inventory_confidence_region:
                inv_x1, inv_y1, inv_x2, inv_y2 = self.inventory_confidence_region
            else:
                inv_x1, inv_y1, inv_x2, inv_y2 = self.inventory_region

            inv_img = screen_img[inv_y1:inv_y2, inv_x1:inv_x2].copy()

            from hsv_detector import detect_items
            items, mask = detect_items(inv_img, self.hsv_config, min_area=200, input_format="BGR")

            # 物品覆盖率作为背包置信度（高覆盖率=低置信度需要存仓）
            if inv_img.size > 0 and items:
                item_area = sum(item["area"] for item in items)
                inv_area = (inv_x2 - inv_x1) * (inv_y2 - inv_y1)
                inv_confidence = 1.0 - min(item_area / inv_area * 5, 1.0)
            else:
                inv_confidence = 1.0

        # 更新显示
        self.stash_conf_label.config(text=f"仓库置信度: {stash_confidence:.2f}")
        self.inventory_conf_label.config(text=f"背包置信度: {inv_confidence:.2f}")
        self._update_stash_display(screen_img, inv_x1, inv_y1, inv_x2, inv_y2, items)

        # 判断逻辑
        if stash_confidence > STASH_OPEN_THRESHOLD:
            print(f"[存仓] 仓库已打开，置信度: {stash_confidence:.2f}")

            if inv_confidence < INVENTORY_FULL_THRESHOLD:
                print(f"[存仓] 背包满了，置信度: {inv_confidence:.2f}，执行存仓")
                self.stash_status_label.config(text="状态: 背包满了，执行存仓...", foreground="yellow")
                self._execute_stash()
                return
            else:
                print(f"[存仓] 背包未满，置信度: {inv_confidence:.2f}")
                self.stash_status_label.config(text="状态: 背包未满", foreground="green")

        # 继续等待检测
        self.root.after(500, self._check_stash_open)

    def _execute_stash(self):
        """执行存仓操作 - 带格子置信度判断"""
        if not self.stash_test_running:
            return

        num_cells = len(self.stash_cells)
        print(f"[存仓] 开始智能存仓，共 {num_cells} 个格子")
        print(f"[存仓] 空格子阈值: {self.EMPTY_CELL_THRESHOLD:.2f}（高于此值跳过）")

        original_pause = pyautogui.PAUSE
        original_min_duration = pyautogui.MINIMUM_DURATION
        original_min_sleep = pyautogui.MINIMUM_SLEEP

        pyautogui.PAUSE = 0
        pyautogui.MINIMUM_DURATION = 0
        pyautogui.MINIMUM_SLEEP = 0

        start_time = time.time()
        stashed_count = 0
        skipped_count = 0

        try:
            pyautogui.keyDown('ctrl')
            time.sleep(0.05)

            for idx, cell in enumerate(self.stash_cells, 1):
                if not self.stash_test_running:
                    break
                if isinstance(cell, list) and len(cell) == 2:
                    p1, p2 = cell
                    if isinstance(p1, list) and len(p1) >= 2 and isinstance(p2, list) and len(p2) >= 2:
                        x1, y1 = p1[0], p1[1]
                        x2, y2 = p2[0], p2[1]
                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2
                        
                        # 检查格子置信度（是否为空格子）
                        confidence = self._check_cell_confidence([x1, y1, x2, y2])
                        
                        if confidence >= self.EMPTY_CELL_THRESHOLD:
                            # 置信度高，认为是空格子，跳过（不输出日志）
                            skipped_count += 1
                            continue
                        else:
                            # 置信度低，认为有物品，执行存仓（输出日志）
                            stashed_count += 1
                            pyautogui.click(cx, cy)
                            print(f"[存仓] 格子 {idx}/{num_cells} - 置信度: {confidence:.2f} - 存仓")
                            
                        time.sleep(0.03)  # 遍历间隔

            pyautogui.keyUp('ctrl')
            elapsed = time.time() - start_time
            print(f"[存仓] ✓ 存仓完成！")
            print(f"[存仓] 总格子: {num_cells} | 存仓: {stashed_count} | 跳过: {skipped_count}")
            print(f"[存仓] 耗时: {elapsed:.2f}秒 | 速度: {num_cells/elapsed:.1f}格子/秒")
            self.stash_status_label.config(text=f"状态: 存仓完成 ({elapsed:.1f}秒)", foreground="green")
            messagebox.showinfo("完成", f"存仓测试完成！共 {num_cells} 格，存仓 {stashed_count} 格，耗时 {elapsed:.2f}秒")

        except Exception as e:
            print(f"[存仓] 出错: {e}")
            try:
                pyautogui.keyUp('ctrl')
            except:
                pass
        finally:
            pyautogui.PAUSE = original_pause
            pyautogui.MINIMUM_DURATION = original_min_duration
            pyautogui.MINIMUM_SLEEP = original_min_sleep
            self.stash_stop_btn.config(state=tk.DISABLED)

    def _check_cell_confidence(self, cell_region):
        """检查单个格子的置信度（是否为空格子）
        
        Args:
            cell_region: 格子区域 [x1, y1, x2, y2]（相对于游戏窗口）
        
        Returns:
            confidence: 置信度（0-1），高于 EMPTY_CELL_THRESHOLD 认为是空格子
        """
        if self.empty_cell_template is None:
            # 如果没有空格子模板，默认认为是空格子（返回高置信度）
            return 1.0
        
        if self.game_window is None:
            return 0.0
        
        try:
            x1, y1, x2, y2 = cell_region
            
            # 截取格子区域（相对于游戏窗口）
            with mss.mss() as sct:
                monitor = {
                    "top": self.game_window["top"] + y1,
                    "left": self.game_window["left"] + x1,
                    "width": x2 - x1,
                    "height": y2 - y1
                }
                screenshot = sct.grab(monitor)
                cell_img = np.array(screenshot)[:, :, :3]
            
            # 计算与空格子模板的匹配度
            confidence = self._get_template_confidence(cell_img, self.empty_cell_template)
            return confidence
            
        except Exception as e:
            print(f"[格子置信度] 检测失败: {e}")
            return 0.0

    def save_stash_config(self):
        """保存仓库相关配置"""
        try:
            config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            # 仓库位置
            config["stash_open_pos"] = self.stash_open_pos

            # 仓库格子
            config["cells_map"] = self.stash_cells

            # 窗口信息
            if self.game_window:
                config["game_window"] = {
                    "left": self.game_window["left"],
                    "top": self.game_window["top"],
                    "width": self.game_window["width"],
                    "height": self.game_window["height"],
                    "title": self.game_window["title"]
                }
            
            # 服务器类型
            config["game_server"] = self.game_server

            # 仓库模板
            if self.template_img is not None:
                config["stash_template"] = self.template_img.tolist()

            # 置信度检测区域和模板
            if self.stash_confidence_region:
                config["stash_confidence_region"] = list(self.stash_confidence_region)
            if self.stash_confidence_template is not None:
                config["stash_confidence_template"] = self.stash_confidence_template.tolist()
            if self.inventory_confidence_region:
                config["inventory_confidence_region"] = list(self.inventory_confidence_region)
            if self.inventory_confidence_template is not None:
                config["inventory_confidence_template"] = self.inventory_confidence_template.tolist()

            # 背包区域
            if self.inventory_region:
                config["inventory_region"] = list(self.inventory_region)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)

            messagebox.showinfo("成功", f"仓库配置已保存到: {self.config_path}")
            self._refresh_stash_display()  # 保存后刷新显示
        except Exception as e:
            messagebox.showerror("错误", f"保存仓库配置失败: {e}")

    def _get_template_confidence(self, screen_img, template_img):
        """获取模板匹配的置信度（优化版）
        
        使用多种匹配方法和图像预处理来提高置信度准确性
        """
        try:
            template_h, template_w = template_img.shape[0], template_img.shape[1]
            screen_h, screen_w = screen_img.shape[0], screen_img.shape[1]

            # 尺寸检查：搜索图像必须大于等于模板图像
            if screen_h < template_h or screen_w < template_w:
                print(f"[模板匹配] 尺寸不足: 搜索区域 {screen_w}x{screen_h}, 模板 {template_w}x{template_h}")
                return 0.0

            # 图像预处理：转为灰度并进行高斯模糊
            gray_template = cv2.cvtColor(template_img, cv2.COLOR_BGR2GRAY)
            gray_screen = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
            
            # 高斯模糊减少噪声
            gray_template = cv2.GaussianBlur(gray_template, (3, 3), 0)
            gray_screen = cv2.GaussianBlur(gray_screen, (3, 3), 0)

            # 使用多种匹配方法取最佳值
            methods = [
                cv2.TM_CCOEFF_NORMED,
                cv2.TM_CCORR_NORMED,
                cv2.TM_SQDIFF_NORMED  # 这个方法是越小越好
            ]
            
            max_confidence = 0.0
            
            for method in methods:
                try:
                    result = cv2.matchTemplate(gray_screen, gray_template, method)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    
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
            print(f"模板匹配失败: {e}")
            return 0.0

    def _update_stash_display(self, screen_img, inv_x1, inv_y1, inv_x2, inv_y2, items):
        """更新存仓测试的画面显示"""
        try:
            display_img = screen_img.copy()

            # 画背包区域框
            cv2.rectangle(display_img, (inv_x1, inv_y1), (inv_x2, inv_y2), (0, 255, 0), 2)

            # 画检测到的物品
            for item in items:
                rx, ry, rw, rh = item["bbox"]
                cx, cy = item["center"]
                screen_rx = inv_x1 + rx
                screen_ry = inv_y1 + ry
                cv2.rectangle(display_img, (screen_rx, screen_ry), (screen_rx+rw, screen_ry+rh), (0, 0, 255), 2)
                cv2.circle(display_img, (screen_rx+cx, screen_ry+cy), 5, (0, 0, 255), -1)

            canvas_w = self.stash_canvas.winfo_width()
            canvas_h = self.stash_canvas.winfo_height()

            if canvas_w <= 1 or canvas_h <= 1:
                return

            img_rgb = cv2.cvtColor(display_img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            pil_img.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)

            self.stash_canvas.delete("all")
            self.stash_canvas.create_image(canvas_w // 2, canvas_h // 2, image=tk_img, anchor=tk.CENTER)
            self.stash_canvas.image = tk_img

        except Exception as e:
            print(f"更新显示失败: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoBuyDebugTool(root)
    root.mainloop()
