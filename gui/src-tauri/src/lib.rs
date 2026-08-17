use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeSet, HashMap},
    fs,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    process::Command,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};
#[cfg(debug_assertions)]
use std::{
    io::{BufRead, BufReader},
    process::Stdio,
    thread,
};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const ENV_KEYS: [&str; 5] = [
    "FLOMO_VLM_BASE_URL",
    "FLOMO_VLM_MODEL",
    "FLOMO_VLM_RETRY_MODEL",
    "FLOMO_VLM_TIMEOUT_SECONDS",
    "FLOMO_VLM_MAX_TOKENS",
];
const GUI_SETTINGS_FILE: &str = ".flomo-gui-settings.json";

#[derive(Default)]
struct WorkflowState {
    active: Option<ActiveWorkflow>,
}

#[derive(Default)]
struct InboxScanState {
    observations: HashMap<String, FileObservation>,
}

#[derive(Clone, Copy)]
struct FileObservation {
    size: u64,
    modified_millis: u128,
}

struct ActiveWorkflow {
    task_id: String,
    process: Option<ActiveProcess>,
    cancelling: bool,
}

enum ActiveProcess {
    Sidecar(CommandChild),
    #[cfg(debug_assertions)]
    Local {
        pid: u32,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AppSettings {
    project_root: String,
    env_file: String,
    raw_root: String,
    store_root: String,
    monthly_root: String,
    chunks_root: String,
    inbox_root: String,
    publish_root: String,
    scan_downloads: bool,
    auto_import: bool,
    vlm_base_url: String,
    vlm_model: String,
    vlm_retry_model: String,
    vlm_timeout_seconds: String,
    vlm_max_tokens: String,
    env_exists: bool,
    runtime_mode: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct GuiPathSettings {
    #[serde(skip_serializing_if = "Option::is_none")]
    raw_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    store_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    monthly_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    chunks_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    inbox_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    publish_root: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    scan_downloads: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    auto_import: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WorkflowRequest {
    action: String,
    provider: String,
    month: Option<String>,
    raw_root: String,
    store_root: String,
    monthly_root: String,
    chunks_root: String,
    publish_root: String,
    env_file: String,
    image: Option<String>,
    zip: Option<String>,
    rounds: u32,
}

#[derive(Debug, Clone, Serialize)]
struct ZipCandidate {
    path: String,
    name: String,
    size: u64,
    modified_millis: u128,
    source: String,
    stable: bool,
}

#[derive(Debug, Clone, Default, Serialize)]
struct ImportStatus {
    suggested_export_date: Option<String>,
    latest_memo_at: Option<String>,
    last_release: Option<String>,
    imports: Vec<ImportEntryStatus>,
}

#[derive(Debug, Clone, Serialize)]
struct ImportEntryStatus {
    original_filename: String,
    status: String,
    error_message: Option<String>,
    failed_images: u64,
    image_failures: Vec<ImageFailureStatus>,
}

#[derive(Debug, Clone, Serialize)]
struct ImageFailureStatus {
    image_id: String,
    month: String,
    error_message: String,
}

#[derive(Debug, Clone, Serialize)]
struct WorkflowStarted {
    task_id: String,
    command: String,
}

#[derive(Debug, Clone, Serialize)]
struct WorkflowOutput {
    task_id: String,
    stream: String,
    line: String,
}

#[derive(Debug, Clone, Serialize)]
struct WorkflowCompleted {
    task_id: String,
    status: String,
    code: Option<i32>,
}

#[tauri::command]
fn read_settings(app: AppHandle) -> Result<AppSettings, String> {
    let project_root = workspace_root(&app)?;
    let env_file = project_root.join(".env");
    let env = read_env_map(&env_file)?;
    let gui_settings = read_gui_path_settings(&gui_settings_path(&project_root))?;

    Ok(AppSettings {
        project_root: project_root.to_string_lossy().into_owned(),
        env_file: env_file.to_string_lossy().into_owned(),
        raw_root: setting_path_or_default(gui_settings.raw_root, project_root.join("raw")),
        store_root: setting_path_or_default(gui_settings.store_root, project_root.join("store")),
        monthly_root: setting_path_or_default(
            gui_settings.monthly_root,
            project_root.join("monthly"),
        ),
        chunks_root: setting_path_or_default(
            gui_settings.chunks_root,
            project_root.join("llm_chunks"),
        ),
        inbox_root: setting_path_or_default(
            gui_settings.inbox_root,
            project_root.join("flomo-inbox"),
        ),
        publish_root: setting_path_or_default(
            gui_settings.publish_root,
            project_root.join("flomo-context"),
        ),
        scan_downloads: gui_settings.scan_downloads.unwrap_or(true),
        auto_import: gui_settings.auto_import.unwrap_or(true),
        vlm_base_url: env
            .get("FLOMO_VLM_BASE_URL")
            .cloned()
            .unwrap_or_else(|| "http://127.0.0.1:1234/v1".to_string()),
        vlm_model: env.get("FLOMO_VLM_MODEL").cloned().unwrap_or_default(),
        vlm_retry_model: env
            .get("FLOMO_VLM_RETRY_MODEL")
            .cloned()
            .unwrap_or_default(),
        vlm_timeout_seconds: env
            .get("FLOMO_VLM_TIMEOUT_SECONDS")
            .cloned()
            .unwrap_or_else(|| "180".to_string()),
        vlm_max_tokens: env
            .get("FLOMO_VLM_MAX_TOKENS")
            .cloned()
            .unwrap_or_else(|| "4096".to_string()),
        env_exists: env_file.exists(),
        runtime_mode: runtime_mode(&app),
    })
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: AppSettings) -> Result<(), String> {
    let env_file = normalize_env_file(&app, &settings.env_file)?;
    let updates = env_updates_from_settings(&settings);
    write_env_file(&env_file, &updates)?;

    let project_root = workspace_root(&app)?;
    write_gui_path_settings(&gui_settings_path(&project_root), &settings)?;
    for path in [&settings.inbox_root, &settings.publish_root] {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            fs::create_dir_all(trimmed)
                .map_err(|error| format!("无法创建同步目录 {trimmed}：{error}"))?;
        }
    }
    Ok(())
}

#[tauri::command]
fn run_workflow(
    app: AppHandle,
    state: State<'_, Mutex<WorkflowState>>,
    request: WorkflowRequest,
) -> Result<WorkflowStarted, String> {
    let mut guarded = state
        .lock()
        .map_err(|_| "无法读取当前任务状态。".to_string())?;
    if guarded.active.is_some() {
        return Err("已有任务正在运行。".to_string());
    }

    validate_request(&request)?;
    let project_root = workspace_root(&app)?;
    let sidecar_args = build_sidecar_args(&request, &project_root);
    let command_text = display_command("flomo-sidecar", &sidecar_args);

    if let Ok(sidecar_command) = app.shell().sidecar("flomo-sidecar") {
        let (mut rx, child) = sidecar_command
            .args(sidecar_args)
            .spawn()
            .map_err(|error| format!("无法启动内置处理程序：{error}"))?;

        let task_id = new_task_id();
        guarded.active = Some(ActiveWorkflow {
            task_id: task_id.clone(),
            process: Some(ActiveProcess::Sidecar(child)),
            cancelling: false,
        });
        drop(guarded);

        let wait_app = app.clone();
        let wait_task_id = task_id.clone();
        tauri::async_runtime::spawn(async move {
            let mut code: Option<i32> = None;
            let mut status = "failed".to_string();
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        emit_output(&wait_app, &wait_task_id, "stdout", &line);
                    }
                    CommandEvent::Stderr(line) => {
                        emit_output(&wait_app, &wait_task_id, "stderr", &line);
                    }
                    CommandEvent::Error(error) => {
                        let _ = wait_app.emit(
                            "workflow-output",
                            WorkflowOutput {
                                task_id: wait_task_id.clone(),
                                stream: "stderr".to_string(),
                                line: error,
                            },
                        );
                    }
                    CommandEvent::Terminated(payload) => {
                        code = payload.code;
                        status = if code == Some(0) { "success" } else { "failed" }.to_string();
                        break;
                    }
                    _ => {}
                }
            }

            finish_workflow(wait_app, wait_task_id, status, code);
        });

        return Ok(WorkflowStarted {
            task_id,
            command: command_text,
        });
    }

