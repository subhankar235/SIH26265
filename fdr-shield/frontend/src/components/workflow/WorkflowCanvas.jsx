import { useMemo } from 'react';
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './workflowCanvas.css';

function stateLabel(status) {
  return String(status || 'not_started').replaceAll('_', ' ');
}

function WorkflowNode({ data, selected }) {
  const outcome = data.kind === 'business_outcome';
  return <div className={`workflow-node ${selected ? 'workflow-node--selected' : ''} ${outcome ? 'workflow-node--outcome' : ''}`}>
    <Handle type="target" position={Position.Left} />
    <div className="workflow-node-icon" aria-hidden="true">{data.icon}</div>
    <div className="workflow-node-copy">
      <strong>{data.label}</strong>
      <span>{outcome ? 'Lifecycle outcome · not an executor node' : `${data.key} · ${stateLabel(data.status)}`}</span>
      {!outcome && data.attempt && <small>Attempt #{data.attempt} · {data.duration_ms ?? 'duration pending'} ms</small>}
      {!outcome && !data.attempt && <small>No persisted attempt yet</small>}
    </div>
    {!outcome && <Handle type="source" position={Position.Right} />}
  </div>;
}

const nodeTypes = { workflow: WorkflowNode };

const icons = {
  extract_document: '▤',
  validate_fields: '✓',
  route_case: '◇',
};

export function buildExecutionGraph(definition, executions, workflow, selectedNodeKey) {
  const latestByKey = new Map();
  for (const attempt of executions || []) {
    const previous = latestByKey.get(attempt.node_key);
    if (!previous || attempt.id > previous.id) latestByKey.set(attempt.node_key, attempt);
  }
  const executorNodes = definition?.nodes || [];
  const positions = {
    extract_document: { x: 40, y: 170 },
    validate_fields: { x: 365, y: 170 },
    route_case: { x: 690, y: 170 },
  };
  const routeAttempt = latestByKey.get('route_case');
  const routedTo = routeAttempt?.output_ref?.route;
  const correctionSelected = routedTo === 'correction';
  const reviewSelected = routedTo === 'human_review';
  const running = ['running', 'retrying', 'not_started'].includes(workflow?.execution_state);

  const nodes = executorNodes.map((definitionNode) => {
    const attempt = latestByKey.get(definitionNode.key);
    const current = workflow?.current_node === definitionNode.key;
    return {
      id: definitionNode.key,
      type: 'workflow',
      position: positions[definitionNode.key] || { x: 40, y: 170 },
      data: {
        key: definitionNode.key,
        label: definitionNode.label,
        kind: 'executor',
        status: attempt?.status || (current&&workflow?.execution_state==='running'?'queued':'not_started'),
        attempt: attempt?.attempt,
        duration_ms: attempt?.duration_ms,
        icon: icons[definitionNode.key] || '•',
      },
      selected: selectedNodeKey === definitionNode.key,
    };
  });

  for (const outcome of definition?.outcomes || []) {
    const reached = outcome.state === 'correction_required' ? correctionSelected : reviewSelected;
    nodes.push({
      id: outcome.id,
      type: 'workflow',
      position: outcome.state === 'correction_required' ? { x: 525, y: 390 } : { x: 855, y: 390 },
      data: {
        key: outcome.state,
        label: outcome.label,
        kind: 'business_outcome',
        status: reached ? 'reached' : 'not_selected',
        icon: reached ? '✓' : '○',
      },
      selected: selectedNodeKey === outcome.id,
    });
  }

  const edges = (definition?.edges || []).map((edge) => {
    const route = edge.label === 'correction' ? correctionSelected
      : edge.label === 'human review' ? reviewSelected
      : Boolean(latestByKey.get(edge.source)?.status === 'succeeded');
    return {
      ...edge,
      type: 'smoothstep',
      animated: route && ['running', 'retrying'].includes(workflow?.execution_state),
      style: { stroke: route ? '#60a5fa' : '#64748b', strokeWidth: route ? 2.5 : 1.5 },
      labelStyle: { fill: '#cbd5e1', fontSize: 11 },
      labelBgStyle: { fill: '#111827', fillOpacity: 0.95 },
    };
  });
  return { nodes, edges, latestByKey };
}

export default function WorkflowCanvas({ definition, executions, workflow, selectedNodeKey, onSelectNode }) {
  const graph = useMemo(
    () => buildExecutionGraph(definition, executions, workflow, selectedNodeKey),
    [definition, executions, workflow, selectedNodeKey],
  );
  return <div className="workflow-canvas" aria-label="Persisted FDR workflow execution graph">
    <ReactFlow
      nodes={graph.nodes}
      edges={graph.edges}
      nodeTypes={nodeTypes}
      onInit={(instance)=>instance.fitView({padding:0.2,minZoom:0.35,maxZoom:1.1})}
      onNodeClick={(_, node) => onSelectNode?.(node.id, graph.latestByKey.get(node.id) || null)}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      deleteKeyCode={null}
      fitView
      fitViewOptions={{ padding: 0.2, minZoom: 0.35, maxZoom: 1.1 }}
      minZoom={0.25}
      maxZoom={1.5}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant="dots" gap={20} size={1} color="#334155" />
      <Controls showInteractive={false} />
      <MiniMap nodeColor={(node) => {
        const status=node.data?.status;
        if(status==='succeeded'||status==='reached')return '#34d399';
        if(status==='failed')return '#f87171';
        if(status==='running'||status==='queued')return '#60a5fa';
        return '#64748b';
      }} maskColor="rgba(2, 6, 23, 0.65)" />
    </ReactFlow>
  </div>;
}
