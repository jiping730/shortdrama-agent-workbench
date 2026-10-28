from agent_platform.domain import (
    InvalidTransition,
    RunStatus,
    StepStatus,
    assert_run_transition,
    assert_step_transition,
    content_hash,
    stable_id,
)


def test_stable_id_and_hash_are_ordered_and_repeatable():
    assert stable_id("scene", "p", 1, "text") == stable_id("scene", "p", 1, "text")
    assert content_hash({"b": 1, "a": 2}) == content_hash({"a": 2, "b": 1})
    assert stable_id("scene", "p", 1, "text") != stable_id("scene", "p", 2, "text")


def test_explicit_state_machine_rejects_illegal_transition():
    assert_run_transition(RunStatus.CREATED, RunStatus.QUEUED)
    assert_step_transition(StepStatus.RUNNING, StepStatus.SUCCEEDED)
    try:
        assert_run_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
    except InvalidTransition:
        pass
    else:  # pragma: no cover
        raise AssertionError("completed run must be terminal")
