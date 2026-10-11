"""Validate deliverables and serialize explicit success/blocker/integrity evidence."""
from common import *
import csv, sys
import openpyxl

required = [BASE / 'REPORT.md', BASE / 'candidate_mapping.csv', BASE / 'logs/session_tool_audit.json', BASE / 'evidence/source_integrity_final.json']
for p in required:
    if not p.is_file():
        raise FileNotFoundError(p)
report = (BASE / 'REPORT.md').read_text(encoding='utf-8')
if 'PARAM/FMG 解析阻塞' not in report or '不能用作注入白名单' not in report:
    raise ValueError('Report missing essential limitation')
raw = (BASE / 'candidate_mapping.csv').read_bytes()
if not raw.startswith(b'\xef\xbb\xbf'):
    raise ValueError('Candidate CSV must be UTF-8 BOM')
with (BASE / 'candidate_mapping.csv').open('r', encoding='utf-8-sig', newline='') as stream:
    reader = csv.DictReader(stream)
    candidates = list(reader)
    columns = reader.fieldnames
assert len(candidates) == 30
for c in candidates:
    if None in c:
        raise ValueError('Malformed extra CSV columns')
    assert c['evidence_status'] == 'EXCEL_ONLY_UNVERIFIED'
    assert c['eligible_for_randomization'] == 'false'
    assert c['confidence'] == 'LOW_EXCEL_ONLY'
    for f in ['item_category','item_id','param_table','param_row_id','slot','quantity','probability_weight','get_flag','shop_price','shop_stock','entity_id','item_lot_id']:
        assert c[f] == '', (c['candidate_key'], f)
    assert c['evidence_path'] and c['evidence_position']
    assert c['bundle_verified'] == 'false' and c['world_location_confirmed'] == 'false'

integrity = json.loads((BASE / 'evidence/source_integrity_final.json').read_text(encoding='utf-8'))
# A fresh final hash check verifies originals once more after the report was produced.
for s in integrity['sources']:
    current_hash = sha256(s['absolute_path'])
    current_size = Path(s['absolute_path']).stat().st_size
    if current_hash != s['sha256_initial'] or current_size != s['size_bytes_initial']:
        raise ValueError(f'Source changed at final manifest gate: {s["absolute_path"]}')
    s['sha256_final_manifest_gate'] = current_hash
    s['size_bytes_final_manifest_gate'] = current_size
copy_checks = integrity['input_copy_checks']
for c in copy_checks:
    assert sha256(c['copy']) == c['sha256']
commands = []
for p in sorted((BASE / 'logs').glob('*.command.json')):
    entry = json.loads(p.read_text(encoding='utf-8'))
    commands.append({'log_path': str(p), 'label': entry['label'], 'argv': entry['argv'], 'cwd': entry['cwd'], 'exit_code': entry.get('exit_code'), 'status': entry.get('status') or ('completed' if entry.get('exit_code') == 0 else 'failed'), 'stdout_path': entry.get('stdout_path'), 'stderr_path': entry.get('stderr_path'), 'runner_argv': entry.get('runner_argv')})
artifacts = []
for p in sorted(BASE.rglob('*')):
    if not p.is_file() or p.name == 'manifest.json' or p.name.startswith('008_build_manifest.'):
        continue
    artifacts.append({'relative_path': p.relative_to(WORKSPACE).as_posix(), 'absolute_path': str(p), 'size_bytes': p.stat().st_size, 'sha256': sha256(p)})
