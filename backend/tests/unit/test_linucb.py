"""Unit tests for the pure `LinUcbBandit` contextual bandit and its policy VO.

These verify the algorithm's contract — cold-start priors, deterministic tie
breaking, exploitation after a reward, exploration of untried arms, and
immutability of the returned policy — without any I/O.
"""
from __future__ import annotations

import pytest

from videocreator.domain.services.linucb import LinUcbBandit
from videocreator.domain.value_objects import BanditArm, BanditPolicy


# ============================================================================
# cold_start
# ============================================================================
def test_cold_start_builds_identity_priors() -> None:
    # Act
    policy = LinUcbBandit(alpha=1.5).cold_start(["a", "b"], dimension=2)

    # Assert — A=I, b=0 per arm; alpha + dimension stamped onto the policy
    assert policy.dimension == 2
    assert policy.alpha == pytest.approx(1.5)
    assert policy.arm_ids == ("a", "b")
    assert policy.arm("a").a_matrix == ((1.0, 0.0), (0.0, 1.0))
    assert policy.arm("a").b_vector == (0.0, 0.0)


def test_cold_start_dedupes_arm_ids_preserving_order() -> None:
    # Act
    policy = LinUcbBandit().cold_start(["a", "b", "a"], dimension=1)

    # Assert
    assert policy.arm_ids == ("a", "b")


def test_cold_start_rejects_empty_arms_and_bad_dimension() -> None:
    bandit = LinUcbBandit()
    with pytest.raises(ValueError, match="at least one arm"):
        bandit.cold_start([], dimension=2)
    with pytest.raises(ValueError, match="dimension must be positive"):
        bandit.cold_start(["a"], dimension=0)


def test_constructor_rejects_negative_alpha() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        LinUcbBandit(alpha=-0.1)


# ============================================================================
# recommend
# ============================================================================
def test_recommend_breaks_ties_to_first_arm() -> None:
    # Arrange — cold policy with no exploration: every arm scores 0.0
    policy = LinUcbBandit(alpha=0.0).cold_start(["a", "b", "c"], dimension=2)
    bandit = LinUcbBandit(alpha=0.0)

    # Act
    decision = bandit.recommend(policy, (1.0, 0.0))

    # Assert — all tied at 0, first inserted arm wins; scores cover every arm
    assert decision.arm_id == "a"
    assert decision.score == pytest.approx(0.0)
    assert set(decision.scores) == {"a", "b", "c"}


def test_recommend_validates_context_dimension() -> None:
    policy = LinUcbBandit().cold_start(["a"], dimension=3)
    with pytest.raises(ValueError, match="dimension 3"):
        LinUcbBandit().recommend(policy, (1.0, 0.0))


def test_recommend_exploits_a_rewarded_arm() -> None:
    # Arrange — no exploration so the choice is pure exploitation
    bandit = LinUcbBandit(alpha=0.0)
    policy = bandit.cold_start(["a", "b"], dimension=2)
    context = (1.0, 0.0)

    # Act — reward arm "b" for this context
    policy = bandit.update(policy, arm_id="b", context=context, reward=1.0)
    decision = bandit.recommend(policy, context)

    # Assert — "b" now predicts a positive reward; "a" is still flat at 0
    assert decision.arm_id == "b"
    assert decision.scores["b"] > decision.scores["a"]


def test_recommend_explores_untried_arm_when_alpha_high() -> None:
    # Arrange — heavily train "a"; leave "b" untouched
    bandit = LinUcbBandit(alpha=2.0)
    policy = bandit.cold_start(["a", "b"], dimension=2)
    context = (1.0, 0.0)
    for _ in range(3):
        policy = bandit.update(policy, arm_id="a", context=context, reward=1.0)

    # Act — the untried arm carries a larger confidence bonus
    decision = bandit.recommend(policy, context)

    # Assert — optimism under uncertainty steers us to explore "b"
    assert decision.arm_id == "b"


# ============================================================================
# update
# ============================================================================
def test_update_is_immutable() -> None:
    # Arrange
    bandit = LinUcbBandit()
    original = bandit.cold_start(["a", "b"], dimension=2)

    # Act
    updated = bandit.update(original, arm_id="a", context=(1.0, 1.0), reward=1.0)

    # Assert — the original policy is untouched; a new one is returned
    assert original.arm("a").b_vector == (0.0, 0.0)
    assert original.arm("a").a_matrix == ((1.0, 0.0), (0.0, 1.0))
    assert updated is not original
    assert updated.arm("a").b_vector == (1.0, 1.0)
    assert updated.arm("a").a_matrix == ((2.0, 1.0), (1.0, 2.0))


def test_update_unknown_arm_raises() -> None:
    policy = LinUcbBandit().cold_start(["a"], dimension=2)
    with pytest.raises(KeyError, match="ghost"):
        LinUcbBandit().update(policy, arm_id="ghost", context=(1.0, 0.0), reward=1.0)


def test_repeated_rewards_converge_on_better_arm() -> None:
    # Arrange — "good" pays out on a feature that "bad" never sees
    bandit = LinUcbBandit(alpha=0.1)
    policy = bandit.cold_start(["good", "bad"], dimension=2)
    good_ctx = (1.0, 0.0)

    # Act — observe the good arm winning repeatedly
    for _ in range(8):
        policy = bandit.update(policy, arm_id="good", context=good_ctx, reward=1.0)

    # Assert — exploitation now clearly favours "good" for that context
    decision = bandit.recommend(policy, good_ctx)
    assert decision.arm_id == "good"
    assert decision.scores["good"] > decision.scores["bad"]


# ============================================================================
# BanditPolicy validation
# ============================================================================
def test_policy_rejects_mismatched_matrix_shape() -> None:
    with pytest.raises(ValueError, match="a_matrix must be 2x2"):
        BanditPolicy(
            dimension=2,
            arms=(BanditArm(arm_id="a", a_matrix=((1.0, 0.0),), b_vector=(0.0, 0.0)),),
        )


def test_policy_rejects_mismatched_vector_length() -> None:
    with pytest.raises(ValueError, match="b_vector must have length 2"):
        BanditPolicy(
            dimension=2,
            arms=(
                BanditArm(
                    arm_id="a", a_matrix=((1.0, 0.0), (0.0, 1.0)), b_vector=(0.0,)
                ),
            ),
        )
