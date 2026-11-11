"""Strict experiment/deployment configuration; standard library only."""
import json
from pathlib import Path

DEFAULTS = dict(
    symmetric_king_prior=False,
    king_opportunity=False,
    growing_insurance=0,
    sustained_search=False,
    coverage_drought=0,
    pareto_rescue=False,
    consistent_dispatch_deadline=False,
    home_watch_hold=False,
    home_watch_scoped=False,
    home_watch_boost=False,
    home_watch_sortie=False,
    first_contact_search=False,
    search_takeover_only=False,
    search_transfer_filter=False,
    home_watch_disciplined=False,
    home_watch_release=False,
    home_watch_clear=False,
    home_watch_screen=False,
    duel_contact_patience=False,
    close_duel_continuation=False,
    contact_king_memory=False,
    stalled_field_column=False,
    contact_field_column=False,
    king_contact_throughput=False,
    king_departure_reply=False,
    home_corridor_delivery=False,
    contact_home_insurance=False,
    rearward_recon=False,
    funded_search_column=False,
    opening_discovery_packet=0,
    memory_search_approach=False,
    king_small_collection=False,
    king_marginal_contribution=False,
    corridor_recall_goal=False,
    neutral_fort_insurance=False,
    large_field_columns=False,
    intercept_safety=False,
    contact_guard=0,
    intercept_floor=4,
    disciplined_intercept=False,
    fresh_replan=False,
    efficient_capture=False,
    production_value=240,
    proactive_guard=False,
    topology=False,
    guard_share=18,
    king_campaign=False,
    information=False,
    lookahead=False,
    shared_supply=False,
    stable_commitment=False,
    deadline_defense=False,
    risk_routes=False,
    packet_budget=False,
    continuous=False,
    every_step=False,
    packet_cap=0,
    opening_steps=0,
    stack_mode=False,
    objective_priority=False,
    phase_aware_forts=False,
    rear_producer_supply=False,
    active_reconnaissance=False,
    proactive_exploration=False,
    adaptive_home_reserve=False,
    prefer_producers=False,
    pickup_routes=False,
    hint_weight=84,
    approach_weight=4,
    command_merge=False,
    cost_routes=False,
    adaptive_pressure=False,
    bridge_patience=0,
    contact_share=0,
    post_intercept_guard=False,
    finish_king=False,
    counter_margin=100,
    post_intercept_share=18,
    contact_focus=False,
    capture_packet=1,
    hold_home=False,
    safety_arbitration=False,
    simultaneous_guard=True,
    transport_min=1,
    urgent_intercept_floor=0,
    fog_memory=0,
    base_guard=2,
    funded_only=False,
    surplus_intercept=False,
    fort_bank=False,
    bank_discount=2,
    economic_intercept=False,
    skirmish=False,
    skirmish_cushion=6,
    threat_margin=2,
    conservation_guard=False,
    ledger_margin=3,
    producer_skirmish=False,
    opening_defense=False,
    late_guard=False,
    late_recall=False,
    recall_cap=0,
    recall_floor_first=False,
    recall_goal_hysteresis=False,
    recall_goal_half_floor=False,
    defense_cover=False,
    deadline_convoy=False,
    king_exposure_release=False,
    king_intrusion_counter=False,
    economic_recall_rate=0,
    response_pool=False,
    response_budget=3,
    stagnation_recovery=False,
    stagnation_window=32,
    king_collection=False,
    late_safety=False,
    deadline_safety=False,
    shared_threat=False,
    contact_mobilization=False,
    mobilization_buffer=0,
    fort_packets=False,
    funded_production=False,
    production_budget=6,
    opening_skirmish=False,
    adaptive_skirmish_cushion=False,
    tactical_depth2=False,
    exchange_recovery=False,
    producer_reserve=False,
    recovery_max_producers=0,
    producer_counterstrike=False,
    production_roots=1,
    economic_recall_max_producers=0,
    precontact_insurance=False,
    producer_investment=False,
    investment_guard=8,
    investment_wait=48,
    opening_zero_mobile=False,
    investment_post_guard=False,
    king_bridge=False,
    king_bridge_guard=8,
    mid_field_packets=False,
    investment_dispatch=True,
    rescue_triage=False,
    post_battle_recovery=False,
    bulk_rear_search=False,
    first_producer_priority=False,
    producer_commitment=False,
    first_fort_funded=False,
    opening_zero_radius=12,
    zero_intercept_relief=False,
    mobile_memory=0,
    infeasible_convoy=False,
    convoy_budget=6,
    home_route_packets=False,
    patient_home_intercept=False,
    precontact_guard_one=False,
    home_route_tail=False,
    sparse_rescue_convoy=False,
    skirmish_income_horizon=0,
    first_fort_convoy=False,
    first_fort_commands=16,
    first_fort_preserve_home=False,
    skirmish_home_stock=False,
    frontier_sources=8,
    opening_wait_recon=False,
    opening_policy=False,
    opening_policy_steps=600,
    opening_policy_wait_trigger=False,
    opening_policy_duel_exit=False,
    opening_policy_current_trigger=False,
    opening_policy_search_trigger=False,
    opening_policy_near_contact_fallback=False,
    opening_policy_scout_only=False,
    opening_policy_release_scout=False,
    opening_policy_scout_priority=False,
    opening_policy_scout_claim_priority=False,
    frontier_mixed_sources=False,
    frontier_direct_supplement=False,
    frontier_mobile_packet=False,
    frontier_drought_steps=0,
    frontier_search_max_producers=0,
    frontier_confirmed_handoff=False,
    frontier_handoff_all_targets=False,
    skirmish_adjacent_support=False,
    mobile_departure_steps=0,
    frontier_road_guard=False,
    frontier_route_home_cost=False,
    frontier_ready_suffix_value=False,
    frontier_funded_shortest_paths=False,
    frontier_funded_field_forts_only=False,
    search_reveal_value=False,
    search_reveal_insured=False,
    search_ready_suffix=False,
    search_contact_safety=False,
    king_forward_pressure=False,
    king_pressure_throughput=False,
    king_two_command_strike=False,
    king_idle_field_approach=False,
    king_idle_field_steps=3,
    opening_memory_exchange=False,
    king_merge_approach=False,
    king_stage_opportunity=False,
    king_stage_relative_gain=False,
    post_intercept_repair=False,
    repair_preserve_interception=False,
    mobilize=False,
    indexed_pickup_paths=False,
    contested_fort_budget=False,
    maneuver_sources=0,
    opening_area_steps=0,
    recon_interval=0,
    unified_frontier=False,
    frontier_signed_ledger=False,
    plain_scout_relief=False,
    safe_opening_area_steps=0,
    plain_guard_margin=1,
    opening_area_after_fort=False,
)


