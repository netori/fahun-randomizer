"""Finish a truthful partial baseline when CLI/decompression are blocked; never randomize."""
from common import *
import collections, csv, re, struct, zipfile

rows = json.loads((BASE / 'evidence/excel_first_sheet_rows.json').read_text(encoding='utf-8'))
summary = json.loads((BASE / 'evidence/excel_first_sheet_summary.json').read_text(encoding='utf-8'))
inventory = json.loads((BASE / 'evidence/mod_structure.json').read_text(encoding='utf-8'))
# Inspect selected incremental ZIP central directories solely for filename collision clues.
selected_zips = [
    MOD.parent / '光荣商人mod增量包（法魂mod专用）/光荣商人mod增量包（9月14日更新v1.2.4）.zip',
    MOD.parent / '哥布林地图增量包（法魂mod专用）/哥布林地图增量包（9月17日更新v2.1.4）.zip',
    MOD.parent / '切换轮盘增量包（法魂mod专用）/切换轮盘增量包（1.4.0汉化版，适配游戏1.17）.zip',
]
conflicts = []
for p in selected_zips:
    if not p.is_file():
        conflicts.append({'absolute_path': str(p), 'status': 'not_found'})
        continue
    meta = record_source(p, 'incremental archive central-directory filenames only; no content extraction or mixing')
    try:
        with zipfile.ZipFile(p, 'r') as z:
            entries = []
            candidates = []
            for item in z.infolist():
                if item.is_dir():
                    continue
                name = item.filename.replace('\\', '/')
                entry = {'name': item.filename, 'size_bytes': item.file_size, 'compressed_size_bytes': item.compress_size, 'crc32': f'{item.CRC:08x}'}
                entries.append(entry)
                lower = name.lower()
                if lower.endswith('/regulation.bin') or lower == 'regulation.bin' or lower.endswith('item_dlc02.msgbnd.dcx') or lower.endswith('menu_dlc02.msgbnd.dcx') or '/msg/zhocn/' in ('/' + lower):
                    candidates.append(entry)
            conflicts.append({'absolute_path': str(p.resolve()), 'sha256': meta['sha256_initial'], 'size_bytes': meta['size_bytes'], 'status': 'central_directory_read_only', 'file_entry_count': len(entries), 'entries': entries, 'possible_same_filename_targets': candidates, 'file_content_compared': False, 'applied': False, 'archive_label_version_not_verified': True})
    except Exception as exc:
        conflicts.append({'absolute_path': str(p), 'status': 'index_read_failed', 'error': repr(exc), 'applied': False})
save_json(BASE / 'evidence/incremental_archive_conflicts.json', conflicts)
# Actual compression markers on copies. No decompression is implemented here.
headers = []
for name in ['item_dlc02.msgbnd.dcx', 'menu_dlc02.msgbnd.dcx']:
    p = BASE / 'inputs/zhocn' / name
    with p.open('rb') as stream:
        h = stream.read(128)
    headers.append({'copy_absolute_path': str(p), 'size_bytes': p.stat().st_size, 'magic_offset_0': h[:4].decode('ascii', 'replace'), 'dcx_header_word_offset_4_hex': f'0x{struct.unpack_from(">I", h, 4)[0]:08x}', 'dcs_magic_offset_24': h[24:28].decode('ascii', 'replace'), 'dcs_word_offset_28': struct.unpack_from('>I', h, 28)[0], 'dcs_word_offset_32': struct.unpack_from('>I', h, 32)[0], 'dcp_magic_offset_36': h[36:40].decode('ascii', 'replace'), 'compression_marker_offset_40': h[40:44].decode('ascii', 'replace'), 'content_decompressed': False, 'language_path_marker': 'zhocn', 'actual_fmg_text_language_verified': False})
possible_oodle = [f for f in inventory['files'] if re.search(r'oo2core|oodle', f['relative_path'], re.I)]
save_json(BASE / 'evidence/compression_dependency_check.json', {'headers': headers, 'specified_mod_root_only': str(MOD), 'oodle_filename_candidates': possible_oodle, 'search_outside_named_mod_performed': False, 'dependency_copied': False, 'native_zstd_distribution_path': str(TOOLS / 'libzstd.dll'), 'zstd_presence_not_krak_decoder_proof': True})

