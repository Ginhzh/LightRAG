use crate::types::{QuestionType, RetrievalPolicy, ToolName};

pub fn build_policy(question_type: &QuestionType) -> RetrievalPolicy {
    match question_type {
        QuestionType::EntityFact => RetrievalPolicy {
            allowed_tools: vec![
                ToolName::SearchEntities,
                ToolName::SearchChunks,
                ToolName::RetrieveContext,
                ToolName::Ask,
            ],
            max_parallel_agents: 3,
            max_steps_per_agent: 2,
            entity_top_k: 5,
            relationship_top_k: 0,
            chunk_top_k: 5,
            max_depth: 0,
            enable_second_round: false,
        },
        QuestionType::RelationQuery | QuestionType::MultiHopRelation => RetrievalPolicy {
            allowed_tools: vec![
                ToolName::SearchEntities,
                ToolName::SearchRelationships,
                ToolName::SearchChunks,
                ToolName::ExpandNeighbors,
                ToolName::RetrieveContext,
                ToolName::Ask,
            ],
            max_parallel_agents: 3,
            max_steps_per_agent: 3,
            entity_top_k: 5,
            relationship_top_k: 5,
            chunk_top_k: 5,
            max_depth: 1,
            enable_second_round: true,
        },
        QuestionType::OpenExploration => RetrievalPolicy {
            allowed_tools: vec![
                ToolName::SearchEntities,
                ToolName::SearchRelationships,
                ToolName::SearchChunks,
                ToolName::ExpandNeighbors,
                ToolName::RetrieveContext,
                ToolName::Ask,
            ],
            max_parallel_agents: 3,
            max_steps_per_agent: 4,
            entity_top_k: 8,
            relationship_top_k: 8,
            chunk_top_k: 5,
            max_depth: 1,
            enable_second_round: true,
        },
    }
}
