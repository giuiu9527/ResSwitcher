# 分辨率切换器 ResSwitcher

Windows 显示分辨率切换工具，**支持输入任意自定义分辨率**。

适合：远程桌面 / 云电脑 / 无显示器主机 / 串流（Moonlight、Parsec、AskLink、向日葵……）——
这些场景下画面来自虚拟显示器，系统自带的分辨率列表是固定的，这个工具可以让你随便加。

## 下载

到 [Releases](../../releases) 下载 `分辨率切换器.exe`，双击运行（会请求管理员权限，点「是」）。
不需要安装 Python，单文件。

## 功能

| 功能 | 说明 |
|---|---|
| 切换分辨率 / 刷新率 | 列出当前显示器支持的所有模式，双击即切换 |
| **任意自定义分辨率** | 输入 `宽 × 高 @ Hz` 点「应用」，列表里没有的会自动添加到虚拟显示器并切换 |
| 删除自定义分辨率 | 列表中绿色的行右键 → 删除 |
| 测试 15 秒 | 切换后倒计时，不按 Enter 自动还原，防止黑屏出不来 |
| 恢复原始 | 一键回到启动时的分辨率 |
| 虚拟显示器驱动 | 内置 [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver)，首次运行一键安装，菜单可卸载 |
| NVIDIA 物理显示器 | 接了真显示器的 N 卡，通过 NVAPI 创建自定义分辨率（= NVIDIA 控制面板「自定义分辨率」） |

## 使用

1. 运行 → 首次会提示安装虚拟显示器驱动，点「是」（几秒钟）
2. 在输入框填想要的分辨率，例如 `3300 × 1300 @ 60`，点「应用」
3. 屏幕闪一下，就切换过去了；以后它会一直在列表里

> 虚拟显示器的配置文件在 `C:\VirtualDisplayDriver\vdd_settings.xml`，程序自动维护，也可以手动改。

## 从源码运行 / 打包

```bash
python src/app.py        # 需要 Python 3.10+，无第三方依赖
build.bat                # 打包成单文件 exe（需要 PyInstaller）
```

## 目录

```
src/app.py          主程序（tkinter GUI）
src/vdd.py          虚拟显示器配置读写 / 重启设备
src/vdd_install.py  虚拟显示器驱动安装 / 卸载（SetupAPI）
src/nvcustom.py     NVAPI 自定义分辨率
driver/             Virtual Display Driver 驱动文件 + 默认配置
```

## 说明

- 仅支持 Windows 10 / 11 x64
- 驱动安装、切换分辨率需要管理员权限
- 虚拟显示器驱动来自开源项目 Virtual Display Driver（MIT），本项目仅做集成
