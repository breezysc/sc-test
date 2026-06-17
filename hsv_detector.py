"""
HSV检测器模块 - 独立的物品识别功能
用于POE2紫色高亮物品检测
"""

import cv2
import numpy as np


def apply_hsv_mask(img, hsv_config):
    """
    应用HSV过滤
    
    参数:
        img: BGR格式的图像（OpenCV格式）
        hsv_config: HSV配置字典，包含 h_min, h_max, s_min, s_max, v_min, v_max
    
    返回:
        mask: 二值掩码图像
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    lower = np.array([
        hsv_config["h_min"], hsv_config["s_min"], hsv_config["v_min"]])
    upper = np.array([
        hsv_config["h_max"], hsv_config["s_max"], hsv_config["v_max"]])
    
    mask = cv2.inRange(hsv, lower, upper)
    
    return mask


def detect_items(img, hsv_config, min_area=500, input_format="BGR"):
    """
    检测图像中的高亮物品
    
    参数:
        img: 图像数组
        hsv_config: HSV配置字典，包含 h_min, h_max, s_min, s_max, v_min, v_max
        min_area: 最小检测面积，默认500
        input_format: 输入图像格式，"BGR"（OpenCV）或 "RGB"（PIL），默认"BGR"
    
    返回:
        detected_items: 检测到的物品列表，每个物品包含:
            - bbox: (x, y, w, h) 边界框
            - center: (x, y) 中心点坐标
            - area: 面积
    """
    # 如果输入是RGB格式，转换为BGR
    if input_format.upper() == "RGB":
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    
    # 应用HSV
    mask = apply_hsv_mask(img, hsv_config)
    
    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # 找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detected_items = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > min_area:
            x, y, w, h = cv2.boundingRect(cnt)
            detected_items.append({
                "bbox": (x, y, w, h),
                "center": (x + w // 2, y + h // 2),
                "area": area
            })
    
    return detected_items, mask


def draw_detection_result(img, items, color=(0, 255, 0), thickness=3, input_format="RGB"):
    """
    在图像上绘制检测结果
    
    参数:
        img: 图像数组
        items: 检测到的物品列表
        color: 绘制颜色，默认绿色
        thickness: 线条粗细，默认3
        input_format: 输入图像格式，"BGR"（OpenCV）或 "RGB"（PIL），默认"RGB"
    
    返回:
        result_img: 绘制了检测结果的图像
    """
    # 确保图像是BGR格式用于OpenCV操作
    if input_format.upper() == "RGB":
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        img_bgr = img.copy()
    
    result_img_bgr = img_bgr.copy()
    
    for item in items:
        x, y, w, h = item["bbox"]
        cx, cy = item["center"]
        
        # 绘制边界框
        cv2.rectangle(result_img_bgr, (x, y), (x + w, y + h), color, thickness)
        
        # 绘制中心点
        cv2.circle(result_img_bgr, (cx, cy), 8, (0, 0, 255), -1)
    
    # 如果输入是RGB格式，转换回RGB
    if input_format.upper() == "RGB":
        result_img = cv2.cvtColor(result_img_bgr, cv2.COLOR_BGR2RGB)
    else:
        result_img = result_img_bgr
    
    return result_img


# 默认HSV配置
DEFAULT_HSV_CONFIG = {
    "h_min": 105,
    "h_max": 180,
    "s_min": 70,
    "s_max": 255,
    "v_min": 70,
    "v_max": 255
}


# 颜色预设
COLOR_PRESETS = {
    "purple": {"h_min": 105, "h_max": 180, "s_min": 70, "s_max": 255, "v_min": 70, "v_max": 255},
    "magenta": {"h_min": 140, "h_max": 180, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
    "red": {"h_min": 0, "h_max": 20, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
    "green": {"h_min": 35, "h_max": 85, "s_min": 100, "s_max": 255, "v_min": 100, "v_max": 255},
}


if __name__ == "__main__":
    # 简单测试
    print("HSV检测器模块测试")
    print("默认配置:", DEFAULT_HSV_CONFIG)
    print("可用预设:", list(COLOR_PRESETS.keys()))