    #[cfg(not(debug_assertions))]
    {
        return Err("内置处理程序缺失，请重新安装应用。".to_string());
    }

    #[cfg(debug_assertions)]
    {
        let (program, args) = build_local_python_command(&request, &project_root);
        let command_text = display_command(&program, &args);
        let mut child = Command::new(&program)
            .args(&args)
            .current_dir(&project_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("无法启动本机 Python：{error}"))?;

        let task_id = new_task_id();
        let pid = child.id();
        guarded.active = Some(ActiveWorkflow {
            task_id: task_id.clone(),
            process: Some(ActiveProcess::Local { pid }),
            cancelling: false,
        });
        drop(guarded);

        if let Some(stdout) = child.stdout.take() {
            spawn_output_reader(app.clone(), task_id.clone(), "stdout", stdout);
        }
        if let Some(stderr) = child.stderr.take() {
            spawn_output_reader(app.clone(), task_id.clone(), "stderr", stderr);
        }

        let wait_app = app.clone();
        let wait_task_id = task_id.clone();
        thread::spawn(move || {
            let code = child.wait().ok().and_then(|status| status.code());
            let status = if code == Some(0) { "success" } else { "failed" }.to_string();
            finish_workflow(wait_app, wait_task_id, status, code);
        });

        Ok(WorkflowStarted {
            task_id,
            command: command_text,
        })
    }
}

#[tauri::command(rename_all = "camelCase")]
fn cancel_workflow(state: State<'_, Mutex<WorkflowState>>, task_id: String) -> Result<(), String> {
    let process = {
        let mut guarded = state
            .lock()
            .map_err(|_| "无法读取当前任务状态。".to_string())?;
        let active = guarded
            .active
            .as_mut()
            .ok_or_else(|| "没有正在运行的任务。".to_string())?;
        if active.task_id != task_id {
            return Err("任务已经变化，无法停止。".to_string());
        }
        active.cancelling = true;
        active.process.take()
    };

    match process {
        Some(ActiveProcess::Sidecar(child)) => child
            .kill()
            .map_err(|error| format!("停止任务失败：{error}")),
        #[cfg(debug_assertions)]
        Some(ActiveProcess::Local { pid }) => kill_process(pid),
        None => Ok(()),
    }
}

