import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import {
  Activity,
  Archive,
  CalendarClock,
  CheckCircle2,
  ChevronsDown,
  Copy,
  FileImage,
  FolderOpen,
  Inbox,
  Moon,
  PauseCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings,
  Sun,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type WorkflowAction = "first" | "daily" | "probe" | "retry" | "import";
type Provider = "lmstudio" | "mock";
type RunStatus = "idle" | "running" | "success" | "failed" | "cancelled";

type AppSettings = {
  project_root: string;
  env_file: string;
  raw_root: string;
  store_root: string;
  monthly_root: string;
  chunks_root: string;
  inbox_root: string;
  publish_root: string;
  scan_downloads: boolean;
  auto_import: boolean;
  vlm_base_url: string;
  vlm_model: string;
  vlm_retry_model: string;
  vlm_timeout_seconds: string;
  vlm_max_tokens: string;
  env_exists: boolean;
  runtime_mode: string;
};

type WorkflowRequest = {
  action: WorkflowAction;
  provider: Provider;
  month?: string;
  raw_root: string;
  store_root: string;
  monthly_root: string;
  chunks_root: string;
  publish_root: string;
  env_file: string;
  image?: string;
  zip?: string;
  rounds: number;
};

type ZipCandidate = {
  path: string;
  name: string;
  size: number;
  modified_millis: number;
  source: "inbox" | "downloads";
  stable: boolean;
};

type ImportStatus = {
  suggested_export_date: string | null;
  latest_memo_at: string | null;
  last_release: string | null;
  imports: Array<{
    original_filename: string;
    status: string;
    error_message: string | null;
    failed_images: number;
    image_failures: Array<{
      image_id: string;
      month: string;
      error_message: string;
    }>;
  }>;
};

type QueueStatus = "running" | "queued" | "success" | "failed" | "cancelled";

type WorkflowStarted = {
  task_id: string;
  command: string;
};

type WorkflowOutput = {
  task_id: string;
  stream: "stdout" | "stderr";
  line: string;
};

type WorkflowCompleted = {
  task_id: string;
  status: "success" | "failed" | "cancelled";
  code: number | null;
};

type LogLine = {
  id: number;
  stream: "system" | "stdout" | "stderr";
  text: string;
};

const defaultSettings: AppSettings = {
  project_root: "",
  env_file: "",
  raw_root: "raw",
  store_root: "store",
  monthly_root: "monthly",
  chunks_root: "llm_chunks",
  inbox_root: "flomo-inbox",
  publish_root: "flomo-context",
  scan_downloads: true,
  auto_import: true,
  vlm_base_url: "http://127.0.0.1:1234/v1",
  vlm_model: "",
  vlm_retry_model: "",
  vlm_timeout_seconds: "180",
  vlm_max_tokens: "4096",
  env_exists: false,
  runtime_mode: "",
};

const actionMeta: Record<
  WorkflowAction,
  { label: string; description: string; icon: typeof Play }
> = {
  import: {
    label: "增量收件",
    description: "接收 Flomo ZIP，自动去重、转换并发布完整快照。",
    icon: Inbox,
  },
  first: {
    label: "首次生成",
    description: "从 raw/ 生成可交给外部 LLM 的 chunks。",
    icon: Play,
  },
  daily: {
    label: "日常更新",
    description: "更新 raw/ 后重新生成 chunks，已成功图片会跳过。",
    icon: RefreshCw,
  },
  probe: {
    label: "探测图片",
    description: "用 LM Studio 检查一张图片是否可读。",
    icon: Search,
  },
  retry: {
    label: "重试失败",
    description: "只重试已经失败的图片记录。",
    icon: RotateCcw,
  },
};

function App() {
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [action, setAction] = useState<WorkflowAction>("first");
  const [provider, setProvider] = useState<Provider>("lmstudio");
  const [month, setMonth] = useState("");
  const [image, setImage] = useState("");
  const [rounds, setRounds] = useState(3);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [activeCommand, setActiveCommand] = useState("");
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [lastOutputPath, setLastOutputPath] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const logOutputRef = useRef<HTMLDivElement>(null);
  const [availableMonths, setAvailableMonths] = useState<string[]>([]);
  const [selectedZip, setSelectedZip] = useState("");
  const [zipCandidates, setZipCandidates] = useState<ZipCandidate[]>([]);
  const [queueStatuses, setQueueStatuses] = useState<Record<string, QueueStatus>>({});
  const [scanError, setScanError] = useState("");
  const [importStatus, setImportStatus] = useState<ImportStatus>({
    suggested_export_date: null,
    latest_memo_at: null,
    last_release: null,
    imports: [],
  });
  const latestPublishedImport = [...importStatus.imports]
    .reverse()
    .find((entry) => entry.status === "published");
  const settingsRef = useRef<AppSettings>(defaultSettings);
  const activeImportPathRef = useRef<string | null>(null);
  const activeImportZipRef = useRef<string | null>(null);
  const attemptedAutoImportsRef = useRef(new Set<string>());

  const lmstudioReady =
    settings.vlm_base_url.trim().length > 0 && settings.vlm_model.trim().length > 0;
  const canRun =
    status !== "running" &&
    (provider === "mock" && action !== "probe" ? true : lmstudioReady) &&
    (action !== "probe" || image.trim().length > 0) &&
    (action !== "import" || selectedZip.trim().length > 0);

  const configState = useMemo(() => {
    if (provider === "mock" && action !== "probe") {
      return { label: "mock 流程", tone: "neutral" };
    }
    if (lmstudioReady) {
      return { label: "LM Studio 已配置", tone: "good" };
    }
    return { label: "LM Studio 未完整配置", tone: "warn" };
  }, [action, lmstudioReady, provider]);

  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("flomo-theme");
    return stored === "light" ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("flomo-theme", theme);
  }, [theme]);

  useEffect(() => {
    settingsRef.current = settings;
  }, [settings]);

  function toggleTheme() {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }

  useEffect(() => {
    void loadSettings();

    const unlistenOutput = listen<WorkflowOutput>("workflow-output", (event) => {
      setLogs((current) => [
        ...current,
        {
          id: current.length + 1,
          stream: event.payload.stream,
          text: event.payload.line,
        },
      ]);
    });

    const unlistenCompleted = listen<WorkflowCompleted>("workflow-completed", (event) => {
      setStatus(event.payload.status);
      setActiveTaskId(null);
      const importKey = activeImportPathRef.current;
      const importedZip = activeImportZipRef.current;
      if (importKey && importedZip) {
        activeImportPathRef.current = null;
        activeImportZipRef.current = null;
        const currentSettings = settingsRef.current;
        invoke<ImportStatus>("read_import_status", {
          rawRoot: currentSettings.raw_root,
          publishRoot: currentSettings.publish_root,
        })
          .then((nextStatus) => {
            setImportStatus(nextStatus);
            const filename = fileNameFromPath(importedZip);
            const entry = [...nextStatus.imports]
              .reverse()
              .find((item) => item.original_filename === filename);
            if (entry?.status === "queued") {
              setStatus("idle");
              setQueueStatuses((current) => ({ ...current, [importKey]: "queued" }));
              pushSystemLog(`已排队：${entry.error_message || "等待 LM Studio 可用"}`);
              window.setTimeout(() => {
                attemptedAutoImportsRef.current.delete(importKey);
                setQueueStatuses((current) => {
                  const next = { ...current };
                  delete next[importKey];
                  return next;
                });
              }, 60_000);
              return;
            }
            const resolved = entry?.status === "published" ? "success" : event.payload.status;
            setQueueStatuses((current) => ({ ...current, [importKey]: resolved }));
          })
          .catch(() => {
            setQueueStatuses((current) => ({
              ...current,
              [importKey]: event.payload.status,
            }));
          });
      }
      const suffix =
        event.payload.code === null ? "" : `，退出码 ${event.payload.code.toString()}`;
      pushSystemLog(`任务${statusLabel(event.payload.status)}${suffix}`);
      // Refresh available months in case new raw data was added
      if (settingsRef.current.raw_root) {
        invoke<string[]>("list_available_months", { rawRoot: settingsRef.current.raw_root })
          .then((months) => setAvailableMonths(months.reverse()))
          .catch(() => {});
      }
    });

    return () => {
      void unlistenOutput.then((dispose) => dispose());
      void unlistenCompleted.then((dispose) => dispose());
    };
  }, []);

  useEffect(() => {
    if (action === "probe") {
      setProvider("lmstudio");
    }
  }, [action]);

  useEffect(() => {
    if (autoScroll && logOutputRef.current) {
      logOutputRef.current.scrollTop = logOutputRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  useEffect(() => {
    if (!settings.raw_root) return;
    invoke<string[]>("list_available_months", { rawRoot: settings.raw_root })
      .then((months) => setAvailableMonths(months.reverse()))
      .catch(() => setAvailableMonths([]));
  }, [settings.raw_root]);

  useEffect(() => {
    if (!settings.inbox_root.trim()) {
      setZipCandidates([]);
      return;
    }
    let disposed = false;
    const scan = () => {
      invoke<ZipCandidate[]>("scan_import_zips", {
        inboxRoot: settings.inbox_root,
        scanDownloads: settings.scan_downloads,
      })
        .then((candidates) => {
          if (!disposed) {
            setZipCandidates(candidates);
            setScanError("");
          }
        })
        .catch((error) => {
          if (!disposed) setScanError(String(error));
        });
    };
    scan();
    const timer = window.setInterval(scan, 3000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [settings.inbox_root, settings.scan_downloads]);

  useEffect(() => {
    if (!settings.raw_root.trim() || !settings.publish_root.trim()) return;
    invoke<ImportStatus>("read_import_status", {
      rawRoot: settings.raw_root,
      publishRoot: settings.publish_root,
    })
      .then(setImportStatus)
      .catch(() => {});
  }, [settings.publish_root, settings.raw_root]);

  useEffect(() => {
    if (!settings.auto_import || status === "running") return;
    if (provider !== "mock" && !lmstudioReady) return;
    const next = zipCandidates.find((candidate) => {
      const key = candidateKey(candidate);
      return (
        candidate.stable &&
        !attemptedAutoImportsRef.current.has(key) &&
        queueStatuses[key] === undefined
      );
    });
    if (!next) return;
    const key = candidateKey(next);
    attemptedAutoImportsRef.current.add(key);
    setAction("import");
    setSelectedZip(next.path);
    void runWorkflow(next.path, true, key);
  }, [lmstudioReady, provider, queueStatuses, settings.auto_import, status, zipCandidates]);

  async function loadSettings() {
    const next = await invoke<AppSettings>("read_settings");
    setSettings(next);
  }

  function updateSettings<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((current) => ({ ...current, [key]: value }));
  }

  function pushSystemLog(text: string) {
    setLogs((current) => [
      ...current,
      {
        id: current.length + 1,
        stream: "system",
        text,
      },
    ]);
  }

  async function saveSettings() {
    await invoke("save_settings", { settings });
    setSettings((current) => ({ ...current, env_exists: true }));
    pushSystemLog("配置已保存");
  }

  async function chooseDirectory(
    field:
      | "raw_root"
      | "store_root"
      | "monthly_root"
      | "chunks_root"
      | "inbox_root"
      | "publish_root",
  ) {
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: settings[field],
    });
    if (typeof selected === "string") {
      updateSettings(field, selected);
    }
  }

  async function chooseImage() {
    const selected = await open({
      directory: false,
      multiple: false,
      filters: [
        {
          name: "图片",
          extensions: ["png", "jpg", "jpeg", "webp", "bmp", "gif"],
        },
      ],
    });
    if (typeof selected === "string") {
      setImage(selected);
    }
  }

  async function chooseZip() {
    const selected = await open({
      directory: false,
      multiple: false,
      defaultPath: settings.inbox_root,
      filters: [{ name: "Flomo 导出", extensions: ["zip"] }],
    });
    if (typeof selected === "string") {
      setSelectedZip(selected);
      setAction("import");
    }
  }

  async function runWorkflow(importZip?: string, automatic = false, importKey?: string) {
    const requestedAction: WorkflowAction = importZip ? "import" : action;
    const zip = importZip ?? selectedZip;
    const queueKey = importKey ?? zip;
    setLogs([]);
    setStatus("running");
    setLastOutputPath("");
    if (requestedAction === "import" && queueKey) {
      activeImportPathRef.current = queueKey;
      activeImportZipRef.current = zip;
      setQueueStatuses((current) => ({ ...current, [queueKey]: "running" }));
    }
    try {
      await invoke("save_settings", { settings });
      const request: WorkflowRequest = {
        action: requestedAction,
        provider,
        month: requestedAction === "import" ? undefined : month.trim() || undefined,
        raw_root: settings.raw_root,
        store_root: settings.store_root,
        monthly_root: settings.monthly_root,
        chunks_root: settings.chunks_root,
        publish_root: settings.publish_root,
        env_file: settings.env_file,
        image: image.trim() || undefined,
        zip: requestedAction === "import" ? zip : undefined,
        rounds,
      };
      const started = await invoke<WorkflowStarted>("run_workflow", { request });
      setActiveTaskId(started.task_id);
      setActiveCommand(started.command);
      pushSystemLog(`${automatic ? "自动收件已启动" : "已启动"}：${started.command}`);
      if (requestedAction === "import") {
        setLastOutputPath(settings.publish_root);
      } else if (requestedAction === "first" || requestedAction === "daily") {
        setLastOutputPath(
          month.trim() ? `${settings.chunks_root}/${month.trim()}` : settings.chunks_root,
        );
      }
    } catch (error) {
      setStatus("failed");
      setActiveTaskId(null);
      if (requestedAction === "import" && queueKey) {
        activeImportPathRef.current = null;
        activeImportZipRef.current = null;
        setQueueStatuses((current) => ({ ...current, [queueKey]: "failed" }));
      }
      pushSystemLog(String(error));
    }
  }

  async function cancelWorkflow() {
    if (!activeTaskId) {
      return;
    }
    await invoke("cancel_workflow", { taskId: activeTaskId });
    pushSystemLog("已请求停止当前任务");
  }

  async function openOutputPath() {
    if (lastOutputPath) {
      await invoke("open_path", { path: lastOutputPath });
    }
  }

  async function handleCopyLogs() {
    if (logs.length === 0) return;
    const text = logs
      .map((line) => `[${line.stream}] ${line.text}`)
      .join("\n");
    await navigator.clipboard.writeText(text);
    pushSystemLog(`已复制 ${logs.length} 条日志到剪贴板`);
  }

  const selectedAction = actionMeta[action];
  const SelectedIcon = selectedAction.icon;

  return (
    <main className="shell">
      <section className="workspace">
        <aside className="sidebar" aria-label="工作流">
          <div className="brandHeader">
            <div className="brand">
              <div className="brandMark">ft</div>
              <div>
                <h1>flomo-transcriber</h1>
                <p>{settings.project_root || "本地资料处理工具"}</p>
              </div>
            </div>
            <button
              className="themeToggle"
              type="button"
              title={theme === "dark" ? "切换亮色主题" : "切换暗色主题"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>

          <nav className="actionList">
            {(Object.keys(actionMeta) as WorkflowAction[]).map((key) => {
              const meta = actionMeta[key];
              const Icon = meta.icon;
              return (
                <button
                  key={key}
                  className={key === action ? "actionButton active" : "actionButton"}
                  aria-current={key === action ? "true" : undefined}
                  disabled={status === "running"}
                  onClick={() => setAction(key)}
                  type="button"
                >
                  <Icon size={18} aria-hidden="true" />
                  <span>{meta.label}</span>
                </button>
              );
            })}
          </nav>

          <div className={`statusPill ${configState.tone}`}>
            <Activity size={16} aria-hidden="true" />
            <span>{configState.label}</span>
          </div>
          <div className="runtimeInfo">
            <span>运行环境</span>
            <strong>{settings.runtime_mode || "检测中"}</strong>
          </div>
        </aside>

        <section className="controlPane">
          <header className="paneHeader">
            <div>
              <h2>
                <SelectedIcon size={22} aria-hidden="true" />
                {selectedAction.label}
              </h2>
              <p>{selectedAction.description}</p>
            </div>
            <div className={`runState ${status}`}>
              {statusIcon(status)}
              <span>{statusLabel(status)}</span>
            </div>
          </header>

          {/* ── 运行设置（置顶 — 每次都要调整的核心参数）── */}
          <section className="sectionBlock">
            <div className="sectionTitle">
              {action === "import" ? (
                <CalendarClock size={18} aria-hidden="true" />
              ) : (
                <Settings size={18} aria-hidden="true" />
              )}
              <h3>{action === "import" ? "同步状态" : "运行设置"}</h3>
              <button
                className="iconButton"
                type="button"
                disabled={!settings.raw_root || status === "running"}
                title="打开 raw 文件夹"
                onClick={() => void invoke("open_path", { path: settings.raw_root })}
              >
                <FolderOpen size={16} aria-hidden="true" />
              </button>
            </div>
            {action === "import" ? (
              <div className="importWorkspace">
                <div className="syncSummary">
                  <div>
                    <span>下次导出起始日</span>
                    <strong>{importStatus.suggested_export_date || "首次导入后显示"}</strong>
                  </div>
                  <p>始终包含最后一天，程序会去除重叠内容。</p>
                </div>

                <label className="field">
                  <span>待导入 ZIP</span>
                  <div className="inlinePicker">
                    <input
                      value={selectedZip}
                      disabled={status === "running"}
                      onChange={(event) => setSelectedZip(event.target.value)}
                      placeholder="选择 Flomo 导出 ZIP"
                    />
                    <button
                      className="iconButton"
                      title="选择 Flomo ZIP"
                      type="button"
                      disabled={status === "running"}
                      onClick={() => void chooseZip()}
                    >
                      <Archive size={18} aria-hidden="true" />
                    </button>
                  </div>
                </label>

                <div className="importOptions">
                  <label className="switchField">
                    <input
                      type="checkbox"
                      checked={settings.auto_import}
                      disabled={status === "running"}
                      onChange={(event) => updateSettings("auto_import", event.target.checked)}
                    />
                    <span>发现完整 ZIP 后自动处理</span>
                  </label>
                  <label className="field compactField">
                    <span>图片处理</span>
                    <select
                      value={provider}
                      disabled={status === "running"}
                      onChange={(event) => setProvider(event.target.value as Provider)}
                    >
                      <option value="lmstudio">LM Studio</option>
                      <option value="mock">mock</option>
                    </select>
                  </label>
                </div>

                <div className="queueHeader">
                  <span>收件队列</span>
                  <span>{zipCandidates.length} 个 ZIP</span>
                </div>
                <div className="queueList" aria-live="polite">
                  {zipCandidates.length === 0 ? (
                    <p className="emptyQueue">正在监控 inbox{settings.scan_downloads ? " 和 Downloads" : ""}。</p>
                  ) : (
                    zipCandidates.map((candidate) => {
                      const key = candidateKey(candidate);
                      const queueStatus = queueStatuses[key];
                      const waitingForModel =
                        settings.auto_import && provider === "lmstudio" && !lmstudioReady;
                      return (
                        <div className="queueItem" key={key}>
                          <div className="queueFile">
                            <strong title={candidate.path}>{candidate.name}</strong>
                            <span>
                              {candidate.source === "downloads" ? "Downloads" : "inbox"} · {formatBytes(candidate.size)}
                            </span>
                          </div>
                          <span className={`queueState ${queueStatus || (candidate.stable ? "ready" : "checking")}`}>
                            {queueStatus
                              ? queueStatusLabel(queueStatus)
                              : candidate.stable
                                ? waitingForModel
                                  ? "等待模型"
                                  : "可导入"
                                : "确认完整性"}
                          </span>
                          <button
                            className="secondaryButton compact"
                            type="button"
                            disabled={!candidate.stable || status === "running" || queueStatus === "success"}
                            onClick={() => {
                              setAction("import");
                              setSelectedZip(candidate.path);
                              void runWorkflow(candidate.path, false, key);
                            }}
                          >
                            {queueStatus === "failed" ||
                            queueStatus === "cancelled" ||
                            queueStatus === "queued"
                              ? "重试"
                              : "导入"}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
                {scanError && <p className="inlineError">{scanError}</p>}
                <p className="syncFootnote">
                  {importStatus.latest_memo_at
                    ? `已发布到 ${importStatus.latest_memo_at}`
                    : "尚无成功发布记录"}
                  {importStatus.last_release ? ` · ${importStatus.last_release}` : ""}
                </p>
                {latestPublishedImport && latestPublishedImport.failed_images > 0 && (
                  <div className="imageWarnings" role="status">
                    <strong>
                      {latestPublishedImport.failed_images} 张图片未完成识别，文字 memo 已正常发布
                    </strong>
                    {latestPublishedImport.image_failures.map((failure) => (
                      <p key={failure.image_id}>
                        {failure.month} · {failure.image_id}：{failure.error_message}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ) : (
            <div className="fieldGrid">
              <label className="field">
                <span>月份</span>
                <select
                  value={month}
                  disabled={status === "running"}
                  onChange={(event) => setMonth(event.target.value)}
                >
                  <option value="">全部月份</option>
                  {availableMonths.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>图片处理</span>
                <select
                  value={provider}
                  disabled={status === "running" || action === "probe"}
                  onChange={(event) => setProvider(event.target.value as Provider)}
                >
                  <option value="lmstudio">LM Studio</option>
                  <option value="mock">mock</option>
                </select>
              </label>
              {action === "retry" && (
                <label className="field">
                  <span>重试轮数</span>
                  <input
                    min={1}
                    max={20}
                    type="number"
                    value={rounds}
                    disabled={status === "running"}
                    onChange={(event) => setRounds(Number(event.target.value))}
                  />
                </label>
              )}
              {action === "probe" && (
                <label className="field wide">
                  <span>目标图片</span>
                  <div className="inlinePicker">
                    <input
                      value={image}
                      disabled={status === "running"}
                      onChange={(event) => setImage(event.target.value)}
                      placeholder="选择一张图片"
                    />
                    <button
                      className="iconButton"
                      title="选择图片"
                      type="button"
                      disabled={status === "running"}
                      onClick={() => void chooseImage()}
                    >
                      <FileImage size={18} aria-hidden="true" />
                    </button>
                  </div>
                </label>
              )}
            </div>
            )}
          </section>

          {/* ── 主要操作按钮 ── */}
          <section className="sectionBlock">
            {status === "running" ? (
              <button
                className="dangerButton primaryButton-large"
                type="button"
                onClick={() => void cancelWorkflow()}
              >
                <PauseCircle size={20} aria-hidden="true" />
                停止运行
              </button>
            ) : (
              <button
                className="primaryButton primaryButton-large"
                type="button"
                disabled={!canRun}
                onClick={() => void runWorkflow()}
              >
                <Play size={20} aria-hidden="true" />
                {action === "import" ? "导入并发布" : "开始运行"}
              </button>
            )}
          </section>

          {/* ── 折叠：路径配置 ── */}
          <details className="collapsibleSection">
            <summary>
              <FolderOpen size={16} aria-hidden="true" />
              路径配置
              <span className="collapsiblePathHint">
                raw · chunks · inbox · publish
              </span>
            </summary>
            <div className="sectionBody">
              <PathInput
                label="raw"
                value={settings.raw_root}
                onChange={(value) => updateSettings("raw_root", value)}
                onPick={() => void chooseDirectory("raw_root")}
                disabled={status === "running"}
              />
              <PathInput
                label="store"
                value={settings.store_root}
                onChange={(value) => updateSettings("store_root", value)}
                onPick={() => void chooseDirectory("store_root")}
                disabled={status === "running"}
              />
              <PathInput
                label="monthly"
                value={settings.monthly_root}
                onChange={(value) => updateSettings("monthly_root", value)}
                onPick={() => void chooseDirectory("monthly_root")}
                disabled={status === "running"}
              />
              <PathInput
                label="llm_chunks"
                value={settings.chunks_root}
                onChange={(value) => updateSettings("chunks_root", value)}
                onPick={() => void chooseDirectory("chunks_root")}
                disabled={status === "running"}
              />
              <div className="pathDivider" />
              <PathInput
                label="inbox"
                value={settings.inbox_root}
                onChange={(value) => updateSettings("inbox_root", value)}
                onPick={() => void chooseDirectory("inbox_root")}
                disabled={status === "running"}
              />
              <PathInput
                label="publish"
                value={settings.publish_root}
                onChange={(value) => updateSettings("publish_root", value)}
                onPick={() => void chooseDirectory("publish_root")}
                disabled={status === "running"}
              />
              <label className="switchField pathSwitch">
                <input
                  type="checkbox"
                  checked={settings.scan_downloads}
                  disabled={status === "running"}
                  onChange={(event) => updateSettings("scan_downloads", event.target.checked)}
                />
                <span>同时扫描 Downloads</span>
              </label>
            </div>
          </details>

          {/* ── 折叠：LM Studio 配置 ── */}
          <details className="collapsibleSection">
            <summary>
              <Settings size={16} aria-hidden="true" />
              LM Studio 配置
              <span className="collapsiblePathHint">
                {settings.vlm_model || ".env"}
              </span>
            </summary>
            <div className="sectionBody">
              <div className="fieldGrid">
                <label className="field wide">
                  <span>Base URL</span>
                  <input
                    value={settings.vlm_base_url}
                    disabled={status === "running"}
                    onChange={(event) => updateSettings("vlm_base_url", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>视觉模型</span>
                  <input
                    value={settings.vlm_model}
                    disabled={status === "running"}
                    onChange={(event) => updateSettings("vlm_model", event.target.value)}
                    placeholder="必填"
                  />
                </label>
                <label className="field">
                  <span>重试模型</span>
                  <input
                    value={settings.vlm_retry_model}
                    disabled={status === "running"}
                    onChange={(event) => updateSettings("vlm_retry_model", event.target.value)}
                    placeholder="可选"
                  />
                </label>
                <label className="field">
                  <span>超时秒数</span>
                  <input
                    value={settings.vlm_timeout_seconds}
                    disabled={status === "running"}
                    onChange={(event) => updateSettings("vlm_timeout_seconds", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Max tokens</span>
                  <input
                    value={settings.vlm_max_tokens}
                    disabled={status === "running"}
                    onChange={(event) => updateSettings("vlm_max_tokens", event.target.value)}
                  />
                </label>
              </div>
            </div>
          </details>

          {/* ── 底部操作栏 ── */}
          <div className="commandHint">
            {status === "running"
              ? "正在执行任务…"
              : action === "import"
                ? settings.auto_import
                  ? "自动收件已开启"
                  : "选择 ZIP 后手动导入"
                : "配置视觉模型后即可运行"}
          </div>
          <footer className="commandBar">
            <button
              className="secondaryButton compact"
              type="button"
              disabled={status === "running"}
              onClick={() => void saveSettings()}
            >
              <Save size={16} aria-hidden="true" />
              保存配置
            </button>
          </footer>
        </section>

        <section className="logPane">
          <header className="logHeader">
            <div>
              <h2>运行日志</h2>
              <p>{activeCommand || "等待任务开始"}</p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                className="secondaryButton compact"
                type="button"
                disabled={logs.length === 0}
                title="复制全部日志到剪贴板"
                onClick={() => void handleCopyLogs()}
              >
                <Copy size={16} aria-hidden="true" />
              </button>
              <button
                className={`secondaryButton compact${autoScroll ? " active" : ""}`}
                type="button"
                title={autoScroll ? "自动滚动已开启 — 点击关闭" : "自动滚动已关闭 — 点击开启"}
                onClick={() => setAutoScroll((prev) => !prev)}
              >
                {autoScroll ? (
                  <ChevronsDown size={16} aria-hidden="true" />
                ) : (
                  <PauseCircle size={16} aria-hidden="true" />
                )}
              </button>
              <button
                className="secondaryButton compact"
                type="button"
                disabled={!lastOutputPath || status === "running"}
                onClick={() => void openOutputPath()}
              >
                <FolderOpen size={16} aria-hidden="true" />
                打开结果
              </button>
            </div>
          </header>
          <div
            className="logOutput"
            aria-live="polite"
            ref={logOutputRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              if (el.scrollHeight - el.scrollTop - el.clientHeight >= 30) {
                setAutoScroll(false);
              }
            }}
          >
            {logs.length === 0 ? (
              <p className="emptyLog">日志会显示在这里。</p>
            ) : (
              logs.map((line) => (
                <div key={line.id} className={`logLine ${line.stream}`}>
                  <span>{line.stream}</span>
                  <pre>{line.text}</pre>
                </div>
              ))
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

function PathInput({
  label,
  value,
  disabled,
  onChange,
  onPick,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onPick: () => void;
}) {
  return (
    <label className="pathField">
      <span>{label}</span>
      <input value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
      <button
        className="iconButton"
        title={`选择 ${label} 目录`}
        type="button"
        disabled={disabled}
        onClick={onPick}
      >
        <FolderOpen size={18} aria-hidden="true" />
      </button>
    </label>
  );
}

function statusLabel(status: RunStatus | WorkflowCompleted["status"]) {
  const labels: Record<RunStatus, string> = {
    idle: "待运行",
    running: "运行中",
    success: "已完成",
    failed: "失败",
    cancelled: "已停止",
  };
  return labels[status];
}

function statusIcon(status: RunStatus) {
  if (status === "success") {
    return <CheckCircle2 size={17} aria-hidden="true" />;
  }
  if (status === "failed") {
    return <XCircle size={17} aria-hidden="true" />;
  }
  if (status === "cancelled") {
    return <PauseCircle size={17} aria-hidden="true" />;
  }
  return <Activity size={17} aria-hidden="true" />;
}

function candidateKey(candidate: ZipCandidate) {
  return `${candidate.path}:${candidate.size}:${candidate.modified_millis}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function queueStatusLabel(status: QueueStatus) {
  const labels: Record<QueueStatus, string> = {
    running: "处理中",
    queued: "等待模型",
    success: "已发布",
    failed: "失败",
    cancelled: "已停止",
  };
  return labels[status];
}

function fileNameFromPath(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

export default App;
