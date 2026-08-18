/**
 * flomo-status — 流水线进度查看工具
 *
 * 注册 `flomo_status` 工具：一次调用读取 raw/、store/、monthly/、llm_chunks/、
 * reports/、flomo-context/ 的清单与记录计数，报告每个 stage 跑到哪一步。
 * 纯只读，不触碰任何数据文件。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import fs from "node:fs";
import path from "node:path";

const STORE_KINDS: Record<string, string> = {
  "memo.raw.jsonl": "memo 原始记录",
  "image.raw.jsonl": "图片原始记录",
  "image.enriched.jsonl": "图片增强结果",
  "missing_image.raw.jsonl": "缺失图片记录",
};

function lineCount(file: string): number {
  try {
    const text = fs.readFileSync(file, "utf8");
    // 与 common/io.py 约定一致：用 \n 切分而非 splitlines()
    return text.split("\n").filter((line) => line.trim() !== "").length;
  } catch {
    return 0;
  }
}

/** image.enriched.jsonl：按 status 统计 + 失败样本 */
function enrichedStats(file: string): {
  total: number;
  byStatus: Record<string, number>;
  errorSamples: string[];
} {
  const byStatus: Record<string, number> = {};
  const errorSamples: string[] = [];
  let total = 0;
  try {
    const text = fs.readFileSync(file, "utf8");
    for (const line of text.split("\n")) {
      if (line.trim() === "") continue;
      let record: { status?: string; error_message?: string | null };
      try {
        record = JSON.parse(line);
      } catch {
        continue;
      }
      total += 1;
      const status = record.status ?? "unknown";
      byStatus[status] = (byStatus[status] ?? 0) + 1;
      if ((status === "failed" || status === "skipped") && record.error_message) {
        const short = record.error_message.slice(0, 60);
        if (!errorSamples.includes(short)) errorSamples.push(short);
      }
    }
  } catch {
    /* 文件不存在或不可读：返回空统计 */
  }
  return { total, byStatus, errorSamples };
}

