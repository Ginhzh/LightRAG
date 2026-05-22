use std::path::Path;
use std::process::Stdio;

use anyhow::{anyhow, Context, Result};
use tokio::process::Command;

use crate::config::AppConfig;
use crate::types::{BaselineFailureKind, BaselineMode, BaselineRun, BaselineRunStatus, EvalCase};

pub async fn run_baseline_case(
    config: &AppConfig,
    case: &EvalCase,
    mode: BaselineMode,
    helper_path: &Path,
) -> Result<BaselineRun> {
    let mut command = Command::new(&config.python.runner);
    command
        .args(&config.python.python_args)
        .arg(helper_path)
        .arg("--question")
        .arg(&case.question)
        .arg("--mode")
        .arg(mode.as_str())
        .current_dir(&config.paths.repo_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = command
        .output()
        .await
        .with_context(|| format!("failed to spawn baseline helper for {}", case.id))?;

    if output.status.success() {
        let stdout = match String::from_utf8(output.stdout) {
            Ok(stdout) => stdout,
            Err(_) => {
                return Ok(BaselineRun {
                    case_id: case.id.clone(),
                    mode,
                    status: BaselineRunStatus::Failure,
                    answer_text: None,
                    raw_json: None,
                    failure_kind: Some(BaselineFailureKind::InvalidUtf8),
                    stderr: Some("baseline stdout is not utf-8".to_string()),
                })
            }
        };
        let raw_json: serde_json::Value = match serde_json::from_str(&stdout) {
            Ok(raw_json) => raw_json,
            Err(_) => {
                return Ok(BaselineRun {
                    case_id: case.id.clone(),
                    mode,
                    status: BaselineRunStatus::Failure,
                    answer_text: None,
                    raw_json: None,
                    failure_kind: Some(BaselineFailureKind::InvalidJson),
                    stderr: Some(stdout),
                })
            }
        };
        let answer_text = extract_answer_text(&raw_json);
        Ok(BaselineRun {
            case_id: case.id.clone(),
            mode,
            status: BaselineRunStatus::Success,
            answer_text,
            raw_json: Some(raw_json),
            failure_kind: None,
            stderr: None,
        })
    } else {
        let stderr = String::from_utf8(output.stderr).unwrap_or_else(|_| String::new());
        let failure_kind = classify_failure(&stderr);
        Ok(BaselineRun {
            case_id: case.id.clone(),
            mode,
            status: BaselineRunStatus::Failure,
            answer_text: None,
            raw_json: None,
            failure_kind: Some(failure_kind),
            stderr: Some(stderr),
        })
    }
}

pub fn extract_answer_text(raw_json: &serde_json::Value) -> Option<String> {
    let paths = [
        &["response"][..],
        &["answer"][..],
        &["content"][..],
        &["result"][..],
        &["response", "content"][..],
        &["llm_response", "content"][..],
        &["data", "response"][..],
        &["data", "answer"][..],
        &["data", "content"][..],
        &["data", "result"][..],
        &["data", "llm_response", "content"][..],
    ];

    paths
        .iter()
        .find_map(|path| value_at_path(raw_json, path).and_then(|value| value.as_str()))
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_string)
}

pub fn parse_mode(raw: &str) -> Result<BaselineMode> {
    match raw {
        "local" => Ok(BaselineMode::Local),
        "global" => Ok(BaselineMode::Global),
        "hybrid" => Ok(BaselineMode::Hybrid),
        "naive" => Ok(BaselineMode::Naive),
        "mix" => Ok(BaselineMode::Mix),
        _ => Err(anyhow!("unsupported baseline mode: {raw}")),
    }
}

fn classify_failure(stderr: &str) -> BaselineFailureKind {
    let lower = stderr.to_lowercase();
    if lower.contains("service is too busy")
        || lower.contains("/chat/completions")
        || lower.contains("service_unavailable_error")
    {
        return BaselineFailureKind::UpstreamLlm;
    }
    if lower.contains("/embeddings") || lower.contains("embedding func") {
        return BaselineFailureKind::UpstreamEmbedding;
    }
    if lower.contains("traceback")
        || lower.contains("runtimeerror")
        || lower.contains("exception")
        || lower.contains("error:")
    {
        return BaselineFailureKind::HelperRuntime;
    }
    BaselineFailureKind::Unknown
}

fn value_at_path<'a>(value: &'a serde_json::Value, path: &[&str]) -> Option<&'a serde_json::Value> {
    path.iter().try_fold(value, |current, key| current.get(key))
}

#[cfg(test)]
mod tests {
    use super::extract_answer_text;

    #[test]
    fn extracts_llm_content_from_structured_lightrag_response() {
        let raw = serde_json::json!({
            "status": "success",
            "data": {
                "entities": [{"entity_name": "克莱恩"}],
                "relationships": [{"src_id": "克莱恩", "tgt_id": "洛根"}],
                "chunks": [{"content": "结构化上下文，不应作为答案整体输出。"}]
            },
            "llm_response": {
                "content": "克莱恩识破洛根骗局，并用格尔曼人设反制。",
                "response_iterator": null,
                "is_streaming": false
            }
        });

        assert_eq!(
            extract_answer_text(&raw).as_deref(),
            Some("克莱恩识破洛根骗局，并用格尔曼人设反制。")
        );
    }

    #[test]
    fn extracts_nested_mcp_ask_answer_text() {
        let raw = serde_json::json!({
            "status": "success",
            "data": {
                "status": "success",
                "llm_response": {
                    "content": "嵌套 MCP ask 答案。"
                }
            }
        });

        assert_eq!(
            extract_answer_text(&raw).as_deref(),
            Some("嵌套 MCP ask 答案。")
        );
    }
}
