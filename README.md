# 知乎创作者研究 Skills

一套可以在本地持续更新的 Agent Skills：使用者提供知乎创作者主页 URL，并在自己的受支持浏览器中完成登录；Agent 按既定流程采集当前用户有权查看的公开内容，生成标准语料，再输出带来源、覆盖率和推断边界的观点分析。

这个仓库不会替你保存知乎账号，也不需要你把密码、Cookie、Token 或浏览器配置交给 Agent。

## 包含的 Skill

| Skill | 作用 |
|---|---|
| `zhihu-public-content-collector` | 从指定知乎主页采集公开回答、文章和想法，规整为 corpus JSON |
| `creator-content-analyzer` | 从 corpus 中归纳主题、观点、论证方式和阶段变化，并保留证据来源 |

两者通过 `Creator Content Corpus 1.0.0` 解耦。已有合规 corpus 时，可以只安装分析 Skill。

## 安装

### Codex / 支持 Agent Skills 的客户端

```bash
git clone https://github.com/Bob-Student/zhihu-creator-research.git
mkdir -p ~/.agents/skills
ln -s "$PWD/zhihu-creator-research/skills/zhihu-public-content-collector" ~/.agents/skills/zhihu-public-content-collector
ln -s "$PWD/zhihu-creator-research/skills/creator-content-analyzer" ~/.agents/skills/creator-content-analyzer
```

如果你不是在执行 `git clone` 的上级目录运行命令，请把 `$PWD/zhihu-creator-research` 换成仓库的绝对路径。也可以直接把两个 Skill 目录复制到客户端约定的 Skills 目录。

### WorkBuddy 兼容入口

若你的 WorkBuddy 使用 `~/.workbuddy/skills/`：

```bash
mkdir -p ~/.workbuddy/skills
ln -s "$PWD/zhihu-creator-research/skills/zhihu-public-content-collector" ~/.workbuddy/skills/zhihu-public-content-collector
ln -s "$PWD/zhihu-creator-research/skills/creator-content-analyzer" ~/.workbuddy/skills/creator-content-analyzer
```

`.codex-plugin/plugin.json` 是 Codex skills-only plugin 清单；是否能直接从插件界面安装，取决于客户端当前支持的插件来源。

## 怎么使用

安装后可以直接对 Agent 说：

- “采集这个知乎博主的全部公开回答、文章和想法：`<主页 URL>`。”
- “只收集他 2025 年以来的文章，输出标准 corpus。”
- “用这份 corpus 总结他的核心观点，每个判断附标题、日期和链接。”
- “比较他 2023 年和 2025 年对某个主题的观点变化。”

若页面要求登录，请在 Agent 正在使用的浏览器窗口中自行登录，然后让它继续。不要在聊天中发送密码、Cookie 或 Token。

## 输出边界

- 采集结果记录发现数、成功数、失败数、时间跨度和完整性。
- 分析结果区分“作者直接表述”“跨内容归纳”“证据不足”。
- 关键词频次只用于发现候选主题，不直接证明作者立场。
- 不推断政治、宗教、健康、性取向、住址等敏感属性。
- 投资类内容只是待核验的社区观点，不构成交易建议，也不应自动改写交易规则。
- 只处理当前用户本来有权查看的公开内容；验证码、权限错误和限流时停止。

## 本地验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_package.py
python3 -m unittest discover -s tests -v
```

两个 `SKILL.md` 遵循开放 Agent Skills 目录格式。仓库还包含 Codex UI 元数据、JSON Schema、合成测试数据和 GitHub Actions。

## 更新与版本

可以持续更新。建议先在本地修改并运行验证，再按语义化版本发布：

- `0.1.1`：修复文档、适配器或脚本缺陷，不改变输入输出合同；
- `0.2.0`：兼容地增加字段、平台路径或分析能力；
- `1.0.0`：形成稳定合同；之后不兼容变更升级主版本。

通过 Git 安装时，执行 `git pull` 即可获得更新；软链无需重建。发布版用户可以切换到相应标签。

README 使用中文不影响运行。Agent 实际读取的是每个目录里的 `SKILL.md`；只有面向英语使用者时才有必要补英文 README。

## 许可证与免责声明

代码和 Skill 指令使用 [Apache License 2.0](LICENSE)。知乎内容的版权仍属于原作者和相应权利人，本仓库不附带任何真实创作者语料。

本项目不是知乎官方产品。使用者应自行遵守平台条款、访问权限、速率限制和当地法律。