#[tauri::command]
fn list_available_months(raw_root: String) -> Result<Vec<String>, String> {
    let raw = PathBuf::from(&raw_root);
    if !raw.is_dir() {
        return Ok(vec![]);
    }

    let mut months: BTreeSet<String> = BTreeSet::new();
    let year_dirs = fs::read_dir(&raw).map_err(|e| format!("无法读取 raw 目录：{e}"))?;

    for year_entry in year_dirs {
        let year_entry = year_entry.map_err(|e| format!("无法读取 raw 子目录：{e}"))?;
        if !year_entry
            .file_type()
            .map_err(|e| format!("无法判断文件类型：{e}"))?
            .is_dir()
        {
            continue;
        }
        let year_name = year_entry.file_name().to_string_lossy().to_string();
        if !year_name.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }

        let batch_dirs = match fs::read_dir(year_entry.path()) {
            Ok(dirs) => dirs,
            Err(_) => continue,
        };

        for batch_entry in batch_dirs {
            let batch_entry = match batch_entry {
                Ok(entry) => entry,
                Err(_) => continue,
            };
            if !batch_entry
                .file_type()
                .map_err(|_| "type error".to_string())?
                .is_dir()
            {
                continue;
            }
            let batch_name = batch_entry.file_name().to_string_lossy().to_string();

            // Extract 8-digit date from batch name like "flomo@User-20260624"
            if let Some(month) = extract_month_from_batch(&batch_name) {
                months.insert(month);
            }
        }
    }

    Ok(months.into_iter().collect())
}

#[tauri::command(rename_all = "camelCase")]
fn scan_import_zips(
    app: AppHandle,
    state: State<'_, Mutex<InboxScanState>>,
    inbox_root: String,
    scan_downloads: bool,
) -> Result<Vec<ZipCandidate>, String> {
    let mut roots = vec![(PathBuf::from(inbox_root), "inbox")];
    if scan_downloads {
        if let Ok(downloads) = app.path().download_dir() {
            roots.push((downloads, "downloads"));
        }
    }

    let mut discovered = Vec::new();
    for (root, source) in roots {
        if !root.is_dir() {
            continue;
        }
        let entries =
            fs::read_dir(&root).map_err(|error| format!("无法扫描 {}：{error}", root.display()))?;
        for entry in entries.flatten() {
            let path = entry.path();
            if !looks_like_flomo_zip(&path) {
                continue;
            }
            let metadata = match entry.metadata() {
                Ok(metadata) if metadata.is_file() => metadata,
                _ => continue,
            };
            let modified_millis = metadata
                .modified()
                .ok()
                .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
                .map(|duration| duration.as_millis())
                .unwrap_or_default();
            discovered.push((path, source.to_string(), metadata.len(), modified_millis));
        }
    }

    discovered.sort_by(|left, right| right.3.cmp(&left.3).then_with(|| left.0.cmp(&right.0)));
    let mut guarded = state
        .lock()
        .map_err(|_| "无法读取收件扫描状态。".to_string())?;
    let mut current = HashMap::new();
    let candidates = discovered
        .into_iter()
        .map(|(path, source, size, modified_millis)| {
            let path_text = path.to_string_lossy().into_owned();
            let unchanged = observation_is_unchanged(
                guarded.observations.get(&path_text),
                size,
                modified_millis,
            );
            let stable = unchanged && zip_directory_is_readable(&path);
            current.insert(
                path_text.clone(),
                FileObservation {
                    size,
                    modified_millis,
                },
            );
            ZipCandidate {
                name: path
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned(),
                path: path_text,
                size,
                modified_millis,
                source,
                stable,
            }
        })
        .collect();
    guarded.observations = current;
    Ok(candidates)
}

#[tauri::command(rename_all = "camelCase")]
fn read_import_status(raw_root: String, publish_root: String) -> Result<ImportStatus, String> {
    let raw_manifest = PathBuf::from(raw_root).join(".import-manifest.json");
    let latest_manifest = PathBuf::from(publish_root).join("latest.json");
    let mut status = ImportStatus::default();

    for path in [raw_manifest, latest_manifest] {
        if !path.is_file() {
            continue;
        }
        let content = fs::read_to_string(&path)
            .map_err(|error| format!("无法读取 {}：{error}", path.display()))?;
        let value: serde_json::Value = serde_json::from_str(&content)
            .map_err(|error| format!("无法解析 {}：{error}", path.display()))?;
        if path.file_name().and_then(|name| name.to_str()) == Some(".import-manifest.json") {
            status.imports = import_entries_from_json(&value);
        }
        if status.suggested_export_date.is_none() {
            status.suggested_export_date = find_json_string(
                &value,
                &[
                    "suggested_export_date",
                    "next_export_start_date",
                    "next_export_date",
                ],
            );
        }
        if status.latest_memo_at.is_none() {
            status.latest_memo_at = find_json_string(
                &value,
                &[
                    "max_successfully_published_created_at",
                    "latest_memo_at",
                    "max_created_at",
                ],
            );
        }
        if status.last_release.is_none() {
            status.last_release = find_json_string(&value, &["release_id", "release", "snapshot"]);
        }
    }

    if status.suggested_export_date.is_none() {
        status.suggested_export_date = status
            .latest_memo_at
            .as_deref()
            .filter(|value| value.len() >= 10)
            .map(|value| value[..10].to_string());
    }
    Ok(status)
}

