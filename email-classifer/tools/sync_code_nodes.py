import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_CODE = {
    "Get next 50 unclassified emails": "get_next_50_unclassified_emails.js",
    "Stop if no fetched emails": "stop_if_no_fetched_emails.js",
    "Normalize trigger email": "normalize_trigger_email.js",
    "Prepare Proton label targets": "prepare_proton_label_targets.js",
    "Apply Proton labels": "apply_proton_labels.js",
    "Apply Proton labels (trigger)": "apply_proton_labels.js",
    "Telemetry start run": "telemetry_start_run.js",
    "Telemetry start run (trigger)": "telemetry_start_run.js",
    "Telemetry restore start payload": "telemetry_restore_payload.js",
    "Telemetry restore start payload (trigger)": "telemetry_restore_payload.js",
    "Telemetry build email items": "telemetry_build_email_items.js",
    "Telemetry build email items (trigger)": "telemetry_build_email_items.js",
    "Telemetry restore email item payload": "telemetry_restore_payload.js",
    "Telemetry restore email item payload (trigger)": "telemetry_restore_payload.js",
    "Telemetry build classification attempt": "telemetry_build_classification_attempt.js",
    "Telemetry restore classification payload": "telemetry_restore_payload.js",
    "Telemetry build label actions": "telemetry_build_label_actions.js",
    "Telemetry build label actions (trigger)": "telemetry_build_label_actions.js",
    "Telemetry restore label action payload": "telemetry_restore_first_payload.js",
    "Telemetry restore label action payload (trigger)": "telemetry_restore_first_payload.js",
    "Telemetry finish run": "telemetry_finish_run.js",
    "Telemetry finish run (trigger)": "telemetry_finish_run.js",
}

STEP_STAGE_SORT_ORDERS = {
    "Start run": 10,
    "Configure batch": 20,
    "Fetch next unclassified emails": 30,
    "Expand fetched emails": 40,
    "Build classification prompt": 50,
    "Classify with Ollama": 60,
    "Prepare Proton label targets": 70,
    "Apply Proton labels": 80,
    "Apply Proton labels (trigger)": 85,
    "Finish run": 100,
}

STEP_STAGES_THAT_PARSE_PAYLOAD_JSON = {
    "Start run",
}


def code_file_for_node(name: str) -> str | None:
    if name.startswith("Telemetry start step: "):
        return "telemetry_start_step.js"
    if name.startswith("Telemetry finish step: "):
        return "telemetry_finish_step.js"
    return NODE_CODE.get(name)


def code_with_step_defaults(name: str, code: str) -> str:
    prefix = "Telemetry start step: "
    if not name.startswith(prefix):
        return code

    stage = name.removeprefix(prefix)
    sort_order = STEP_STAGE_SORT_ORDERS.get(stage)
    if sort_order is None:
        return code

    parse_payload_json = stage in STEP_STAGES_THAT_PARSE_PAYLOAD_JSON
    source_line = "  const item = inputItem.json ?? {};"
    if parse_payload_json:
        prefix_code = """function telemetryPayload(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return null;
  }
}

"""
        replacement = """  const rawSourceItem = inputItem.json ?? {};
  const parsedSourceItem = telemetryPayload(rawSourceItem.payload_json ?? rawSourceItem.payloadJson ?? rawSourceItem.payload);
  const sourceItem = parsedSourceItem && typeof parsedSourceItem === 'object'
    ? parsedSourceItem
    : rawSourceItem;
  const item = {
    ...sourceItem,
    telemetry_step_name: TELEMETRY_STEP_NAME,
    telemetry_step_type: TELEMETRY_STEP_TYPE,
    telemetry_step_sort_order: TELEMETRY_STEP_SORT_ORDER,
  };"""
    else:
        prefix_code = ""
        replacement = """  const sourceItem = inputItem.json ?? {};
  const item = {
    ...sourceItem,
    telemetry_step_name: TELEMETRY_STEP_NAME,
    telemetry_step_type: TELEMETRY_STEP_TYPE,
    telemetry_step_sort_order: TELEMETRY_STEP_SORT_ORDER,
  };"""
    if source_line not in code:
        raise ValueError("telemetry_start_step.js shape changed; cannot inject stage defaults")

    return (
        f"const TELEMETRY_STEP_NAME = {json.dumps(stage)};\n"
        "const TELEMETRY_STEP_TYPE = 'n8n-stage';\n"
        f"const TELEMETRY_STEP_SORT_ORDER = {sort_order};\n\n"
        + prefix_code
        + code.replace(source_line, replacement)
    )


def code_with_finish_step_id(name: str, code: str) -> str:
    prefix = "Telemetry finish step: "
    if not name.startswith(prefix):
        return code

    stage = name.removeprefix(prefix)
    restore_start_name = f"Telemetry restore step start: {stage}"
    source_line = "  const item = inputItem.json ?? {};"
    replacement = """  const sourceItem = inputItem.json ?? {};
  const item = {
    ...sourceItem,
    telemetry_step_id: currentStepId(inputItem, index) || sourceItem.telemetry_step_id || sourceItem.step_id || '',
  };"""
    if source_line not in code:
        raise ValueError("telemetry_finish_step.js shape changed; cannot inject step id recovery")

    return (
        f"const TELEMETRY_RESTORE_STEP_START_NODE = {json.dumps(restore_start_name)};\n\n"
        """function stepSourceIndex(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function pairedSourceIndex(inputItem, fallbackIndex) {
  const paired = inputItem?.pairedItem;
  if (Array.isArray(paired)) {
    for (const entry of paired) {
      const parsed = pairedSourceIndex({ pairedItem: entry }, fallbackIndex);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  if (typeof paired === 'number') return stepSourceIndex(paired, fallbackIndex);
  if (paired && typeof paired === 'object') {
    return stepSourceIndex(paired.item ?? paired.itemIndex ?? paired.sourceIndex, fallbackIndex);
  }

  const json = inputItem?.json ?? {};
  return stepSourceIndex(
    json.telemetry_step_source_index ?? json.source_index ?? json.sourceIndex,
    fallbackIndex,
  );
}

function currentStepId(inputItem, fallbackIndex) {
  const sourceItems = $(TELEMETRY_RESTORE_STEP_START_NODE).all();
  const index = pairedSourceIndex(inputItem, fallbackIndex);
  const source = sourceItems[index]?.json ?? sourceItems[0]?.json ?? {};
  const json = inputItem?.json ?? {};
  return source.telemetry_step_id || source.step_id || json.telemetry_step_id || json.step_id || '';
}

"""
        + code.replace(source_line, replacement)
    )


def sync(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node in workflow["nodes"]:
        filename = code_file_for_node(node["name"])
        if filename:
            code = (ROOT / "code-nodes" / filename).read_text(
                encoding="utf-8",
            )
            code = code_with_step_defaults(node["name"], code)
            node["parameters"]["jsCode"] = code_with_finish_step_id(node["name"], code)
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync(ROOT / "workflow.json")
    sync(ROOT / "workflow-imap-trigger.json")
