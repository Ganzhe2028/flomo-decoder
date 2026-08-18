/**
 * flomo-guardian — flomo-transcriber 项目守门员扩展
 *
 * 把 AGENTS.md 的 ANTI-PATTERNS 变成运行时护栏：
 * 1. 拦截对事实层（raw/、store/）与派生层（monthly/、llm_chunks/、reports/、
 *    flomo-context/）的 write/edit —— 事实层不可改写，派生层删了重跑即可。
 * 2. 拦截命中数据目录的 `rm -rf`。
 * 3. 源码改动后提醒更新 UpdateLog.md（项目硬性约定）。
 *
 * 只在交互环境（hasUI）下执行拦截，print/json 模式静默放行。
 */
import {
  isToolCallEventType,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";
import path from "node:path";

const TRUTH_ROOTS = ["raw", "store"]; // 事实层：HTML 导出 + raw JSONL
const DERIVED_ROOTS = ["monthly", "llm_chunks", "reports", "flomo-context"]; // 派生层：可重新生成
const SOURCE_ROOTS = ["src", "scripts", "gui", "tests"]; // 源码目录：改完要记 UpdateLog
const SOURCE_FILES = ["pyproject.toml", "Makefile", "AGENTS.md"];
const WRITE_TOOLS = new Set(["write", "edit", "patch"]);

function targetPath(input: Record<string, unknown>, cwd: string): string | null {
  const raw = input?.path ?? input?.filePath;
  if (typeof raw !== "string" || raw.trim() === "") return null;
  return path.isAbsolute(raw) ? path.normalize(raw) : path.resolve(cwd, raw);
}

/** target 是否位于 root 目录内（含等于 root 本身） */
function isUnder(target: string, root: string): boolean {
  const rel = path.relative(root, target);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (!ctx.hasUI) return;

    // 1) 写工具命中受保护数据目录 → 确认
    if (WRITE_TOOLS.has(event.toolName)) {
      const target = targetPath(event.input as Record<string, unknown>, ctx.cwd);
      if (target) {
        const truthRoots = TRUTH_ROOTS.map((r) => path.resolve(ctx.cwd, r));
        const derivedRoots = DERIVED_ROOTS.map((r) => path.resolve(ctx.cwd, r));
        const inTruth = truthRoots.some((r) => isUnder(target, r));
        const inDerived = derivedRoots.some((r) => isUnder(target, r));
        if (inTruth || inDerived) {
          const isRawJsonl = /\.raw\.jsonl$/.test(target);
          const message = isRawJsonl
            ? "store/*.raw.jsonl 是 Stage 1 事实层，下游不得改写"
            : inTruth
              ? "raw/ 与 store/ 是事实层数据，直接写入会污染流水线"
              : "monthly/、llm_chunks/、reports/ 是可重新生成的派生层，写入会在下次重跑时被覆盖";
          const ok = await ctx.ui.confirm(
            "flomo 数据目录写入确认",
            `${path.relative(ctx.cwd, target)}\n${message}\n\n确定要写入吗？`,
          );
          if (!ok) {
            return { block: true, reason: "用户拒绝写入 flomo 受保护数据目录" };
          }
          return;
        }
      }
    }

    // 2) rm -rf 命中数据目录 → 确认
    if (isToolCallEventType("bash", event)) {
      const command = event.input.command ?? "";
      const isRmRecursive =
        /\brm\b[^\n]*\s(?:-{1,2}[a-zA-Z]*[rf][a-zA-Z]*|-r\s+-f)\b/.test(command);
      const touchesData =
        /(?:raw|store|monthly|llm_chunks|reports|flomo-context)/.test(command);
      if (isRmRecursive && touchesData) {
        const ok = await ctx.ui.confirm(
          "危险删除确认",
          `${command}\n\n涉及流水线数据目录。事实层删除不可恢复，派生层删除需重跑对应 stage。确定执行？`,
        );
        if (!ok) {
          return { block: true, reason: "用户取消了数据目录删除" };
        }
      }
    }
  });

  // 3) 源码改动 → 提醒 UpdateLog
  pi.on("tool_result", async (event, ctx) => {
    if (!ctx.hasUI || event.isError || !WRITE_TOOLS.has(event.toolName)) return;
    const target = targetPath(event.input as Record<string, unknown>, ctx.cwd);
    if (!target) return;
    const inSource =
      SOURCE_ROOTS.some((r) => isUnder(target, path.resolve(ctx.cwd, r))) ||
      SOURCE_FILES.includes(path.basename(target));
    if (inSource) {
      ctx.ui.notify("检测到源码改动：记得更新 UpdateLog.md", "info");
    }
  });
}
