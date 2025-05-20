#!/usr/bin/env python3
"""
A2A(Agent2Agent)와 MCP(Model Context Protocol) 프로토콜 아키텍처 정의

A2A: 에이전트 간의 '협업'에 초점을 맞춘 프로토콜
MCP: AI 모델과 외부 '도구' 및 '데이터 소스' 간의 '통합'에 중점을 둔 프로토콜

참고: https://codingespresso.tistory.com/entry/Agent2AgentA2A%EC%99%80-MCP-%EC%99%84%EB%B2%BD-%EB%B9%84%EA%B5%90-%EB%B6%84%EC%84%9D
"""

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Callable

# --------------- MCP(Model Context Protocol) 구현 ---------------

class MCPResource(ABC):
    """MCP 리소스 추상 클래스 - 모든 도구와 데이터 소스의 기본"""
    
    @abstractmethod
    def get_definition(self) -> Dict[str, Any]:
        """리소스의 정의 반환 - 모델이 리소스를 이해하는 데 사용"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """리소스 실행 - 모델이 리소스를 호출할 때 사용"""
        pass


@dataclass
class MCPToolDefinition:
    """MCP 도구 정의 - 클라이언트가 도구를 이해하는 데 사용"""
    name: str
    description: str
    parameters: Dict[str, Any]
    return_schema: Dict[str, Any]
    version: str = "1.0"
    is_stateful: bool = False


class MCPTool(MCPResource):
    """MCP 도구 구현 - 함수 호출과 유사한 인터페이스"""
    
    def __init__(self, 
                 name: str, 
                 description: str, 
                 parameters: Dict[str, Any],
                 return_schema: Dict[str, Any],
                 implementation: Callable):
        self.definition = MCPToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            return_schema=return_schema
        )
        self.implementation = implementation
    
    def get_definition(self) -> Dict[str, Any]:
        """도구 정의를 반환"""
        return asdict(self.definition)
    
    def execute(self, **kwargs) -> Dict[str, Any]:
        """도구 실행 로직"""
        try:
            result = self.implementation(**kwargs)
            return {
                "status": "success",
                "result": result
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }


class MCPDataSource(MCPResource):
    """MCP 데이터 소스 구현 - 데이터에 접근하는 인터페이스"""
    
    def __init__(self, 
                 name: str, 
                 description: str, 
                 schema: Dict[str, Any],
                 query_implementation: Callable):
        self.name = name
        self.description = description
        self.schema = schema
        self.query_implementation = query_implementation
    
    def get_definition(self) -> Dict[str, Any]:
        """데이터 소스 정의를 반환"""
        return {
            "name": self.name,
            "description": self.description,
            "type": "data_source",
            "schema": self.schema
        }
    
    def execute(self, query: str, **kwargs) -> Dict[str, Any]:
        """데이터 소스 쿼리 실행"""
        try:
            result = self.query_implementation(query, **kwargs)
            return {
                "status": "success",
                "result": result
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }


class MCPRegistry:
    """MCP 리소스 레지스트리 - 사용 가능한 모든 리소스 관리"""
    
    def __init__(self):
        self.resources: Dict[str, MCPResource] = {}
    
    def register_resource(self, resource: MCPResource):
        """새 리소스 등록"""
        resource_def = resource.get_definition()
        self.resources[resource_def["name"]] = resource
        return resource_def["name"]
    
    def get_resource(self, name: str) -> Optional[MCPResource]:
        """이름으로 리소스 조회"""
        return self.resources.get(name)
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """사용 가능한 모든 리소스 목록 반환"""
        return [r.get_definition() for r in self.resources.values()]
    
    def execute_resource(self, name: str, **kwargs) -> Dict[str, Any]:
        """이름으로 리소스 실행"""
        resource = self.get_resource(name)
        if not resource:
            return {
                "status": "error",
                "error": f"Resource '{name}' not found",
                "error_type": "ResourceNotFound"
            }
        return resource.execute(**kwargs)


# --------------- A2A(Agent2Agent) 프로토콜 구현 ---------------

class InteractionModality(str, Enum):
    """A2A 상호작용 모달리티"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    STRUCTURED_DATA = "structured_data"
    AUDIO = "audio"
    VIDEO = "video"


