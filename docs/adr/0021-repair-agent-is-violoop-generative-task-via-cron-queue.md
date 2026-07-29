---
status: accepted
---

# 修复 Agent = violoop generative 任务,由 cron 轮询队列触发

修复 bug 的运行时 AI 需要能读码、跑测试、写 diff。落地形态与触发方式两个决策。

**决定一:用 violoop 自带的 generative/hybrid 任务当 agent,不装外部 Claude Code、不在后端自造 agent 循环。** violoop 本身就是一个可被程序触发、带工具与分档权限(local-automation/full-trust)的 AI 执行器,底层就是「读码-跑测试-改码」的循环,免去重造。跑在**隔离 git worktree** 上(非主工作树),AI 改坏也污染不到正在跑的评测/线上进程。用 **heavy 档模型**(violoop 最强推理档;注意 violoop 模型是内部分层 mini/fast/medium/heavy,不能直接点名某个 Claude 版本,heavy 即最强档,等价用户说的「调最强模型」)。

**决定二:cron 每 5 分钟扫 `queued` 反馈触发(队列轮询),不做「提交即同步调 AI」。** 轮询让反馈系统与修复 AI 彻底解耦——后端完全不用知道 AI 存在,AI/violoop 挂了不影响系统主体,反馈也不丢(排队等 violoop 回来接着修)。并发被 cron 天然串行化,堵死「多 agent 同时改同一仓库打架」(系统此前踩过并发踩踏)。贴合系统既有的状态驱动队列模式(intake/assignment 都非同步调用)。

## Consequences

链路依赖 owner 这台机器上的 violoop 在线;violoop 不在则补丁不产出,但队列保证反馈不丢。
