#!/usr/bin/env python3
"""
游戏启动器 - Game Launcher
版本: 1.0.0
功能: 提供图形界面启动游戏，支持国服/国际服选择
"""

import os
import sys
import time
import logging
import traceback
import subprocess
from datetime import datetime
from tkinter import Tk, Label, Entry, Button, Frame, Radiobutton, StringVar, messagebox, filedialog, ttk

# 常量定义
VERSION = "1.0.0"
MIN_WIDTH = 600
MIN_HEIGHT = 350
LOG_MAX_SIZE = 5 * 1024 * 1024  # 5MB
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "GameLauncherLogs")

# 日志配置
def setup_logging():
    """设置日志系统"""
    os.makedirs(LOG_DIR, exist_ok=True)
    
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y%m%d')}.log")
    
    # 检查日志文件大小，超过限制则重命名
    if os.path.exists(log_file):
        if os.path.getsize(log_file) > LOG_MAX_SIZE:
            backup_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y%m%d')}_backup.log")
            if os.path.exists(backup_file):
                os.remove(backup_file)
            os.rename(log_file, backup_file)
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def log_info(message):
    """记录信息日志"""
    logging.info(message)

def log_error(message):
    """记录错误日志"""
    logging.error(message)

def log_exception(exc):
    """记录异常堆栈"""
    logging.error(f"异常: {exc}\n{traceback.format_exc()}")

class GameLauncher:
    """游戏启动器主类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"游戏启动器 v{VERSION}")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.resizable(True, True)
        
        # 设置窗口居中
        self.center_window()
        
        # 变量
        self.game_path = StringVar()
        self.server_type = StringVar(value="china")  # 默认国服
        
        # 加载历史配置
        self.load_config()
        
        # 创建界面
        self.create_widgets()
        
        # 记录启动信息
        log_info(f"========== 游戏启动器 v{VERSION} 启动 ==========")
        log_info(f"操作系统: {sys.platform}")
        log_info(f"Python版本: {sys.version}")
        log_info(f"屏幕分辨率: {root.winfo_screenwidth()}x{root.winfo_screenheight()}")
    
    def center_window(self):
        """窗口居中显示"""
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        x = (screen_width - MIN_WIDTH) // 2
        y = (screen_height - MIN_HEIGHT) // 2
        
        self.root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}+{x}+{y}")
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # 标题
        title_label = ttk.Label(main_frame, text="游戏启动器", font=('Arial', 16, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # 游戏路径输入区
        path_frame = ttk.LabelFrame(main_frame, text="游戏路径", padding="10")
        path_frame.pack(fill="x", pady=(0, 15))
        
        self.path_entry = ttk.Entry(path_frame, textvariable=self.game_path, width=50, font=('Arial', 10))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        browse_btn = ttk.Button(path_frame, text="浏览", command=self.browse_game_path)
        browse_btn.pack(side="right")
        
        # 客户端选择区
        server_frame = ttk.LabelFrame(main_frame, text="客户端选择", padding="10")
        server_frame.pack(fill="x", pady=(0, 15))
        
        china_radio = ttk.Radiobutton(server_frame, text="国服", variable=self.server_type, value="china",
                                     command=lambda: log_info(f"切换到国服"))
        china_radio.pack(side="left", padx=(0, 30))
        
        global_radio = ttk.Radiobutton(server_frame, text="国际服", variable=self.server_type, value="global",
                                       command=lambda: log_info(f"切换到国际服"))
        global_radio.pack(side="left")
        
        # 状态显示区
        self.status_label = ttk.Label(main_frame, text="就绪", font=('Arial', 10), foreground='green')
        self.status_label.pack(pady=(0, 15))
        
        # 操作按钮区
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        
        launch_btn = ttk.Button(button_frame, text="启动游戏", command=self.launch_game, style='Accent.TButton')
        launch_btn.pack(fill="x", pady=(0, 10))
        
        exit_btn = ttk.Button(button_frame, text="退出", command=self.exit_app)
        exit_btn.pack(fill="x")
        
        # 设置样式
        style = ttk.Style()
        style.configure('Accent.TButton', font=('Arial', 12, 'bold'))
    
    def browse_game_path(self):
        """浏览游戏路径"""
        file_path = filedialog.askopenfilename(
            title="选择游戏启动程序",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        
        if file_path:
            self.game_path.set(file_path)
            log_info(f"选择游戏路径: {file_path}")
            self.validate_path()
    
    def validate_path(self):
        """验证路径有效性"""
        path = self.game_path.get().strip()
        
        if not path:
            self.status_label.config(text="请选择游戏路径", foreground='orange')
            return False
        
        if not os.path.exists(path):
            self.status_label.config(text="错误: 文件不存在", foreground='red')
            log_error(f"路径不存在: {path}")
            return False
        
        if not path.lower().endswith('.exe'):
            self.status_label.config(text="错误: 不是可执行文件", foreground='red')
            log_error(f"不是可执行文件: {path}")
            return False
        
        if not os.access(path, os.X_OK):
            self.status_label.config(text="错误: 权限不足", foreground='red')
            log_error(f"权限不足: {path}")
            return False
        
        self.status_label.config(text="路径有效", foreground='green')
        log_info(f"路径验证通过: {path}")
        return True
    
    def launch_game(self):
        """启动游戏"""
        # 验证路径
        if not self.validate_path():
            return
        
        game_path = self.game_path.get().strip()
        server = self.server_type.get()
        
        log_info(f"========== 开始启动游戏 ==========")
        log_info(f"游戏路径: {game_path}")
        log_info(f"服务器类型: {'国服' if server == 'china' else '国际服'}")
        
        try:
            self.status_label.config(text="正在启动游戏...", foreground='blue')
            self.root.update()
            
            # 启动游戏进程
            process = subprocess.Popen(game_path, shell=True)
            log_info(f"游戏进程已启动，PID: {process.pid}")
            
            self.status_label.config(text="游戏已启动", foreground='green')
            log_info("游戏启动成功")
            
            # 保存配置
            self.save_config()
            
            # 询问是否关闭启动器
            if messagebox.askyesno("游戏已启动", "游戏已成功启动，是否关闭启动器？"):
                self.exit_app()
                
        except Exception as e:
            self.status_label.config(text=f"启动失败: {str(e)}", foreground='red')
            log_error(f"启动失败: {e}")
            log_exception(e)
            messagebox.showerror("启动失败", f"无法启动游戏:\n{str(e)}")
    
    def load_config(self):
        """加载历史配置"""
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
                log_info("配置加载成功")
            except Exception as e:
                log_error(f"加载配置失败: {e}")
    
    def save_config(self):
        """保存配置"""
        config_path = os.path.join(LOG_DIR, "config.ini")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(f"game_path={self.game_path.get()}\n")
                f.write(f"server={self.server_type.get()}\n")
            log_info("配置保存成功")
        except Exception as e:
            log_error(f"保存配置失败: {e}")
    
    def exit_app(self):
        """退出应用"""
        log_info("========== 游戏启动器退出 ==========")
        self.root.quit()

def main():
    """主函数"""
    try:
        setup_logging()
        
        root = Tk()
        app = GameLauncher(root)
        root.mainloop()
        
    except Exception as e:
        log_error(f"程序异常: {e}")
        log_exception(e)
        messagebox.showerror("程序错误", f"程序运行出错:\n{str(e)}")

if __name__ == "__main__":
    main()