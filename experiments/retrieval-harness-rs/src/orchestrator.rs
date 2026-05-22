use std::collections::HashSet;

use crate::baseline::extract_answer_text;
use crate::config::AppConfig;
use crate::evidence::{empty_bundle, evaluate_sufficiency, merge_results};
use crate::mcp_client::call_mcp_tool;
use crate::policy::build_policy;
use crate::types::{
    AgentBudget, AgentStatus, ChunkHit, EntityHit, EvalCase, ExplorerRole, HarnessRun,
    OrchestratorPreview, RelationHit, SubagentResult, SubagentTask, ToolCallRecord, ToolName,
};

pub fn preview_for_case(case: &EvalCase) -> OrchestratorPreview {
    let policy = build_policy(&case.question_type);
    let mut initial_bundle = empty_bundle();
    initial_bundle.sufficiency = evaluate_sufficiency(&initial_bundle);
    let planned_tasks = build_tasks(case, &policy);
    let seeded_results = seed_results(case, &planned_tasks);
    let merged_evidence = merge_results(&seeded_results);
    let next_action = match merged_evidence.sufficiency {
        crate::types::EvidenceSufficiency::Sufficient => "retrieve_context_then_answer",
        crate::types::EvidenceSufficiency::Partial if policy.enable_second_round => {
            "second_round_exploration"
        }
        crate::types::EvidenceSufficiency::Partial => "stop_partial_evidence",
        crate::types::EvidenceSufficiency::Empty => "stop_no_evidence",
    }
    .to_string();

    OrchestratorPreview {
        case_id: case.id.clone(),
        question_type: case.question_type.clone(),
        allowed_tools: policy.allowed_tools.clone(),
        max_parallel_agents: policy.max_parallel_agents,
        max_steps_per_agent: policy.max_steps_per_agent,
        entity_top_k: policy.entity_top_k,
        relationship_top_k: policy.relationship_top_k,
        chunk_top_k: policy.chunk_top_k,
        max_depth: policy.max_depth,
        enable_second_round: policy.enable_second_round,
        planned_tasks,
        seeded_results,
        initial_evidence: initial_bundle,
        merged_evidence,
        next_action,
    }
}

pub async fn run_harness_case(config: &AppConfig, case: &EvalCase) -> anyhow::Result<HarnessRun> {
    let policy = build_policy(&case.question_type);
    let planned_tasks = build_tasks(case, &policy);
    let entity_task = planned_tasks
        .iter()
        .find(|task| matches!(task.role, ExplorerRole::EntityExplorer))
        .expect("entity task should exist");
    let relation_task = planned_tasks
        .iter()
        .find(|task| matches!(task.role, ExplorerRole::RelationExplorer))
        .expect("relation task should exist");
    let chunk_task = planned_tasks
        .iter()
        .find(|task| matches!(task.role, ExplorerRole::ChunkExplorer))
        .expect("chunk task should exist");

    let (entity_result, relation_result, chunk_result) = tokio::try_join!(
        run_task(config, entity_task, case),
        run_task(config, relation_task, case),
        run_task(config, chunk_task, case),
    )?;

    let explorer_results = vec![entity_result, relation_result, chunk_result];

    let merged_evidence = merge_results(&explorer_results);
    let next_action = match merged_evidence.sufficiency {
        crate::types::EvidenceSufficiency::Sufficient => "retrieve_context_then_answer",
        crate::types::EvidenceSufficiency::Partial if policy.enable_second_round => {
            "second_round_exploration"
        }
        crate::types::EvidenceSufficiency::Partial => "stop_partial_evidence",
        crate::types::EvidenceSufficiency::Empty => "stop_no_evidence",
    }
    .to_string();

    let retrieve_context_result = if next_action == "retrieve_context_then_answer" {
        Some(
            call_mcp_tool(
                config,
                &config.paths.mcp_helper,
                ToolName::RetrieveContext,
                serde_json::json!({ "query": case.question }),
            )
            .await?,
        )
    } else {
        None
    };

    let final_answer_result = if next_action == "retrieve_context_then_answer" {
        Some(
            call_mcp_tool(
                config,
                &config.paths.mcp_helper,
                ToolName::Ask,
                serde_json::json!({
                    "query": case.question,
                    "options": {
                        "mode": "mix",
                        "top_k": policy.entity_top_k.max(policy.relationship_top_k).max(5),
                        "chunk_top_k": policy.chunk_top_k.max(5),
                        "stream": false
                    }
                }),
            )
            .await?,
        )
    } else {
        None
    };
    let final_answer_text = final_answer_result.as_ref().and_then(extract_answer_text);

    Ok(HarnessRun {
        case_id: case.id.clone(),
        planned_tasks,
        explorer_results,
        merged_evidence,
        next_action: if final_answer_result.is_some() {
            "answered".to_string()
        } else {
            next_action
        },
        retrieve_context_result,
        final_answer_result,
        final_answer_text,
    })
}

