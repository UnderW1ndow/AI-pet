/**
 * 工具调用 → 工作状态气泡里的**具体**详情（「翻翻 index.ts 看看嘛」「该推上去了吧，我来」）。
 *
 * 设计要点（改文案时只碰数据表，不用读逻辑）：
 *   1. **文案是数据**：`TOOL_COPY`（工具 → 3 句）、`COMMAND_COPY`（命令/子命令 → 3 句）与两个
 *      兜底表。加工具、加命令、改语气 = 加一行字符串，不碰任何判定代码。
 *   2. **语气跟人设走**：与 `workStatusTexts` 同一套口吻（温柔乖巧带点俏皮，10~18 字），
 *      并且**必须带上具体对象**（文件名 / 命令名）——没有对象的气泡等于没说。
 *   3. **没有语义就不硬编**：`npm` / `python` / `node` 这类「只是跑代码」的命令不进表，
 *      走兜底「跑一下 {cmd} 咯」；`git log` / `git push` 这类有明确作用的才细化到子命令。
 *   4. **复合命令一律不猜**：含 `;` `|` `&&` `||` 换行 → 返回 null，让前端回落到
 *      `workStatusTexts` 的配置文案（`cd …; npx prettier; npx tsc` 显示「cd」是在骗人）。
 *   5. **目标太长就换短句**：目标超过 TARGET_DISPLAY_MAX（20 码点）时整句换成该工具的氛围兜底，
 *      不带文件名 / 工具名——气泡是氛围，不是信息面板（`grep` 的正则
 *      `WORK_STATE_GAP_MS|busyFlip|…` 硬塞进去会直接撑破气泡）。
 *
 * 两条刻意的取舍：
 *   - **大参数不解析**：`write` / `edit` 的 arguments 里带着整个文件内容，动辄几百 KB。
 *     超过 MAX_ARGS_CHARS 就不再 JSON.parse —— 宁可少一句气泡，也不在一个热事件里白花时间。
 *   - **命令只看命令名**：`pwsh` 的 command 里可能带 token / 内网地址，而气泡是**上屏**内容。
 *     只取第一个「像命令」的 token，参数一律不显示。
 *
 * 本模块是 host 自包含实现（不 import src/shared —— DSH 单文件加载约束）；
 * 唯一的依赖是同级的 ./work-status，只为一个常量：气泡宽度上限 TASK_TEXT_MAX。
 */
/**
 * `tool/call` 事件 → 气泡详情；跳过 / 无法解析 / 无信息量 → null。
 *
 * 返回值可以直接写进 `sections.workStatus.data.task`（长度 ≤ TASK_TEXT_MAX + 1）。
 */
export declare function toolDetailFromEvent(event: {
    data?: {
        name?: unknown;
        arguments?: unknown;
    };
} | null | undefined): string | null;