fn import_entries_from_json(value: &serde_json::Value) -> Vec<ImportEntryStatus> {
    value
        .get("imports")
        .and_then(serde_json::Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|entry| {
            Some(ImportEntryStatus {
                original_filename: entry.get("original_filename")?.as_str()?.to_string(),
                status: entry.get("status")?.as_str()?.to_string(),
                error_message: entry
                    .get("error_message")
                    .and_then(serde_json::Value::as_str)
                    .map(str::to_string),
                failed_images: entry
                    .get("failed_images")
                    .and_then(serde_json::Value::as_u64)
                    .unwrap_or(0),
                image_failures: entry
                    .get("image_failures")
                    .and_then(serde_json::Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(|failure| {
                        Some(ImageFailureStatus {
                            image_id: failure.get("image_id")?.as_str()?.to_string(),
                            month: failure.get("month")?.as_str()?.to_string(),
                            error_message: failure.get("error_message")?.as_str()?.to_string(),
                        })
                    })
                    .collect(),
            })
        })
        .collect()
}

fn looks_like_flomo_zip(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    let lower = name.to_ascii_lowercase();
    if !lower.starts_with("flomo@") || !lower.ends_with(".zip") {
        return false;
    }
    let stem = &lower[..lower.len() - 4];
    let mut parts = stem.rsplit('-');
    let last = parts.next().unwrap_or_default();
    if last.len() == 8 && last.bytes().all(|byte| byte.is_ascii_digit()) {
        return true;
    }
    let is_hash_suffix =
        (8..=64).contains(&last.len()) && last.bytes().all(|byte| byte.is_ascii_hexdigit());
    is_hash_suffix
        && parts
            .next()
            .is_some_and(|date| date.len() == 8 && date.bytes().all(|byte| byte.is_ascii_digit()))
}

fn observation_is_unchanged(
    previous: Option<&FileObservation>,
    size: u64,
    modified_millis: u128,
) -> bool {
    previous.is_some_and(|value| value.size == size && value.modified_millis == modified_millis)
}

fn zip_directory_is_readable(path: &Path) -> bool {
    const MAX_END_RECORD: u64 = 65_557;
    let mut file = match fs::File::open(path) {
        Ok(file) => file,
        Err(_) => return false,
    };
    let file_len = match file.metadata() {
        Ok(metadata) => metadata.len(),
        Err(_) => return false,
    };
    if file_len < 22 {
        return false;
    }
    let tail_len = file_len.min(MAX_END_RECORD) as usize;
    if file.seek(SeekFrom::End(-(tail_len as i64))).is_err() {
        return false;
    }
    let mut tail = vec![0_u8; tail_len];
    if file.read_exact(&mut tail).is_err() {
        return false;
    }
    let Some(position) = tail
        .windows(4)
        .rposition(|window| window == [0x50, 0x4b, 0x05, 0x06])
    else {
        return false;
    };
    if position + 22 > tail.len() {
        return false;
    }
    let comment_len = u16::from_le_bytes([tail[position + 20], tail[position + 21]]) as usize;
    if position + 22 + comment_len != tail.len() {
        return false;
    }
    let directory_size = u32::from_le_bytes([
        tail[position + 12],
        tail[position + 13],
        tail[position + 14],
        tail[position + 15],
    ]) as u64;
    let directory_offset = u32::from_le_bytes([
        tail[position + 16],
        tail[position + 17],
        tail[position + 18],
        tail[position + 19],
    ]) as u64;
    let bounds_are_valid = directory_offset
        .checked_add(directory_size)
        .is_some_and(|end| end <= file_len);
    if !bounds_are_valid {
        return false;
    }
    if directory_size == 0 {
        return true;
    }
    if file.seek(SeekFrom::Start(directory_offset)).is_err() {
        return false;
    }
    let mut signature = [0_u8; 4];
    file.read_exact(&mut signature).is_ok() && signature == [0x50, 0x4b, 0x01, 0x02]
}

fn find_json_string(value: &serde_json::Value, keys: &[&str]) -> Option<String> {
    match value {
        serde_json::Value::Object(map) => {
            for key in keys {
                if let Some(value) = map.get(*key).and_then(serde_json::Value::as_str) {
                    return Some(value.to_string());
                }
            }
            map.values().find_map(|value| find_json_string(value, keys))
        }
        serde_json::Value::Array(values) => values
            .iter()
            .rev()
            .find_map(|value| find_json_string(value, keys)),
        _ => None,
    }
}

fn extract_month_from_batch(name: &str) -> Option<String> {
    // Find 8 consecutive digits → YYYYMMDD → derive YYYY-MM
    let bytes = name.as_bytes();
    let mut i = 0;
    while i + 8 <= bytes.len() {
        if bytes[i..i + 8].iter().all(|b| b.is_ascii_digit()) {
            let date_str = &name[i..i + 8];
            return Some(format!("{}-{}", &date_str[..4], &date_str[4..6]));
        }
        i += 1;
    }
    None
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let target = PathBuf::from(path);
    if !target.exists() {
        return Err("路径不存在。".to_string());
    }

    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("explorer");
        command.arg(&target);
        command
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(&target);
        command
    };

    #[cfg(all(unix, not(target_os = "macos")))]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(&target);
        command
    };

    command
        .spawn()
        .map_err(|error| format!("无法打开路径：{error}"))?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(Mutex::new(WorkflowState::default()))
        .manage(Mutex::new(InboxScanState::default()))
        .invoke_handler(tauri::generate_handler![
            read_settings,
            save_settings,
            run_workflow,
            cancel_workflow,
            list_available_months,
            scan_import_zips,
            read_import_status,
            open_path
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(debug_assertions)]
fn dev_project_root() -> Result<PathBuf, String> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .ok_or_else(|| "无法定位项目根目录。".to_string())
}

