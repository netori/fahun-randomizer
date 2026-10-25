# 视频封面（v1.4.2）

- `../视频封面_16x9_1920x1080.png`：1920×1080，视频平台 16:9 封面
- `../视频封面_4x3_1600x1200.png`：1600×1200，4:3 封面
- 背景：`../源图/背景_生成图.png`（同目录相对路径 `../源图/背景_生成图.png`）
- 字体：Noto Serif SC（标题）/ Noto Sans SC（正文）；字体缺失时回退到华文中宋 / 微软雅黑

## 改字 / 重新出图

直接编辑 `封面_16x9.html` 或 `封面_4x3.html`，然后用 Chrome 无头渲染：

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu ^
  --hide-scrollbars --force-device-scale-factor=1 --virtual-time-budget=2000 ^
  --window-size=1920,1080 --screenshot=封面_16x9.png "file:///F:/.../封面_16x9.html"
```

4:3 版把 `--window-size` 改为 `1600,1200`。

## 当前文案

- 主标题：法魂随机器
- 副标题：职业物品 × 敌人 × BOSS —— 全部重新洗牌
- 卖点：7 份内置预设 · 多阶段 / 双人 BOSS · 独立存档 · 本体零改动
- 三条事实：物品只换地点不换名字 / 敌人全图 2.4 万个位置重排 / 方案独立覆盖层 + 每套方案一份存档
- 底部：同一颗种子，完全不同的交界地。 / 本体零改动 · 一键还原