class TaskStatus(str, Enum):
    """A2A 작업 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    WAITING_FOR_INPUT = "waiting_for_input"


@dataclass
class AgentCard:
    """
    A2A 에이전트 카드 - 에이전트의 기능과 역량을 설명
    
    에이전트 카드는 에이전트 디스커버리 단계에서 중요한 역할을 함
    """
    agent_id: str
    name: str
    description: str
    version: str
    skills: List[str]
    supported_modalities: List[InteractionModality] = field(default_factory=lambda: [InteractionModality.TEXT])
    auth_required: bool = False
    api_version: str = "1.0"
    organization: Optional[str] = None
    contact_info: Optional[str] = None
    documentation_url: Optional[str] = None
    endpoints: Dict[str, str] = field(default_factory=dict)


@dataclass
class Task:
    """
    A2A 작업 정의 - 에이전트 간 협업의 기본 단위
    
    작업은 상태를 유지하며 여러 에이전트 간에 공유될 수 있음
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_by: str = ""
    assigned_to: Optional[str] = None
    priority: int = 1  # 1(낮음) ~ 5(높음)
    deadline: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)  # 하위 작업 ID 목록
    parent_task: Optional[str] = None  # 상위 작업 ID
    tags: List[str] = field(default_factory=list)


class A2AAgent:
    """
    A2A 프로토콜을 구현한 기본 에이전트
    """
    
    def __init__(self, agent_card: AgentCard, mcp_registry: Optional[MCPRegistry] = None):
        self.agent_card = agent_card
        self.tasks: Dict[str, Task] = {}
        self.mcp_registry = mcp_registry or MCPRegistry()
    
    def get_agent_card(self) -> Dict[str, Any]:
        """에이전트 카드 반환 - 에이전트 디스커버리에 사용"""
        return asdict(self.agent_card)
    
    def create_task(self, title: str, description: str, context: Dict[str, Any] = None) -> str:
        """새 작업 생성"""
        task = Task(
            title=title,
            description=description,
            created_by=self.agent_card.agent_id,
            context=context or {}
        )
        self.tasks[task.task_id] = task
        return task.task_id
    
    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """작업을 다른 에이전트에 할당"""
        if task_id in self.tasks:
            self.tasks[task_id].assigned_to = agent_id
            self.tasks[task_id].status = TaskStatus.IN_PROGRESS
            self.update_task_history(task_id, f"작업이 {agent_id}에게 할당되었습니다.")
            return True
        return False
    
    def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """작업 상태 업데이트"""
        if task_id in self.tasks:
            self.tasks[task_id].status = status
            self.update_task_history(task_id, f"작업 상태가 {status}로 변경되었습니다.")
            return True
        return False
    
    def update_task_history(self, task_id: str, message: str) -> bool:
        """작업 기록 업데이트"""
        if task_id in self.tasks:
            self.tasks[task_id].history.append({
                "agent_id": self.agent_card.agent_id,
                "message": message,
                "timestamp": str(uuid.uuid4())  # 실제로는 시간 사용
            })
            return True
        return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """작업 정보 반환"""
        if task_id in self.tasks:
            return asdict(self.tasks[task_id])
        return None
    
    def call_mcp_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """MCP 도구 호출 - MCP와 A2A의 통합 지점"""
        if not self.mcp_registry:
            return {"status": "error", "message": "MCP Registry not available"}
        return self.mcp_registry.execute_resource(tool_name, **kwargs)
    
    def communicate(self, to_agent_id: str, task_id: str, message: str, 
                   modality: InteractionModality = InteractionModality.TEXT, 
                   data: Optional[Any] = None) -> Dict[str, Any]:
        """다른 에이전트와 통신 - A2A의 핵심 기능"""
        if task_id not in self.tasks:
            return {"status": "error", "message": f"Task {task_id} not found"}
        
        # 지원하는 모달리티인지 확인
        if modality not in self.agent_card.supported_modalities:
            return {"status": "error", "message": f"Modality {modality} not supported"}
        
        # 작업 기록 업데이트
        self.update_task_history(task_id, message)
        
        # 실제 통신은 A2A 서버를 통해 이루어짐 (여기서는 로컬 시뮬레이션)
        return {
            "status": "success",
            "message": f"Message sent to {to_agent_id} for task {task_id}",
            "modality": modality,
            "timestamp": str(uuid.uuid4())  # 실제로는 시간 사용
        }
    
    def accept_task(self, task_id: str) -> Dict[str, Any]:
        """다른 에이전트로부터 할당된 작업 수락"""
        if task_id in self.tasks:
            if self.tasks[task_id].assigned_to == self.agent_card.agent_id:
                self.tasks[task_id].status = TaskStatus.IN_PROGRESS
                self.update_task_history(task_id, "작업을 수락하였습니다.")
                return {"status": "success", "message": "Task accepted"}
        return {"status": "error", "message": "Task not found or not assigned to this agent"}
    
    def reject_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        """다른 에이전트로부터 할당된 작업 거절"""
        if task_id in self.tasks:
            if self.tasks[task_id].assigned_to == self.agent_card.agent_id:
                self.tasks[task_id].status = TaskStatus.REJECTED
                self.update_task_history(task_id, f"작업 거절 이유: {reason}")
                return {"status": "success", "message": "Task rejected"}
        return {"status": "error", "message": "Task not found or not assigned to this agent"}
    
    def complete_task(self, task_id: str, result: Dict[str, Any] = None) -> Dict[str, Any]:
        """작업 완료 처리"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.COMPLETED
            if result:
                self.tasks[task_id].context["result"] = result
            self.update_task_history(task_id, "작업이 완료되었습니다.")
            return {"status": "success", "message": "Task completed"}
        return {"status": "error", "message": "Task not found"}
    
    def create_subtask(self, parent_task_id: str, title: str, description: str) -> Optional[str]:
        """하위 작업 생성 - 복잡한 작업을 분할할 때 유용"""
        if parent_task_id not in self.tasks:
            return None
        
        subtask_id = self.create_task(title, description, {"parent_task": parent_task_id})
        self.tasks[subtask_id].parent_task = parent_task_id
        self.tasks[parent_task_id].subtasks.append(subtask_id)
        
        self.update_task_history(parent_task_id, f"하위 작업이 생성되었습니다: {title}")
        return subtask_id


# --------------- A2A와 MCP의 통합 예시 ---------------

def create_mechanic_agent_with_tools() -> A2AAgent:
    """도구를 갖춘 정비사 에이전트 생성 예시"""
    # 1. 에이전트 카드 생성
    mechanic_card = AgentCard(
        agent_id="mechanic_001",
        name="자동차 정비사",
        description="자동차 진단 및 수리를 수행하는 전문 에이전트",
        version="1.0",
        skills=["car_diagnosis", "car_repair", "parts_replacement"],
        supported_modalities=[InteractionModality.TEXT, InteractionModality.IMAGE],
        organization="Auto Repair Shop",
        documentation_url="https://example.com/mechanic-agent-docs"
    )
    
    # 2. MCP 레지스트리 생성
    mcp_registry = MCPRegistry()
    
    # 3. 진단 스캐너 도구 정의 및 등록
    def scan_vehicle_impl(vehicle_id: str) -> Dict[str, Any]:
        # 실제로는 스캐너 장치와 연결될 수 있음
        return {
            "error_codes": ["P0300", "P0171"],
            "descriptions": {
                "P0300": "Random/Multiple Cylinder Misfire Detected",
                "P0171": "System Too Lean (Bank 1)"
            }
        }
    
    scanner_tool = MCPTool(
        name="scan_vehicle",
        description="차량 진단 스캐너를 사용하여 오류 코드 조회",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {"type": "string", "description": "차량 ID"}
            },
            "required": ["vehicle_id"]
        },
        return_schema={
            "type": "object",
            "properties": {
                "error_codes": {"type": "array", "items": {"type": "string"}},
                "descriptions": {"type": "object"}
            }
        },
        implementation=scan_vehicle_impl
    )
    
    mcp_registry.register_resource(scanner_tool)
    
    # 4. 수리 매뉴얼 데이터 소스 정의 및 등록
    repair_procedures = {
        "P0300": [
            "점화 플러그 검사 및 교체",
            "점화 코일 검사",
            "연료 인젝터 검사",
            "압축 테스트 수행"
        ],
        "P0171": [
            "공기 필터 검사",
            "MAF 센서 세척",
            "연료 압력 테스트",
            "산소 센서 검사"
        ]
    }
    
    def get_repair_procedure_impl(query: str, error_code: str, vehicle_make: str, vehicle_model: str) -> Dict[str, Any]:
        if error_code in repair_procedures:
            return {
                "error_code": error_code,
                "vehicle": f"{vehicle_make} {vehicle_model}",
                "procedure": repair_procedures[error_code]
            }
        return {"error": "Procedure not found"}
    
    repair_manual_source = MCPDataSource(
        name="repair_manual",
        description="수리 매뉴얼 데이터베이스에서 오류 코드별 수리 절차 조회",
        schema={
            "type": "object",
            "properties": {
                "error_code": {"type": "string", "description": "오류 코드"},
                "vehicle_make": {"type": "string", "description": "차량 제조사"},
                "vehicle_model": {"type": "string", "description": "차량 모델"}
            },
            "required": ["error_code"]
        },
        query_implementation=get_repair_procedure_impl
    )
    
    mcp_registry.register_resource(repair_manual_source)
    
    # 5. 에이전트 생성 및 반환
    return A2AAgent(mechanic_card, mcp_registry)


# --------------- 시스템 비교 설명 ---------------

def explain_a2a_vs_mcp():
    """A2A와 MCP의 차이점 설명"""
    explanation = """
    # A2A와 MCP 프로토콜 비교
    
    ## 1. 주요 초점
    - A2A(Agent2Agent): 에이전트 간의 '협업'에 초점
    - MCP(Model Context Protocol): AI 모델과 외부 '도구' 및 '데이터 소스' 간의 '통합'에 중점
    
    ## 2. 설계 원칙
    - A2A: 수평적 오케스트레이션, 에이전트 간의 태스크 조정 및 통신 표준화
    - MCP: 수직적 통합, AI 모델이 다양한 외부 도구와 안전하게 통신하는 방법 표준화
    
    ## 3. 아키텍처 차이
    - A2A: 에이전트 디스커버리, 태스크 관리, 상태 공유에 중점
    - MCP: 도구 정의, 함수 호출, 결과 반환 패턴에 중점
    
    ## 4. 개발 주체
    - A2A: Google이 50개 이상의 파트너와 협력하여 개발
    - MCP: Anthropic이 개발, Microsoft와 Google의 지원
    
    ## 5. 용도
    - A2A: 여러 AI 에이전트가 복잡한 작업을 협력하여 수행해야 하는 경우
    - MCP: 단일 AI 모델이 다양한 외부 도구와 데이터에 접근해야 하는 경우
    """
    return explanation


if __name__ == "__main__":
    # 시스템 설명 출력
    print(explain_a2a_vs_mcp())
    
    # 통합 에이전트 생성 예시
    agent = create_mechanic_agent_with_tools()
    print(f"\n에이전트 카드 정보: {json.dumps(agent.get_agent_card(), indent=2, ensure_ascii=False)}")
    
    # MCP 도구 호출 예시
    scan_result = agent.call_mcp_tool("scan_vehicle", vehicle_id="VIN_XYZ123")
    print(f"\nMCP 도구 호출 결과: {json.dumps(scan_result, indent=2, ensure_ascii=False)}") 