fn workspace_root(_app: &AppHandle) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    {
        return dev_project_root();
    }

    #[cfg(not(debug_assertions))]
    {
        let root = _app
            .path()
            .app_data_dir()
            .map_err(|error| format!("无法定位应用数据目录：{error}"))?;
        fs::create_dir_all(&root).map_err(|error| format!("无法创建应用数据目录：{error}"))?;
        Ok(root)
    }
}

fn runtime_mode(app: &AppHandle) -> String {
    if app.shell().sidecar("flomo-sidecar").is_ok() {
        "内置 sidecar".to_string()
    } else if cfg!(debug_assertions) {
        "开发模式：本机 Python".to_string()
    } else {
        "sidecar 缺失".to_string()
    }
}

fn normalize_env_file(app: &AppHandle, path: &str) -> Result<PathBuf, String> {
    let requested = PathBuf::from(path);
    if requested.is_absolute() {
        return Ok(requested);
    }
    Ok(workspace_root(app)?.join(requested))
}

fn gui_settings_path(project_root: &Path) -> PathBuf {
    project_root.join(GUI_SETTINGS_FILE)
}

fn setting_path_or_default(value: Option<String>, default_path: PathBuf) -> String {
    value
        .map(|path| path.trim().to_string())
        .filter(|path| !path.is_empty())
        .unwrap_or_else(|| default_path.to_string_lossy().into_owned())
}

