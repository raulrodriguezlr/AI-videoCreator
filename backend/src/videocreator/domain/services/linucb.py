"""LinUcbBandit — a disjoint LinUCB contextual bandit (Li et al., 2010).

Pure decision logic with **zero third-party dependencies**: the small dense
linear algebra (solve / outer-product / dot) is hand-rolled so the domain layer
stays import-light and the learned policy serializes trivially for local-first
persistence. Given a feature `context` x it scores each arm by

    score(a) = theta_a . x  +  alpha * sqrt(x^T * A_a^-1 * x)

where theta_a = A_a^-1 * b_a. That is the predicted reward plus an
upper-confidence bonus that shrinks as an arm is tried more; the highest score
wins. Used to choose the best title/thumbnail variant for a video, balancing
exploitation of what works against exploration of untried options.

The bandit is *stateless*: every method takes a `BanditPolicy` and returns a
new one, so learned state lives in persistence, never in the service instance.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import sqrt

from videocreator.domain.value_objects import (
    BanditArm,
    BanditDecision,
    BanditPolicy,
)

Matrix = tuple[tuple[float, ...], ...]
Vector = tuple[float, ...]

# Pivot magnitudes below this treat the design matrix as singular. With the
# identity ridge prior baked into every cold-start arm, this should never trip.
_SINGULAR_EPS = 1e-12


class LinUcbBandit:
    """Stateless disjoint LinUCB policy operations (cold-start / score / learn)."""

    def __init__(self, *, alpha: float = 1.0) -> None:
        if alpha < 0.0:
            raise ValueError("alpha (exploration weight) must be non-negative")
        self._alpha = alpha

    def cold_start(self, arm_ids: Iterable[str], *, dimension: int) -> BanditPolicy:
        """Create a fresh policy: each arm gets the identity prior `A=I, b=0`."""
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        ids = tuple(dict.fromkeys(arm_ids))  # dedupe, preserve order
        if not ids:
            raise ValueError("a bandit needs at least one arm")
        identity = _identity(dimension)
        zeros = tuple(0.0 for _ in range(dimension))
        arms = tuple(
            BanditArm(arm_id=arm_id, a_matrix=identity, b_vector=zeros)
            for arm_id in ids
        )
        return BanditPolicy(dimension=dimension, alpha=self._alpha, arms=arms)

    def recommend(self, policy: BanditPolicy, context: Sequence[float]) -> BanditDecision:
        """Pick the arm with the highest UCB score for `context` (ties → first)."""
        x = self._validate_context(policy, context)
        scores = {arm.arm_id: self._ucb(arm, x, policy.alpha) for arm in policy.arms}
        best = max(scores, key=scores.__getitem__)
        return BanditDecision(arm_id=best, score=scores[best], scores=scores)

    def update(
        self,
        policy: BanditPolicy,
        *,
        arm_id: str,
        context: Sequence[float],
        reward: float,
    ) -> BanditPolicy:
        """Apply a rank-1 reward update to one arm, returning a new policy."""
        x = self._validate_context(policy, context)
        target = policy.arm(arm_id)  # raises KeyError on unknown arm
        new_a = _add_outer(target.a_matrix, x)
        new_b = tuple(b + reward * xi for b, xi in zip(target.b_vector, x, strict=True))
        learned = BanditArm(arm_id=arm_id, a_matrix=new_a, b_vector=new_b)
        arms = tuple(learned if a.arm_id == arm_id else a for a in policy.arms)
        return policy.model_copy(update={"arms": arms})

    # ---- internals --------------------------------------------------------
    @staticmethod
    def _ucb(arm: BanditArm, x: Vector, alpha: float) -> float:
        theta = _solve(arm.a_matrix, arm.b_vector)
        mean = _dot(theta, x)
        a_inv_x = _solve(arm.a_matrix, x)
        bonus = alpha * sqrt(max(_dot(x, a_inv_x), 0.0))
        return mean + bonus

    @staticmethod
    def _validate_context(policy: BanditPolicy, context: Sequence[float]) -> Vector:
        x = tuple(float(value) for value in context)
        if len(x) != policy.dimension:
            raise ValueError(
                f"context must have dimension {policy.dimension}, got {len(x)}"
            )
        return x


# ============================================================================
# Hand-rolled dense linear algebra (small dimensions only)
# ============================================================================
def _identity(n: int) -> Matrix:
    return tuple(tuple(1.0 if i == j else 0.0 for j in range(n)) for i in range(n))


def _dot(u: Vector, v: Vector) -> float:
    return sum(a * b for a, b in zip(u, v, strict=True))


def _add_outer(matrix: Matrix, x: Vector) -> Matrix:
    """Return `matrix + x·xᵀ` (the LinUCB design-matrix rank-1 update)."""
    return tuple(
        tuple(matrix[i][j] + x[i] * x[j] for j in range(len(x)))
        for i in range(len(x))
    )


def _solve(matrix: Matrix, vector: Vector) -> Vector:
    """Solve `M z = vector` via Gauss-Jordan elimination with partial pivoting."""
    n = len(matrix)
    aug = [[*row, vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot, best = col, abs(aug[col][col])
        for row in range(col + 1, n):
            magnitude = abs(aug[row][col])
            if magnitude > best:
                best, pivot = magnitude, row
        if best < _SINGULAR_EPS:
            raise ValueError("LinUCB design matrix is singular")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pivot_value = aug[col][col]
        aug[col] = [value / pivot_value for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            aug[row] = [a - factor * b for a, b in zip(aug[row], aug[col], strict=True)]
    return tuple(row[n] for row in aug)


__all__ = ["LinUcbBandit"]
