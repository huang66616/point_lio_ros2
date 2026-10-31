# 可选：rosbag2 播放完成证据工具

此目录只保留 `supervisor.py`、测试、`rosbag2_transport_evidence.patch`、上游 Apache-2.0 `LICENSE` 和 `NOTICE`。补丁基于 ROS 2 rosbag2 `0.15.16`、提交 `45548c4ef61d481e91f50e696d1a4ff46dac8475`。未打包完整 rosbag2 源码或构建产物。

在**独立目录**取得对应 rosbag2 源码后，核对提交哈希，在源码根目录执行：

```bash
git apply --check /absolute/path/to/rosbag2_transport_evidence.patch
git apply /absolute/path/to/rosbag2_transport_evidence.patch
source /opt/ros/humble/setup.bash
colcon build --base-paths rosbag2_transport --packages-select rosbag2_transport \
  --allow-overriding rosbag2_transport --cmake-args -DBUILD_TESTING=OFF
```

上面是候选版的**待复验**安装说明，不应对原工作区中的源码执行 `git apply`。加载该 overlay 只用于播放器终端；Point-LIO 节点终端使用普通 ROS 环境。播放时以 `python3 supervisor.py --bag <bag_dir> --player <overlay>/install/rosbag2_transport/lib/rosbag2_transport/verified_rosbag_play --output-root <new_run_root> --rate 1.0` 创建独立 UUID 结果目录。`natural_end` 只证明播放器 reader EOF、loader 完成、队列排空、计数一致且进程正常退出，不证明 DDS 送达或 Point-LIO 处理完成。

补丁已在独立的基准源码副本中通过 `git apply --check` 并构建成功。若构建目录不在工具目录内，可用环境变量指定播放器与测试产物位置：

```bash
source /opt/ros/humble/setup.bash
source <overlay>/install/setup.bash
VERIFIED_ROSBAG_PLAYER=<overlay>/install/rosbag2_transport/lib/rosbag2_transport/verified_rosbag_play \
ROSBAG_TEST_ARTIFACTS_ROOT=<new_test_artifacts_root> \
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_completion
```

`<new_test_artifacts_root>` 可以是独立验证目录；测试会在其下新建 UUID 子目录并保留记录，不会复用旧结果。候选补丁的独立构建及集成测试已验证，14/14 通过。ROS DDS 网络不可用时，集成测试会失败；这与代码正确性需分开判断。
