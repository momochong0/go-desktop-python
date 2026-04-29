# 围棋小课堂 - Python版 🏆

一款面向围棋初学者的桌面教学应用，大字体、大棋盘，语音讲解带你入门。

![界面预览](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## 功能特点

- 🗣️ **语音讲解** - 自动解说每步棋的策略和位置（使用Windows系统语音）
- 🎯 **智能提示** - 气数警告、危险提示、落子建议
- 📏 **多种棋盘** - 支持 9路、13路、19路 棋盘
- ⚙️ **难度调节** - 适合不同水平的学习者
- 📖 **详细解说** - 简评/详解模式自由切换
- ⭐ **级位系统** - 从业余10级到业余9段，挑战升级！

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行程序

```bash
python main.py
```

## 技术栈

- **PyWebView** - 轻量级桌面应用框架
- **pyttsx3** - Windows系统语音（TTS）
- **HTML5 + JavaScript** - 游戏界面和逻辑

## 项目结构

```
go-desktop-python/
├── main.py           # 主程序入口
├── requirements.txt # 依赖列表
└── README.md        # 说明文档
```

## 打包为可执行文件

### 使用 PyInstaller

```bash
# 安装打包工具
pip install pyinstaller

# 打包为单个exe文件
pyinstaller --onefile --windowed --name "围棋小课堂" main.py
```

打包后的文件位于 `dist/` 目录。

## 游戏说明

### 基本规则
- 你下黑棋，电脑下白棋
- 黑棋先走
- 点击棋盘交叉点落子
- 围棋目标是围住更多的地盘

### 胜利条件
- 使用中国规则（黑贴6.5子）
- 终子数 = 棋子数 + 提子数
- 黑方终子数 > 白方终子数 + 6.5 则黑胜

### 级位系统
- 从业余10级开始
- 每赢一局升级
- 最高可达到业余9段
- AI难度会随级位提升而增加

## 快捷操作

| 操作 | 说明 |
|------|------|
| 点击棋盘 | 落子 |
| 新游戏 | 开始新一局 |
| 跳过 | 跳过本回合 |
| 悔棋 | 撤销最近两步 |

## 语音设置

- **语速**：可调节慢速/正常/较快
- **静音**：可随时切换
- **重播**：重复上一句解说

## License

MIT License
