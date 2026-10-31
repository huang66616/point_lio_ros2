# 候选文件选择与来源

源仓库分支为 `optimize/mid360-baseline`，HEAD 为 `571696bfcf28b8531ef5a2d2ea153f59124f9b08`。候选副本从当时**实际工作树**逐文件复制，不是单纯 `git archive HEAD`；因此包含 `include/ikd-Tree/ikd_Tree.cpp`、`ikd_Tree.h`、`src/laserMapping.cpp`、`launch/mapping_mid360.launch.py` 的未提交修改。`config/mid360.yaml` 是已跟踪但当时无未提交差异的 MID-360 适配文件。完整逐文件来源、SHA-256 和原 Git 状态见 [FILE_MANIFEST.json](FILE_MANIFEST.json)。

## 候选副本相对原工作树的改动

- `src/laserMapping.cpp`：给每次启动创建独立 `pointlio-XXXXXX` 运行目录；位置、矩阵、IMU 日志与可选 PCD 均写入此目录。默认父目录 `/tmp`，可用 `POINTLIO_RUN_ROOT` 指定已存在的父目录。创建或打开失败即退出，避免静默写入源码目录。算法计算和 ROS 输出接口未变。
- `README.md`：改为针对 MID-360 的候选版复现说明；原 README 原文保存在 `docs/UPSTREAM_README.md`。
- `tools/rosbag_completion_ws/README.md`：说明基准源码提交、补丁使用、隔离构建与测试环境变量。
- `tools/rosbag_completion_ws/test_completion.py`：支持用环境变量指定独立构建的播放器和独立测试产物根目录；原测试逻辑未改。
- `.gitignore`：候选版忽略构建、测试、日志、bag 与备份产物。
- 新增 `docs/` 下的结果摘要、许可证疑点、验证记录和逐文件清单；新增基于 rosbag2 0.15.16 的差异补丁及其原许可和 NOTICE。

## 排除而未删除的原仓库内容

- `image/`：约 246 MiB 的历史 GIF/图片；当前 README 通过上游 URL 引用历史图，不依赖本地图片构建。链接可用性仍受上游网站影响。
- `Log/`：用户已有日志和绘图脚本；节点现在写独立目录，不应把历史日志作为候选源码。
- `PCD/temp.txt`：历史输出占位文件；候选运行时按需创建独立 PCD 目录。
- `.gitmodules`：内容与当前普通文件布局不一致，且此候选不使用子模块；正式发布时是否保留仍需确认。
- `include/IKFoM/` 内编辑器配置：本机开发设置，与构建无关；IKFoM 源码、README 和 LICENSE 已保留。
- 原仓库所有 `.before_*`、`.baseline-backup`：保护其原始备份，仅不纳入候选。
- `tools/rosbag_completion_ws/` 下的完整 `results/`、`build/`、`install/`、`log/`、`test_artifacts/`、`__pycache__/`、失败的源码检出与完整 rosbag2 检出：只保留可审阅补丁、脚本、测试、说明及相应许可文本。
- 原始 rosbag 数据与历史运行原始日志：不作为源码发布；关键历史数值精简至 `TEST_RESULTS.md`。

没有删除或修改原仓库的任何文件。排除理由仅适用于此候选副本，不能自动代表正式发布决定。