function listMonths(dir: string): string[] {
  try {
    return fs
      .readdirSync(dir)
      .filter((name) => /^\d{4}-\d{2}$/.test(name) && fs.statSync(path.join(dir, name)).isDirectory())
      .sort();
  } catch {
    return [];
  }
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "flomo_status",
    label: "Flomo Pipeline Status",
    description:
      "只读查看 flomo-transcriber 流水线进度：raw/store/monthly/llm_chunks/reports 各目录的记录计数、图片增强状态分布、导入清单与快照发布状态。用于判断某 stage 是否完成、哪个月需要重跑，避免盲目重跑。",
    parameters: Type.Object({
      month: Type.Optional(
        Type.String({ description: "可选，YYYY-MM 格式；只统计指定月份的数据" }),
      ),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const root = ctx.cwd;
      const month = params.month;
      const lines: string[] = ["# flomo 流水线状态"];

      // ── raw/：HTML 导出 + 导入清单 ──
      const rawRoot = path.join(root, "raw");
      let exportDirs = 0;
      let importInfo = "";
      try {
        exportDirs = fs
          .readdirSync(rawRoot)
          .filter((name) => !name.startsWith(".") && fs.statSync(path.join(rawRoot, name)).isDirectory())
          .length;
        const manifestPath = path.join(rawRoot, ".import-manifest.json");
        if (fs.existsSync(manifestPath)) {
          const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
          const imports = Array.isArray(manifest.imports) ? manifest.imports : [];
          if (imports.length > 0) {
            const latest = imports[imports.length - 1];
            importInfo = `（最近导入 ${imports.length} 个 ZIP，最近状态: ${latest.status ?? "?"}）`;
          }
        }
      } catch {
        /* raw/ 不存在视为未开始 */
      }
      lines.push(`\n## Stage 1 extract — raw/\n导出目录 ${exportDirs} 个 ${importInfo}`);

      // ── store/：各 JSONL 计数 ──
      const storeRoot = path.join(root, "store");
      lines.push(`\n## Stage 2 enrich — store/`);
      let storeRows: string[] = [];
      for (const [file, label] of Object.entries(STORE_KINDS)) {
        const full = path.join(storeRoot, file);
        if (!fs.existsSync(full)) {
          storeRows.push(`- ${file}：未生成`);
          continue;
        }
        if (file === "image.enriched.jsonl") {
          const { total, byStatus, errorSamples } = enrichedStats(full);
          const statusText =
            Object.entries(byStatus)
              .map(([k, v]) => `${k} ${v}`)
              .join(" / ") || "无记录";
          storeRows.push(`- ${file}（${label}）：${total} 条 — ${statusText}`);
          if (errorSamples.length > 0) {
            storeRows.push(`  失败/跳过样本：${errorSamples.slice(0, 3).join("；")}`);
          }
        } else {
          storeRows.push(`- ${file}（${label}）：${lineCount(full)} 条`);
        }
      }
      if (fs.existsSync(path.join(storeRoot, "link_map.json"))) {
        storeRows.push("- link_map.json：存在（Notion 双向链接映射）");
      }
      lines.push(...storeRows);

      // ── monthly/ ──
      const monthlyRoot = path.join(root, "monthly");
      const monthlyFiles = (() => {
        try {
          return fs
            .readdirSync(monthlyRoot)
            .filter((name) => /^\d{4}-\d{2}\.enriched\.jsonl$/.test(name))
            .filter((name) => !month || name.startsWith(month))
            .sort();
        } catch {
          return [];
        }
      })();
      const monthlyTotal = monthlyFiles.reduce(
        (sum, name) => sum + lineCount(path.join(monthlyRoot, name)),
        0,
      );
      lines.push(`\n## Stage 3 merge — monthly/\n${monthlyFiles.length} 个月文件，共 ${monthlyTotal} 条记录`);
      if (monthlyFiles.length > 0 && monthlyFiles.length <= 12) {
        lines.push(`月份：${monthlyFiles.map((f) => f.replace(".enriched.jsonl", "")).join(", ")}`);
      }

      // ── llm_chunks/ ──
      const chunksRoot = path.join(root, "llm_chunks");
      const chunkMonths = listMonths(chunksRoot).filter((m) => !month || m === month);
      let chunkFiles = 0;
      const chunkBreakdown: string[] = [];
      for (const m of chunkMonths) {
        const dir = path.join(chunksRoot, m);
        const count = fs
          .readdirSync(dir)
          .filter((name) => name.endsWith(".json") && !name.startsWith(".")).length;
        chunkFiles += count;
        chunkBreakdown.push(`${m}: ${count}`);
      }
      lines.push(
        `\n## Stage 4 chunk — llm_chunks/\n${chunkMonths.length} 个月，共 ${chunkFiles} 个 chunk 文件`,
      );
      if (chunkBreakdown.length > 0 && chunkBreakdown.length <= 12) {
        lines.push(`明细：${chunkBreakdown.join("，")}`);
      }

      // ── reports/ ──
      const reportsRoot = path.join(root, "reports");
      let reportFiles = 0;
      try {
        reportFiles = fs
          .readdirSync(reportsRoot)
          .filter((name) => !month || name.startsWith(month)).length;
      } catch {
        /* reports/ 不存在视为未生成 */
      }
      lines.push(`\n## Stage 5 report — reports/\n${reportFiles} 个报告文件`);

      // ── flomo-context/：快照发布 ──
      const publishRoot = path.join(root, "flomo-context");
      let publishInfo = "尚未发布";
      try {
        const latestPath = path.join(publishRoot, "latest.json");
        if (fs.existsSync(latestPath)) {
          const latest = JSON.parse(fs.readFileSync(latestPath, "utf8"));
          publishInfo = `latest: ${latest.release_id ?? "?"}（数据到 ${latest.next_export_start_date ?? "?"} 前，下一导出建议从该日期开始）`;
        }
        const snapshotsRoot = path.join(publishRoot, "snapshots");
        const snapshotCount = fs.existsSync(snapshotsRoot)
          ? fs.readdirSync(snapshotsRoot).filter((n) => !n.startsWith(".")).length
          : 0;
        publishInfo += `，历史快照 ${snapshotCount} 个`;
      } catch {
        /* 目录不存在 */
      }
      lines.push(`\n## 发布 — flomo-context/\n${publishInfo}`);

      lines.push(
        `\n---\n根目录：${root}\n提示：需要重跑时参考 skill: flomo-pipeline-ops，或运行对应 validator 脚本。`,
      );

      return {
        content: [{ type: "text", text: lines.join("\n") }],
        details: {},
      };
    },
  });
}
