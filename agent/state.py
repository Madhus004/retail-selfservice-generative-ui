from typing import Any, Dict, List, Literal, Optional, TypedDict


UIMode = Literal[
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "wrongDeliveryClaim",
    "claimSubmitted",
    "cancellationBuilder",
    "cancellationConfirmed",
]


AgentIntent = Literal[
    "WHERE_IS_MY_ORDER",
    "SELECT_ORDER",
    "WRONG_DELIVERY",
    "SUBMIT_WRONG_DELIVERY_CLAIM",
    "ORDER_NOT_LISTED",
    "CANCEL_ORDER",
    "UNKNOWN",
]


AgentStepStatus = Literal["pending", "running", "complete"]


A2UIComponentType = Literal[
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "deliveryProof",
    "serviceRecovery",
    "wrongDeliveryClaim",
    "claimSubmitted",
    "cancellationBuilder",
    "cancellationConfirmed",
]


class AgentStep(TypedDict):
    label: str
    status: AgentStepStatus


class A2UIComponent(TypedDict):
    type: A2UIComponentType
    props: Dict[str, Any]


class AgentUIState(TypedDict, total=False):
    uiMode: UIMode
    assistantMessage: str
    canvasData: Dict[str, Any]
    agentSteps: List[AgentStep]

    # Deterministic (not LLM-chosen) quick-reply suggestions for this turn
    suggestedReplies: List[str]

    # Declarative A2UI-style payload
    a2uiVersion: str
    a2ui: List[A2UIComponent]


class AgentState(TypedDict, total=False):
    userMessage: str
    pageContext: Optional[Dict[str, Any]]
    intent: AgentIntent
    orderNumber: Optional[str]

    recentOrdersData: Dict[str, Any]
    promiseDashboardData: Dict[str, Any]
    cancellationEligibleOrdersData: Dict[str, Any]

    promiseResult: Optional[str]
    promiseReasonCode: Optional[str]
    issueType: Optional[str]

    policyData: Dict[str, Any]

    customerExplanation: Optional[str]

    # LLM UI planner output after validation
    a2uiComponents: List[A2UIComponent]

    uiState: AgentUIState
    error: Optional[str]