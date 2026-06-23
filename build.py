"""
AutoBuy 打包脚本
使用 PyInstaller 打包为单个 EXE 文件
"""

import subprocess
import os
import shutil

def build_exe():
    # 清理旧构建
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")
    
    # PyInstaller 命令
    cmd = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--noupx",
        "--name=AutoBuy",
        "--icon=icon.ico",
        "--add-data=templates;templates",
        "--add-data=*.json;.",
        "--add-data=cc.png;.",
        "--hidden-import=hsv_detector",
        "--hidden-import=window_locator",
        "--hidden-import=template_locator_integrator",
        "launcher.py"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("stdout:", result.stdout)
        print("stderr:", result.stderr)
        print("打包成功！")
        
        # 复制依赖文件到 dist 目录
        copy_dependencies()
        
    except subprocess.CalledProcessError as e:
        print(f"打包失败: {e}")
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)

def copy_dependencies():
    """复制依赖文件到 dist 目录"""
    dist_dir = "dist"
    
    # 需要复制的文件
    files_to_copy = [
        "auto_buy_new.py",
        "hsv_detector.py",
        "window_locator.py",
        "template_locator_integrator.py",
        "auto_buy_config.json",
        "good.json",
        "inventory_hash_config.json",
        "inventory_config.json",
        "cc.png",
    ]
    
    dirs_to_copy = [
        "templates"
    ]
    
    for f in files_to_copy:
        if os.path.exists(f):
            shutil.copy(f, dist_dir)
            print(f"复制: {f}")
    
    for d in dirs_to_copy:
        if os.path.exists(d):
            dest = os.path.join(dist_dir, d)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(d, dest)
            print(f"复制目录: {d}")
    
    print("依赖文件复制完成")

if __name__ == "__main__":
    build_exe()