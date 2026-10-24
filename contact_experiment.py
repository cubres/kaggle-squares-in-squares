"""Portable original contact-axis experiment, prvsiyan, 24 October 2026.
Seeds retain their individual construction credits. Supply the current official
metric module explicitly. No files, network, model calls, or notebook mutations.
Call rerun_contact_experiment(seed, official_metric) for one bounded experiment.
"""
import math, time, warnings
import numpy as np
from scipy.optimize import linprog, OptimizeWarning
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from threadpoolctl import threadpool_limits

def span(p):
    h = (np.abs(np.cos(p[:, 2])) + np.abs(np.sin(p[:, 2]))) / 2
    low = np.min(p[:, :2] - h[:, None], axis=0)
    return float(np.max(np.max(p[:, :2] + h[:, None], axis=0) - low)), low, h

def normalize(p):
    q = p.copy()
    q[:, :2] -= span(q)[1]
    return q

def geometry(p, radius=2.1):
    pairs = cKDTree(p[:, :2]).query_pairs(radius, output_type='ndarray')
    i, j = pairs.T
    c, s = np.cos(p[:, 2]), np.sin(p[:, 2])
    x = np.column_stack((c[i], -s[i], c[j], -s[j]))
    y = np.column_stack((s[i], c[i], s[j], c[j]))
    d = p[j, :2] - p[i, :2]
    projections = d[:, 0, None] * x + d[:, 1, None] * y
    delta = p[i, 2] - p[j, 2]
    rad = (1 + np.abs(np.cos(delta)) + np.abs(np.sin(delta))) / 2
    return pairs, x, y, projections, rad

def repair(p, clearance=4e-9):
    q = normalize(p)
    _, _, _, projection, rad = geometry(q, 1.5)
    scale = max(1., float(np.max((rad + clearance) / np.max(np.abs(projection), axis=1))))
    if scale > 1.002:
        raise ValueError('candidate requires excessive expansion')
    q[:, :2] *= scale
    return normalize(q)

def squeeze(p, clearance=4e-9):
    """Ablation: reclaim decimal safety slack only; no topology improvement."""
    q = normalize(p)
    _, _, _, projection, rad = geometry(q, 1.5)
    scale = float(np.max((rad + clearance) / np.max(np.abs(projection), axis=1)))
    if not .99999 <= scale < 1:
        return q
    q[:, :2] *= scale
    return normalize(q)

