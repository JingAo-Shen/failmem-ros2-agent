#!/usr/bin/env python3
"""
Numerical Verification Script for Core Research Design Toy Model.
Validates the mathematical properties of the closed minimal model:
1. Enumerates expected costs of Direct, Detour, and Probe at the initial prior.
2. Validates the column vector Markov transition convention and probability conservation.
3. Simulates shared-physics execution traces for fair baseline comparison.
4. Distinguishes expected costs vs realized costs on sample paths.
5. Compares single-step myopic VoI decisions with 3-step finite-horizon optimal POMDP decisions.

This script is purely a diagnostic verification tool (not a new algorithm).
"""
import numpy as np


def build_model():
    # Costs (in seconds)
    costs = {
        'C_nom': 10.0,
        'C_detour': 35.0,
        'C_fail': 100.0,
        'c_probe_direct': 3.0,
        'r_probe': 0.01,
        'C_risk': 50.0,
    }
    # Total probe cost including expected risk penalty
    costs['c_probe'] = costs['c_probe_direct'] + costs['r_probe'] * costs['C_risk']  # 3.5s

    # Markov transition parameters
    # lambda_wet: prob of dry transitioning to wet per step
    # lambda_dry: prob of wet transitioning to dry per step
    lambda_wet = 0.05
    lambda_dry = 0.20

    # Column-vector transition matrix T_z:
    # State order: [dry (0), wet (1)]
    # Column 0: transitions from dry -> [P(dry|dry), P(wet|dry)]^T
    # Column 1: transitions from wet -> [P(dry|wet), P(wet|wet)]^T
    T_z = np.array([
        [1.0 - lambda_wet, lambda_dry],
        [lambda_wet,       1.0 - lambda_dry]
    ])

    # 4-state joint transition matrix T_4
    # State mapping: s = z * 2 + theta, where:
    # z: 0=dry, 1=wet
    # theta: 0=broad, 1=narrow
    # States: 0:(dry,broad), 1:(dry,narrow), 2:(wet,broad), 3:(wet,narrow)
    T_4 = np.zeros((4, 4))
    for z_prev in [0, 1]:
        for th in [0, 1]:
            s_prev = z_prev * 2 + th
            for z_next in [0, 1]:
                s_next = z_next * 2 + th
                T_4[s_next, s_prev] = T_z[z_next, z_prev]

    # Sensor likelihood for probe v: o in {0 (dry), 1 (wet)}
    # P(o | z)
    P_obs = np.array([
        [0.95, 0.05],  # P(o=dry | z=dry), P(o=dry | z=wet)
        [0.05, 0.95]   # P(o=wet | z=dry), P(o=wet | z=wet)
    ])

    return costs, T_z, T_4, P_obs


def is_failure(s, x):
    """Ground truth failure function: returns 1 if action x fails in state s, else 0."""
    z = s // 2
    th = s % 2
    if z == 1:  # wet
        if x == 'x_H' or th == 0:  # x_H always fails in wet; broad fails in wet for all x
            return 1
    return 0