fn build_tasks(case: &EvalCase, policy: &crate::types::RetrievalPolicy) -> Vec<SubagentTask> {
    vec![
        SubagentTask {
            case_id: case.id.clone(),
            role: ExplorerRole::EntityExplorer,
            objective: format!("Find core entities for question: {}", case.question),
            allowed_tools: vec![ToolName::SearchEntities],
            budget: AgentBudget {
                max_steps: policy.max_steps_per_agent,
                timeout_seconds: 30,
                top_k: policy.entity_top_k,
                max_depth: 0,
            },
        },
        SubagentTask {
            case_id: case.id.clone(),
            role: ExplorerRole::RelationExplorer,
            objective: format!("Find key relationships for question: {}", case.question),
            allowed_tools: if policy.max_depth > 0 {
                vec![ToolName::SearchRelationships, ToolName::ExpandNeighbors]
            } else {
                vec![ToolName::SearchRelationships]
            },
            budget: AgentBudget {
                max_steps: policy.max_steps_per_agent,
                timeout_seconds: 30,
                top_k: policy.relationship_top_k.max(1),
                max_depth: policy.max_depth,
            },
        },
        SubagentTask {
            case_id: case.id.clone(),
            role: ExplorerRole::ChunkExplorer,
            objective: format!("Find supporting chunks for question: {}", case.question),
            allowed_tools: vec![ToolName::SearchChunks],
            budget: AgentBudget {
                max_steps: policy.max_steps_per_agent,
                timeout_seconds: 30,
                top_k: policy.chunk_top_k,
                max_depth: 0,
            },
        },
    ]
}

fn seed_results(case: &EvalCase, tasks: &[SubagentTask]) -> Vec<SubagentResult> {
    let subject = case
        .subject_hint
        .clone()
        .unwrap_or_else(|| "unknown-subject".to_string());
    let relation_hits = relation_preview_hits(case, &subject);

    tasks
        .iter()
        .map(|task| match task.role {
            ExplorerRole::EntityExplorer => SubagentResult {
                role: ExplorerRole::EntityExplorer,
                status: AgentStatus::Success,
                tool_calls: vec![ToolCallRecord {
                    tool: ToolName::SearchEntities,
                    note: "seeded preview hit from subject_hint".to_string(),
                }],
                entity_hits: vec![EntityHit {
                    value: subject.clone(),
                    source: "subject_hint".to_string(),
                }],
                relationship_hits: vec![],
                chunk_hits: vec![],
                summary: format!("Entity explorer would start from subject `{subject}`"),
                confidence: 0.5,
                should_continue: false,
            },
            ExplorerRole::RelationExplorer => {
                let mut tool_calls: Vec<ToolCallRecord> = relation_hits
                    .iter()
                    .map(|hit| ToolCallRecord {
                        tool: ToolName::SearchRelationships,
                        note: format!("preview relation query for {}", hit.source),
                    })
                    .collect();
                if task
                    .allowed_tools
                    .iter()
                    .any(|tool| matches!(tool, ToolName::ExpandNeighbors))
                {
                    tool_calls.push(ToolCallRecord {
                        tool: ToolName::ExpandNeighbors,
                        note: "preview allows neighbor expansion".to_string(),
                    });
                }
                SubagentResult {
                    role: ExplorerRole::RelationExplorer,
                    status: AgentStatus::Success,
                    tool_calls,
                    entity_hits: vec![],
                    relationship_hits: relation_hits.clone(),
                    chunk_hits: vec![],
                    summary: format!(
                        "Relation explorer would probe {} related hint(s) from `{subject}`",
                        relation_hits.len()
                    ),
                    confidence: 0.55,
                    should_continue: task.allowed_tools.len() > 1,
                }
            }
            ExplorerRole::ChunkExplorer => SubagentResult {
                role: ExplorerRole::ChunkExplorer,
                status: AgentStatus::Success,
                tool_calls: vec![ToolCallRecord {
                    tool: ToolName::SearchChunks,
                    note: "seeded preview support chunk".to_string(),
                }],
                entity_hits: vec![],
                relationship_hits: vec![],
                chunk_hits: vec![
                    ChunkHit {
                        value: format!("supporting chunk for `{}`", case.question),
                        source: "question".to_string(),
                    },
                    ChunkHit {
                        value: format!("additional supporting chunk for `{}`", subject),
                        source: "subject_hint".to_string(),
                    },
                ],
                summary: format!(
                    "Chunk explorer would gather support text for `{}`",
                    case.question
                ),
                confidence: 0.45,
                should_continue: false,
            },
        })
        .collect()
}