def validate(values):
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError('Unknown strategy setting')
    result = dict(DEFAULTS)
    for key, value in values.items():
        if type(value) is not type(DEFAULTS[key]):
            raise ValueError('Invalid type for ' + key)
        if type(value) is int and not 0 <= value <= 4096:
            raise ValueError('Out of range: ' + key)
        if key == 'mobile_memory' and value > 12:
            raise ValueError('Mobile uncertainty is limited to twelve estimated steps')
        if key == 'mobile_departure_steps' and value > 12:
            raise ValueError('Departure warning is limited to twelve legal observations')
        if key == 'convoy_budget' and not 1 <= value <= 8:
            raise ValueError('Rescue collection is limited to one through eight commands')
        if key == 'skirmish_income_horizon' and value > 200:
            raise ValueError('Tactical income valuation is limited to two hundred steps')
        if key == 'first_fort_commands' and not 2 <= value <= 24:
            raise ValueError('First-fort sequence is limited to two through twenty-four commands')
        if key == 'frontier_sources' and not 1 <= value <= 32:
            raise ValueError('Frontier source coverage is limited to one through thirty-two sources')
        if key == 'maneuver_sources' and value and not 8 <= value <= 64:
            raise ValueError('Maneuver departure budget must be zero or eight through sixty-four')
        if key == 'opening_policy_steps' and not 1 <= value <= 800:
            raise ValueError('Opening policy handoff is limited to one through eight hundred observations')
        if key == 'king_idle_field_steps' and not 1 <= value <= 8:
            raise ValueError('Idle field approach is limited to one through eight commands')
        result[key] = value
    if result['repair_preserve_interception'] and not result['post_intercept_repair']:
        raise ValueError('Repair interception relief requires post-intercept repair')
    if result['post_intercept_repair'] and not (result['continuous'] and result['deadline_defense']):
        raise ValueError('Post-interception repair requires the continuous defense arbiter')
    if result['plain_scout_relief'] and not (result['unified_frontier'] and result['frontier_signed_ledger']):
        raise ValueError('Plain scout relief requires the unified signed frontier')
    if result['recall_goal_hysteresis'] and not (result['continuous'] and result['late_recall']
            and result['recall_cap'] > 0 and result['economic_recall_rate'] > 0):
        raise ValueError('Recall goal hysteresis requires bounded continuous late recall')
    if result['recall_floor_first'] and not (result['continuous'] and result['late_recall']
            and result['recall_cap'] > 0 and result['economic_recall_rate'] > 0):
        raise ValueError('Recall floor priority requires bounded continuous late recall')
    if result['plain_guard_margin'] not in (0,1):
        raise ValueError('Ordinary-road extra guard margin must be zero or one')
    if result['plain_guard_margin']==0 and not result['frontier_signed_ledger']:
        raise ValueError('Ordinary-road margin ablation requires the signed frontier ledger')
    if result['safe_opening_area_steps'] and not (result['unified_frontier'] and result['mobilize']):
        raise ValueError('Contact-aware area opening requires unified mode and mobilize')
    if result['safe_opening_area_steps'] > 100:
        raise ValueError('Contact-aware area opening is limited to the first hundred observations')
    if result['king_stage_relative_gain'] and not result['king_stage_opportunity']:
        raise ValueError('Relative stage gain requires the stage opportunity evaluator')
    if result['frontier_signed_ledger'] and not (result['unified_frontier'] and result['mobilize']):
        raise ValueError('Signed frontier ledger requires unified frontier mode and mobilize')
    if result['unified_frontier']:
        if not result['continuous']:
            raise ValueError('Unified frontier requires continuous arbitration')
        if result['opening_area_steps'] or result['recon_interval']:
            raise ValueError('Unified frontier currently supports opening_area_steps=0 and recon_interval=0')
    return result


def load():
    path = Path(__file__).with_name('parameters.json')
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else dict(DEFAULTS)
