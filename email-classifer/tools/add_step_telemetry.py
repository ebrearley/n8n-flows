import json
import uuid
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

WORKFLOW_PATHS = (
    ROOT / "workflow.json",
    ROOT / "workflow-imap-trigger.json",
)

STAGES = [
    {
        "stage": "Fetch next unclassified emails",
        "node": "Get next 50 unclassified emails",
        "sort": 30,
    },
    {
        "stage": "Build classification prompt",
        "node": "Build classification prompt",
        "sort": 50,
    },
    {
        "stage": "Classify with Ollama",
        "node": "Classify with Ollama",
        "sort": 60,
    },
    {
        "stage": "Prepare Proton label targets",
        "node": "Prepare Proton label targets",
        "sort": 70,
    },
    {
        "stage": "Apply Proton labels",
        "node": "Apply Proton labels",
        "sort": 80,
    },
    {
        "stage": "Finish run",
        "node": "Telemetry finish run",
        "sort": 100,
    },
]

GENERATED_PREFIXES = (
    "Telemetry start step: ",
    "Telemetry record step: ",
    "Telemetry restore step start: ",
    "Telemetry finish step: ",
    "Telemetry update step: ",
    "Telemetry restore step finish: ",
)

POSTGRES_CREDENTIALS = {
    "postgres": {
        "id": "wspg_a409ed51b8f18c5e",
        "name": "Workflow Status Postgres",
    },
}

INSERT_STEP_QUERY = """INSERT INTO workflow_steps (run_id, name, type, status, sort_order, started_at, input_json)
SELECT NULLIF($1, '')::uuid, $2, $3, 'running', $4::int, $5::timestamptz, $6::jsonb
WHERE NULLIF($1, '') IS NOT NULL
RETURNING id AS step_id, $7::int AS source_index;"""

UPDATE_STEP_QUERY = """WITH updated AS (
  UPDATE workflow_steps
  SET
    status = $2,
    stopped_at = $3::timestamptz,
    duration_ms = (extract(epoch from ($3::timestamptz - started_at)) * 1000)::int,
    output_json = $4::jsonb,
    error_json = CASE WHEN $5 IS NULL OR $5 = '' THEN NULL ELSE $5::jsonb END
  WHERE id = NULLIF($1, '')::uuid
  RETURNING id
)
SELECT $6::int AS source_index;"""


def generated_name(name: str) -> bool:
    return name.startswith(GENERATED_PREFIXES)


def node_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"email-classifer-step-telemetry:{name}"))


def connection_to(name: str) -> dict:
    return {"node": name, "type": "main", "index": 0}


def stage_node_names(stage: str) -> dict[str, str]:
    return {
        "start": f"Telemetry start step: {stage}",
        "record": f"Telemetry record step: {stage}",
        "restore_start": f"Telemetry restore step start: {stage}",
        "finish": f"Telemetry finish step: {stage}",
        "update": f"Telemetry update step: {stage}",
        "restore_finish": f"Telemetry restore step finish: {stage}",
    }


def read_code(filename: str) -> str:
    return (ROOT / "code-nodes" / filename).read_text(encoding="utf-8")


def start_step_code(stage: str, sort_order: int, base_code: str) -> str:
    defaults = f"""const TELEMETRY_STEP_NAME = {json.dumps(stage)};
const TELEMETRY_STEP_TYPE = 'n8n-stage';
const TELEMETRY_STEP_SORT_ORDER = {sort_order};

"""
    source_line = "  const item = inputItem.json ?? {};"
    replacement = """  const sourceItem = inputItem.json ?? {};
  const item = {
    ...sourceItem,
    telemetry_step_name: sourceItem.telemetry_step_name || TELEMETRY_STEP_NAME,
    telemetry_step_type: sourceItem.telemetry_step_type || TELEMETRY_STEP_TYPE,
    telemetry_step_sort_order: sourceItem.telemetry_step_sort_order ?? TELEMETRY_STEP_SORT_ORDER,
  };"""
    if source_line not in base_code:
        raise ValueError("telemetry_start_step.js shape changed; cannot inject stage defaults")
    return defaults + base_code.replace(source_line, replacement)


def code_node(name: str, position: list[int], js_code: str) -> dict:
    return {
        "id": node_id(name),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "parameters": {
            "mode": "runOnceForAllItems",
            "language": "javaScript",
            "jsCode": js_code,
        },
    }


def postgres_node(name: str, position: list[int], query: str, replacement: str) -> dict:
    return {
        "id": node_id(name),
        "name": name,
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.6,
        "position": position,
        "parameters": {
            "operation": "executeQuery",
            "query": query,
            "options": {
                "queryBatching": "independently",
                "queryReplacement": replacement,
            },
        },
        "credentials": deepcopy(POSTGRES_CREDENTIALS),
    }


def restore_start_code(stage: str) -> str:
    start_name = f"Telemetry start step: {stage}"
    return f"""function sourceIndex(value) {{
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}}

return $input.all().map((inputItem) => {{
  const result = inputItem?.json ?? {{}};
  const index = sourceIndex(result.source_index ?? result.sourceIndex ?? result.telemetry_step_source_index);
  const sourceItems = $('{start_name}').all();
  const restored = sourceItems[index]?.json ?? sourceItems[0]?.json ?? result;
  return {{
    json: {{
      ...restored,
      telemetry_step_id: result.step_id || result.telemetry_step_id || restored.telemetry_step_id || '',
    }},
    pairedItem: index,
  }};
}});
"""


