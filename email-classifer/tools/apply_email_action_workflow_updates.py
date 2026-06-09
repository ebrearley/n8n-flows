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
    for name in NODE_POSITIONS:
        set_position(workflow, name)
    update_connections(workflow)
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for path in WORKFLOW_FILES:
        update_workflow(path)


if __name__ == "__main__":
    main()
