import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILES = [ROOT / "workflow.json", ROOT / "workflow-imap-trigger.json"]

NODE_IDS = {
    "Plan email actions": "e5f83dc9-d89b-4d6d-8399-8f7f7b0d61a1",
    "Execute email action": "2c2f6111-0922-45b9-8f78-441197ba4f78",
    "Execute email action (trigger)": "eb97dbfe-891b-4cf7-a3ee-5c4f220d9fa3",
}

NODE_POSITIONS = {
    "Plan email actions": [1260, 520],
    "Inspect Proton label targets": [1400, 360],
    "From bulk loop?": [1530, 360],
    "Apply Proton labels": [1790, 260],
    "Apply Proton labels (trigger)": [1790, 520],
    "Execute email action": [2050, 260],
    "Execute email action (trigger)": [2050, 520],
}

ACTION_ASSIGNMENTS = [
    {
        "id": "email-actions-mode",
        "name": "emailActionsMode",
        "value": "live",
        "type": "string",
    },
    {
        "id": "action-archive-mailbox",
        "name": "actionArchiveMailbox",
        "value": "Archive",
        "type": "string",
    },
    {
        "id": "action-spam-mailbox",
        "name": "actionSpamMailbox",
        "value": "Spam",
        "type": "string",
    },
    {
        "id": "action-trash-mailbox",
        "name": "actionTrashMailbox",
        "value": "Trash",
        "type": "string",
    },
]

ACTION_HINTS_START = "<!-- action-hints:start -->"
ACTION_HINTS_END = "<!-- action-hints:end -->"
ACTION_HINTS_SECTION = ACTION_HINTS_START + """
## Action hints
Include `action_hints` in every response. Use conservative values. If evidence is missing or ambiguous, use false, null, or "unknown".

```json
"action_hints": {
  "two_factor_code": false,
  "event_notice": false,
  "event_time": null,
  "backup_job": false,
  "backup_status": "unknown",
  "has_errors": false
}
```

- `action_hints`: include this object in every response.
- `two_factor_code`: true only for one-time passcodes, MFA, login verification, or security-code emails.
- `event_notice`: true only for event reminders, calendar notifications, or invitations.
- `event_time`: ISO 8601 date-time with timezone for the event, or null when no clear event time exists.
- `backup_job`: true only for backup job notifications.
- `backup_status`: "success", "failure", "warning", or "unknown".
- `has_errors`: true when the email mentions errors, failures, warnings, partial completion, or missed backup jobs.
""" + ACTION_HINTS_END


def read_code(name: str) -> str:
    return (ROOT / "code-nodes" / name).read_text(encoding="utf-8")


def node_by_name(workflow: dict) -> dict:
    return {node["name"]: node for node in workflow["nodes"]}


def code_node(name: str, js_code: str, position: list[int]) -> dict:
    return {
        "id": NODE_IDS[name],
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "parameters": {
            "language": "javaScript",
            "jsCode": js_code,
        },
    }


def ensure_code_node(workflow: dict, name: str, source_file: str) -> None:
    nodes = node_by_name(workflow)
    js_code = read_code(source_file)
    if name in nodes:
        nodes[name]["parameters"]["language"] = "javaScript"
        nodes[name]["parameters"]["jsCode"] = js_code
        nodes[name]["position"] = NODE_POSITIONS[name]
        return
    workflow["nodes"].append(code_node(name, js_code, NODE_POSITIONS[name]))


def ensure_assignment(workflow: dict, assignment: dict) -> None:
    configure = node_by_name(workflow)["Configure Proton IMAP batch"]
    assignments = configure["parameters"]["assignments"]["assignments"]
    for existing in assignments:
        if existing["name"] == assignment["name"]:
            existing.update(assignment)
            return
    assignments.append(dict(assignment))


def remove_marked_action_hints_section(value: str) -> str:
    while ACTION_HINTS_START in value or ACTION_HINTS_END in value:
        start = value.find(ACTION_HINTS_START)
        end = value.find(ACTION_HINTS_END)
        if start == -1 or end == -1 or end < start:
            raise ValueError("Malformed action hints section markers")
        end += len(ACTION_HINTS_END)
        value = value[:start].rstrip() + "\n" + value[end:].lstrip()
    return value