names = collections.defaultdict(list)
for row in rows:
    names[str(row.get('Name') or '').strip()].append(row['excel_row'])
rune_name_rows = [r for r in rows if re.search(r'\brune\b|卢恩', str(r.get('Name') or ''), re.I)]
chinese_name_rows = [r['excel_row'] for r in rows if re.search(r'[\u3400-\u9fff]', str(r.get('Name') or ''))]
chinese_any_rows = [r['excel_row'] for r in rows if re.search(r'[\u3400-\u9fff]', ' '.join(str(r.get(k) or '') for k in ['Name', 'Text', 'Location']))]
variant_name_rows = [r for r in rows if re.search(r'altered|改装', str(r.get('Name') or ''), re.I)]
analysis = {'summary': summary, 'duplicate_exact_names': {n: rs for n, rs in names.items() if n and len(rs) > 1}, 'rune_word_in_name_rows': rune_name_rows, 'chinese_in_name_rows': chinese_name_rows, 'chinese_in_any_first_sheet_cell_rows': chinese_any_rows, 'altered_word_in_name_rows': variant_name_rows, 'actual_param_items_verified': 0, 'actual_rewards_verified': 0, 'actual_world_locations_verified': 0, 'warning': 'This is an Excel-only lead catalogue, not a verified eligibility/ID/reward whitelist.'}
save_json(BASE / 'evidence/excel_lead_analysis.json', analysis)
# Explicit groups below are investigation questions, NOT assertions of real Bundles.
groups = [
    ('excel_starcaller_four_name_cluster', range(443, 447), '四个名称组成的职业套装线索；同Location文字不证明同Lot或4件Bundle'),
    ('excel_volcanist_four_name_cluster', range(451, 455), '四个名称组成的职业套装线索；需要实际同部位和奖励关联证据'),
    ('excel_necromancer_four_name_cluster', range(463, 467), '四个名称组成的职业套装线索；不凭相邻行认定Bundle'),
    ('excel_kaiden_scattered_location_clues', range(6, 10), '分散Location文字线索；获取方式和世界位置未确认'),
    ('excel_scaled_scattered_location_clues', range(14, 18), '分散Location文字线索；不把Location文本转换为Entity ID'),
    ('excel_azur_three_named_pieces', range(193, 196), '仅出现三个Azur命名部件；不是已确认3件套或共享腿部件事实'),
    ('excel_old_sorcerer_generic_leg_clue', [192], '通用命名腿部件的共享风险线索；未确认物品ID或多个套装共同引用'),
    ('excel_preceptor_alternative_head_clue', range(332, 337), '五个名称含额外Mask of Confidence；需区分变体/替代头部，未定位PARAM'),
    ('excel_npc_label_not_shop_proof', [476], 'Location为War Counselor Iji；NPC标签不是ShopLineupParam或商店库存证据'),
]
index = {r['excel_row']: r for r in rows}
fieldnames = ['candidate_key','evidence_status','eligible_for_randomization','confidence','item_category','item_id','name','fmg_name','fmg_file','fmg_entry_id','param_table','param_row_id','slot','quantity','probability_weight_field','probability_weight','get_flag_field','get_flag','shop_price_field','shop_price','shop_stock_field','shop_stock','shop_condition_fields','body_part_verified','body_part_hint_only','group_hint_only','bundle_verified','excel_sheet','excel_row','excel_name_match','excel_location_text','fmg_match','param_located','world_location_confirmed','entity_id','item_lot_id','reward_reference_count','evidence_path','evidence_position','notes']
candidates = []
def part_hint(name):
    if re.search(r'hood|helm|hat|crown|mask', name, re.I): return 'head_name_hint_only'
    if re.search(r'robe|armor|garb|gown', name, re.I): return 'chest_name_hint_only'
    if re.search(r'glove|gauntlet|bracer|manchette|wraps', name, re.I): return 'arms_name_hint_only'
    if re.search(r'boot|greaves|trousers|legwrap', name, re.I): return 'legs_name_hint_only'
    return ''
