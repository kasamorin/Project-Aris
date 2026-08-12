# Project Aris

## 简述

在当今，人与人之间的信任逐渐淡化，互联网让人之间的边界变得模糊。于此，人的界限也逐渐模糊，你无法知道与你对话的究竟是人还是AI。因此，我想创造一位类似于Neuro-sama的拟人AI，暂命名：Project-Aris

## 大致实现

* Aris
  * 记忆系统
    * 工具
      * Embedding Model （已定案：热记忆本地 Bekko-embedding-v1-a25m / OpenVINO CPU，冷记忆云端 Cloudflare BGE-M3，见 EMBEDDING.md）
      * 数据库（预计 PostgreSQL + pgvector & GraphRAG）
  * 语音系统
    * TTS（预计Edge TTS / Azure TTS）
    * STT（暂无）
  * 人格系统
    * 提示词工程（2026-08-12 已落地简单版，persona 模块）
    * 世界观/人际关系/成长轨迹（后续演进）
    * 其他-未定
  * 行为
    * 函数调用
    * MCP 服务器
      * 连接外部 MCP 服务器
      * 自建 MCP 服务器（可能很多个）
    * Skills
    * 联网搜索
      * Tavily API 唯一主链路（2026-08-12 定案，见 WEB-SEARCH.md）
      * 国内源深抓、按 id 点开读正文（web_open）后续再加
  * 插件系统
    * 后续可能增加（MCP 服务器可做同样的事）
