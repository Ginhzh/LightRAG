use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::types::BaselineMode;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PythonConfig {
    pub runner: String,
    pub python_args: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathsConfig {
    pub repo_root: PathBuf,
    pub default_cases: PathBuf,
    pub mcp_helper: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BaselineConfig {
    pub modes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub python: PythonConfig,
    pub paths: PathsConfig,
    pub baseline: BaselineConfig,
}

impl AppConfig {
    pub fn load(config_path: &Path) -> Result<Self> {
        let raw = fs::read_to_string(config_path)
            .with_context(|| format!("failed to read config file {}", config_path.display()))?;
        let mut config: AppConfig =
            toml::from_str(&raw).context("failed to parse config TOML")?;

        let config_dir = config_path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from("."));

        if config.paths.repo_root.is_relative() {
            config.paths.repo_root = config_dir.join(&config.paths.repo_root);
        }
        if config.paths.default_cases.is_relative() {
            config.paths.default_cases = config_dir.join(&config.paths.default_cases);
        }
        if config.paths.mcp_helper.is_relative() {
            config.paths.mcp_helper = config_dir.join(&config.paths.mcp_helper);
        }
        Ok(config)
    }

    pub fn baseline_modes(&self) -> Result<Vec<BaselineMode>> {
        self.baseline
            .modes
            .iter()
            .map(|mode| match mode.as_str() {
                "local" => Ok(BaselineMode::Local),
                "global" => Ok(BaselineMode::Global),
                "hybrid" => Ok(BaselineMode::Hybrid),
                "naive" => Ok(BaselineMode::Naive),
                "mix" => Ok(BaselineMode::Mix),
                _ => anyhow::bail!("unsupported baseline mode in config: {}", mode),
            })
            .collect()
    }
}
