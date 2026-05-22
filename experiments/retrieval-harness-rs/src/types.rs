use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum QuestionType {
    EntityFact,
    RelationQuery,
    MultiHopRelation,
    OpenExploration,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvalCase {
    pub id: String,
    pub question: String,
    pub question_type: QuestionType,
    pub subject_hint: Option<String>,
    #[serde(default)]
    pub related_hints: Vec<String>,
    pub expected_answer: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BaselineMode {
    #[serde(rename = "local")]
    Local,
    #[serde(rename = "global")]
    Global,
    #[serde(rename = "hybrid")]
    Hybrid,
    #[serde(rename = "naive")]
    Naive,
    #[serde(rename = "mix")]
    Mix,
}

impl BaselineMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Global => "global",
            Self::Hybrid => "hybrid",
            Self::Naive => "naive",
            Self::Mix => "mix",
        }
    }

    pub fn all() -> Vec<Self> {
        vec![
            Self::Local,
            Self::Global,
            Self::Hybrid,
            Self::Naive,
            Self::Mix,
        ]
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BaselineRunStatus {
    Success,
    Failure,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum BaselineFailureKind {
    ProcessSpawn,
    InvalidUtf8,
    InvalidJson,
    UpstreamLlm,
    UpstreamEmbedding,
    HelperRuntime,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BaselineRun {
    pub case_id: String,
    pub mode: BaselineMode,
    pub status: BaselineRunStatus,
    pub answer_text: Option<String>,
    pub raw_json: Option<serde_json::Value>,
    pub failure_kind: Option<BaselineFailureKind>,
    pub stderr: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ToolName {
    SearchEntities,
    SearchRelationships,
    SearchChunks,
    ExpandNeighbors,
    RetrieveContext,
    Plan,
    Trace,
    Ask,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievalPolicy {
    pub allowed_tools: Vec<ToolName>,
    pub max_parallel_agents: usize,
    pub max_steps_per_agent: usize,
    pub entity_top_k: usize,
    pub relationship_top_k: usize,
    pub chunk_top_k: usize,
    pub max_depth: usize,
    pub enable_second_round: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EvidenceSufficiency {
    Empty,
    Partial,
    Sufficient,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceBundle {
    pub entities: Vec<String>,
    pub relationships: Vec<String>,
    pub chunks: Vec<String>,
    pub references: Vec<String>,
    pub source_agents: Vec<String>,
    pub sufficiency: EvidenceSufficiency,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExplorerRole {
    EntityExplorer,
    RelationExplorer,
    ChunkExplorer,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentBudget {
    pub max_steps: usize,
    pub timeout_seconds: u64,
    pub top_k: usize,
    pub max_depth: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubagentTask {
    pub case_id: String,
    pub role: ExplorerRole,
    pub objective: String,
    pub allowed_tools: Vec<ToolName>,
    pub budget: AgentBudget,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AgentStatus {
    Ready,
    Success,
    Failure,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallRecord {
    pub tool: ToolName,
    pub note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntityHit {
    pub value: String,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelationHit {
    pub value: String,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkHit {
    pub value: String,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubagentResult {
    pub role: ExplorerRole,
    pub status: AgentStatus,
    pub tool_calls: Vec<ToolCallRecord>,
    pub entity_hits: Vec<EntityHit>,
    pub relationship_hits: Vec<RelationHit>,
    pub chunk_hits: Vec<ChunkHit>,
    pub summary: String,
    pub confidence: f32,
    pub should_continue: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorPreview {
    pub case_id: String,
    pub question_type: QuestionType,
    pub allowed_tools: Vec<ToolName>,
    pub max_parallel_agents: usize,
    pub max_steps_per_agent: usize,
    pub entity_top_k: usize,
    pub relationship_top_k: usize,
    pub chunk_top_k: usize,
    pub max_depth: usize,
    pub enable_second_round: bool,
    pub planned_tasks: Vec<SubagentTask>,
    pub seeded_results: Vec<SubagentResult>,
    pub initial_evidence: EvidenceBundle,
    pub merged_evidence: EvidenceBundle,
    pub next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarnessRun {
    pub case_id: String,
    pub planned_tasks: Vec<SubagentTask>,
    pub explorer_results: Vec<SubagentResult>,
    pub merged_evidence: EvidenceBundle,
    pub next_action: String,
    pub retrieve_context_result: Option<serde_json::Value>,
    pub final_answer_result: Option<serde_json::Value>,
    pub final_answer_text: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseComparison {
    pub case_id: String,
    pub question: String,
    pub harness: HarnessRun,
    pub baselines: Vec<BaselineRun>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarnessSuiteRun {
    pub total_cases: usize,
    pub cases: Vec<CaseComparison>,
    pub harness_successes: usize,
    pub baseline_successes: usize,
    pub baseline_failures: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaseSummary {
    pub id: String,
    pub question_type: QuestionType,
    pub question: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunSummary {
    pub total_cases: usize,
    pub total_runs: usize,
    pub successes: usize,
    pub failures: usize,
}