def solve(p, *, branch=None, trust=.2, max_seconds=1.5):
    n = len(p)
    p = normalize(p)
    old, _, h = span(p)
    pairs, x, y, projection, rad = geometry(p)
    i, j = pairs.T
    k = np.argmax(np.abs(projection), axis=1)
    if branch is not None:
        k[branch[0]] = branch[1]
    row = np.arange(len(i))
    signs = np.sign(projection[row, k])
    ux, uy = x[row, k] * signs, y[row, k] * signs
    rows = np.repeat(row, 4)
    cols = np.column_stack((2*i, 2*i+1, 2*j, 2*j+1)).ravel()
    values = np.column_stack((ux, uy, -ux, -uy)).ravel()
    rhs = -(rad + 2e-9)
    wall_rows = np.repeat(len(i) + np.arange(2*n), 2)
    wall_cols = np.column_stack((np.arange(2*n), np.full(2*n, 2*n))).ravel()
    rows = np.r_[rows, wall_rows]
    cols = np.r_[cols, wall_cols]
    values = np.r_[values, np.tile([1., -1.], 2*n)]
    rhs = np.r_[rhs, -np.repeat(h, 2)]
    matrix = coo_matrix((values, (rows, cols)), shape=(len(rhs), 2*n+1)).tocsr()
    limits = [(max(h[a//2], p[a//2, a%2]-trust), p[a//2, a%2]+trust) for a in range(2*n)]
    limits.append((math.sqrt(n), old+1e-7))
    cost = np.r_[np.zeros(2*n), 1.]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', OptimizeWarning)
        result = linprog(cost, A_ub=matrix, b_ub=rhs, bounds=limits, method='highs',
            options={'threads': 1, 'time_limit': max_seconds,
                     'dual_feasibility_tolerance': 1e-9, 'primal_feasibility_tolerance': 1e-9})
    if not result.success:
        return None, [], {'status': int(result.status), 'message': result.message}
    q = p.copy()
    q[:, :2] = result.x[:-1].reshape(n, 2)
    q = repair(q)
    # Distances omitted from the LP exceed 2.1; under the .2 coordinate
    # trust box their final distance remains >2.1-.4*sqrt(2)>sqrt(2).
    dual = np.abs(result.ineqlin.marginals[:len(i)])
    alternatives = []
    for edge in np.argsort(-dual)[:40]:
        if dual[edge] < 1e-8:
            continue
        for axis in np.argsort(-np.abs(projection[edge])):
            parallel = abs(x[edge, axis]*x[edge, k[edge]] + y[edge, axis]*y[edge, k[edge]])
            deficit = rad[edge] - abs(projection[edge, axis])
            if parallel < .98 and -1e-6 <= deficit <= .2:
                alternatives.append((int(edge), int(axis)))
                break
    return q, alternatives[:4], {'status': 0, 'dual_alternatives': len(alternatives), 'pairs': len(i)}

def decimals(p):
    return [{'n': str(len(p)), 'square_id': str(i), 'x': format(x, '.17g'),
             'y': format(y, '.17g'), 'angle': format(a, '.17g')} for i, (x, y, a) in enumerate(p)]


def rerun_contact_experiment(seed, official_metric, *, rounds=3, clearance=4e-8):
    """Return an exact-decimal, interval-checked local result; keep original on failure.

    Three rounds: fixed-angle LP, then at most four dual-guided alternative axes.
    Numerical libraries and HiGHS use one thread. Results may vary by solver build.
    The returned decimal_rows are the only accepted output; official_score is null.
    """
    if not isinstance(rounds, int) or not 1 <= rounds <= 3:
        raise ValueError('rounds must be between one and three')
    if clearance != 4e-8:
        raise ValueError('This measured experiment fixes clearance at 4e-8')
    n = int(seed['n'])
    original_pose = np.array(seed['poses'], dtype=float)
    if original_pose.shape != (n, 3) or n < 2 or not np.all(np.isfinite(original_pose)):
        raise ValueError('Invalid seed shape or non-finite coordinate')
    started = time.monotonic()
    original_rows = decimals(original_pose)
    original = official_metric.evaluate_single_puzzle(n, original_rows)
    if original[2] is None or original[3] != 'ok':
        raise ValueError('Seed failed the supplied official interval metric')
    candidates = [('original', original_pose)]
    details = []
    with threadpool_limits(limits=1):
        for round_number in range(rounds):
            current = min(candidates, key=lambda item: span(item[1])[0])[1]
            try:
                q, branches, info = solve(current, max_seconds=2)
                if q is not None:
                    candidates.append((f'fixed_LP_round{round_number}', repair(q, clearance=clearance)))
                for branch in branches:
                    try:
                        trial, _, trial_info = solve(current, branch=branch, max_seconds=2)
                        if trial is not None:
                            candidates.append((f'contact_exchange_round{round_number}:{branch}', repair(trial, clearance=clearance)))
                        details.append({'round': round_number, 'branch': branch, 'solver': trial_info})
                    except (ValueError, RuntimeError) as error:
                        details.append({'round': round_number, 'branch': branch, 'error': type(error).__name__})
            except (ValueError, RuntimeError) as error:
                details.append({'round': round_number, 'error': type(error).__name__})
    method, proposed_pose = min(candidates, key=lambda item: span(item[1])[0])
    proposed_rows = decimals(proposed_pose)
    proposed = official_metric.evaluate_single_puzzle(n, proposed_rows)
    accepted = proposed[2] is not None and proposed[3] == 'ok' and proposed[1] < original[1]-1e-12
    selected_pose, selected_rows, selected = (proposed_pose, proposed_rows, proposed) if accepted else (original_pose, original_rows, original)
    record = {k:seed[k] for k in ('n','source_record','source_sha256','source_url','credit')}
    record.update(method=method if accepted else 'original_incumbent_preserved', proposed_method=method,
        baseline_metric=original, candidate_metric=proposed, selected_metric=selected,
        clearance=clearance, rounds=rounds, gain=original[1]-selected[1], accepted=bool(accepted),
        official_score=None, poses=selected_pose.tolist(), decimal_rows=selected_rows,
        attempts=details, elapsed_seconds=time.monotonic()-started,
        note='Local interval result only; no Kaggle score or publication claim.')
    return record
