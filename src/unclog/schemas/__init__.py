"""Core data model (brief §13). Pydantic is the source of truth; JSON Schema is exported."""

from .common import (
    AgentOutput,
    Evidence,
    EvidenceType,
    Grounded,
    Source,
    SourceKind,
    UnclogModel,
)
from .delivery import (
    DeployedSystem,
    EvalCase,
    EvalRun,
    EvalSuite,
    ResultsLedgerEntry,
    SyncSession,
)
from .design import (
    ActionTag,
    AIRole,
    ConstraintLink,
    Delta,
    DeltaI,
    DeltaOE,
    DeltaT,
    Finding,
    GoalNode,
    GoalNodeKind,
    Opportunity,
    Position,
    Priority,
    RealizationPath,
    Risk,
    Scores,
    SimRun,
    ValueModel,
)
from .diagnosis import (
    REQUIRED_DOMAINS,
    Buffer,
    ConfirmationTest,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    Domain,
    DomainName,
    DomainVerdict,
    FlowEdge,
    FlowNode,
    FocusingAction,
    FocusStep,
    Policy,
    Resource,
    StageMetric,
    Task,
)
from .engagement import TIOE, Engagement, Function, Goal, Process, ProcessHealth

#: Entities exported as JSON Schema (brief §13: JSON Schema + Pydantic mirrors).
ENTITIES: dict[str, type[UnclogModel]] = {
    m.__name__: m
    for m in (
        Engagement,
        Goal,
        Source,
        Evidence,
        Function,
        Process,
        Domain,
        StageMetric,
        FlowNode,
        FlowEdge,
        Resource,
        Task,
        Constraint,
        Policy,
        Buffer,
        FocusingAction,
        GoalNode,
        Opportunity,
        ValueModel,
        Risk,
        Finding,
        SimRun,
        DeployedSystem,
        EvalSuite,
        EvalRun,
        SyncSession,
        ResultsLedgerEntry,
        AgentOutput,
    )
}

__all__ = [n for n in dir() if not n.startswith("_")]
