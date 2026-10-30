# 外部源码补丁与恢复快照

补丁应对照固定上游版本应用；适配源码本身以当前仓库检出内容为准。来源身份见 [source.json](../locks/source.json)。

## 默认构建使用的补丁

| 文件 | 用途与应用入口 |
| --- | --- |
| [chimera-determinism.patch](chimera-determinism.patch) | 固定输入准备规则；由 `build/chimera/apply_determinism.py` 校验并应用 |
| [rosetta-zero-chi-boundary.patch](rosetta-zero-chi-boundary.patch) | 固定 Rosetta 版本的非 Pro 近零分类修复；由 `build/apply_rosetta_zero_chi.py` 校验并应用 |

Rosetta 补丁仅在 `abs(chi)<1e-10` 度时将分类函数的局部角度视为零，不改原子坐标，保留 Pro 与正负 120 度规则。源码准备及 Rosetta 构建入口均已接入。镜像及验证身份见 [rosetta-zero-chi.json](../locks/rosetta-zero-chi.json)。

构建脚本只接受预期源文件哈希或已修复哈希；未知修改会停止，避免覆盖其他改动。修复不代表整条随机搜索严格等价。

## 交付范围

本目录保留生产构建使用的两份外部源码补丁。未启用的试验补丁和独立历史诊断资料保存在模型仓库外，不属于源码交付内容。

## 实现提交归档

- `implementation.patch`：上游基线 `8b77f9897258064ef1d9a5ac4a42a547fb3eacea` 到实现提交 `0c44db4d54293138c765572936b498ea8be7a786` 的完整补丁。
- `implementation.json`：提交身份、补丁 SHA256 和还原验证记录。

已使用独立临时 Git 索引从基线应用补丁，完整文件树与实现提交一致。该检查不重新运行模型。

归档单独提交，因此补丁不包含归档提交自身。历史工作区快照保存在模型仓库外，不作为发布恢复入口。
