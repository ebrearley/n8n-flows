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


def sync(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node in workflow["nodes"]:
        filename = NODE_CODE.get(node["name"])
        if filename:
            node["parameters"]["jsCode"] = (ROOT / "code-nodes" / filename).read_text(
                encoding="utf-8",
            )
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync(ROOT / "workflow.json")
    sync(ROOT / "workflow-imap-trigger.json")
