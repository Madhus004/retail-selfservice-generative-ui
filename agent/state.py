from typing import Any, Dict, List, Literal, Optional, TypedDict


UIMode = Literal[
    "welcome",
    "orderSelection",
    "promiseDashboard",
    "wrongDeliveryClaim",
    "claimSubmitted",
]


AgentIntent = Literal[
    "WHERE_IS_MY_ORDER",
    "SELECT_ORDER",
    "WRONG_DELIVERY",
    "SUBMIT_WRONG_DELIVERY_CLAIM",
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

    # Declarative A2UI-style payload
    a2uiVersion: str
    a2ui: List[A2UIComponent]


class AgentState(TypedDict, total=False):
    userMessage: str
    intent: AgentIntent
    orderNumber: Optional[str]

    recentOrdersData: Dict[str, Any]
    promiseDashboardData: Dict[str, Any]

    promiseResult: Optional[str]
    promiseReasonCode: Optional[str]
    issueType: Optional[str]

    policyData: Dict[str, Any]

    customerExplanation: Optional[str]

    uiState: AgentUIState
    error: Optional[str]