async fn run_task(
    config: &AppConfig,
    task: &SubagentTask,
    case: &EvalCase,
) -> anyhow::Result<SubagentResult> {
    let subject = case
        .subject_hint
        .clone()
        .unwrap_or_else(|| case.question.clone());

    match task.role {
        ExplorerRole::EntityExplorer => {
            let payload = serde_json::json!({
                "query": subject,
                "top_k": task.budget.top_k,
            });
            let result = call_mcp_tool(
                config,
                &config.paths.mcp_helper,
                ToolName::SearchEntities,
                payload,
            )
            .await?;
            let hits = extract_entity_hits(&result);
            Ok(SubagentResult {
                role: ExplorerRole::EntityExplorer,
                status: AgentStatus::Success,
                tool_calls: vec![ToolCallRecord {
                    tool: ToolName::SearchEntities,
                    note: "real MCP entity search".to_string(),
                }],
                entity_hits: hits,
                relationship_hits: vec![],
                chunk_hits: vec![],
                summary: "Entity explorer completed real MCP search".to_string(),
                confidence: 0.6,
                should_continue: false,
            })
        }
        ExplorerRole::RelationExplorer => {
            let relation_queries = relation_search_queries(case, &subject);
            let (search_hits, mut tool_calls) =
                run_relation_searches(config, &relation_queries, task.budget.top_k).await?;
            let (expanded_hits, expansion_calls) =
                run_weak_link_expansions(config, task, case, &search_hits).await?;
            tool_calls.extend(expansion_calls);
            let hits = merge_relation_hits(search_hits, expanded_hits);
            let should_continue = task.budget.max_depth > 0
                && task
                    .allowed_tools
                    .iter()
                    .any(|tool| matches!(tool, ToolName::ExpandNeighbors))
                && hits.is_empty();
            Ok(SubagentResult {
                role: ExplorerRole::RelationExplorer,
                status: AgentStatus::Success,
                tool_calls,
                entity_hits: vec![],
                relationship_hits: hits,
                chunk_hits: vec![],
                summary: format!(
                    "Relation explorer searched {} query path(s) and expanded weak links",
                    relation_queries.len()
                ),
                confidence: 0.6,
                should_continue,
            })
        }
        ExplorerRole::ChunkExplorer => {
            let payload = serde_json::json!({
                "query": case.question,
                "top_k": task.budget.top_k,
            });
            let result = call_mcp_tool(
                config,
                &config.paths.mcp_helper,
                ToolName::SearchChunks,
                payload,
            )
            .await?;
            let hits = extract_chunk_hits(&result);
            Ok(SubagentResult {
                role: ExplorerRole::ChunkExplorer,
                status: AgentStatus::Success,
                tool_calls: vec![ToolCallRecord {
                    tool: ToolName::SearchChunks,
                    note: "real MCP chunk search".to_string(),
                }],
                entity_hits: vec![],
                relationship_hits: vec![],
                chunk_hits: hits,
                summary: "Chunk explorer completed real MCP search".to_string(),
                confidence: 0.6,
                should_continue: false,
            })
        }
    }
}

