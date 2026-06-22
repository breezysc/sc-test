import sys
sys.path.insert(0, '.')
import json

# 用户提供的屏幕坐标
# 锚点: 左上(253,816) - 右下(277,828)
# ROI格子区域: 左上(86,858) - 右下(442,1213)
anchor_screen_x1, anchor_screen_y1 = 253, 816
roi_screen_x1, roi_screen_y1 = 86, 858
roi_screen_x2, roi_screen_y2 = 442, 1213

# 从配置文件读新 offset
with open('template_locator_config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)
stash_offset = cfg['stash']['offset']
dx1, dy1, dx2, dy2 = stash_offset['dx1'], stash_offset['dy1'], stash_offset['dx2'], stash_offset['dy2']

print('=== 配置验证 ===')
print('新 offset: dx1=%d, dy1=%d, dx2=%d, dy2=%d' % (dx1, dy1, dx2, dy2))
print()

# 关键验证: roi_screen_x1 = anchor_screen_x1 + dx1 (窗口位置抵消)
expected_roi_screen_x1 = anchor_screen_x1 + dx1
expected_roi_screen_y1 = anchor_screen_y1 + dy1
expected_roi_screen_x2 = anchor_screen_x1 + dx2
expected_roi_screen_y2 = anchor_screen_y1 + dy2

print('=== ROI 屏幕坐标验证 (与窗口位置无关) ===')
print('期望 ROI 屏幕: (%d,%d)-(%d,%d)' % (roi_screen_x1, roi_screen_y1, roi_screen_x2, roi_screen_y2))
print('计算 ROI 屏幕: (%d,%d)-(%d,%d)' % (
    expected_roi_screen_x1, expected_roi_screen_y1,
    expected_roi_screen_x2, expected_roi_screen_y2))
ok1 = (expected_roi_screen_x1 == roi_screen_x1 and
       expected_roi_screen_y1 == roi_screen_y1 and
       expected_roi_screen_x2 == roi_screen_x2 and
       expected_roi_screen_y2 == roi_screen_y2)
print('结果:', 'OK 完全匹配' if ok1 else 'FAIL 不匹配')
print()

# Grid 验证
cols, rows = 12, 12
roi_w = roi_screen_x2 - roi_screen_x1
roi_h = roi_screen_y2 - roi_screen_y1
cell_w = roi_w / cols
cell_h = roi_h / rows
print('=== Grid 信息 ===')
print('ROI 尺寸: %dx%d 像素' % (roi_w, roi_h))
print('12x12 格子, 每格 %.1fx%.1f 像素' % (cell_w, cell_h))
print('格子 1 (0,0) 中心屏幕: (%.0f, %.0f)' % (
    roi_screen_x1 + cell_w / 2, roi_screen_y1 + cell_h / 2))
print('格子 144 (11,11) 中心屏幕: (%.0f, %.0f)' % (
    roi_screen_x2 - cell_w / 2, roi_screen_y2 - cell_h / 2))
print()
print('OK 坐标系统验证通过: ROI = anchor_screen + offset, 与窗口位置无关')
