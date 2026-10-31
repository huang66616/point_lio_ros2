# Point-LIO ROS 2 / MID-360 发布候选版

这是供代码审查的独立候选副本，基于 `huang66616/point_lio_ros2` 的 `571696bfcf28b8531ef5a2d2ea153f59124f9b08` 和当时工作树中的四处未提交修改。MID-360 适配已在该提交中；本次工作树优化集中在 ikd-Tree 最近邻结果缓冲、堆分配和局部地图容器复用。原上游说明保存在 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)，其中部分旧命令不适用于本候选版。

**发布状态：** 许可证元数据仍有未解决冲突，见 [docs/LICENSE_AUDIT.md](docs/LICENSE_AUDIT.md)。此副本供学长审查；正式公开发布前须核实许可和归属。

## 已验证环境与范围

Ubuntu、ROS 2 Humble、Intel Core i9-12900KS（24 逻辑 CPU）、Release 构建。现有验证使用 MID-360 录制的 `sensor_msgs/msg/PointCloud2` 和 `sensor_msgs/msg/Imu` rosbag；未把实机接线与驱动启动列为已验证步骤。源码中的点类型要求点云含 `x/y/z/intensity/tag/line/timestamp` 字段，`timestamp` 为每点时间。普通 `PointCloud2` 即使话题名相同，也未必满足此格式。

## 依赖与构建

需要 ROS 2 Humble、`colcon`、C++14 编译器，以及 [CMakeLists.txt](CMakeLists.txt) 所列的 `rclcpp`、`rclpy`、`sensor_msgs`、`geometry_msgs`、`nav_msgs`、`tf2_ros`、`pcl_ros`、`pcl_conversions`、`visualization_msgs`、Eigen3、PCL、Python 开发头文件；OpenMP 在可用时启用。MID-360 rosbag 回放所用代码的 `livox_ros_driver2` CMake 依赖处于注释状态；实机驱动安装和数据字段仍需按设备环境核实。未在本阶段安装新软件包。

以下命令将构建输出放在源码目录外，`SRC` 指向此候选目录：

```bash
source /opt/ros/humble/setup.bash
SRC=/absolute/path/to/pointlio_release_candidate
BUILD=/absolute/path/to/new/empty/build_workspace
colcon --log-base "$BUILD/log" build --base-paths "$SRC" \
  --packages-select point_lio --build-base "$BUILD/build" \
  --install-base "$BUILD/install" --cmake-args -DCMAKE_BUILD_TYPE=Release
source "$BUILD/install/setup.bash"
```

`BUILD` 请使用新目录，以免覆盖旧记录。构建是否在其他机器上成功仍需复验。

## MID-360 配置与启动

[config/mid360.yaml](config/mid360.yaml) 使用 `/livox/lidar`、`/livox/imu`；`preprocess.lidar_type=1`，`timestamp_unit=3`（纳秒），`scan_line=4`。`launch/mapping_mid360.launch.py` 加载该 YAML，并设置滤波、地图等参数。实机外参值须由使用者核对，不能直接视为通用标定。

候选版节点每次启动在 `POINTLIO_RUN_ROOT` 下新建 `pointlio-XXXXXX` 目录；未指定时使用 `/tmp`。目录必须已存在且可写。`pos_log.txt`、`mat_out.txt`、`imu_pbp.txt` 和启用 PCD 保存时的文件均写在该独立目录，程序会输出实际路径。目录创建或日志打开失败时节点退出，不写回源码树 `Log/`。

```bash
source /opt/ros/humble/setup.bash
source "$BUILD/install/setup.bash"
RUN_ROOT=/absolute/path/to/new/run_root
mkdir -p "$RUN_ROOT/ros_log"
POINTLIO_RUN_ROOT="$RUN_ROOT" ROS_LOG_DIR="$RUN_ROOT/ros_log" \
  ros2 launch point_lio mapping_mid360.launch.py rviz:=false
```

这是已验证实验所用的 launch、YAML 和 `rviz:=false` 组合；候选版新增日志隔离后也完成一次短包回放验证，见 [docs/VALIDATION.md](docs/VALIDATION.md)。默认 launch 会启动 RViz，只有有图形环境时再尝试。

## rosbag 回放与输出检查

在独立终端启动节点后，以 1.0 倍速回放 MID-360 短包。普通 `ros2 bag play` 可用于基本检查，但它的正常命令返回不能单独证明节点处理完毕。已有实验使用 [tools/rosbag_completion_ws/README.md](tools/rosbag_completion_ws/README.md) 中的播放器证据工具；工具须单独构建，且只能在播放器终端加载其 overlay。

```bash
source /opt/ros/humble/setup.bash
ros2 bag play /absolute/path/to/mid360_test --rate 1.0
```

外部订阅者在历史测试中分别观察到 `/aft_mapped_to_init`、`/path`、`/cloud_registered` 及节点 TF。手工检查时可在另一终端使用 `ros2 topic info`、`ros2 topic hz` 和 `ros2 topic echo --once`；这些交互式命令在本候选副本上**待验证**。短包自带 `/tf`，检查节点 TF 时不能把它与 bag 的 TF 混计。不要用里程计条数代替全部点云处理帧数。

## 性能结果与口径

详见 [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md)。在现有短包、当前机器和当前配置下，内部单帧耗时均值从 **10.931 ms** 降至 **10.397 ms**；P95 从 **14.564 ms** 降至 **13.932 ms**；节点点云回调至外部点云订阅者的延迟均值从 **16.851 ms** 降至 **16.350 ms**。每个版本运行两次。内部计时覆盖 IMU 处理、估计/配准与地图插入；外部延迟另含回调预处理、发布、DDS 送达和订阅者调度，但不含 bag 发布到节点回调的时间。这是组合改动在该条件下的小幅收益，不能推广为其他设备或数据集的性能保证。

当前优化版完成一次约 277 秒长包回放，节点接收 **55,435** 条 IMU 和 **2,772** 帧点云，其中 **2,768** 帧完成常规处理。没有同条件的优化前长包基线，不能据此宣称长包性能提升。尾段处理耗时、外部延迟及 RSS 上升尚未归因。

## 已知限制

- MID-360 实机驱动、其他机器的依赖安装及更长时段的候选版运行仍需复验。
- rosbag 播放器的 publish API 成功不证明 DDS 送达；节点接收不等于每帧都完成常规处理。
- 当前优化未做逐项消融；日志隔离改动须与历史性能实验区分。
- `include/common_lib.h` 中旧的 `DEBUG_FILE_DIR` 宏仍指向编译时源码目录，但当前编译的节点没有调用它；以后新增文件输出时需继续遵守独立运行目录约定。
- `package.xml` 的 BSD 字段沿袭上游，而根许可证为 GPLv2 文本，正式发布前须解决许可证元数据与第三方归属问题。
- 原始工作树中的完整报告、日志、备份和 rosbag 均未纳入本候选版。
