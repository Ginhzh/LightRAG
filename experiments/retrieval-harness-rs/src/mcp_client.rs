use std::path::Path;
use std::process::Stdio;

use anyhow::{Context, Result};
use tokio::process::Command;

use crate::config::AppConfig;
use crate::types::ToolName;

pub async fn call_mcp_tool(
    config: &AppConfig,
    helper_path: &Path,
    tool: ToolName,
    payload: serde_json::Value,
) -> Result<serde_json::Value> {
    let mut command = Command::new(&config.python.runner);
    command
        .args(&config.python.python_args)
        .arg(helper_path)
        .arg("--tool")
        .arg(tool_name(&tool))
        .arg("--payload")
        .arg(payload.to_string())
        .current_dir(&config.paths.repo_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = command
        .output()
        .await
        .with_context(|| format!("failed to spawn MCP helper for tool {}", tool_name(&tool)))?;

    if output.status.success() {
        let stdout = String::from_utf8(output.stdout).context("mcp helper stdout is not utf-8")?;
        let value: serde_json::Value =
            serde_json::from_str(&stdout).context("mcp helper stdout is not valid json")?;
        Ok(value)
    } else {
        let stderr = String::from_utf8(output.stderr).unwrap_or_else(|_| String::new());
        Err(anyhow::anyhow!(
            "mcp helper failed for tool {}: {}",
            tool_name(&tool),
            stderr
        ))
    }
}

fn tool_name(tool: &ToolName) -> &'static str {
    match tool {
        ToolName::SearchEntities => "graphrag_search_entities",
        ToolName::SearchRelationships => "graphrag_search_relationships",
        ToolName::SearchChunks => "graphrag_search_chunks",
        ToolName::ExpandNeighbors => "graphrag_expand_neighbors",
        ToolName::RetrieveContext => "graphrag_retrieve_context",
        ToolName::Plan => "graphrag_plan",
        ToolName::Trace => "graphrag_trace",
        ToolName::Ask => "graphrag_ask",
    }
}
