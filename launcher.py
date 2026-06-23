"""
AutoBuy 自动购买工具 - 启动器
功能：提供UI界面配置游戏路径
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import os
import sys

class AutoBuyLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoBuy 自动购买工具")
        self.root.geometry("400x280")
        self.root.resizable(False, False)
        
        # 默认配置
        self.config = {
            "server": "china",  # 默认国服
            "game_path": ""
        }
        
        self.create_widgets()
    
    def create_widgets(self):
        # 标题
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill="x")
        
        title_label = ttk.Label(title_frame, text="AutoBuy 自动购买工具", 
                               font=("Arial", 16, "bold"))
        title_label.pack()
        
        # 服务器选择
        server_frame = ttk.LabelFrame(self.root, text="服务器选择", padding="10")
        server_frame.pack(fill="x", padx=10, pady=5)
        
        self.server_var = tk.StringVar(value="china")
        
        china_radio = ttk.Radiobutton(server_frame, text="国服", 
                                      variable=self.server_var, value="china")
        china_radio.pack(anchor="w", padx=5)
        
        global_radio = ttk.Radiobutton(server_frame, text="国际服", 
                                       variable=self.server_var, value="global")
        global_radio.pack(anchor="w", padx=5)
        
        # 游戏路径
        path_frame = ttk.LabelFrame(self.root, text="游戏路径", padding="10")
        path_frame.pack(fill="x", padx=10, pady=5)
        
        path_inner = ttk.Frame(path_frame)
        path_inner.pack(fill="x")
        
        self.path_entry = ttk.Entry(path_inner, width=40)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        browse_btn = ttk.Button(path_inner, text="浏览", command=self.browse_game)
        browse_btn.pack(side="right")
        
        # 操作按钮
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill="x")
        
        start_btn = ttk.Button(btn_frame, text="启动", command=self.start, 
                               style="Accent.TButton")
        start_btn.pack(side="left", expand=True, padx=5)
        
        exit_btn = ttk.Button(btn_frame, text="退出", command=self.root.quit)
        exit_btn.pack(side="right", expand=True, padx=5)
        
        # 状态显示
        status_frame = ttk.Frame(self.root, padding="10")
        status_frame.pack(fill="x")
        
        self.status_label = ttk.Label(status_frame, text="就绪", 
                                      foreground="green")
        self.status_label.pack()
        
        # 设置按钮样式
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Arial", 10, "bold"))
    
    def browse_game(self):
        path = filedialog.askopenfilename(
            title="选择游戏可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)
    
    def start(self):
        self.status_label.config(text="启动中...", foreground="orange")
        self.root.update()
        
        # 获取游戏路径
        game_path = self.path_entry.get().strip()
        if not game_path:
            messagebox.showerror("错误", "请选择游戏路径！")
            self.status_label.config(text="请选择游戏路径", foreground="red")
            return
        
        if not os.path.exists(game_path):
            messagebox.showerror("错误", "游戏路径不存在！")
            self.status_label.config(text="游戏路径不存在", foreground="red")
            return
        
        # 构建命令 - 直接运行 auto_buy_new.py
        cmd = [sys.executable, "auto_buy_new.py"]
        cmd.append(f"--server={self.server_var.get()}")
        cmd.append(f"--game={game_path}")
        
        try:
            # 直接启动程序（不在新窗口中运行）
            subprocess.Popen(cmd, cwd=os.path.dirname(__file__))
            self.status_label.config(text="已启动", foreground="green")
            messagebox.showinfo("成功", "AutoBuy 已启动！")
        except Exception as e:
            self.status_label.config(text=f"启动失败: {e}", foreground="red")
            messagebox.showerror("错误", f"启动失败: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = AutoBuyLauncher(root)
    root.mainloop()