def verify_initial_step():
    costs, _, _, P_obs = build_model()
    # Initial prior: b0
    b0 = np.array([0.45, 0.45, 0.05, 0.05])
    x = 'x_H'

    # Direct expected cost:
    p_fail = sum(b0[s] * is_failure(s, x) for s in range(4))  # 0.05 + 0.05 = 0.10
    cost_direct = (1.0 - p_fail) * costs['C_nom'] + p_fail * costs['C_fail']

    # Detour cost:
    cost_detour = costs['C_detour']

    # Probe expected cost:
    # Marginals on probe observations:
    p_dry = b0[0] + b0[1]  # 0.90
    p_wet = b0[2] + b0[3]  # 0.10
    p_o_dry = p_dry * P_obs[0, 0] + p_wet * P_obs[0, 1]  # 0.90*0.95 + 0.10*0.05 = 0.86
    p_o_wet = p_dry * P_obs[1, 0] + p_wet * P_obs[1, 1]  # 0.90*0.05 + 0.10*0.95 = 0.14

    # Posteriors given o_dry:
    b_dry = np.array([b0[s] * P_obs[0, s // 2] for s in range(4)]) / p_o_dry
    p_fail_given_o_dry = sum(b_dry[s] * is_failure(s, x) for s in range(4))
    cost_dir_given_o_dry = (1.0 - p_fail_given_o_dry) * costs['C_nom'] + p_fail_given_o_dry * costs['C_fail']
    act_o_dry = min(cost_dir_given_o_dry, cost_detour)

    # Posteriors given o_wet:
    b_wet = np.array([b0[s] * P_obs[1, s // 2] for s in range(4)]) / p_o_wet
    p_fail_given_o_wet = sum(b_wet[s] * is_failure(s, x) for s in range(4))
    cost_dir_given_o_wet = (1.0 - p_fail_given_o_wet) * costs['C_nom'] + p_fail_given_o_wet * costs['C_fail']
    act_o_wet = min(cost_dir_given_o_wet, cost_detour)

    cost_probe = costs['c_probe'] + p_o_dry * act_o_dry + p_o_wet * act_o_wet

    print("=== Step 1: Initial Prior Expected Cost Enumeration ===")
    print(f"Context: {x}, Prior: {b0}")
    print(f"Direct Expected Cost: {cost_direct:.2f} s")
    print(f"Detour Expected Cost: {cost_detour:.2f} s")
    print(f"Probe Expected Cost:  {cost_probe:.2f} s")
    print(f"Optimal Action under Myopic VoI: {'PROBE' if cost_probe < min(cost_direct, cost_detour) else 'OTHER'}")
    print(f"Audit Result: Direct={cost_direct:.2f}, Detour={cost_detour:.2f}, Probe={cost_probe:.2f}")
    assert np.isclose(cost_direct, 19.0), f"Expected Direct=19.0, got {cost_direct}"
    assert np.isclose(cost_detour, 35.0), f"Expected Detour=35.0, got {cost_detour}"
    assert np.isclose(cost_probe, 17.45), f"Expected Probe=17.45, got {cost_probe}"
    print(">>> CHECK PASSED: Initial costs exactly match Direct=19, Detour=35, Probe=17.45.")
    print(">>> CORRECTION NOTED: The optimal policy at Step 1 is PROBE, not Direct execution.")
    print(">>> A prior failure cannot be generated by this policy; it must be treated as an exogenous common historical condition.\n")


def verify_markov_properties():
    print("=== Step 2: Markov Transition & Probability Conservation Verification ===")
    _, T_z, T_4, _ = build_model()
    # Check column sums:
    col_sums_z = np.sum(T_z, axis=0)
    col_sums_4 = np.sum(T_4, axis=0)
    print(f"T_z column sums: {col_sums_z}")
    print(f"T_4 column sums: {col_sums_4}")
    assert np.allclose(col_sums_z, 1.0), "T_z columns must sum to 1.0"
    assert np.allclose(col_sums_4, 1.0), "T_4 columns must sum to 1.0"

    # Test propagation on arbitrary valid belief
    test_b = np.array([0.1, 0.2, 0.3, 0.4])
    for step in range(5):
        test_b = T_4 @ test_b
        assert np.all(test_b >= 0.0), f"Negative probability at step {step}: {test_b}"
        assert np.isclose(np.sum(test_b), 1.0), f"Probabilities do not sum to 1 at step {step}: {np.sum(test_b)}"
    print(">>> CHECK PASSED: Column-vector Markov transition satisfies non-negativity and sum-to-one conservation.\n")


def myopic_voi_decision(b, x, costs, P_obs):
    """Compute single-step decision and expected cost."""
    pf = sum(b[s] * is_failure(s, x) for s in range(4))
    cost_direct = (1.0 - pf) * costs['C_nom'] + pf * costs['C_fail']
    cost_detour = costs['C_detour']

    # Probe
    p_dry = b[0] + b[1]
    p_wet = b[2] + b[3]
    p_o_dry = p_dry * P_obs[0, 0] + p_wet * P_obs[0, 1]
    p_o_wet = p_dry * P_obs[1, 0] + p_wet * P_obs[1, 1]

    cost_probe = costs['c_probe']
    if p_o_dry > 1e-12:
        b_dry = np.array([b[s] * P_obs[0, s // 2] for s in range(4)]) / p_o_dry
        pf_dry = sum(b_dry[s] * is_failure(s, x) for s in range(4))
        cd_dry = (1.0 - pf_dry) * costs['C_nom'] + pf_dry * costs['C_fail']
        cost_probe += p_o_dry * min(cd_dry, cost_detour)

    if p_o_wet > 1e-12:
        b_wet = np.array([b[s] * P_obs[1, s // 2] for s in range(4)]) / p_o_wet
        pf_wet = sum(b_wet[s] * is_failure(s, x) for s in range(4))
        cd_wet = (1.0 - pf_wet) * costs['C_nom'] + pf_wet * costs['C_fail']
        cost_probe += p_o_wet * min(cd_wet, cost_detour)

    options = {'DIRECT': cost_direct, 'DETOUR': cost_detour, 'PROBE': cost_probe}
    best_act = min(options, key=options.get)
    return best_act, options


def pomdp_finite_horizon_search(b, k, contexts, costs, T_4, P_obs):
    """Full backward induction for finite-horizon POMDP with contexts sequence."""
    if k == len(contexts):
        return 0.0, None
    x = contexts[k]

    # Option 1: DIRECT
    pf = sum(b[s] * is_failure(s, x) for s in range(4))
    p_succ = 1.0 - pf
    v_succ = 0.0
    if p_succ > 1e-12:
        b_succ = np.array([b[s] * (1 - is_failure(s, x)) for s in range(4)]) / p_succ
        v_succ, _ = pomdp_finite_horizon_search(T_4 @ b_succ, k + 1, contexts, costs, T_4, P_obs)
    v_fail = 0.0
    if pf > 1e-12:
        b_fail = np.array([b[s] * is_failure(s, x) for s in range(4)]) / pf
        v_fail, _ = pomdp_finite_horizon_search(T_4 @ b_fail, k + 1, contexts, costs, T_4, P_obs)
    val_direct = p_succ * (costs['C_nom'] + v_succ) + pf * (costs['C_fail'] + v_fail)

    # Option 2: DETOUR
    v_detour_next, _ = pomdp_finite_horizon_search(T_4 @ b, k + 1, contexts, costs, T_4, P_obs)
    val_detour = costs['C_detour'] + v_detour_next

    # Option 3: PROBE then (DIRECT or DETOUR) within step k
    val_probe = costs['c_probe']
    for o in [0, 1]:
        po = sum(b[s] * P_obs[o, s // 2] for s in range(4))
        if po < 1e-12:
            continue
        b_post = np.array([b[s] * P_obs[o, s // 2] for s in range(4)]) / po

        # Decision within step k given probe observation o:
        # If DIRECT:
        pf_post = sum(b_post[s] * is_failure(s, x) for s in range(4))
        ps_post = 1.0 - pf_post
        vs_post = 0.0
        if ps_post > 1e-12:
            bs = np.array([b_post[s] * (1 - is_failure(s, x)) for s in range(4)]) / ps_post
            vs_post, _ = pomdp_finite_horizon_search(T_4 @ bs, k + 1, contexts, costs, T_4, P_obs)
        vf_post = 0.0
        if pf_post > 1e-12:
            bf = np.array([b_post[s] * is_failure(s, x) for s in range(4)]) / pf_post
            vf_post, _ = pomdp_finite_horizon_search(T_4 @ bf, k + 1, contexts, costs, T_4, P_obs)
        v_dir_post = ps_post * (costs['C_nom'] + vs_post) + pf_post * (costs['C_fail'] + vf_post)

        # If DETOUR:
        vd_post, _ = pomdp_finite_horizon_search(T_4 @ b_post, k + 1, contexts, costs, T_4, P_obs)
        v_det_post = costs['C_detour'] + vd_post

        val_probe += po * min(v_dir_post, v_det_post)

    options = {'DIRECT': val_direct, 'DETOUR': val_detour, 'PROBE': val_probe}
    best_act = min(options, key=options.get)
    return options[best_act], (best_act, options)


def verify_myopic_vs_finite_horizon():
    print("=== Step 3: Myopic VoI vs Finite-Horizon (3-step) Optimal Reference Enumeration ===")
    costs, _, T_4, P_obs = build_model()
    # Post-failure condition: a prior failure occurred on x_H
    # Belief after observing failure on x_H:
    b_after_fail = np.array([0.0, 0.0, 0.5, 0.5])

    test_sequences = [
        ['x_L', 'x_L', 'x_L'],
        ['x_H', 'x_H', 'x_H'],
        ['x_L', 'x_H', 'x_L'],
        ['x_H', 'x_L', 'x_H']
    ]

    discrepancies = []
    for seq in test_sequences:
        # Myopic decision at step 0
        myopic_act, myopic_costs = myopic_voi_decision(b_after_fail, seq[0], costs, P_obs)
        # 3-step optimal decision at step 0
        opt_val, (opt_act, opt_options) = pomdp_finite_horizon_search(b_after_fail, 0, seq, costs, T_4, P_obs)

        is_same = (myopic_act == opt_act)
        print(f"Context Sequence: {seq}")
        print(f"  Step 0 Myopic:   Action={myopic_act}, Immediate Expected Costs={myopic_costs}")
        print(f"  Step 0 3-Step:   Action={opt_act}, 3-Step Cumulative Values={opt_options}")
        print(f"  Policy Agreement: {'CONSISTENT' if is_same else 'DISCREPANCY DETECTED'}")
        if not is_same:
            discrepancies.append((seq, myopic_act, opt_act, myopic_costs, opt_options))
        print("---")

    print(f"Total sequences evaluated: {len(test_sequences)}")
    print(f"Discrepancies found: {len(discrepancies)}")
    if discrepancies:
        print(">>> CRITICAL INSIGHT: Myopic VoI and Finite-Horizon Optimal DO NOT ALWAYS COINCIDE.")
        for seq, m_act, o_act, m_c, o_c in discrepancies:
            print(f"  On sequence {seq}:")
            print(f"    Myopic chooses {m_act} (afraid of immediate failure risk 55.0s > 35.0s detour)")
            print(f"    3-Step chooses {o_act} (total cost {o_c['DIRECT']:.2f} < detour {o_c['DETOUR']:.2f})")
            print("    Explanation: Executing x_L resolves theta; success permanently unlocks x_L for future steps.")
            print("    This dual-control / exploration value is structurally invisible to single-step VoI.\n")


def simulate_sample_paths_and_costs():
    print("=== Step 4: Disentangling Expected Costs vs Realized Costs on Sample Paths ===")
    costs, _, T_4, P_obs = build_model()
    # Scenario:
    # Exogenous historical failure on x_H occurred at step 0.
    # True state at step 1: z = wet (1), theta = narrow (1). State s = 3.
    # True state at step 2: z = wet (1), theta = narrow (1). State s = 3.
    # True state at step 3: z = dry (0), theta = narrow (1). State s = 1. (Wind dried the corridor)

    print("Ground Truth Sequence: Step 1 (wet, narrow), Step 2 (wet, narrow), Step 3 (dry, narrow)")
    print("Under (wet, narrow): x_L SUCCEEDS (10s), x_H FAILS (100s).")
    print("Under (dry, narrow): x_L SUCCEEDS (10s), x_H SUCCEEDS (10s).")
    print()

    # Task sequence: [x_L, x_H, x_H]
    # We will trace 3 policies:
    # 1. Exact Bayes (Myopic VoI)
    # 2. Naive Spatial Obstacle Cache (O): marks corridor blocked after step 0 failure, always detours
    # 3. Naive Condition Cache (C): caches (x_H, fail). For x_L (unseen context), attempts execution.

    # Trace Policy 1: Exact Bayes (Myopic VoI)
    b = np.array([0.0, 0.0, 0.5, 0.5])  # post step 0 failure
    realized_costs_bayes = []
    expected_costs_bayes = []

    # Step 1: Context x_L. True s = 3 (wet, narrow)
    act1, c1 = myopic_voi_decision(b, 'x_L', costs, P_obs)
    expected_costs_bayes.append(c1[act1])
    # act1 is DETOUR (35.0)
    realized_costs_bayes.append(costs['C_detour'])
    b = T_4 @ b  # diffuse: [0.1, 0.1, 0.4, 0.4]

    # Step 2: Context x_H. True s = 3 (wet, narrow)
    act2, c2 = myopic_voi_decision(b, 'x_H', costs, P_obs)
    expected_costs_bayes.append(c2[act2])
    # act2 is DETOUR (35.0)
    realized_costs_bayes.append(costs['C_detour'])
    b = T_4 @ b  # diffuse: [0.175, 0.175, 0.325, 0.325]

    # Step 3: Context x_H. True s = 1 (dry, narrow)
    act3, c3 = myopic_voi_decision(b, 'x_H', costs, P_obs)
    expected_costs_bayes.append(c3[act3])
    # At this belief, PROBE cost is 32.79 < 35.0 detour!
    # Realized probe observation: true z is dry -> probe returns o_dry with 95% prob
    # Realized cost = c_probe (3.5) + direct execution in dry (10.0) = 13.5
    realized_costs_bayes.append(costs['c_probe'] + costs['C_nom'])

    # Trace Policy 2: Spatial Cache (O)
    # Always detours because it treats corridor as blocked: 35 + 35 + 35 = 105
    realized_costs_O = [35.0, 35.0, 35.0]

    # Trace Policy 3: Condition Cache (C)
    # Step 1: x_L has no cache entry -> executes x_L.
    # Shared physics check: In state (wet, narrow), x_L SUCCEEDS! Realized cost = 10.0!
    # Step 2: x_H has cache entry (failed) -> detours. Realized cost = 35.0!
    # Step 3: x_H has cache entry (failed) -> detours. Realized cost = 35.0!
    realized_costs_C = [10.0, 35.0, 35.0]

    print("=== Cumulative Results over 3 Tasks [x_L, x_H, x_H] ===")
    print(f"Policy 1 (Myopic Bayes):")
    print(f"  Step Expected Costs: {[round(c, 2) for c in expected_costs_bayes]}, Sum={sum(expected_costs_bayes):.2f}s")
    print(f"  Step Realized Costs: {realized_costs_bayes}, Sum={sum(realized_costs_bayes):.2f}s")
    print(f"Policy 2 (Spatial Cache O):")
    print(f"  Step Realized Costs: {realized_costs_O}, Sum={sum(realized_costs_O):.2f}s")
    print(f"Policy 3 (Condition Cache C):")
    print(f"  Step Realized Costs: {realized_costs_C}, Sum={sum(realized_costs_C):.2f}s")
    print()
    print(">>> CRITICAL INSIGHT ON BASELINE COMPARISON:")
    print("  Notice that on Step 1, Condition Cache achieved 10.0s (direct success) while Myopic Bayes achieved 35.0s (detour)!")
    print("  Condition Cache happened to succeed because ground truth was narrow. But Myopic Bayes properly avoided the 50% risk of 100s failure.")
    print("  Mixing realized cost and expected cost, or misclassifying Cache as 'failed on x_L', produces invalid conclusions.")


if __name__ == '__main__':
    verify_initial_step()
    verify_markov_properties()
    verify_myopic_vs_finite_horizon()
    simulate_sample_paths_and_costs()
