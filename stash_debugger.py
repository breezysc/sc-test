#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存仓调试工具 - 专门用于调试仓库相关功能
可以测试仓库格子点击和仓库位置点击
配置保存到 auto_buy_config.json
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import time
import mss
from PIL import Image, ImageTk


class StashDebugger:
    def __init__(self, root):
        self.root = root
        self.root.title("存仓调试工具")
        self.root.geometry("800x600")
        
        # 配置
        self.config_path = "auto_buy_config.json"
        self.stash_open_pos = [900, 380]
        self.stash_cells = []
        
        # 背包区域设置
        self.inventory_region = None  # (x1, y1, x2, y2)
        self.grid_cols = 12
        self.grid_rows = 5
        
        # 加载配置
        self.load_config()
        
        # 创建UI
        self.create_ui()
    
    def load_config(self):
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if "stash_open_pos" in config and len(config["stash_open_pos"]) == 2:
                        self.stash_open_pos = config["stash_open_pos"]
                    if "cells_map" in config and len(config["cells_map"]) > 0:
                        self.stash_cells = config["cells_map"]
                    # 从cells_map计算行列数
                    if self.stash_cells:
                        self.guess_grid_size()
                print(f"✓ 已加载配置: {len(self.stash_cells)} 个格子")
            except Exception as e:
                print(f"加载配置失败: {e}")
    
    def guess_grid_size(self):
        """从cells_map猜测行列数"""
        if not self.stash_cells:
            return
        
        # 获取所有格子的x坐标，去重后计算列数
        x_coords = set()
        for cell in self.stash_cells:
            x1, y1 = cell[0]
            x_coords.add(x1)
        
        self.grid_cols = len(x_coords)
        self.grid_rows = len(self.stash_cells) // self.grid_cols
    
    def save_config(self):
        """保存配置"""
        try:
            config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config["stash_open_pos"] = self.stash_open_pos
            config["cells_map"] = self.stash_cells
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            messagebox.showinfo("成功", "配置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")
    
    def select_stash_position(self):
        """选择仓库位置"""
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
                          text="点击选择仓库NPC位置", 
                          fill="green", font=("Arial", 20, "bold"))
        
        def on_click(event):
            self.stash_open_pos = [event.x, event.y]
            self.stash_pos_label.config(
                text=f"仓库位置: ({event.x}, {event.y})",
                foreground="green"
            )
            calib_window.destroy()
            self.root.deiconify()
        
        def on_cancel(event=None):
            calib_window.destroy()
            self.root.deiconify()
        
        canvas.bind("<Button-1>", on_click)
        calib_window.bind("<Escape>", on_cancel)
        canvas.bg_photo = bg_photo
    
    def select_inventory_region(self):
        """选择背包区域"""
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
                          text="拖动选择背包区域（包含所有格子）", 
                          fill="cyan", font=("Arial", 20, "bold"))
        
        canvas.create_text(screenshot.width // 2, 60, 
                          text=f"当前行列: {self.grid_cols}x{self.grid_rows}", 
                          fill="white", font=("Arial", 14))
        
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
                messagebox.showerror("错误", "选择区域太小，请重新选择")
                return
            
            self.inventory_region = (x1, y1, x2, y2)
            self.generate_cells()
            
            self.inventory_label.config(
                text=f"背包区域: ({x1},{y1})-({x2},{y2}) {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)}格",
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
    
    def generate_cells(self):
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
                
                self.stash_cells.append([
                    [cell_x1, cell_y1],
                    [cell_x2, cell_y2]
                ])
        
        print(f"✓ 已生成 {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)} 个格子")
    
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
                
                # 如果已经选择了背包区域，重新生成格子
                if self.inventory_region:
                    self.generate_cells()
                    self.inventory_label.config(
                        text=f"背包区域: {self.inventory_region} {self.grid_cols}x{self.grid_rows}={len(self.stash_cells)}格",
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
    
    def show_cells_visualization(self):
        """显示格子可视化"""
        if not self.stash_cells:
            messagebox.showwarning("警告", "没有格子配置")
            return
        
        vis_window = tk.Toplevel(self.root)
        vis_window.title("背包格子可视化")
        vis_window.geometry("600x500")
        
        canvas = tk.Canvas(vis_window, bg="black")
        canvas.pack(fill=tk.BOTH, expand=True)
        
        # 计算格子大小（缩放显示）
        max_x = max(cell[1][0] for cell in self.stash_cells)
        max_y = max(cell[1][1] for cell in self.stash_cells)
        min_x = min(cell[0][0] for cell in self.stash_cells)
        min_y = min(cell[0][1] for cell in self.stash_cells)
        
        scale = min(500 / (max_x - min_x), 400 / (max_y - min_y))
        offset_x = 50
        offset_y = 50
        
        # 绘制格子
        for i, cell in enumerate(self.stash_cells):
            x1, y1 = cell[0]
            x2, y2 = cell[1]
            
            # 缩放坐标
            sx1 = offset_x + (x1 - min_x) * scale
            sy1 = offset_y + (y1 - min_y) * scale
            sx2 = offset_x + (x2 - min_x) * scale
            sy2 = offset_y + (y2 - min_y) * scale
            
            # 绘制格子
            canvas.create_rectangle(sx1, sy1, sx2, sy2, outline="green", width=2)
            
            # 显示格子编号
            cx = (sx1 + sx2) // 2
            cy = (sy1 + sy2) // 2
            canvas.create_text(cx, cy, text=str(i + 1), fill="white", font=("Arial", 8))
        
        # 添加说明
        canvas.create_text(300, 470, text=f"共 {len(self.stash_cells)} 个格子 ({self.grid_cols}x{self.grid_rows})", fill="white")
    
    def test_stash_click(self):
        """测试仓库位置点击"""
        import pyautogui
        x, y = self.stash_open_pos
        print(f"测试点击仓库位置: ({x}, {y})")
        
        pyautogui.moveTo(x, y, duration=0.1)
        pyautogui.click()
        messagebox.showinfo("测试", f"已点击仓库位置 ({x}, {y})")
    
    def test_cell_click(self):
        """测试格子点击"""
        if not self.stash_cells:
            messagebox.showwarning("警告", "没有格子配置")
            return
        
        import pyautogui
        
        cell = self.stash_cells[0]
        x1, y1 = cell[0]
        x2, y2 = cell[1]
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        print(f"测试点击格子: ({center_x}, {center_y})")
        
        pyautogui.keyDown('ctrl')
        pyautogui.moveTo(center_x, center_y, duration=0.1)
        pyautogui.click()
        pyautogui.keyUp('ctrl')
        
        messagebox.showinfo("测试", f"已Ctrl+点击格子 ({center_x}, {center_y})")
    
    def test_all_cells(self):
        """测试所有格子"""
        if not self.stash_cells:
            messagebox.showwarning("警告", "没有格子配置")
            return
        
        import pyautogui
        
        messagebox.showinfo("提示", "即将开始测试所有格子，点击确定后3秒开始")
        time.sleep(3)
        
        for i, cell in enumerate(self.stash_cells[:6]):
            x1, y1 = cell[0]
            x2, y2 = cell[1]
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            
            print(f"测试格子 {i+1}: ({center_x}, {center_y})")
            
            pyautogui.keyDown('ctrl')
            pyautogui.moveTo(center_x, center_y, duration=0.1)
            pyautogui.click()
            pyautogui.keyUp('ctrl')
            time.sleep(0.5)
        
        messagebox.showinfo("完成", "已测试前6个格子")
    
    def show_cells_info(self):
        """显示格子信息"""
        if not self.stash_cells:
            messagebox.showinfo("信息", "没有格子配置")
            return
        
        info = f"格子总数: {len(self.stash_cells)} ({self.grid_cols}x{self.grid_rows})\n\n"
        for i, cell in enumerate(self.stash_cells[:12]):
            x1, y1 = cell[0]
            x2, y2 = cell[1]
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            info += f"格子{i+1}: ({x1},{y1})-({x2},{y2}) 中心: ({center_x},{center_y})\n"
        
        if len(self.stash_cells) > 12:
            info += f"\n... 还有 {len(self.stash_cells) - 12} 个格子"
        
        messagebox.showinfo("格子信息", info)
    
    def create_ui(self):
        """创建界面"""
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 背包区域设置
        inv_frame = ttk.LabelFrame(main_frame, text="背包格子设置", padding=10)
        inv_frame.pack(fill=tk.X, pady=5)
        
        inv_btn_frame = ttk.Frame(inv_frame)
        inv_btn_frame.pack(fill=tk.X)
        
        ttk.Button(inv_btn_frame, text="🎒 选择背包区域", command=self.select_inventory_region).pack(side=tk.LEFT, padx=5)
        ttk.Button(inv_btn_frame, text="📐 设置行列数", command=self.show_grid_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(inv_btn_frame, text="👁️ 查看格子布局", command=self.show_cells_visualization).pack(side=tk.LEFT, padx=5)
        
        self.inventory_label = ttk.Label(inv_btn_frame, text=f"背包区域: 未选择 ({self.grid_cols}x{self.grid_rows})", foreground="gray")
        self.inventory_label.pack(side=tk.RIGHT)
        
        # 仓库位置设置
        stash_frame = ttk.LabelFrame(main_frame, text="仓库位置设置", padding=10)
        stash_frame.pack(fill=tk.X, pady=5)
        
        stash_btn_frame = ttk.Frame(stash_frame)
        stash_btn_frame.pack(fill=tk.X)
        
        ttk.Button(stash_btn_frame, text="📍 选择仓库位置", command=self.select_stash_position).pack(side=tk.LEFT, padx=5)
        self.stash_pos_label = ttk.Label(stash_btn_frame, text=f"仓库位置: ({self.stash_open_pos[0]}, {self.stash_open_pos[1]})")
        self.stash_pos_label.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(stash_btn_frame, text="💾 保存配置", command=self.save_config).pack(side=tk.RIGHT)
        
        # 测试功能
        test_frame = ttk.LabelFrame(main_frame, text="测试功能", padding=10)
        test_frame.pack(fill=tk.X, pady=5)
        
        test_btn_frame = ttk.Frame(test_frame)
        test_btn_frame.pack(fill=tk.X)
        
        ttk.Button(test_btn_frame, text="🔘 测试仓库点击", command=self.test_stash_click).pack(side=tk.LEFT, padx=5)
        ttk.Button(test_btn_frame, text="🔘 测试单个格子", command=self.test_cell_click).pack(side=tk.LEFT, padx=5)
        ttk.Button(test_btn_frame, text="🔘 测试前6个格子", command=self.test_all_cells).pack(side=tk.LEFT, padx=5)
        ttk.Button(test_btn_frame, text="📋 查看格子信息", command=self.show_cells_info).pack(side=tk.LEFT, padx=5)
        
        # 使用提示
        tips_frame = ttk.LabelFrame(main_frame, text="使用提示")
        tips_frame.pack(fill=tk.X, pady=10)
        
        tips_text = """
1. 先设置背包区域：点击"选择背包区域"拖动选择包含所有格子的区域
2. 设置行列数（默认12列x5行=60格）
3. 点击"查看格子布局"确认格子划分是否正确
4. 设置仓库位置：点击"选择仓库位置"
5. 测试点击功能确认位置正确
6. 点击"保存配置"保存到 auto_buy_config.json
        """
        ttk.Label(tips_frame, text=tips_text, justify=tk.LEFT).pack(padx=10, pady=5)


if __name__ == "__main__":
    root = tk.Tk()
    app = StashDebugger(root)
    root.mainloop()
