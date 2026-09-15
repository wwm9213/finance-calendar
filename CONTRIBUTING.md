# Contributing

欢迎提交数据源解析修复、新市场 provider 和兼容性改进。

1. 从最新默认分支创建功能分支。
2. 保持数据源失败互不影响，并为新来源定义稳定 `scope`。
3. 新增或修改解析器时使用最小 HTML/ICS fixture 编写离线测试，不让测试依赖实时网络。
4. 运行 `python -m pytest -q` 和 `python -m src.validate dist`。
5. 在 Pull Request 中说明一手来源、UID 稳定策略、时区和缓存回退行为。

请勿提交 API Key、Cookie、账户信息或其他凭据。
