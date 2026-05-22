use crate::types::{BaselineRun, CaseSummary, EvalCase, RunSummary};

pub fn summarize_cases(cases: &[EvalCase]) -> Vec<CaseSummary> {
    cases.iter()
        .map(|case| CaseSummary {
            id: case.id.clone(),
            question_type: case.question_type.clone(),
            question: case.question.clone(),
        })
        .collect()
}

pub fn summarize_runs(runs: &[BaselineRun]) -> RunSummary {
    let successes = runs
        .iter()
        .filter(|run| matches!(run.status, crate::types::BaselineRunStatus::Success))
        .count();
    let failures = runs.len().saturating_sub(successes);
    RunSummary {
        total_cases: runs.len(),
        total_runs: runs.len(),
        successes,
        failures,
    }
}