manifest = {
    'format_version': 1,
    'investigation': 'baseline-20261010',
    'created_utc': now(),
    'workspace': str(WORKSPACE),
    'mod_root_read_only': str(MOD),
    'status': 'PARTIAL_BASELINE_COMPLETE__PARAM_FMG_PARSE_BLOCKED',
    'requested_route': {'provider': 'opencode-go-native', 'model': 'deepseek-v4.1-flash', 'actual_runtime_route_verified': False},
    'agent_teams_or_subagents_created': False,
    'allowed_direct_write_roots': [str(TOOLS), str(BASE)],
    'safety': {'randomization_implemented': False, 'randomization_executed': False, 'original_mod_tool_processed': False, 'original_mod_modified': False, 'workbook_modified': False, 'save_or_game_files_read_or_modified': False, 'game_launched': False, 'roundtrip_repack_attempted': False, 'deployed': False, 'dependency_downloaded_or_installed': False, 'registry_or_shell_registration_attempted': False, 'environment_or_client_configuration_modified': False, 'incremental_mod_content_mixed': False, 'outside_named_mod_oodle_search_performed': False, 'sandbox_permissions_argument_constraint_deviation': True, 'tool_internal_runtime_cache_write_locations_not_audited': True, 'audit': str(BASE / 'logs/session_tool_audit.json')},
    'tool': {'executable': str(TOOLS / 'WitchyBND.exe'), 'pe_file_version': '3.0.1.0', 'pe_product_version': '3.0.1.0+3e03b31249ce7786078d4432ab02a2ed1ca593c2', 'version_evidence': str(BASE / 'logs/004_exe_metadata.stdout.txt'), 'zip_entries': 19, 'zip_path_traversal_check': 'passed', 'actual_full_help_available': False, 'available_commands_documented_not_successfully_verified': ['--help', '-s (README documented silent flag)'], 'recursive_default': False, 'fmg_param_serialization_successfully_verified': False, 'regulation_decryption_successfully_verified': False, 'internal_regulation_version': None, 'param_definition_version_match': None},
    'environment': {'python_executable': sys.executable, 'python_version': sys.version, 'openpyxl_version': openpyxl.__version__, 'source': 'load_workspace_dependencies bundled runtime'},
    'dependencies': {'native_zstd_present_in_tool_distribution': True, 'oodle_filename_candidate_count_within_allowed_mod': 0, 'krak_text_container_count': 2, 'console_redirection_blocker': 'PromptPlus requires a terminal/console without redirection environment!.', 'conpty_help_job': {'job_id': 'bash-15', 'final_status': 'killed', 'exit_code': None, 'full_stdout_stderr_capture_available': False}},
    'excel': json.loads((BASE / 'evidence/excel_first_sheet_summary.json').read_text(encoding='utf-8')),
    'language': {'excel_first_sheet_actual_language': 'English', 'msg_directory_marker': 'zhocn', 'actual_fmg_content_language_verified': False},
    'source_integrity': {'registered_source_count': len(integrity['sources']), 'all_registered_sources_unchanged': True, 'final_gate_utc': now(), 'sources': integrity['sources'], 'input_copy_checks': copy_checks, 'proof_scope': integrity['proof_scope']},
    'candidate_mapping': {'path': str(BASE / 'candidate_mapping.csv'), 'utf8_bom': True, 'csv_column_count': len(columns), 'rows': len(candidates), 'excel_only_low_confidence_rows': len(candidates), 'verified_category_id_rows': 0, 'verified_reward_slot_rows': 0, 'verified_shop_rows': 0, 'verified_bundle_rows': 0, 'verified_world_location_rows': 0, 'injection_whitelist': False, 'unknown_fields_empty_not_zero': True},
    'roundtrip': json.loads((BASE / 'evidence/roundtrip_test.json').read_text(encoding='utf-8')),
    'commands_completed_before_manifest_gate': commands,
    'authoritative_command_log_glob': str(BASE / 'logs/*.command.json'),
    'manifest_gate_command_log': str(BASE / 'logs/008_build_manifest.command.json'),
    'manifest_gate_log_not_yet_closed_at_manifest_write': True,
    'artifact_hashes': artifacts,
    'artifact_hash_exclusions': ['manifest.json (self-reference)', 'logs/008_build_manifest.* (active current command streams; command.json closes after this script returns)'],
    'primary_deliverables': [str(BASE / 'REPORT.md'), str(BASE / 'manifest.json'), str(BASE / 'candidate_mapping.csv'), str(BASE / 'logs')]
}
save_json(BASE / 'manifest.json', manifest)
# Reopen to establish output JSON syntax and invariants.
check = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
assert check['source_integrity']['all_registered_sources_unchanged']
assert check['candidate_mapping']['injection_whitelist'] is False
print(json.dumps({'manifest_path': str(BASE / 'manifest.json'), 'report_path': str(BASE / 'REPORT.md'), 'csv_path': str(BASE / 'candidate_mapping.csv'), 'logs': str(BASE / 'logs'), 'source_hash_gate': '27/27 unchanged', 'input_copy_hash_gate': '3/3 unchanged', 'candidate_rows': len(candidates), 'verified_rewards': 0, 'csv_bom_and_structure': 'passed', 'manifest_json_reopen': 'passed', 'parse_status': 'blocked'}, ensure_ascii=False))
