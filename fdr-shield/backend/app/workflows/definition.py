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


def next_node(node_key: str, branch: str | None = None) -> str | None:
    if node_key == 'extract_document': return 'validate_fields'
    if node_key == 'validate_fields': return 'route_case'
    if node_key == 'route_case': return None
    raise ValueError(f'Unknown workflow node: {node_key}')


def downstream_nodes(node_key: str) -> list[str]:
    order=list(NODES)
    if node_key not in order: raise ValueError(f'Unknown workflow node: {node_key}')
    return order[order.index(node_key):]
