"""memory 模块 —— 记忆系统（占位）。

Embedding 提供方抽象：本地模型优先（Bekko-embedding-v1-a25m，待用户实测
CPU 占用确认），Cloudflare Workers AI BGE-M3 作备选。
每次会话启动需向用户确认当前采用的方案。

存储：PostgreSQL + pgvector（语义向量）+ 后期 GraphRAG（图谱）。
"""
