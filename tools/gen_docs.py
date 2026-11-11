"""Generate docs/MODULES.md and docs/PARAMETERS.md from the source tree.

Usage (from the repository root):

    python tools/gen_docs.py

The generator only reads local files; it never contacts the Commander-II
platform, and it does not import `Core.py` (which needs the platform SDK).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUP_ORDER = (
    ('platform', '平台入口与适配', (
        'Core.py', 'worker.py', 'bfs_agent.py',
    )),
    ('geo', '几何与配置', (
        'std_geometry.py', 'std_config.py', 'std_parameters.py',
    )),
    ('state', '观测、状态与记忆', (
        'std_state.py', 'std_road_graph.py', 'std_force_belief.py',
        'std_mobility.py', 'std_reserve.py', 'std_threat.py',
        'std_departure_warning.py', 'std_packets.py',
    )),
    ('econ', '经济、扩张与产能', (
        'std_economy.py', 'std_investment.py', 'std_investment_execution.py',
        'std_fort_assembly.py', 'std_neutral_funding.py', 'std_nearby_capital.py',
        'std_nearby_retention.py', 'std_fort_survey.py', 'std_colonize.py',
        'std_expansion.py', 'std_producer.py',
        'std_patience.py', 'std_blind_opening.py', 'std_post_capital_guard.py',
        'std_single_capital_fortress.py', 'std_adjacent_income.py',
        'std_adjacent_threat_relief.py',
    )),
    ('army', '调兵、防守与供给', (
        'std_routing.py', 'std_maneuver.py', 'std_supply.py', 'std_merge.py',
        'std_logistics.py',
        'std_rear_supply.py', 'std_recall_goal.py', 'std_security.py',
        'std_deadline_convoy.py', 'std_deadline_strike.py', 'std_convoy.py',
        'std_corridor.py', 'std_fortress_corridor.py', 'std_recovery.py',
        'std_king_recovery.py', 'std_repair.py', 'std_reinforcement.py',
        'std_rescue_utility.py', 'std_transport_path_guard.py',
        'std_connected_reserve.py', 'std_guard_pool.py', 'std_home_watch.py',
        'std_dispatch_deadline.py', 'std_reversal_recovery.py',
        'std_frontier_handoff.py', 'std_frontier_paths.py',
        'std_frontier_sources.py', 'std_frontier_value.py',
    )),
    ('info', '侦察与信息价值', (
        'std_recon.py', 'std_reconnaissance.py', 'std_search_column.py',
        'std_search_value.py', 'std_main_column.py', 'std_opening.py',
        'std_opening_exchange.py', 'std_stage_value.py', 'std_commitment.py',
    )),
    ('fight', '战斗、攻防与目标排序', (
        'std_combat.py', 'std_defense.py', 'std_skirmish.py',
        'std_skirmish_support.py', 'std_tactical.py', 'std_joint_response.py',
        'std_campaign.py', 'std_objectives.py', 'std_decisions.py',
        'std_multi_front_truce.py', 'std_rival_pressure.py',
        'std_king_pressure.py', 'std_king_tempo.py', 'std_king_bridge.py',
        'std_king_opportunity.py', 'std_king_prior.py',
        'std_response_control.py', 'std_duel_raid_reserve.py',
    )),
    ('special', '特殊地图 314', (
        'std_map314.py', 'std_map314_profile.py', 'std_map314_strategy.py',
    )),
    ('arbiter', '统一仲裁与增强层', (
        'std_continuous.py', 'std_enhancements.py', 'std_opening_policy.py',
    )),
    ('reference', '移植的参考策略（见 PROVENANCE.md）', (
        'std_probe_policy.py', 'std_probe_economy.py', 'std_probe_campaign.py',
    )),
)


def first_doc_line(path):
    """Return the first non-empty line of the module docstring."""
    try:
        source = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return ''
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ''
    doc = ast.get_docstring(tree) or ''
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ''


def line_count(path):
    return len(path.read_text(encoding='utf-8').splitlines())


def modules():
    files = {p.name: p for p in ROOT.glob('*.py')}
    grouped = []
    used = set()
    for key, title, names in GROUP_ORDER:
        rows = []
        for name in names:
            path = files.get(name)
            if path is None:
                continue
            used.add(name)
            rows.append((name, line_count(path), first_doc_line(path)))
        if rows:
            grouped.append((key, title, rows))
    rest = sorted(set(files) - used)
    if rest:
        grouped.append(('other', '其他模块', [
            (n, line_count(files[n]), first_doc_line(files[n])) for n in rest
        ]))
    return grouped


def write_modules(grouped):
    total_files = sum(len(rows) for _, _, rows in grouped)
    total_lines = sum(lines for _, _, rows in grouped for _, lines, _ in rows)
    out = [
        '# 模块清单',
        '',
        '> 本文件由 `tools/gen_docs.py` 自动生成，请勿手工编辑。',
        '',
        '仓库共 **{} 个 Python 模块 / {} 行**（不含测试与工具脚本）。'
        '每个文件的模块文档字符串已概括其职责；这里的表格只摘取首行。'
        .format(total_files, total_lines),
        '',
    ]
    for _, title, rows in grouped:
        out.append('## {}'.format(title))
        out.append('')
        out.append('| 模块 | 行数 | 职责 |')
        out.append('| --- | ---: | --- |')
        for name, lines, summary in rows:
            summary = summary.replace('|', '\\|')
            out.append('| `{}` | {} | {} |'.format(name, lines, summary))
        out.append('')
    (ROOT / 'docs' / 'MODULES.md').write_text('\n'.join(out), encoding='utf-8')


def write_parameters():
    from std_config import DEFAULTS, validate

    params_path = ROOT / 'parameters.json'
    production = json.loads(params_path.read_text(encoding='utf-8'))
    validate(production)

    def fmt(value):
        return '`{}`'.format(json.dumps(value, ensure_ascii=False))

    changed = []
    same = []
    for key in sorted(DEFAULTS):
        default = DEFAULTS[key]
        prod = production.get(key, default)
        row = (key, type(default).__name__, fmt(default), fmt(prod))
        (changed if prod != default else same).append(row)

    out = [
        '# 参数参考',
        '',
        '> 本文件由 `tools/gen_docs.py` 根据 `std_config.py` 与 `parameters.json` '
        '自动生成，请勿手工编辑。',
        '',
        '共 **{}** 个可调参数，其中 **{}** 项在生产配置中与默认值不同，'
        '**{}** 项保持默认。所有参数最终都要经过 `std_config.validate()`：'
        '未知键、类型不符、越界值以及互相冲突的开关组合都会直接抛出 '
        '`ValueError`，不会静默降级。'.format(len(DEFAULTS), len(changed), len(same)),
        '',
        '- 默认值 = `std_config.DEFAULTS`（冻结的狩猎者基线）。',
        '- 生产值 = 仓库根目录 `parameters.json`（本次参赛版本）。',
        '',
        '## 生产配置中启用的项目',
        '',
        '| 参数 | 类型 | 默认值 | 生产值 |',
        '| --- | --- | --- | --- |',
    ]
    for key, kind, default, prod in changed:
        out.append('| `{}` | {} | {} | {} |'.format(key, kind, default, prod))
    out += [
        '',
        '## 生产配置中保持默认的项目',
        '',
        '| 参数 | 类型 | 默认值 | 生产值 |',
        '| --- | --- | --- | --- |',
    ]
    for key, kind, default, prod in same:
        out.append('| `{}` | {} | {} | {} |'.format(key, kind, default, prod))
    out.append('')
    (ROOT / 'docs' / 'PARAMETERS.md').write_text('\n'.join(out), encoding='utf-8')
    return len(DEFAULTS), len(changed), len(same)


def main():
    grouped = modules()
    write_modules(grouped)
    total, changed, same = write_parameters()
    print('docs/MODULES.md  : {} modules'.format(sum(len(r) for _, _, r in grouped)))
    print('docs/PARAMETERS.md: {} parameters ({} changed, {} default)'
          .format(total, changed, same))


if __name__ == '__main__':
    main()
