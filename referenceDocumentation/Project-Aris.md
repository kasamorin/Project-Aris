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
    * 提示词工程
    * 其他-未定
  * 行为
    * 函数调用
    * MCP服务器
    * Skills
    * 插件
    * 联网搜索
      * Google & Bing 优先
      * Tavily 备选

