use crate::types::{
    ChunkHit, EntityHit, EvidenceBundle, EvidenceSufficiency, RelationHit, SubagentResult,
};

pub fn empty_bundle() -> EvidenceBundle {
    EvidenceBundle {
        entities: Vec::new(),
        relationships: Vec::new(),
        chunks: Vec::new(),
        references: Vec::new(),
        source_agents: Vec::new(),
        sufficiency: EvidenceSufficiency::Empty,
    }
}

pub fn evaluate_sufficiency(bundle: &EvidenceBundle) -> EvidenceSufficiency {
    let has_entities = !bundle.entities.is_empty();
    let has_relationships = !bundle.relationships.is_empty();
    let chunk_count = bundle.chunks.len();

    if has_entities && (has_relationships || chunk_count >= 2) {
        EvidenceSufficiency::Sufficient
    } else if has_entities || has_relationships || chunk_count > 0 {
        EvidenceSufficiency::Partial
    } else {
        EvidenceSufficiency::Empty
    }
}

pub fn merge_results(results: &[SubagentResult]) -> EvidenceBundle {
    let mut bundle = empty_bundle();
    for result in results {
        append_entities(&mut bundle.entities, &result.entity_hits);
        append_relationships(&mut bundle.relationships, &result.relationship_hits);
        append_chunks(&mut bundle.chunks, &result.chunk_hits);
        bundle
            .source_agents
            .push(format!("{:?}", result.role));
    }
    bundle.sufficiency = evaluate_sufficiency(&bundle);
    bundle
}

fn append_entities(target: &mut Vec<String>, hits: &[EntityHit]) {
    for hit in hits {
        if !target.iter().any(|value| value == &hit.value) {
            target.push(hit.value.clone());
        }
    }
}

fn append_relationships(target: &mut Vec<String>, hits: &[RelationHit]) {
    for hit in hits {
        if !target.iter().any(|value| value == &hit.value) {
            target.push(hit.value.clone());
        }
    }
}

fn append_chunks(target: &mut Vec<String>, hits: &[ChunkHit]) {
    for hit in hits {
        if !target.iter().any(|value| value == &hit.value) {
            target.push(hit.value.clone());
        }
    }
}