async fn run_relation_searches(
    config: &AppConfig,
    queries: &[String],
    top_k: usize,
) -> anyhow::Result<(Vec<RelationHit>, Vec<ToolCallRecord>)> {
    let mut handles = Vec::new();
    for query in queries {
        let config = config.clone();
        let helper_path = config.paths.mcp_helper.clone();
        let query = query.clone();
        handles.push(tokio::spawn(async move {
            let payload = serde_json::json!({
                "query": query,
                "top_k": top_k,
            });
            let result = call_mcp_tool(
                &config,
                &helper_path,
                ToolName::SearchRelationships,
                payload,
            )
            .await?;
            Ok::<_, anyhow::Error>((query, result))
        }));
    }

    let mut hits = Vec::new();
    let mut tool_calls = Vec::new();
    for handle in handles {
        let (query, result) = handle.await??;
        tool_calls.push(ToolCallRecord {
            tool: ToolName::SearchRelationships,
            note: format!("real MCP relation search: {query}"),
        });
        hits.extend(extract_relation_hits(&result));
    }
    Ok((dedupe_relation_hits(hits), tool_calls))
}

async fn run_weak_link_expansions(
    config: &AppConfig,
    task: &SubagentTask,
    case: &EvalCase,
    relation_hits: &[RelationHit],
) -> anyhow::Result<(Vec<RelationHit>, Vec<ToolCallRecord>)> {
    if task.budget.max_depth == 0
        || !task
            .allowed_tools
            .iter()
            .any(|tool| matches!(tool, ToolName::ExpandNeighbors))
    {
        return Ok((Vec::new(), Vec::new()));
    }

    let seeds = expansion_seeds(case, relation_hits);
    let mut handles = Vec::new();
    for seed in seeds {
        let config = config.clone();
        let helper_path = config.paths.mcp_helper.clone();
        let depth = task.budget.max_depth.clamp(1, 2);
        let limit = task.budget.top_k.max(1);
        handles.push(tokio::spawn(async move {
            let payload = serde_json::json!({
                "entity_id": seed,
                "depth": depth,
                "limit": limit,
            });
            let result =
                call_mcp_tool(&config, &helper_path, ToolName::ExpandNeighbors, payload).await?;
            Ok::<_, anyhow::Error>((seed, result))
        }));
    }

    let mut hits = Vec::new();
    let mut tool_calls = Vec::new();
    for handle in handles {
        let (seed, result) = handle.await??;
        tool_calls.push(ToolCallRecord {
            tool: ToolName::ExpandNeighbors,
            note: format!("weak-link expansion from {seed}"),
        });
        hits.extend(extract_relation_hits(&result));
    }
    Ok((dedupe_relation_hits(hits), tool_calls))
}

fn relation_preview_hits(case: &EvalCase, subject: &str) -> Vec<RelationHit> {
    if case.related_hints.is_empty() {
        return vec![RelationHit {
            value: format!("{subject} -> {}", case.question),
            source: "question".to_string(),
        }];
    }

    case.related_hints
        .iter()
        .filter_map(|related| {
            let related = related.trim();
            if related.is_empty() {
                None
            } else {
                Some(RelationHit {
                    value: format!("{subject} -> {related}"),
                    source: format!("related_hint:{related}"),
                })
            }
        })
        .collect()
}

fn relation_search_queries(case: &EvalCase, subject: &str) -> Vec<String> {
    let mut queries = Vec::new();
    if case.related_hints.is_empty() {
        push_unique(&mut queries, case.question.clone());
        return queries;
    }

    for related in &case.related_hints {
        push_unique(&mut queries, format!("{subject} {related}"));
    }
    push_unique(&mut queries, format!("{subject} {}", case.question));
    queries
}