def ensure_action_hints_schema(value: str) -> str:
    if '"action_hints"' in value:
        return value
    category_schema_tail = '  "reason": string\n}\n```'
    if category_schema_tail not in value:
        raise ValueError("System prompt is missing expected category schema")
    action_hints_schema = """  "reason": string,
  "action_hints": {
    "two_factor_code": boolean,
    "event_notice": boolean,
    "event_time": string | null,
    "backup_job": boolean,
    "backup_status": "success" | "failure" | "warning" | "unknown",
    "has_errors": boolean
  }
}
```"""
    return value.replace(category_schema_tail, action_hints_schema, 1)


def update_system_prompt(workflow: dict) -> None:
    build_prompt = node_by_name(workflow)["Build classification prompt"]
    assignments = build_prompt["parameters"]["assignments"]["assignments"]
    for assignment in assignments:
        if assignment["name"] != "systemPrompt":
            continue
        value = remove_marked_action_hints_section(assignment["value"])
        rules_anchor = "\n## Rules\n"
        if rules_anchor not in value:
            raise ValueError("System prompt is missing ## Rules anchor")

        legacy_optional_anchor = "\n## Optional action hints\n"
        if legacy_optional_anchor in value:
            prefix, legacy_and_rest = value.split(legacy_optional_anchor, 1)
            _legacy_optional, suffix = legacy_and_rest.split(rules_anchor, 1)
            value = f"{prefix.rstrip()}{rules_anchor}{suffix.lstrip()}"

        value = ensure_action_hints_schema(value)
        prefix, suffix = value.split(rules_anchor, 1)
        value = "\n\n".join([prefix.rstrip(), ACTION_HINTS_SECTION, f"## Rules\n{suffix.lstrip()}"])

        if value.count(ACTION_HINTS_START) != 1 or value.count(ACTION_HINTS_END) != 1:
            raise ValueError("System prompt must contain exactly one action hints section")

        assignment["value"] = value
        return
    raise ValueError("Build classification prompt is missing systemPrompt assignment")


def set_position(workflow: dict, name: str) -> None:
    node_by_name(workflow)[name]["position"] = NODE_POSITIONS[name]


def connect_to(node_name: str) -> dict:
    return {"node": node_name, "type": "main", "index": 0}


def update_connections(workflow: dict) -> None:
    workflow["connections"]["Prepare Proton label targets"] = {
        "main": [[connect_to("Plan email actions")]]
    }
    workflow["connections"]["Plan email actions"] = {
        "main": [[connect_to("Inspect Proton label targets")]]
    }
    workflow["connections"]["Inspect Proton label targets"] = {
        "main": [[connect_to("From bulk loop?")]]
    }
    workflow["connections"]["From bulk loop?"] = {
        "main": [
            [connect_to("Apply Proton labels")],
            [connect_to("Apply Proton labels (trigger)")],
        ]
    }
    workflow["connections"]["Apply Proton labels"] = {
        "main": [[connect_to("Execute email action")]]
    }
    workflow["connections"]["Execute email action"] = {
        "main": [[connect_to("Loop Over Emails")]]
    }
    workflow["connections"]["Apply Proton labels (trigger)"] = {
        "main": [[connect_to("Execute email action (trigger)")]]
    }
    workflow["connections"].pop("Execute email action (trigger)", None)


def update_workflow(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    ensure_code_node(workflow, "Plan email actions", "plan_email_actions.js")
    ensure_code_node(workflow, "Execute email action", "execute_email_action.js")
    ensure_code_node(workflow, "Execute email action (trigger)", "execute_email_action.js")
    node_by_name(workflow)["Prepare Proton label targets"]["parameters"]["jsCode"] = read_code(
        "prepare_proton_label_targets.js"
    )
    for assignment in ACTION_ASSIGNMENTS:
        ensure_assignment(workflow, assignment)
    update_system_prompt(workflow)
    for name in NODE_POSITIONS:
        set_position(workflow, name)
    update_connections(workflow)
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for path in WORKFLOW_FILES:
        update_workflow(path)


if __name__ == "__main__":
    main()
