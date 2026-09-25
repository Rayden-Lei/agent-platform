"""运行时能力层：对话与工作流共用的"读哪份配置、怎么组装"。

与 rag / workflow / tools / model_gateway 同层（06 第 1 节）：只依赖 db / core / model_gateway，不调 services，
所以服务层与 workflow 引擎都能直接调用，不会形成 services → workflow → services 的双向依赖。
"""
