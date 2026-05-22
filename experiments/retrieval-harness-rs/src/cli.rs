use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};

use crate::baseline::{parse_mode, run_baseline_case};
use crate::config::AppConfig;
use crate::orchestrator::{preview_for_case, run_harness_case};
use crate::report::{summarize_cases, summarize_runs};
use crate::types::{BaselineMode, CaseComparison, EvalCase, HarnessSuiteRun};

const DEFAULT_CONFIG_PATH: &str = "experiments/retrieval-harness-rs/config/default.toml";
const BASELINE_HELPER_PATH: &str = "experiments/retrieval-harness-rs/python/run_baseline.py";

#[derive(Parser, Debug)]
#[command(name = "retrieval-harness")]
#[command(about = "Experimental retrieval harness for LightRAG baseline evaluation")]
struct Cli {
    #[arg(long, default_value = DEFAULT_CONFIG_PATH)]
    config: PathBuf,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    InspectConfig,
    ListCases {
        #[arg(long)]
        cases: Option<PathBuf>,
    },
    RunBaseline {
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        mode: String,
    },
    RunAllBaselines {
        #[arg(long)]
        cases: Option<PathBuf>,
    },
    PreviewHarness {
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        case_id: Option<String>,
    },
    RunHarness {
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        case_id: String,
    },
    RunHarnessSuite {
        #[arg(long)]
        cases: Option<PathBuf>,
        #[arg(long)]
        baseline_modes: Option<String>,
        #[arg(long)]
        output: Option<PathBuf>,
    },
}

pub async fn run() -> Result<()> {
    let cli = Cli::parse();
    let config = AppConfig::load(&cli.config)?;

    match cli.command {
        Commands::InspectConfig => {
            println!("{}", serde_json::to_string_pretty(&config)?);
        }
        Commands::ListCases { cases } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let summaries = summarize_cases(&cases);
            println!("{}", serde_json::to_string_pretty(&summaries)?);
        }
        Commands::RunBaseline { cases, mode } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let mode = parse_mode(&mode)?;
            let helper = config.paths.repo_root.join(BASELINE_HELPER_PATH);
            let first_case = cases
                .first()
                .context("run-baseline requires at least one eval case")?;
            let result = run_baseline_case(&config, first_case, mode, &helper).await?;
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        Commands::RunAllBaselines { cases } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let helper = config.paths.repo_root.join(BASELINE_HELPER_PATH);
            let mut runs = Vec::new();
            for case in &cases {
                for mode in BaselineMode::all() {
                    runs.push(run_baseline_case(&config, case, mode, &helper).await?);
                }
            }
            println!("{}", serde_json::to_string_pretty(&runs)?);
            eprintln!("{}", serde_json::to_string_pretty(&summarize_runs(&runs))?);
        }
        Commands::PreviewHarness { cases, case_id } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let previews = build_previews(&cases, case_id.as_deref())?;
            println!("{}", serde_json::to_string_pretty(&previews)?);
        }
        Commands::RunHarness { cases, case_id } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let case = cases
                .iter()
                .find(|case| case.id == case_id)
                .with_context(|| format!("case_id not found: {case_id}"))?;
            let run = run_harness_case(&config, case).await?;
            println!("{}", serde_json::to_string_pretty(&run)?);
        }
        Commands::RunHarnessSuite {
            cases,
            baseline_modes,
            output,
        } => {
            let cases = load_cases(resolve_cases_path(cases, &config))?;
            let suite = run_harness_suite(
                &config,
                &cases,
                baseline_modes.as_deref(),
                output.as_deref(),
            )
            .await?;
            println!("{}", serde_json::to_string_pretty(&suite)?);
        }
    }

    Ok(())
}

fn resolve_cases_path(cases: Option<PathBuf>, config: &AppConfig) -> PathBuf {
    cases.unwrap_or_else(|| config.paths.default_cases.clone())
}

fn load_cases(path: PathBuf) -> Result<Vec<EvalCase>> {
    let raw = fs::read_to_string(&path)
        .with_context(|| format!("failed to read cases file {}", path.display()))?;
    let cases: Vec<EvalCase> =
        serde_json::from_str(&raw).context("failed to parse eval cases JSON")?;
    Ok(cases)
}

