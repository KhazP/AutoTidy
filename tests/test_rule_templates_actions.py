import queue
from unittest.mock import patch

import constants
from config_manager import ConfigManager
from worker import MonitoringWorker


class SingleCycleStopEvent:
    """Stop event replacement that allows a single monitoring cycle."""

    def __init__(self):
        self._is_set = False

    def is_set(self):
        return self._is_set

    def wait(self, timeout):
        self._is_set = True
        return True

    def set(self):
        self._is_set = True


def test_rule_templates_actions_are_recognized(monkeypatch, tmp_path):
    """Applying templates should result in worker actions that are all supported."""

    monkeypatch.setattr(ConfigManager, "_get_config_dir", lambda self: tmp_path / "config")

    config_manager = ConfigManager("AutoTidyTemplateTests")
    config_manager.config['folders'] = []
    config_manager.config.setdefault('settings', {})['dry_run_mode'] = True

    custom_templates = []
    expected_actions = set()

    for template_index, template in enumerate(constants.RULE_TEMPLATES):
        new_rules = []
        for rule_index, rule in enumerate(template.get('rules', [])):
            watch_dir = tmp_path / f"template_{template_index}_{rule_index}" / "watch"
            watch_dir.mkdir(parents=True, exist_ok=True)
            (watch_dir / "example.txt").write_text("content")

            normalized_action = config_manager.normalize_action(rule.get('action', 'move'))
            expected_actions.add(normalized_action)

            destination_folder = rule.get('destination_folder', '')
            if normalized_action in {"move", "copy"} and destination_folder:
                dest_dir = tmp_path / f"template_{template_index}_{rule_index}" / "dest"
                dest_dir.mkdir(parents=True, exist_ok=True)
                destination_folder = str(dest_dir)
            else:
                destination_folder = "" if normalized_action in {"delete_to_trash", "delete_permanently"} else destination_folder

            new_rule = dict(rule)
            new_rule['folder_to_watch'] = str(watch_dir)
            new_rule['destination_folder'] = destination_folder
            new_rule['action'] = normalized_action
            new_rules.append(new_rule)

        custom_templates.append({
            'name': template['name'],
            'description': template.get('description', ''),
            'rules': new_rules
        })

    monkeypatch.setattr(constants, "RULE_TEMPLATES", custom_templates, raising=False)

    total_rules = 0
    for template in custom_templates:
        for rule in template['rules']:
            normalized_rule = dict(rule)
            total_rules += 1
            config_manager.add_folder(rule['folder_to_watch'], normalized_rule)
            config_manager.update_folder_rule(
                path=rule['folder_to_watch'],
                age_days=normalized_rule.get('days_older_than', 0),
                pattern=normalized_rule.get('file_pattern', '*.*'),
                rule_logic=normalized_rule.get('rule_logic', 'OR'),
                use_regex=normalized_rule.get('use_regex', False),
                action=normalized_rule.get('action', 'move'),
                exclusions=normalized_rule.get('exclusions', []),
                destination_folder=normalized_rule.get('destination_folder', ''),
                enabled=normalized_rule.get('enabled', True)
            )

    log_queue = queue.Queue()
    worker = MonitoringWorker(config_manager, log_queue)
    worker._stop_event = SingleCycleStopEvent()

    with patch('worker.check_file', return_value=True), patch('worker.process_file_action') as process_mock:
        process_mock.return_value = (True, 'processed')
        worker.run()

    assert process_mock.call_count == total_rules
    processed_actions = {call.args[3] for call in process_mock.call_args_list}
    assert processed_actions == expected_actions
    assert processed_actions.issubset({"move", "copy", "delete_to_trash", "delete_permanently"})