fn optional_path(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn gui_path_settings_from_app_settings(settings: &AppSettings) -> GuiPathSettings {
    GuiPathSettings {
        raw_root: optional_path(&settings.raw_root),
        store_root: optional_path(&settings.store_root),
        monthly_root: optional_path(&settings.monthly_root),
        chunks_root: optional_path(&settings.chunks_root),
        inbox_root: optional_path(&settings.inbox_root),
        publish_root: optional_path(&settings.publish_root),
        scan_downloads: Some(settings.scan_downloads),
        auto_import: Some(settings.auto_import),
    }
}

fn read_gui_path_settings(path: &Path) -> Result<GuiPathSettings, String> {
    if !path.exists() {
        return Ok(GuiPathSettings::default());
    }

    let content =
        fs::read_to_string(path).map_err(|error| format!("无法读取 GUI 设置：{error}"))?;
    if content.trim().is_empty() {
        return Ok(GuiPathSettings::default());
    }

    serde_json::from_str(&content).map_err(|error| format!("无法解析 GUI 设置：{error}"))
}

fn write_gui_path_settings(path: &Path, settings: &AppSettings) -> Result<(), String> {
    let gui_settings = gui_path_settings_from_app_settings(settings);
    let mut content = serde_json::to_string_pretty(&gui_settings)
        .map_err(|error| format!("无法生成 GUI 设置：{error}"))?;
    content.push('\n');
    fs::write(path, content).map_err(|error| format!("无法写入 GUI 设置：{error}"))
}

fn read_env_map(path: &Path) -> Result<HashMap<String, String>, String> {
    let mut values = HashMap::new();
    if !path.exists() {
        return Ok(values);
    }

    let content = fs::read_to_string(path).map_err(|error| format!("无法读取 .env：{error}"))?;
    for line in content.lines() {
        if let Some((key, value)) = parse_env_line(line) {
            values.insert(key, value);
        }
    }
    Ok(values)
}

fn parse_env_line(line: &str) -> Option<(String, String)> {
    let trimmed = line.trim();
    if trimmed.is_empty() || trimmed.starts_with('#') {
        return None;
    }
    let assignment = trimmed.strip_prefix("export ").unwrap_or(trimmed);
    let (raw_key, raw_value) = assignment.split_once('=')?;
    let key = raw_key.trim();
    if key.is_empty() {
        return None;
    }
    Some((key.to_string(), unquote_env_value(raw_value.trim())))
}

fn unquote_env_value(value: &str) -> String {
    if value.len() >= 2 {
        let bytes = value.as_bytes();
        if (bytes[0] == b'"' && bytes[value.len() - 1] == b'"')
            || (bytes[0] == b'\'' && bytes[value.len() - 1] == b'\'')
        {
            return value[1..value.len() - 1].to_string();
        }
    }
    value.to_string()
}

fn env_updates_from_settings(settings: &AppSettings) -> HashMap<String, String> {
    let pairs = [
        ("FLOMO_VLM_BASE_URL", settings.vlm_base_url.trim()),
        ("FLOMO_VLM_MODEL", settings.vlm_model.trim()),
        ("FLOMO_VLM_RETRY_MODEL", settings.vlm_retry_model.trim()),
        (
            "FLOMO_VLM_TIMEOUT_SECONDS",
            settings.vlm_timeout_seconds.trim(),
        ),
        ("FLOMO_VLM_MAX_TOKENS", settings.vlm_max_tokens.trim()),
    ];

    pairs
        .into_iter()
        .filter(|(_, value)| !value.is_empty())
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect()
}

fn write_env_file(path: &Path, updates: &HashMap<String, String>) -> Result<(), String> {
    let original = if path.exists() {
        fs::read_to_string(path).map_err(|error| format!("无法读取 .env：{error}"))?
    } else {
        String::new()
    };

    let mut seen: HashMap<String, bool> = ENV_KEYS
        .iter()
        .map(|key| ((*key).to_string(), false))
        .collect();
    let mut lines = Vec::new();

    for line in original.lines() {
        if let Some((key, _)) = parse_env_line(line) {
            if ENV_KEYS.contains(&key.as_str()) {
                if let Some(value) = updates.get(&key) {
                    lines.push(format!("{key}={value}"));
                    seen.insert(key, true);
                }
                continue;
            }
        }
        lines.push(line.to_string());
    }

    for key in ENV_KEYS {
        if !seen.get(key).copied().unwrap_or(false) {
            if let Some(value) = updates.get(key) {
                lines.push(format!("{key}={value}"));
            }
        }
    }

    let mut content = lines.join("\n");
    if !content.is_empty() {
        content.push('\n');
    }
    fs::write(path, content).map_err(|error| format!("无法写入 .env：{error}"))
}

fn validate_request(request: &WorkflowRequest) -> Result<(), String> {
    if !matches!(
        request.action.as_str(),
        "first" | "daily" | "probe" | "retry" | "import"
    ) {
        return Err("未知操作。".to_string());
    }
    if !matches!(request.provider.as_str(), "lmstudio" | "mock") {
        return Err("图片处理方式必须是 lmstudio 或 mock。".to_string());
    }
    if request.action == "probe" && request.image.as_deref().unwrap_or("").trim().is_empty() {
        return Err("探测图片需要先选择图片。".to_string());
    }
    if request.action == "retry" && request.rounds == 0 {
        return Err("重试轮数必须大于 0。".to_string());
    }
    if request.action == "import" {
        let zip = request.zip.as_deref().unwrap_or("").trim();
        if zip.is_empty() || !Path::new(zip).is_file() {
            return Err("导入前需要选择有效的 Flomo ZIP。".to_string());
        }
        if request.publish_root.trim().is_empty() {
            return Err("导入前需要设置发布目录。".to_string());
        }
    }
    Ok(())
}

fn build_sidecar_args(request: &WorkflowRequest, project_root: &Path) -> Vec<String> {
    let mut args = vec![
        "--action".to_string(),
        request.action.clone(),
        "--project-root".to_string(),
        project_root.to_string_lossy().into_owned(),
        "--env-file".to_string(),
        request.env_file.clone(),
    ];

    if matches!(
        request.action.as_str(),
        "first" | "daily" | "retry" | "import"
    ) {
        args.extend(["--provider".to_string(), request.provider.clone()]);
    }

    args.extend([
        "--raw-root".to_string(),
        request.raw_root.clone(),
        "--store-root".to_string(),
        request.store_root.clone(),
        "--monthly-root".to_string(),
        request.monthly_root.clone(),
        "--chunks-root".to_string(),
        request.chunks_root.clone(),
    ]);

    if request.action == "import" {
        if let Some(zip) = request.zip.as_ref() {
            args.extend(["--zip".to_string(), zip.clone()]);
        }
        args.extend(["--publish-root".to_string(), request.publish_root.clone()]);
    }

    if let Some(month) = request
        .month
        .as_ref()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
    {
        args.extend(["--month".to_string(), month.to_string()]);
    }

    if request.action == "probe" {
        if let Some(image) = request.image.as_ref() {
            args.extend(["--image".to_string(), image.clone()]);
        }
    }

    if request.action == "retry" {
        args.extend(["--rounds".to_string(), request.rounds.to_string()]);
    }

    args
}

#[cfg(debug_assertions)]
fn build_local_python_command(
    request: &WorkflowRequest,
    project_root: &Path,
) -> (String, Vec<String>) {
    let mut args = vec![
        "scripts/guide.py".to_string(),
        "--action".to_string(),
        request.action.clone(),
        "--env-file".to_string(),
        request.env_file.clone(),
    ];

    if matches!(
        request.action.as_str(),
        "first" | "daily" | "retry" | "import"
    ) {
        args.extend(["--provider".to_string(), request.provider.clone()]);
    }

    args.extend([
        "--raw-root".to_string(),
        request.raw_root.clone(),
        "--store-root".to_string(),
        request.store_root.clone(),
        "--monthly-root".to_string(),
        request.monthly_root.clone(),
        "--chunks-root".to_string(),
        request.chunks_root.clone(),
    ]);

    if request.action == "import" {
        if let Some(zip) = request.zip.as_ref() {
            args.extend(["--zip".to_string(), zip.clone()]);
        }
        args.extend(["--publish-root".to_string(), request.publish_root.clone()]);
    }

    if let Some(month) = request
        .month
        .as_ref()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
    {
        args.extend(["--month".to_string(), month.to_string()]);
    }

    if request.action == "probe" {
        if let Some(image) = request.image.as_ref() {
            args.extend(["--image".to_string(), image.clone()]);
        }
    }

    if request.action == "retry" {
        args.extend(["--rounds".to_string(), request.rounds.to_string()]);
    }

    let program = std::env::var("PYTHON").unwrap_or_else(|_| "python".to_string());
    let guide_path = project_root.join("scripts").join("guide.py");
    if guide_path.exists() {
        args[0] = guide_path.to_string_lossy().into_owned();
    }
    (program, args)
}

fn display_command(program: &str, args: &[String]) -> String {
    std::iter::once(program.to_string())
        .chain(args.iter().cloned())
        .map(|part| {
            if part.contains(' ') {
                format!("\"{}\"", part.replace('"', "\\\""))
            } else {
                part
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn emit_output(app: &AppHandle, task_id: &str, stream: &str, bytes: &[u8]) {
    let line = String::from_utf8_lossy(bytes).trim_end().to_string();
    let _ = app.emit(
        "workflow-output",
        WorkflowOutput {
            task_id: task_id.to_string(),
            stream: stream.to_string(),
            line,
        },
    );
}

fn finish_workflow(app: AppHandle, task_id: String, mut status: String, code: Option<i32>) {
    let state = app.state::<Mutex<WorkflowState>>();
    if let Ok(mut guarded) = state.lock() {
        if let Some(active) = &guarded.active {
            if active.task_id == task_id && active.cancelling {
                status = "cancelled".to_string();
            }
        }
        if guarded
            .active
            .as_ref()
            .is_some_and(|active| active.task_id == task_id)
        {
            guarded.active = None;
        }
    }

    let _ = app.emit(
        "workflow-completed",
        WorkflowCompleted {
            task_id,
            status,
            code,
        },
    );
}

#[cfg(debug_assertions)]
fn spawn_output_reader<R>(app: AppHandle, task_id: String, stream: &'static str, reader: R)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let buffered = BufReader::new(reader);
        for line in buffered.lines().map_while(Result::ok) {
            let _ = app.emit(
                "workflow-output",
                WorkflowOutput {
                    task_id: task_id.clone(),
                    stream: stream.to_string(),
                    line,
                },
            );
        }
    });
}

fn new_task_id() -> String {
    static TASK_COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    let counter = TASK_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    format!("workflow-{millis}-{}-{counter}", std::process::id())
}

#[cfg(debug_assertions)]
fn kill_process(pid: u32) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let status = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status();

    #[cfg(not(target_os = "windows"))]
    let status = Command::new("kill")
        .args(["-TERM", &pid.to_string()])
        .status();

    match status {
        Ok(status) if status.success() => Ok(()),
        Ok(status) => Err(format!("停止任务失败，退出码：{status}")),
        Err(error) => Err(format!("停止任务失败：{error}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_settings(env_file: &Path) -> AppSettings {
        AppSettings {
            project_root: "project".to_string(),
            env_file: env_file.to_string_lossy().into_owned(),
            raw_root: "raw".to_string(),
            store_root: "store".to_string(),
            monthly_root: "monthly".to_string(),
            chunks_root: "llm_chunks".to_string(),
            inbox_root: "flomo-inbox".to_string(),
            publish_root: "flomo-context".to_string(),
            scan_downloads: true,
            auto_import: true,
            vlm_base_url: "http://127.0.0.1:1234/v1".to_string(),
            vlm_model: "local-vlm".to_string(),
            vlm_retry_model: String::new(),
            vlm_timeout_seconds: "180".to_string(),
            vlm_max_tokens: "4096".to_string(),
            env_exists: true,
            runtime_mode: "test".to_string(),
        }
    }

    #[test]
    fn env_writer_preserves_comments_and_unrelated_values() {
        let dir = std::env::temp_dir().join(new_task_id());
        fs::create_dir_all(&dir).unwrap();
        let env_file = dir.join(".env");
        fs::write(
            &env_file,
            "# keep\nOTHER=value\nFLOMO_VLM_MODEL=old\nFLOMO_VLM_RETRY_MODEL=old-retry\n",
        )
        .unwrap();

        let updates = env_updates_from_settings(&sample_settings(&env_file));
        write_env_file(&env_file, &updates).unwrap();
        let content = fs::read_to_string(&env_file).unwrap();

        assert!(content.contains("# keep"));
        assert!(content.contains("OTHER=value"));
        assert!(content.contains("FLOMO_VLM_MODEL=local-vlm"));
        assert!(!content.contains("old-retry"));
    }

    #[test]
    fn gui_path_settings_round_trip_persists_folder_paths() {
        let dir = std::env::temp_dir().join(new_task_id());
        fs::create_dir_all(&dir).unwrap();
        let settings_file = gui_settings_path(&dir);
        let mut settings = sample_settings(&dir.join(".env"));
        settings.raw_root = "D:/Flomo/raw".to_string();
        settings.store_root = "D:/Flomo/store".to_string();
        settings.monthly_root = "D:/Flomo/monthly".to_string();
        settings.chunks_root = "D:/Flomo/chunks".to_string();
        settings.inbox_root = "D:/Flomo/inbox".to_string();
        settings.publish_root = "D:/Flomo/context".to_string();
        settings.scan_downloads = false;

        write_gui_path_settings(&settings_file, &settings).unwrap();
        let content = fs::read_to_string(&settings_file).unwrap();
        let stored = read_gui_path_settings(&settings_file).unwrap();

        assert!(content.contains("\"raw_root\": \"D:/Flomo/raw\""));
        assert!(!content.contains("vlm_model"));
        assert_eq!(stored.raw_root.as_deref(), Some("D:/Flomo/raw"));
        assert_eq!(stored.store_root.as_deref(), Some("D:/Flomo/store"));
        assert_eq!(stored.inbox_root.as_deref(), Some("D:/Flomo/inbox"));
        assert_eq!(stored.publish_root.as_deref(), Some("D:/Flomo/context"));
        assert_eq!(stored.scan_downloads, Some(false));
        assert_eq!(
            setting_path_or_default(stored.monthly_root, PathBuf::from("monthly")),
            "D:/Flomo/monthly"
        );
    }

    #[test]
    fn gui_path_settings_omits_empty_paths_and_uses_defaults() {
        let dir = std::env::temp_dir().join(new_task_id());
        fs::create_dir_all(&dir).unwrap();
        let settings_file = gui_settings_path(&dir);
        let mut settings = sample_settings(&dir.join(".env"));
        settings.raw_root = "   ".to_string();

        write_gui_path_settings(&settings_file, &settings).unwrap();
        let content = fs::read_to_string(&settings_file).unwrap();
        let stored = read_gui_path_settings(&settings_file).unwrap();

        assert!(!content.contains("raw_root"));
        assert_eq!(
            setting_path_or_default(stored.raw_root, PathBuf::from("fallback")),
            "fallback"
        );
    }

    #[test]
    fn command_builder_maps_main_actions_to_guide() {
        let request = WorkflowRequest {
            action: "first".to_string(),
            provider: "mock".to_string(),
            month: Some("2026-05".to_string()),
            raw_root: "raw".to_string(),
            store_root: "store".to_string(),
            monthly_root: "monthly".to_string(),
            chunks_root: "llm_chunks".to_string(),
            publish_root: "flomo-context".to_string(),
            env_file: ".env".to_string(),
            image: None,
            zip: None,
            rounds: 3,
        };

        let args = build_sidecar_args(&request, Path::new("project"));
        assert!(has_arg_pair(&args, "--action", "first"));
        assert!(has_arg_pair(&args, "--provider", "mock"));
        assert!(has_arg_pair(&args, "--month", "2026-05"));
    }

    #[test]
    fn command_builder_maps_probe_image() {
        let request = WorkflowRequest {
            action: "probe".to_string(),
            provider: "lmstudio".to_string(),
            month: None,
            raw_root: "raw".to_string(),
            store_root: "store".to_string(),
            monthly_root: "monthly".to_string(),
            chunks_root: "llm_chunks".to_string(),
            publish_root: "flomo-context".to_string(),
            env_file: ".env".to_string(),
            image: Some("store/images/example.png".to_string()),
            zip: None,
            rounds: 3,
        };

        let args = build_sidecar_args(&request, Path::new("project"));
        assert!(has_arg_pair(&args, "--action", "probe"));
        assert!(has_arg_pair(&args, "--image", "store/images/example.png"));
        assert!(!args.iter().any(|arg| arg == "--provider"));
    }

    #[test]
    fn command_builder_maps_import_zip_and_publish_root() {
        let request = WorkflowRequest {
            action: "import".to_string(),
            provider: "lmstudio".to_string(),
            month: None,
            raw_root: "raw".to_string(),
            store_root: "store".to_string(),
            monthly_root: "monthly".to_string(),
            chunks_root: "llm_chunks".to_string(),
            publish_root: "flomo-context".to_string(),
            env_file: ".env".to_string(),
            image: None,
            zip: Some("flomo-inbox/flomo-export.zip".to_string()),
            rounds: 3,
        };

        let args = build_sidecar_args(&request, Path::new("project"));
        assert!(has_arg_pair(&args, "--action", "import"));
        assert!(has_arg_pair(&args, "--zip", "flomo-inbox/flomo-export.zip"));
        assert!(has_arg_pair(&args, "--publish-root", "flomo-context"));
        assert!(has_arg_pair(&args, "--provider", "lmstudio"));
    }

    #[test]
    fn zip_readiness_rejects_partial_and_accepts_empty_archive() {
        let dir = std::env::temp_dir().join(new_task_id());
        fs::create_dir_all(&dir).unwrap();
        let partial = dir.join("flomo-partial.zip");
        fs::write(&partial, b"PK\x03\x04unfinished").unwrap();
        assert!(!zip_directory_is_readable(&partial));

        let complete = dir.join("flomo-complete.zip");
        fs::write(
            &complete,
            [
                0x50, 0x4b, 0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            ],
        )
        .unwrap();
        assert!(zip_directory_is_readable(&complete));
    }

    #[test]
    fn inbox_filter_and_two_scan_stability_match_import_contract() {
        assert!(looks_like_flomo_zip(Path::new(
            "flomo@ExampleUser-20260817.zip"
        )));
        assert!(looks_like_flomo_zip(Path::new(
            "flomo@ExampleUser-20260817-deadbeef.zip"
        )));
        assert!(!looks_like_flomo_zip(Path::new("notes-20260817.zip")));

        let previous = FileObservation {
            size: 42,
            modified_millis: 100,
        };
        assert!(observation_is_unchanged(Some(&previous), 42, 100));
        assert!(!observation_is_unchanged(Some(&previous), 43, 100));
        assert!(!observation_is_unchanged(None, 42, 100));
    }

    #[test]
    fn import_status_keeps_image_failure_reasons() {
        let value = serde_json::json!({
            "imports": [{
                "original_filename": "flomo@ExampleUser-20260817.zip",
                "status": "published",
                "failed_images": 1,
                "image_failures": [{
                    "image_id": "image-1",
                    "month": "2026-08",
                    "error_message": "model response was truncated"
                }]
            }]
        });
        let entries = import_entries_from_json(&value);

        assert_eq!(entries[0].failed_images, 1);
        assert_eq!(entries[0].image_failures[0].month, "2026-08");
        assert_eq!(
            entries[0].image_failures[0].error_message,
            "model response was truncated"
        );
    }

    fn has_arg_pair(args: &[String], key: &str, value: &str) -> bool {
        args.windows(2)
            .any(|pair| pair[0] == key && pair[1] == value)
    }
}