fn build_previews(cases: &[EvalCase], case_id: Option<&str>) -> Result<Vec<crate::types::OrchestratorPreview>> {
    if let Some(case_id) = case_id {
        let case = cases
            .iter()
            .find(|case| case.id == case_id)
            .with_context(|| format!("case_id not found: {case_id}"))?;
        return Ok(vec![preview_for_case(case)]);
    }
    Ok(cases.iter().map(preview_for_case).collect())
}

async fn run_harness_suite(
    config: &AppConfig,
    cases: &[EvalCase],
    baseline_modes_override: Option<&str>,
    output_path: Option<&Path>,
) -> Result<HarnessSuiteRun> {
    let helper = config.paths.repo_root.join(BASELINE_HELPER_PATH);
    let baseline_modes = match baseline_modes_override {
        Some(raw) => parse_mode_list(raw)?,
        None => config.baseline_modes()?,
    };
    let mut comparisons = Vec::new();
    let mut harness_successes = 0usize;
    let mut baseline_successes = 0usize;
    let mut baseline_failures = 0usize;
    let mut output_file = prepare_output_file(output_path)?;

    for (index, case) in cases.iter().enumerate() {
        let harness = run_harness_case(config, case).await?;
        if harness.final_answer_result.is_some() || harness.retrieve_context_result.is_some() {
            harness_successes += 1;
        }

        let mut baselines = Vec::new();
        for mode in &baseline_modes {
            let run = run_baseline_case(config, case, mode.clone(), &helper).await?;
            if matches!(run.status, crate::types::BaselineRunStatus::Success) {
                baseline_successes += 1;
            } else {
                baseline_failures += 1;
            }
            baselines.push(run);
        }

        let comparison = CaseComparison {
            case_id: case.id.clone(),
            question: case.question.clone(),
            harness,
            baselines,
        };

        write_case_result(output_file.as_mut(), &comparison)?;
        print_case_summary(index + 1, cases.len(), &comparison);

        comparisons.push(comparison);
    }

    Ok(HarnessSuiteRun {
        total_cases: cases.len(),
        cases: comparisons,
        harness_successes,
        baseline_successes,
        baseline_failures,
    })
}

fn prepare_output_file(output_path: Option<&Path>) -> Result<Option<fs::File>> {
    let Some(output_path) = output_path else {
        return Ok(None);
    };
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create output dir {}", parent.display()))?;
    }
    let file = fs::File::create(output_path)
        .with_context(|| format!("failed to create output file {}", output_path.display()))?;
    Ok(Some(file))
}

fn write_case_result(file: Option<&mut fs::File>, comparison: &CaseComparison) -> Result<()> {
    let Some(file) = file else {
        return Ok(());
    };
    serde_json::to_writer(&mut *file, comparison).context("failed to write case result json")?;
    file.write_all(b"\n")
        .context("failed to append newline to case result")?;
    file.flush().context("failed to flush case result output")?;
    Ok(())
}

fn print_case_summary(index: usize, total: usize, comparison: &CaseComparison) {
    let harness_status = if comparison.harness.final_answer_result.is_some()
        || comparison.harness.retrieve_context_result.is_some()
    {
        "ok"
    } else {
        "fail"
    };

    let baseline_bits: Vec<String> = comparison
        .baselines
        .iter()
        .map(|run| {
            let status = match run.status {
                crate::types::BaselineRunStatus::Success => "ok".to_string(),
                crate::types::BaselineRunStatus::Failure => format!(
                    "fail:{}",
                    run.failure_kind
                        .as_ref()
                        .map(|kind| format!("{kind:?}"))
                        .unwrap_or_else(|| "Unknown".to_string())
                ),
            };
            format!("{}={}", run.mode.as_str(), status)
        })
        .collect();

    eprintln!(
        "[{}/{}] {} harness={} baselines=[{}]",
        index,
        total,
        comparison.case_id,
        harness_status,
        baseline_bits.join(", ")
    );
}

fn parse_mode_list(raw: &str) -> Result<Vec<BaselineMode>> {
    raw.split(',')
        .map(|item| parse_mode(item.trim()))
        .collect()
}

#[allow(dead_code)]
fn _normalize_path(path: &Path) -> PathBuf {
    path.to_path_buf()
}
