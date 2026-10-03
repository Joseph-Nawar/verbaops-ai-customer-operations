import pytest

from verbaops.actions.models import ActionState
from verbaops.actions.transitions import InvalidActionTransitionError, validate_action_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionState.PROPOSED, ActionState.POLICY_DENIED),
        (ActionState.PROPOSED, ActionState.AWAITING_APPROVAL),
        (ActionState.PROPOSED, ActionState.AWAITING_CONFIRMATION),
        (ActionState.PROPOSED, ActionState.READY_TO_EXECUTE),
        (ActionState.PROPOSED, ActionState.FAILED),
        (ActionState.PROPOSED, ActionState.EXPIRED),
        (ActionState.AWAITING_APPROVAL, ActionState.AWAITING_CONFIRMATION),
        (ActionState.AWAITING_APPROVAL, ActionState.READY_TO_EXECUTE),
        (ActionState.AWAITING_APPROVAL, ActionState.REJECTED),
        (ActionState.AWAITING_APPROVAL, ActionState.EXPIRED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.READY_TO_EXECUTE),
        (ActionState.AWAITING_CONFIRMATION, ActionState.REJECTED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.EXPIRED),
        (ActionState.READY_TO_EXECUTE, ActionState.EXECUTING),
        (ActionState.READY_TO_EXECUTE, ActionState.POLICY_DENIED),
        (ActionState.READY_TO_EXECUTE, ActionState.EXPIRED),
        (ActionState.EXECUTING, ActionState.SUCCEEDED),
        (ActionState.EXECUTING, ActionState.FAILED),
        (ActionState.EXECUTING, ActionState.READY_TO_EXECUTE),
        (ActionState.EXECUTING, ActionState.UNRESOLVED),
        (ActionState.UNRESOLVED, ActionState.EXECUTING),
        (ActionState.UNRESOLVED, ActionState.SUCCEEDED),
        (ActionState.UNRESOLVED, ActionState.FAILED),
        (ActionState.UNRESOLVED, ActionState.UNRESOLVED),
    ],
)
def test_approved_lifecycle_edges_are_allowed(current: ActionState, target: ActionState) -> None:
    validate_action_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionState.PROPOSED, ActionState.EXECUTING),
        (ActionState.AWAITING_APPROVAL, ActionState.POLICY_DENIED),
        (ActionState.AWAITING_CONFIRMATION, ActionState.AWAITING_APPROVAL),
        (ActionState.READY_TO_EXECUTE, ActionState.SUCCEEDED),
        (ActionState.EXECUTING, ActionState.POLICY_DENIED),
        (ActionState.POLICY_DENIED, ActionState.PROPOSED),
        (ActionState.REJECTED, ActionState.READY_TO_EXECUTE),
        (ActionState.SUCCEEDED, ActionState.EXECUTING),
        (ActionState.FAILED, ActionState.READY_TO_EXECUTE),
        (ActionState.EXPIRED, ActionState.AWAITING_CONFIRMATION),
    ],
)
def test_unapproved_lifecycle_edges_are_rejected(current: ActionState, target: ActionState) -> None:
    with pytest.raises(InvalidActionTransitionError):
        validate_action_transition(current, target)
