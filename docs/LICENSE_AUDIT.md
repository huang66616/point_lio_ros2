# 许可证与归属核查（待最终确认）

- 根目录 `LICENSE` 是 GNU GPL Version 2（June 1991）完整许可证文本；`include/IKFoM/LICENSE` 同为 GPLv2 文本。均按原样保留。
- `package.xml` 的 `<license>BSD</license>` 可在上游 `dfloreaa/point_lio_ros2` 同一文件中找到，属继承的元数据；它与当前仓库根 GPLv2 文本不一致。候选版未擅自改成 GPL 或更换 LICENSE。
- `include/ikd-Tree/` 的本地副本没有独立 LICENSE 文件；其上游 hku-mars/ikd-Tree 仓库标为 GPL-2.0。应确认当前拷贝来源版本和版权声明，并在正式发布说明中准确归属。
- `include/IKFoM/` 保留其本地 LICENSE 和源码版权信息；上游来源是 hku-mars/IKFoM。
- 可选的 rosbag 播放证据补丁基于 ROS 2 rosbag2 `0.15.16`，基准提交 `45548c4ef61d481e91f50e696d1a4ff46dac8475`。本候选只包含差异补丁、工具脚本、上游 Apache License 2.0 与 NOTICE，未复制完整 rosbag2 源码。构建时需从上游取得对应版本，并保留原项目许可声明。

**待确认：** 逐文件著作权与 GPLv2/Apache 2.0 组合分发方式、`package.xml` 应如何准确标注、贡献者署名，以及候选版是否符合预期分享范围。在这些问题解决前，不将候选版标记为许可审查完成。此文档是来源核查记录，不是法律意见。
