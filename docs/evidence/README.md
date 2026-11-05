# 验证证据索引

## 保存与引用规则

日常检查通过 Harness 或专项审查入口运行，原始报告、日志和构建产物留在 `.local/harness/` 或 `.local/reviews/`。通过只覆盖该次源码与执行范围；doctor 只证明环境就绪。

需要提交正式证据时，人工核对并脱敏后保存到 `docs/evidence/<日期>-<主题>-<提交或运行标识>/`，同目录 README 记录源码 HEAD、未提交源码指纹、实际命令、环境版本、检查范围、结果和限制。每批使用独立目录，不覆盖上一批报告；涉及未提交代码时不能只写 HEAD。验证记录应链接具体批次，截图也应说明页面、输入与版本。

## 根目录保留快照

以下文件保留原路径和原内容，便于追溯已有链接。它们是历史快照，不证明当前代码通过。本次仅核对文件内容、结构与摘要，没有重新执行其中的业务检查，也没有认定它们与每条历史记录一一对应。`passed` 和检查数不能代替源码版本核对。

已确认的引用歧义：

- `validation-ingestion.json` 现存 164 项检查；历史记录曾用同一路径指代 65、73、88、113、115、149、164 等批次。仅数量相同也不能证明是同一批次。
- `validation-contracts.json` 现存 48 个操作、317 项检查；不能支持历史 23 或 37 个操作的记录，也不是当前契约的重新验证结果。
- `validation-export-path-migration.json` 现存 16 项检查，与历史一段记载的 15 项不同；本次不据此改写历史计数。

因此已将上述历史段落的报告链接改为本说明，保留原有运行目录、指纹与文字记录作为查证线索。本次未从 Git 历史或本机运行目录恢复各批次独立报告；不能确认来源的证据不补造、不以现存快照顶替。

下表 SHA256 在 2026-09-20 文档整理时计算，仅标识保留文件内容，不是业务源码指纹。

2026-11-05 换行核对：14 个保留文件在仓库中均为 LF 字节；直接按磁盘字节计算为 0/14 匹配，把同一文本在内存中规范化为 CRLF 后 14/14 全部匹配。因此本表应按 CRLF 规范化核对，索引值无需改写，也不因此修改任何 JSON。原表未记录 2026-09-20 计算时的换行环境，不能据此断言当时由某台 Windows 生成；该差异不表示文件损坏、被改写或来源不明，也不追加证明任何业务检查通过。只读复核命令（不写文件，预期输出 `14 / 14`）：

```bash
python3 - <<'PY'
import re, hashlib, pathlib
base = pathlib.Path('docs/evidence')
rows = [m.groups() for m in (re.match(r'\| \[([^\]]+)\]\(([^)]+)\) \| `([0-9a-f]{64})` \|', line) for line in (base / 'README.md').read_text(encoding='utf-8').splitlines()) if m]
crlf = lambda p: p.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
print(sum(hashlib.sha256(crlf((base / rel).resolve())).hexdigest() == exp for _, rel, exp in rows), '/', len(rows))
PY
```

| 保留文件 | SHA256 |
|---|---|
| [validation-account-delete.json](../validation-account-delete.json) | `65066516b3700777ae87f807ee6ffd75bb9380324f105208dd74b070e4e08fdc` |
| [validation-browser.json](../validation-browser.json) | `be4bd4a02e973175300e162c996246b5a1e384dcd928a2cd38bde2ae856d3b32` |
| [validation-contracts.json](../validation-contracts.json) | `ec8fcf18e3834273a153486f35ed785b5b24b419ebe694b7e1c06ff085c9cacb` |
| [validation-database.json](../validation-database.json) | `589ca69effd23c610c2b20a5281e6f058ab4720864935d4498b6fa609988d147` |
| [validation-demo.json](../validation-demo.json) | `2faf2fdc8f16e999adc10421316aa5edc9b642bbe332b7457aea79827ed17311` |
| [validation-export-path-migration.json](../validation-export-path-migration.json) | `9abe02eeedaa7c126ff1c6dd406834c48ee8636e75559298fc15c6ac71971055` |
| [validation-framework.json](../validation-framework.json) | `43a1f3ccee1580adc47112474b1021f3e740506ee40bbd040e19b0ebadb481da` |
| [validation-infrastructure.json](../validation-infrastructure.json) | `7de2c7ae458e1ffbb8d2b538b6c883a512b8cd0ca33c8575cddfd09fe77e50f0` |
| [validation-ingestion.json](../validation-ingestion.json) | `6a4ffc7a83e99b31a7ba30c174b8892205d91873b9c525fd886b064689bc5637` |
| [validation-initialization.json](../validation-initialization.json) | `15a9fabe23076cfd9884ccdd065a19c4dca95b8009aab472d0ca902079fdb4f2` |
| [validation-lan-account-cleanup.json](../validation-lan-account-cleanup.json) | `1c401a3775f7c1fed69d0a0e0040b17ea76278c5265c21ae6954eea92e17979c` |
| [validation-scene-delete.json](../validation-scene-delete.json) | `bae78cd2fb8410fc8b8ec8be302f213cd0fe35da5731dbd1130bd3e366f12a15` |
| [validation-secret-scan.json](../validation-secret-scan.json) | `473532ed2d36b3b282eb9bfde1b7dfd1f4b963cee3c277e68dde9005375ba941` |
| [design-review-evidence.json](../design-review-evidence.json) | `296bc08362f35bee311e16c8b7d203daf32282096a8f003933da444d8ef8fca0` |

## Issue 专项材料

[GH-1 首页](issue-1/README.md)、[GH-3 审计动作](issue-3/README.md)、[GH-4 发布版本展示](issue-4/README.md)、[GH-7 密码策略](issue-7/README.md)、[GH-9 场景列表入口与列宽](issue-9/README.md) 保留对应阶段的自查和待验收项。后续验证见 [验证记录](../06-validation.md)，不能把实施时的待验收描述当作当前完成状态，也不能仅凭自查认定已合并或部署。
