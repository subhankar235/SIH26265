"""Versioned, deterministic workflow graph. LLMs do not choose transitions."""
from dataclasses import dataclass

WORKFLOW_VERSION = 'fdr-case-v1'


@dataclass(frozen=True)
class NodeDefinition:
    key: str
    side_effect_class: str
    max_attempts: int = 3
    retry_base_seconds: int = 2
    timeout_seconds: int = 120


NODES = {
    'extract_document': NodeDefinition('extract_document', 'pure', timeout_seconds=180),
    'validate_fields': NodeDefinition('validate_fields', 'idempotent_effect'),
    'route_case': NodeDefinition('route_case', 'idempotent_effect'),
}
START_NODE = 'extract_document'

<<<<<<< HEAD
NODE_LABELS = {
    'extract_document':'Extract document fields',
    'validate_fields':'Validate declarations and extracted fields',
    'route_case':'Route case for correction or official review',
}
WORKFLOW_EDGES = [
    {'id':'extract-to-validate','source':'extract_document','target':'validate_fields'},
    {'id':'validate-to-route','source':'validate_fields','target':'route_case'},
    {'id':'route-to-correction','source':'route_case','target':'outcome-correction','label':'correction'},
    {'id':'route-to-review','source':'route_case','target':'outcome-review','label':'human review'},
]
WORKFLOW_OUTCOMES = [
    {'id':'outcome-correction','label':'Correction required','state':'correction_required',
     'kind':'business_outcome'},
    {'id':'outcome-review','label':'AICTE Official review','state':'ready_for_review',
     'kind':'business_outcome'},
]


def public_definition() -> dict:
    """Expose the immutable executor graph and clearly labeled non-executable outcomes."""
    return {
        'version':WORKFLOW_VERSION,
        'editable':False,
        'nodes':[{'key':node.key,'label':NODE_LABELS[node.key],
            'side_effect_class':node.side_effect_class,'max_attempts':node.max_attempts,
            'timeout_seconds':node.timeout_seconds,'start':node.key==START_NODE}
            for node in NODES.values()],
        'outcomes':WORKFLOW_OUTCOMES,
        'edges':WORKFLOW_EDGES,
    }

=======
>>>>>>> a27ee110f6ba3d79cb2eb0cff239996b7f97ea26

def next_node(node_key: str, branch: str | None = None) -> str | None:
    if node_key == 'extract_document': return 'validate_fields'
    if node_key == 'validate_fields': return 'route_case'
    if node_key == 'route_case': return None
    raise ValueError(f'Unknown workflow node: {node_key}')


def downstream_nodes(node_key: str) -> list[str]:
    order=list(NODES)
    if node_key not in order: raise ValueError(f'Unknown workflow node: {node_key}')
    return order[order.index(node_key):]
