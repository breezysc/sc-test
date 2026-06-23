"""
AutoBuy 自动购买工具 - 启动器
功能：提供UI界面选择服务器和游戏路径，实时显示运行日志
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import threading
import subprocess
import os
import sys
import queue
import time

class AutoBuyLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoBuy 自动购买工具")
        self.root.geometry("600x500")
        self.root.minsize(500, 400)
        
        # 运行状态
        self.is_running = False
        self.process = None
        self.game_path = ""
        
        self.create_widgets()
    
    def create_widgets(self):
        # 顶部设置区域
        settings_frame = ttk.Frame(self.root, padding="10")
        settings_frame.pack(fill="x")
        
        # 服务器选择
        server_frame = ttk.LabelFrame(settings_frame, text="服务器选择", padding="5")
        server_frame.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.server_var = tk.StringVar(value="china")
        
        china_radio = ttk.Radiobutton(server_frame, text="国服", 
                                      variable=self.server_var, value="china")
        china_radio.pack(side="left", padx=5)
        
        global_radio = ttk.Radiobutton(server_frame, text="国际服", 
                                       variable=self.server_var, value="global")
        global_radio.pack(side="left", padx=5)
        
        # 游戏路径
        path_frame = ttk.LabelFrame(settings_frame, text="游戏路径", padding="5")
        path_frame.pack(side="left", fill="x", expand=True)
        
        path_inner = ttk.Frame(path_frame)
        path_inner.pack(fill="x")
        
        self.path_entry = ttk.Entry(path_inner, width=30)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        browse_btn = ttk.Button(path_inner, text="浏览", command=self.browse_game, width=6)
        browse_btn.pack(side="right")
        
        # 控制按钮区域
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill="x")
        
        self.start_btn = ttk.Button(control_frame, text="启动", command=self.toggle_run,
                                    style="Accent.TButton", width=15)
        self.start_btn.pack(side="left", padx=5)
        
        self.status_label = ttk.Label(control_frame, text="状态: 已暂停", 
                                      foreground="orange", font=("Arial", 10, "bold"))
        self.status_label.pack(side="left", padx=20)
        
        # 日志区域
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding="5")
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, 
                                                    font=("Consolas", 9),
                                                    state="disabled",
                                                    bg="black", fg="lime")
        self.log_text.pack(fill="both", expand=True)
        
        # 配置标签样式
        self.log_text.tag_config("info", foreground="white")
        self.log_text.tag_config("warning", foreground="yellow")
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("success", foreground="lime")
        
        # 设置按钮样式
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Arial", 10, "bold"))
        style.configure("Running.TButton", font=("Arial", 10, "bold"))
        
        # 窗口关闭时清理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def browse_game(self):
        path = filedialog.askopenfilename(
            title="选择游戏可执行文件",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)
            self.game_path = path
    
    def log_message(self, message, tag="info"):
        """添加日志消息到文本框"""
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, message + "\n", tag)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.root.after(0, append)
    
    def toggle_run(self):
        """切换运行/暂停状态"""
        if not self.is_running:
            self.start()
        else:
            self.pause()
    
    def start(self):
        """启动程序"""
        # 获取游戏路径
        game_path = self.path_entry.get().strip()
        if not game_path:
            self.log_message("[错误] 请选择游戏路径！", "error")
            return
        
        if not os.path.exists(game_path):
            self.log_message("[错误] 游戏路径不存在！", "error")
            return
        
        self.game_path = game_path
        self.is_running = True
        
        # 更新UI
        self.start_btn.config(text="暂停")
        self.status_label.config(text="状态: 运行中", foreground="green")
        self.log_message("=" * 50, "info")
        self.log_message("[启动] AutoBuy 开始运行", "success")
        self.log_message(f"[配置] 服务器: {self.server_var.get()}", "info")
        self.log_message(f"[配置] 游戏路径: {game_path}", "info")
        self.log_message("=" * 50, "info")
        
        # 在后台线程中运行
        self.running_thread = threading.Thread(target=self.run_script, daemon=True)
        self.running_thread.start()
    
    def run_script(self):
        """在新进程中运行 auto_buy_new.py"""
        try:
            cmd = [
                sys.executable,
                "auto_buy_new.py",
                f"--server={self.server_var.get()}",
                f"--game={self.game_path}"
            ]
            
            # 使用 Popen 获取输出，CREATE_NO_WINDOW 阻止创建新窗口
            self.process = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # 实时读取输出
            for line in self.process.stdout:
                if not self.is_running:
                    break
                line = line.strip()
                if line:
                    # 根据日志内容设置颜色
                    if "[错误]" in line or "✗" in line or "失败" in line:
                        self.log_message(line, "error")
                    elif "[成功]" in line or "✓" in line or "已启动" in line:
                        self.log_message(line, "success")
                    elif "[警告]" in line or "⚠" in line:
                        self.log_message(line, "warning")
                    else:
                        self.log_message(line, "info")
            
            # 等待进程结束
            self.process.wait()
            
        except Exception as e:
            self.log_message(f"[错误] 运行失败: {e}", "error")
        
        # 进程结束后重置状态
        self.root.after(0, self.process_ended)
    
    def process_ended(self):
        """进程结束时调用"""
        self.is_running = False
        self.start_btn.config(text="启动")
        self.status_label.config(text="状态: 已结束", foreground="gray")
        self.log_message("[结束] 程序已停止", "warning")
    
    def pause(self):
        """暂停/停止程序"""
        self.is_running = False
        
        if self.process:
            try:
                # 尝试优雅关闭
                self.process.terminate()
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
            except:
                pass
        
        # 更新UI
        self.start_btn.config(text="启动")
        self.status_label.config(text="状态: 已暂停", foreground="orange")
        self.log_message("[暂停] 程序已停止", "warning")
    
    def on_closing(self):
        """窗口关闭时"""
        if self.is_running:
            self.pause()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = AutoBuyLauncher(root)
    root.mainloop()