for group, nums, note in groups:
    for number in nums:
        source = index[number]
        entry = {f: '' for f in fieldnames}
        entry.update({'candidate_key': f'excel_row_{number}', 'evidence_status': 'EXCEL_ONLY_UNVERIFIED', 'eligible_for_randomization': 'false', 'confidence': 'LOW_EXCEL_ONLY', 'name': source.get('Name') or '', 'body_part_hint_only': part_hint(str(source.get('Name') or '')), 'group_hint_only': group, 'bundle_verified': 'false', 'excel_sheet': summary['worksheet_name'], 'excel_row': number, 'excel_name_match': 'SOURCE_CELL_ONLY_NO_FMG_JOIN', 'excel_location_text': source.get('Location') or '', 'fmg_match': 'NOT_PARSED', 'param_located': 'false', 'world_location_confirmed': 'false', 'evidence_path': 'investigation/baseline-20261010/evidence/excel_first_sheet.csv', 'evidence_position': f'Sheet3 (2)!A{number}:C{number}; evidence/excel_first_sheet.csv#L{number}', 'notes': note + '；类别、ID、实际schema字段、价格/库存/flag均未知，空白不是0或默认值'})
        candidates.append(entry)
with output_path(BASE / 'candidate_mapping.csv').open('x', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(candidates)
if (BASE / 'candidate_mapping.csv').read_bytes()[:3] != b'\xef\xbb\xbf':
    raise ValueError('CSV BOM missing')
save_json(BASE / 'evidence/candidate_summary.json', {'candidate_rows': len(candidates), 'verified_id_rows': 0, 'verified_reward_rows': 0, 'verified_bundle_rows': 0, 'excel_only_low_confidence_rows': len(candidates), 'utf8_bom': True, 'not_injection_whitelist': True})
save_json(BASE / 'evidence/roundtrip_test.json', {'status': 'NOT_ATTEMPTED_BLOCKED', 'disposable_copy_created': False, 'content_modified': False, 'repack_command_executed': False, 'game_started': False, 'deployment_performed': False, 'blockers': ['Actual full CLI help unavailable: PromptPlus redirection check; ConPTY attempt cancelled', 'Outer regulation and FMG containers have not been successfully parsed', 'KRAK text container requires legal available compression dependency; none located within the permitted MOD directory', 'Internal regulation/definitions versions and semantic baseline unknown'], 'future_comparison_required': ['container entry IDs/names/order/flags and compression metadata', 'PARAM row IDs and all decoded field values plus schema versions', 'FMG entry IDs/text and null/empty distinction'], 'byte_equality_is_not_required': True})

# Rehash EVERY registered original input after all read-only source work finishes.
registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
integrity = []
for key, source in registry['sources'].items():
    p = Path(key)
    current_size = p.stat().st_size
    current_hash = sha256(p)
    same = current_size == source['size_bytes'] and current_hash == source['sha256_initial']
    source.update({'size_bytes_final': current_size, 'sha256_final': current_hash, 'unchanged': same, 'final_hash_utc': now()})
    integrity.append({'absolute_path': key, 'size_bytes_initial': source['size_bytes'], 'size_bytes_final': current_size, 'sha256_initial': source['sha256_initial'], 'sha256_final': current_hash, 'unchanged': same, 'roles': source['roles']})
save_json(REGISTRY, registry, exclusive=False)
copy_checks = []
for entry in json.loads((BASE / 'evidence/input_copies.json').read_text(encoding='utf-8')):
    current = sha256(entry['copy'])
    copy_checks.append({**entry, 'sha256_final_copy': current, 'unchanged_from_copied_source': current == entry['sha256']})
all_unchanged = all(x['unchanged'] for x in integrity)
save_json(BASE / 'evidence/source_integrity_final.json', {'completed_utc': now(), 'registered_source_count': len(integrity), 'all_registered_sources_unchanged': all_unchanged, 'sources': integrity, 'input_copy_checks': copy_checks, 'proof_scope': 'Only registered actually-read inputs, not every file in the machine or unexpanded MOD'})

# REPORT links use full workspace/absolute paths; narrative avoids inventing fields/IDs.
def link(label, p, lines=''):
    suffix = '#' + lines if lines else ''
    return f'[{label}](<{Path(p).as_posix()}{suffix}>)'
L = lambda label, rel, lines='': link(label, BASE / rel, lines)
modlink = lambda label, rel, lines='': link(label, MOD / rel, lines)
toollink = lambda label, rel, lines='': link(label, TOOLS / rel, lines)
cmds = []
for p in sorted((BASE / 'logs').glob('*.command.json')):
    item = json.loads(p.read_text(encoding='utf-8'))
    cmds.append(f"### {item['label']}\n\n精确子进程命令：`{item.get('windows_command_line', '')}`。工作目录：`{item.get('cwd', '')}`。退出码：`{item.get('exit_code') if item.get('exit_code') is not None else '未知（被取消，不能视为成功）'}`。完整参数/终端状态见 {link(p.name, p)}。" + (f" 原始 stdout 见 {link('stdout', item['stdout_path'])}；stderr 见 {link('stderr', item['stderr_path'])}。" if item.get('stdout_path') else ' 完整流捕获不可用，工具行观察及取消原因已保留。'))
pack_lines = []
for item in conflicts:
    targets = [x['name'] for x in item.get('possible_same_filename_targets', [])]
    pack_lines.append(f"`{Path(item['absolute_path']).name}`：状态 `{item['status']}`；同名目标线索 {json.dumps(targets, ensure_ascii=False)}。仅中央目录，不作字节/参数内容比较，不代表已经合并或已生效。")
report = f'''# 法魂 MOD 独立基础调查（2026-10-10）

## 结论与状态

**状态：基础文件核验完成；PARAM/FMG 解析阻塞；无已证实奖励映射。** 本轮没有实现或运行随机化，没有回包、部署或启动游戏，没有修改原 MOD、存档、游戏或资料表。所有主动生成的文件均位于获准的工具目录或本调查目录。源文件完整性结论：**已登记并实际读取的 {len(integrity)} 个源文件全部前后大小与 SHA256 一致：{str(all_unchanged).lower()}**，证明范围见 {L('最终完整性记录', 'evidence/source_integrity_final.json')}；这不等于全机器所有文件的零写入证明。

工具 ZIP 校验后解压成功不是资源解包成功；资源解包成功也不等于游戏兼容验证。本轮三份必要原件已经复制，但未对它们执行解包命令，因此没有内部 PARAM 行、FMG entry 或游戏运行结果。{L('候选映射CSV', 'candidate_mapping.csv')} 有 {len(candidates)} 条 **Excel-only、LOW、eligible=false** 的线索，没有任何已证实类别+ID、奖励slot或Bundle。该 CSV 不能用作注入白名单。

用户请求的路由为 `provider=opencode-go-native, model=deepseek-v4.1-flash`；本调查不能从提示词或本地数据证明宿主实际模型路由，未宣称已切换模型。未创建 Agent Teams、teammates 或子代理，只向指定父代理发送调查事实。

## 边界与操作审计

当前工作区用 `pwd` 核实为 `F:/game/studygame/elden ring/THE_COVERAGE-随机开发/随机mod`。开始时 `tools/witchybnd-3.0.1.0/` 与 `investigation/baseline-20261010/` 均不存在；新建脚本/日志/输出使用排他创建，不覆盖不明文件。未删除或移动任何原件，未注册右键/外壳，未主动改注册表、环境变量或客户端配置，未下载或安装依赖。

**请求参数层偏差必须披露：** 最初两次目录核验工具请求因 `sandbox_permissions`/justification 参数被拒绝，未执行；后续若干 bash 请求仍携带与当前 `danger-full-access` 模式相等的字段，未提升权限，但这不符合用户“禁止设置该字段”的要求。不得据此声称所有执行参数完全合规。详情及非包装器命令的 stdout/stderr/退出码见 {L('工具层补充审计', 'logs/session_tool_audit.json')}。可执行工具的内部临时运行时缓存落点未独立审计；源哈希证明不能扩张成全机器零缓存写入保证。

没有扫描其他游戏、用户文档、浏览器或存档。读到启动脚本中的游戏 exe 路径后，仅作为文字证据保存，没有跟随该路径。增量包仅为冲突线索读取三个已列明 ZIP 的中央目录，不解出、不混入本体、不比较或执行其成员。

## 输入、路径与版本

### 工具与压缩包

源工具包：{link('WitchyBND ZIP', WORKSPACE / 'WitchyBND-3.0.1.0-win-x64.zip')}，48,308,252 字节，SHA256 `a3e6b2a0f7eac13f5e83b6602a1149322439c0662baa140ecdd84be28af50364`。19 个 ZIP 条目均先检查绝对路径、驱动器/冒号、`..`、符号链接和大小预算；无路径穿越与大小预算异常。全部分发文件在读取或执行前登记路径、大小与哈希。ZIP 条目/CRC/落点见 {L('ZIP检查清单', 'evidence/tool_zip_entries.json')}。

{toollink('WitchyBND.exe', 'WitchyBND.exe')} 的 PE FileVersion 为 **3.0.1.0**，ProductVersion 为 **3.0.1.0+3e03b31249ce7786078d4432ab02a2ed1ca593c2**，不是仅相信 ZIP 文件名。版本读取证据见 {L('版本输出', 'logs/004_exe_metadata.stdout.txt', 'L1-L6')}。工具哈希：`00aa5b321d5af0179d3c9154a48d2ab3bb55772eaf624a439cc5f6ad4e21982b`。

已用 read 工具读取 {toollink('README', 'README.md', 'L7-L18')} 和 {toollink('appsettings.json', 'appsettings.json', 'L1-L20')}。README 宣称支持 DCX、BND4、FMG、PARAM 等；这是文档能力，未在本数据上验证成功。已证实的文档入口是 `--help`，以及 README 已文档化的 `-s` 静默选项，不据此猜测其他参数。PARAM/FMG XML 的实际输出结构、regulation 解密、递归与回包语义尚未得到实际帮助/成功结果核验。

配置默认 `Recursive=false`、`Offline=false`、`Parallel=true`、`PauseOnError=true`、`ParamCellStyle=Attribute`、`ParamDefaultValueThreshold=0.8`、`BackupMethod=OverwriteAlways`。未修改分发配置。README 关于“指定输出位置会写 sourcePath 并回包写回原位置”的说明见 {toollink('README:668–673', 'README.md', 'L668-L673')}，因此本轮不使用输出位置参数来直接处理原 MOD。

### 本体结构与真正的候选资源

仅枚举指定本体的名称与stat元数据，得到 {inventory['file_count']} 个文件；全结构清单见 {L('本体结构', 'evidence/mod_structure.json')}，未全量解包。找到的实际主候选是 {modlink('mod/regulation.bin', 'mod/regulation.bin')}，2,977,120 字节，SHA256 `cab62c7f839706e4373b38b94f3b2aa2ae99872146790497b4e08fb84cfea6c6`。根目录备份名 `regulation.bin.prev` 不被当成主候选，没有读取其内容或复制。

文本主候选为 {modlink('简中item容器', 'mod/msg/zhocn/item_dlc02.msgbnd.dcx')}（365,049 字节，SHA256 `d7441782f05c4142078a62f7105949e44b569070758d56130074704e4b46921f`）与 {modlink('简中menu容器', 'mod/msg/zhocn/menu_dlc02.msgbnd.dcx')}（505,355 字节，SHA256 `1935acdb09fce59182bf6d6a55608c94fb79f56fbc13a8c1bfc54aeb284a3231`）。目录语言标识为 `zhocn`，只能认定“简体中文候选”；未解开 FMG，**不能声称实际所有文本已核实为简中**。其他语言与 `.bak` 没有混入。

只复制上述三个主候选到 {L('regulation输入副本', 'inputs/regulation.bin')}、{L('item输入副本', 'inputs/zhocn/item_dlc02.msgbnd.dcx')}、{L('menu输入副本', 'inputs/zhocn/menu_dlc02.msgbnd.dcx')}，复制时均比对源哈希，最终副本也再次比对，见 {L('复制记录', 'evidence/input_copies.json')}。没有直接向原 MOD 路径运行 WitchyBND。

本体 {modlink('version.txt', 'version.txt', 'L1')} 的文本是 `3.0.2.0`，仅证明此文件中的声明。{modlink('启动脚本文字', 'Start_Convergence_YAFSML.bat', 'L8-L8')} 中声明的游戏路径亦只是配置文字；目录中的 `1.17.1` 不证明已验证游戏/参数版本。regulation 头部最前 16 字节为零，后续并非已读取的 BND/PARAM 明文；未解密，因此**内部 regulation version、PARAM dataVersion、definitions匹配全部未知**。

### Excel首工作表重新核验

来源 {link('法魂资料整合表', WORKSPACE / '法魂资料整合表.xlsx')}，282,013 字节，SHA256 `59f2d0a64981286dc479ccd37015de0e45b28f5932c5d6ad698eccd400881b89`。已先加载 `office-xlsx`，并使用 load_workspace_dependencies 返回的捆绑 Python 和 openpyxl **{summary['openpyxl_version']}**；read_only=True、data_only=False，只遍历 worksheet index 0。

首表确为 **Sheet3 (2)**，表头 **Name / Text / Location**。样式维度 max_row=1000，不等于1000条数据；实有 **611** 条非空条目，**104** 条 Location 空白，首表数字单元格为 **0**、公式为 **0**。Name/Text/Location 中中文行计数为 **{len(chinese_any_rows)}**；实读内容为英文。Name 中以独立单词 `Rune` 或“卢恩”查找命中 **{len(rune_name_rows)}**，不能将装备说明里的“rune gain”当成职业法术卢恩。此结果只针对首表，不推及其他工作表。

首表原值逐条保存在 {L('首表CSV', 'evidence/excel_first_sheet.csv')}（UTF-8 BOM）与 {L('首表JSON', 'evidence/excel_first_sheet_rows.json')}；统计与精确重复名称分析见 {L('首表统计', 'evidence/excel_first_sheet_summary.json')} 和 {L('线索分析', 'evidence/excel_lead_analysis.json')}。其他工作表只读取元数据名称，未读取其值。表中的地名和英文名称不是数字物品ID、Entity ID或ItemLot ID。

## 解析与依赖阻塞

`WitchyBND.exe --help` 和 `WitchyBND.exe -s --help` 均在普通重定向执行环境退出 **1**，stdout 均为 `PromptPlus requires a terminal/console without redirection environment!.`，stderr为空。不是解析成功，也不能把“工具存在/可启动”当作CLI已确认。

随后做一次仅使用系统 Windows ConPTY 的承载适配，仍观察到相同错误并挂起，任务 `bash-15` 已取消且收集 killed 状态。不进入无参数菜单、不发送交互输入、不重复同条件运行。该次完整 stdout/stderr 未成功落盘，真实退出码未知；不能伪造为0或1，详见 {L('取消命令记录', 'logs/006_witchy_console_help.command.json')}。

两份文本输入副本的头部均实际标明 **DCX / DCP KRAK**，偏移与原始header字段见 {L('压缩依赖检查', 'evidence/compression_dependency_check.json')}。指定本体目录文件名中没有 `oo2core`/`Oodle` 候选；工具包也没有 Oodle DLL，只有 {toollink('libzstd.dll', 'libzstd.dll')}（已登记哈希）。ZSTD库存在不能证明可解KRAK。README 记载 Oodle自动寻找Steam游戏目录的行为，见 {toollink('README:518–523', 'README.md', 'L518-L523')}；为遵守“不扫描其他游戏”，不执行可能触发自动寻找的解包请求。未下载、安装或从系统目录取依赖。

优先目标 `ItemLotParam_map`、`ItemLotParam_enemy`、`ShopLineupParam`、`EquipParamProtector`、`EquipParamGoods` 仍是**待读取目标**，不是已验证存在/已解析表。没有 PARAM/FMG XML 产物；没有删除清单/XML/未知成员。未因格式或schema不匹配绕开命名，未自写解密/随机化替代实现。

## 基础候选样例（只有Excel证据）

**四部件职业套装线索**：Starcaller（443–446行）、Volcanist（451–454行）、Necromancer（463–466行）。英文名称与首表说明/Location实读，可用于后续定点找FMG和参数，但目前不能称为完整4件 Bundle；同地名、同文字、相邻四行都不证明同Lot、同奖励或原子领取。证据见 {L('Starcaller/Volcanist样例', 'evidence/excel_first_sheet.csv', 'L443-L454')}、{L('Necromancer样例', 'evidence/excel_first_sheet.csv', 'L463-L466')}。

**分散套装线索**：Kaiden（6–9行）和Scaled（14–17行）的Location文字分别不同，可作为分散获取的调查问题；尚未证实实际世界对象、地图坐标或事件调用。证据见 {L('Kaiden/Scaled样例', 'evidence/excel_first_sheet.csv', 'L6-L17')}。

**普通完整职业法术卢恩/分半幽影卢恩**：无已证实样例。首表没有Rune命名条目，FMG与EquipParamGoods未解开，因此未找到可追溯的完整职业法术卢恩、幽影两半中间物或完整版奖励指向；不是认定这些物品不存在。未来只让完整版入候选，两半中间物排除；本次不改事件、配方或对话，不自动认定 RecipeParam/TalkParam 存在。

**商店奖励**：没有读取 ShopLineupParam，故没有已证实价格/库存/出售条件样例。首表476行只写 `War Counselor Iji`，这不是商店奖励证明。`Nomadic Merchant's ...` 的物品名也不是商店出售证明。{L('NPC标签样例', 'evidence/excel_first_sheet.csv', 'L476')} 保留为低置信调查线索，所有商店字段留空。

候选CSV中 item_category/item_id/param_table/param_row_id/slot/quantity/probability/get_flag/shop各字段都空白；空白表示未知，**不是0、默认值或无条件**。body_part_hint_only来自英文名称，body_part_verified留空。每条线索都有首表单元格位置、证据路径、confidence与eligible=false。字段名未声称来自尚未读取的schema。

## 必须分开的风险

### 共享部件

192行 `Old Sorcerer's Legwraps` 为通用名称，193–195行有三个Azur名称部件，见 {L('通用腿与Azur线索', 'evidence/excel_first_sheet.csv', 'L189-L195')}。这足以提示“不要按四行机械分组”，但**不能证明同一数字物品ID被多个职业Bundle共享**。实际 EquipParamProtector行、FMG ID和各奖励引用需联合确认。

### 3件套/缺部件

首表Azur只有三个连续的专属名称，Traveler's三个名称在387–389行；可能为3件套、共享第四件或资料表漏项，本轮不能选择其中一种解释。Snow Witch在首表383–386行反而有四个名称（含Gloves），不得套用原版游戏或其他版本的3件常识。证据见 {L('套装缺项线索', 'evidence/excel_first_sheet.csv', 'L383-L391')}。

### 改装/替代变体

332–336行含Preceptor四个名称和额外 `Mask of Confidence`，是替代头/变体核验线索，不是PARAM变体事实。Name中Altered/改装命中 {len(variant_name_rows)}，不能证明MOD不存在改装版本；真实 ID、部位、变体引用均未知。证据见 {L('Preceptor线索', 'evidence/excel_first_sheet.csv', 'L332-L336')}。

### 目标Lot多引用与领取状态

没有展开地图、事件、ESD或配方，未确认 ItemLotParam 行被多少个实体/事件引用、是否复用、是否重复可领取、是否有状态条件或奖励flag。未来“一Lot只改目标slot”需先读取整个Lot保持其他slot/类别/数量/权重/flag不变，不能因库存1推断敌人掉落单次。Entity ID、ItemLot ID、物品ID分别建列，不得混用。

### 数字ID与类别字段

不同装备/Goods类别之间的数字空间和category字段未核实。未来若实际schema必须同时携带物品类别，不能为迎合“只改ID”隐去这一事实；同部位装备替换亦必须依据真实schema字段，而不是CSV名称猜测。shop库存1与价格/出售flag/状态条件需要单独实读，不能从用户目标当成既有数据。

### 增量MOD同文件冲突

{chr(10).join(pack_lines)}

具体ZIP中央目录、条目大小、CRC与源哈希见 {L('增量包冲突线索', 'evidence/incremental_archive_conflicts.json')}。只匹配文件名/目标路径，未比较成员内容；即使同名也不直接证明语义冲突，未发现同名也不能证明没有事件/脚本间接冲突。没有把这些包作为本体基线。

## 职业说明书FMG与双向映射

职业说明书FMG内部文件名与entry ID目前**未知**，没有给出假样例。只定位到 `zhocn` 的item/menu外层候选，未证明指南在哪个容器、哪个FMG或语言实际内容。后续应先用真实FMG entry和文字找到职业路线/装备说明，再与参数物品+奖励关联；Excel英文名称不能自动与中文FMG精确连接。

应分别生成“位置→当前物品/Bundle”与“物品/Bundle→位置”两种映射，保留多值关系与证据/不确定性；位置节点必须来自真实世界对象与奖励引用，不是仅从Location地名派生。指南定点更新职业说明entry，不全局替换物品名称或所有FMG相同文本。尚未展开地图/事件，所以不能证明世界位置唯一性或完整依赖闭包。

## 零内容修改回包复验

**未执行，阻塞而非失败产品。** 没有建立disposable回包副本，因为外层未成功解析、内部版本和XML语义未知、KRAK依赖不齐。完整记录见 {L('回包试验状态', 'evidence/roundtrip_test.json')}。没有删除原件或部署试验产物，没有启动游戏。

未来最小试验应在另一份disposable副本保留全部原容器成员和清单/XML，零语义修改回包，然后再解析，比对容器条目ID/名字/顺序/flags、PARAM所有行/字段/版本、FMG所有entry文本及空字符串/null区别。压缩/加密后字节不同不自动算失败，必须以解码语义和容器结构为判断。解析成功仍不是游戏兼容性证明。

## 下一步最小测试（本轮没有执行）

先解决正式非交互CLI/原生控制台承载与合法现有Oodle依赖的供给位置；不得让自动Steam扫描扩大本轮边界，亦不通过右键注册、环境变量或安装依赖绕过。依赖需用户或主代理在明确获准路径提供，之后重新登记路径/大小/SHA256。

随后仍只对三份输入的新工作副本执行外层展开，确认内部regulation版本与definitions版本；schema不匹配就停止该环节，不强行按旧字段读取。外层成功后只对优先五个PARAM和必要中文FMG转可读格式，保留全部容器清单/元数据；先验证一个4件Bundle、一个分散部件、一个完整职业法术卢恩和一个商店条目的真实类别+ID/奖励slot/flag/数量/权重。

再核查Lot多引用、状态和位置唯一性；未读取地图/事件时继续标未知。最后才做disposable零修改回包再解析语义比较。用户所述未来随机化规则是需求边界，不是本次实现或已验证可行性结论。

## 精确命令与日志

本轮常规子进程全部记录argv、Windows精确命令行、工作目录、stdout、stderr、退出码和时间。初始pwd/路径核验及被拒参数请求见 {L('会话补充审计', 'logs/session_tool_audit.json')}。ConPTY取消状态和流捕获缺失如实注明，不视为命令通过。

{chr(10).join(cmds)}

收尾脚本与manifest生成命令的日志将在 {L('日志目录', 'logs')} 内继续保存；精确命令索引为 `logs/*.command.json`。日志命令成功只证明脚本的记录/统计动作完成，不证明资源解析成功。

## 交付与完整性

主要交付是 {L('REPORT', 'REPORT.md')}、{L('manifest', 'manifest.json')}、{L('候选映射CSV', 'candidate_mapping.csv')} 与 {L('logs', 'logs')}。辅助脚本只做哈希、ZIP安全解压/索引、首表读取、复制、压缩头检查、证据统计与日志，没有随机化功能。

最终源哈希结果见 {L('source_integrity_final', 'evidence/source_integrity_final.json')}：{len(integrity)} 个源文件全部未变，三份输入副本也与复制时源哈希一致。未读取的本体文件不在内容完整性证明范围中。当前没有已证实PARAM/FMG奖励候选，没有游戏兼容验证结果；继续实现前必须解除上述阻塞并补齐实际数据证据。
'''
with output_path(BASE / 'REPORT.md').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(report)
print(json.dumps({'status': 'partial_baseline_parse_blocked', 'candidate_rows': len(candidates), 'verified_param_rows': 0, 'registered_source_count': len(integrity), 'all_registered_sources_unchanged': all_unchanged, 'copies_unchanged': all(x['unchanged_from_copied_source'] for x in copy_checks), 'incremental_indices': [{'name': Path(x['absolute_path']).name, 'status': x['status'], 'same_filename_target_count': len(x.get('possible_same_filename_targets', []))} for x in conflicts], 'report_path': str(BASE / 'REPORT.md')}, ensure_ascii=False))
if not all_unchanged:
    raise SystemExit(2)