fn expansion_seeds(case: &EvalCase, relation_hits: &[RelationHit]) -> Vec<String> {
    let mut seeds = Vec::new();
    if let Some(subject) = &case.subject_hint {
        push_unique(&mut seeds, subject.clone());
    }
    for related in &case.related_hints {
        push_unique(&mut seeds, related.clone());
    }
    for hit in relation_hits {
        if let Some((src, tgt)) = hit.value.split_once(" -> ") {
            push_unique(&mut seeds, src.to_string());
            push_unique(&mut seeds, tgt.to_string());
        }
    }
    seeds.truncate(12);
    seeds
}

fn merge_relation_hits(primary: Vec<RelationHit>, secondary: Vec<RelationHit>) -> Vec<RelationHit> {
    let mut merged = primary;
    merged.extend(secondary);
    dedupe_relation_hits(merged)
}

fn dedupe_relation_hits(hits: Vec<RelationHit>) -> Vec<RelationHit> {
    let mut seen = HashSet::new();
    hits.into_iter()
        .filter(|hit| seen.insert(hit.value.clone()))
        .collect()
}

fn push_unique(values: &mut Vec<String>, value: String) {
    let value = value.trim();
    if !value.is_empty() && !values.iter().any(|existing| existing == value) {
        values.push(value.to_string());
    }
}

fn extract_entity_hits(value: &serde_json::Value) -> Vec<EntityHit> {
    value
        .get("data")
        .and_then(|data| data.get("entities"))
        .and_then(|entities| entities.as_array())
        .map(|entities| {
            entities
                .iter()
                .take(3)
                .filter_map(|entity| {
                    entity
                        .get("entity_name")
                        .and_then(|name| name.as_str())
                        .map(|name| EntityHit {
                            value: name.to_string(),
                            source: "mcp".to_string(),
                        })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn extract_relation_hits(value: &serde_json::Value) -> Vec<RelationHit> {
    value
        .get("data")
        .and_then(|data| data.get("relationships"))
        .and_then(|rels| rels.as_array())
        .map(|rels| {
            rels.iter()
                .take(3)
                .filter_map(|rel| {
                    let src = rel.get("src_id").and_then(|v| v.as_str())?;
                    let tgt = rel.get("tgt_id").and_then(|v| v.as_str())?;
                    Some(RelationHit {
                        value: format!("{src} -> {tgt}"),
                        source: "mcp".to_string(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

fn extract_chunk_hits(value: &serde_json::Value) -> Vec<ChunkHit> {
    value
        .get("data")
        .and_then(|data| data.get("chunks"))
        .and_then(|chunks| chunks.as_array())
        .map(|chunks| {
            chunks
                .iter()
                .take(3)
                .filter_map(|chunk| {
                    chunk
                        .get("chunk_id")
                        .and_then(|id| id.as_str())
                        .map(|id| ChunkHit {
                            value: id.to_string(),
                            source: "mcp".to_string(),
                        })
                })
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{QuestionType, ToolName};

    fn relation_case() -> EvalCase {
        EvalCase {
            id: "adv-round3-weak-link".to_string(),
            question: "威尔相关判断为什么需要覆盖阿蒙分身？".to_string(),
            question_type: QuestionType::MultiHopRelation,
            subject_hint: Some("威尔".to_string()),
            related_hints: vec![
                "命运途径".to_string(),
                "阿蒙分身".to_string(),
                "水银之蛇".to_string(),
            ],
            expected_answer: None,
            tags: vec!["weak-link".to_string()],
        }
    }

    #[test]
    fn preview_relation_explorer_probes_every_related_hint() {
        let preview = preview_for_case(&relation_case());
        let relation_result = preview
            .seeded_results
            .iter()
            .find(|result| matches!(result.role, ExplorerRole::RelationExplorer))
            .expect("relation explorer result should be seeded");

        let values: Vec<&str> = relation_result
            .relationship_hits
            .iter()
            .map(|hit| hit.value.as_str())
            .collect();

        assert!(values.contains(&"威尔 -> 命运途径"));
        assert!(values.contains(&"威尔 -> 阿蒙分身"));
        assert!(values.contains(&"威尔 -> 水银之蛇"));
        assert!(
            relation_result
                .tool_calls
                .iter()
                .filter(|call| matches!(call.tool, ToolName::SearchRelationships))
                .count()
                >= 3
        );
    }
}