def restore_finish_code(stage: str) -> str:
    finish_name = f"Telemetry finish step: {stage}"
    return f"""function sourceIndex(value) {{
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}}

return $input.all().map((inputItem) => {{
  const result = inputItem?.json ?? {{}};
  const index = sourceIndex(result.source_index ?? result.sourceIndex ?? result.telemetry_step_source_index);
  const sourceItems = $('{finish_name}').all();
  const restored = sourceItems[index]?.json ?? sourceItems[0]?.json ?? result;
  return {{
    json: {{
      ...restored,
    }},
    pairedItem: index,
  }};
}});
"""


def remove_generated_nodes(workflow: dict) -> None:
    workflow["nodes"] = [
        node for node in workflow["nodes"] if not generated_name(node["name"])
    ]


def remove_generated_connections(workflow: dict) -> None:
    connections = workflow.get("connections", {})
    for name in list(connections):
        if generated_name(name):
            del connections[name]

    for connection in connections.values():
        for outputs in connection.values():
            if not isinstance(outputs, list):
                continue
            for output in outputs:
                if not isinstance(output, list):
                    continue
                output[:] = [
                    edge for edge in output if not generated_name(edge.get("node", ""))
                ]


def redirect_main_destination(connections: dict, old_name: str, new_name: str) -> None:
    for connection in connections.values():
        for output in connection.get("main", []):
            if not isinstance(output, list):
                continue
            for edge in output:
                if edge.get("node") == old_name:
                    edge["node"] = new_name


def unwrap_stage_connections(workflow: dict) -> None:
    connections = workflow.setdefault("connections", {})
    for stage_config in STAGES:
        names = stage_node_names(stage_config["stage"])
        target_name = stage_config["node"]
        target_connection = connections.get(target_name)
        restore_finish_connection = connections.get(names["restore_finish"])

        if target_connection and restore_finish_connection:
            main_outputs = target_connection.get("main", [])
            first_output = main_outputs[0] if main_outputs else []
            if any(edge.get("node") == names["finish"] for edge in first_output):
                target_connection["main"] = deepcopy(
                    restore_finish_connection.get("main", []),
                )

        redirect_main_destination(connections, names["start"], target_name)

    remove_generated_connections(workflow)


def target_position(workflow: dict, target_name: str) -> tuple[int, int]:
    for node in workflow["nodes"]:
        if node["name"] == target_name:
            position = node.get("position", [0, 0])
            return int(position[0]), int(position[1])
    raise ValueError(f"Missing target node: {target_name}")


def generated_positions(workflow: dict, stage_config: dict, index: int) -> dict[str, list[int]]:
    x, y = target_position(workflow, stage_config["node"])
    lane_y = y - 260 - (index * 100)
    return {
        "start": [x - 270, lane_y],
        "record": [x - 60, lane_y],
        "restore_start": [x + 150, lane_y],
        "finish": [x + 150, lane_y + 120],
        "update": [x + 360, lane_y + 120],
        "restore_finish": [x + 570, lane_y + 120],
    }


def append_stage_nodes(workflow: dict) -> None:
    start_code = read_code("telemetry_start_step.js")
    finish_code = read_code("telemetry_finish_step.js")

    for index, stage_config in enumerate(STAGES):
        stage = stage_config["stage"]
        names = stage_node_names(stage)
        positions = generated_positions(workflow, stage_config, index)

        workflow["nodes"].extend(
            [
                code_node(
                    names["start"],
                    positions["start"],
                    start_step_code(stage, stage_config["sort"], start_code),
                ),
                postgres_node(
                    names["record"],
                    positions["record"],
                    INSERT_STEP_QUERY,
                    "={{ $json.telemetry_step_params }}",
                ),
                code_node(
                    names["restore_start"],
                    positions["restore_start"],
                    restore_start_code(stage),
                ),
                code_node(names["finish"], positions["finish"], finish_code),
                postgres_node(
                    names["update"],
                    positions["update"],
                    UPDATE_STEP_QUERY,
                    "={{ $json.telemetry_step_finish_params }}",
                ),
                code_node(
                    names["restore_finish"],
                    positions["restore_finish"],
                    restore_finish_code(stage),
                ),
            ],
        )


def set_main_connection(connections: dict, source: str, target: str) -> None:
    connection = connections.setdefault(source, {})
    connection["main"] = [[connection_to(target)]]


def instrument_stage_connections(workflow: dict) -> None:
    connections = workflow.setdefault("connections", {})

    for stage_config in STAGES:
        stage = stage_config["stage"]
        target_name = stage_config["node"]
        names = stage_node_names(stage)
        target_connection = connections.setdefault(target_name, {})
        original_target_main = deepcopy(target_connection.get("main", []))

        redirect_main_destination(connections, target_name, names["start"])

        set_main_connection(connections, names["start"], names["record"])
        set_main_connection(connections, names["record"], names["restore_start"])
        set_main_connection(connections, names["restore_start"], target_name)
        target_connection["main"] = [[connection_to(names["finish"])]]
        set_main_connection(connections, names["finish"], names["update"])
        set_main_connection(connections, names["update"], names["restore_finish"])

        if original_target_main:
            connections[names["restore_finish"]] = {"main": original_target_main}
        else:
            connections[names["restore_finish"]] = {"main": [[]]}


def add_step_telemetry(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    unwrap_stage_connections(workflow)
    remove_generated_nodes(workflow)
    append_stage_nodes(workflow)
    instrument_stage_connections(workflow)
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for workflow_path in WORKFLOW_PATHS:
        add_step_telemetry(workflow_path)
