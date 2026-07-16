# 来源增量观察与相对权重

`dist/data-pipeline/sources/history/` 保存来源事实的时间变化，`dist/data-pipeline/sources/reliability/` 输出仅供分析的相对权重。两者都属于公开诊断数据，不属于 npm 消费接口，也不会改变正式数据来源。

## 存量与增量

该能力首次启用时，为每个成功解析的改修来源建立一次完整基线：

```text
dist/data-pipeline/sources/history/
├── baseline/<source>.json   # 首次完整存量，建立后不改写
├── current/<source>.json    # 最近一次成功解析的完整状态
├── changes/<source>.nedb    # 后续事实变化，一行一个 JSON 事件
├── runs.nedb                # 每次成功观察的摘要
└── manifest.json            # 基线时间、当前哈希和累计事件数
```

历史以跨来源可比较事实为粒度：

`itemId + shipId + capability + updateTargetItemId`

来源内部的多条路线仍保留在事实的 `routes` 证据中，但仅路线标签变化不会制造大量伪增量。

变化类型只有四种：

- `added`：首次出现在基线之后；
- `removed`：此前存在、本次成功解析后消失；
- `modified`：同一事实的星期结论发生变化；
- `reappeared`：曾被删除的事实再次出现。

解析失败或来源状态不是 `ok` 时，本次来源会被跳过，不会被错误记录成全量删除。

## 同行佐证

每条增量同时记录当时其他来源的状态：

- `corroborated`：至少一个其他来源给出相同结论；
- `outlier`：至少两个其他来源形成一致结论，而本来源不同；
- `unconfirmed`：覆盖不足或其他来源也不一致，暂时不能判断。

这些标签只表达相对证据，不证明事实真假。

## 相对权重

`dist/data-pipeline/sources/reliability/summary.json` 依据以下信号给出平均值为 1 左右的建议权重：

1. 两两重叠事实的一致率；
2. 其他至少两个来源形成共识时，本来源的跟随率；
3. 积累到足够增量事件后，历史变化被同行佐证的比例。

参数位于 `configs/source-reliability.json`。当前输出被限制在 `0.75..1.25`，初始阶段没有历史事件时只使用当前横向一致性，置信度不会标为高。

权重的边界是：

- 只用于后续分析和人工设定策略；
- 不参与正式数据选举；
- 不以覆盖较少直接判定来源不可靠；
- 不把多数票当成官方事实；
- Akashi List 仍是当前改修正式投影的既定来源，验证来源不会自动覆盖它。

## 运行可观察性

执行严格数据构建后，人类结果会直接显示各来源的建议权重和置信度。完整 `data-validate` 日志还会逐来源记录：

- `relativeWeight`；
- `confidence`；
- 当前一致性分；
- 累计历史事件数；
- 历史信号是否已经参与权重。

同一摘要也写入 `dist/data-pipeline/local-validation.json` 的 `sourceReliability` 字段。日志和报告均明确标记为 advisory-only，不改变正式数据选举。
