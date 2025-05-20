#!/usr/bin/env python3
"""
MSA 기반 A2A-MCP 통합 에이전트 프레임워크의 기본 클래스 구현
"""

import json
import uuid
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Callable
from pydantic import BaseModel, Field

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# --------- 기본 데이터 모델 ---------

class AgentStatus(str, Enum):
    """에이전트 상태 정의"""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


class TaskStatus(str, Enum):
    """작업 상태 정의"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    WAITING_FOR_INPUT = "waiting_for_input"
    CANCELLED = "cancelled"


class InteractionModality(str, Enum):
    """상호작용 모달리티"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    STRUCTURED_DATA = "structured_data"
    AUDIO = "audio"
    VIDEO = "video"


class AgentCard(BaseModel):
    """
    에이전트 카드 - 에이전트의 기능과 역량을 설명하는 데이터 모델
    """
    agent_id: str
    name: str
    description: str
    version: str
    skills: List[str]
    supported_modalities: List[InteractionModality] = Field(default_factory=lambda: [InteractionModality.TEXT])
    auth_required: bool = False
    api_version: str = "1.0"
    organization: Optional[str] = None
    contact_info: Optional[str] = None
    documentation_url: Optional[str] = None
    endpoints: Dict[str, str] = Field(default_factory=dict)


class TaskEvent(BaseModel):
    """작업 이벤트 - 작업 이력을 구성하는 이벤트"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    event_type: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    details: Dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    """
    작업 정의 - 에이전트 간 협업의 기본 단위
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 1  # 1(낮음) ~ 5(높음)
    created_by: str
    assigned_to: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    deadline: Optional[datetime] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    history: List[TaskEvent] = Field(default_factory=list)
    subtasks: List[str] = Field(default_factory=list)
    parent_task: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# --------- MCP 클라이언트 ---------

class MCPClient:
    """MCP 서버와 통신하는 클라이언트"""
    
    def __init__(self, server_url: str, api_key: Optional[str] = None):
        """
        MCP 클라이언트 초기화
        
        Args:
            server_url: MCP 서버 URL
            api_key: 인증 API 키 (선택사항)
        """
        self.server_url = server_url
        self.api_key = api_key
        self.logger = logging.getLogger("mcp_client")
    
    async def execute_tool(self, tool_name: str, **parameters) -> Dict[str, Any]:
        """
        MCP 도구 실행
        
        Args:
            tool_name: 실행할 도구 이름
            parameters: 도구 실행에 필요한 매개변수
            
        Returns:
            도구 실행 결과
        """
        self.logger.info(f"MCP 도구 실행: {tool_name}")
        # 실제 구현에서는 HTTP 요청을 수행합니다.
        # 여기서는 시뮬레이션만 수행합니다.
        
        execution_id = str(uuid.uuid4())
        
        # 모의 응답
        return {
            "execution_id": execution_id,
            "status": "success",
            "result": {"message": f"{tool_name} 실행 완료", "parameters": parameters},
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """
        도구 실행 상태 조회
        
        Args:
            execution_id: 실행 ID
            
        Returns:
            실행 상태 정보
        """
        self.logger.info(f"도구 실행 상태 조회: {execution_id}")
        # 실제 구현에서는 HTTP 요청을 수행합니다.
        
        # 모의 응답
        return {
            "execution_id": execution_id,
            "status": "completed",
            "start_time": (datetime.now().timestamp() - 60),
            "end_time": datetime.now().timestamp(),
            "result": {"message": "실행 완료"}
        }
    
    async def cancel_execution(self, execution_id: str) -> Dict[str, Any]:
        """
        도구 실행 취소
        
        Args:
            execution_id: 취소할 실행 ID
            
        Returns:
            취소 결과
        """
        self.logger.info(f"도구 실행 취소: {execution_id}")
        # 실제 구현에서는 HTTP 요청을 수행합니다.
        
        # 모의 응답
        return {
            "execution_id": execution_id,
            "status": "cancelled",
            "message": "실행이 취소되었습니다."
        }


# --------- A2A 프로토콜 구현 ---------

class A2AProtocol:
    """A2A 프로토콜 구현 클래스"""
    
    def __init__(self, agent_id: str, broker_url: Optional[str] = None):
        """
        A2A 프로토콜 초기화
        
        Args:
            agent_id: 현재 에이전트 ID
            broker_url: A2A 브로커 URL (선택사항)
        """
        self.agent_id = agent_id
        self.broker_url = broker_url
        self.logger = logging.getLogger("a2a_protocol")
    
    async def send_message(self, to_agent_id: str, task_id: str, message: str,
                          modality: InteractionModality = InteractionModality.TEXT,
                          data: Optional[Any] = None) -> Dict[str, Any]:
        """
        다른 에이전트에게 메시지 전송
        
        Args:
            to_agent_id: 수신 에이전트 ID
            task_id: 관련 작업 ID
            message: 메시지 내용
            modality: 메시지 모달리티
            data: 추가 데이터
            
        Returns:
            전송 결과
        """
        self.logger.info(f"메시지 전송: {self.agent_id} -> {to_agent_id}, 작업: {task_id}")
        
        # 실제 구현에서는 메시지 브로커를 통해 메시지를 전송합니다.
        # 여기서는 시뮬레이션만 수행합니다.
        
        message_id = str(uuid.uuid4())
        
        # 모의 응답
        return {
            "message_id": message_id,
            "status": "sent",
            "from_agent": self.agent_id,
            "to_agent": to_agent_id,
            "task_id": task_id,
            "timestamp": datetime.now().isoformat()
        }
    
    async def register_task(self, task: Task) -> Dict[str, Any]:
        """
        A2A 시스템에 작업 등록
        
        Args:
            task: 등록할 작업
            
        Returns:
            등록 결과
        """
        self.logger.info(f"작업 등록: {task.task_id}")
        
        # 실제 구현에서는 A2A 서버에 작업을 등록합니다.
        # 여기서는 시뮬레이션만 수행합니다.
        
        # 모의 응답
        return {
            "task_id": task.task_id,
            "status": "registered",
            "message": "작업이 성공적으로 등록되었습니다."
        }


# --------- LLM 커넥터 ---------

class LLMConnector:
    """LLM 서비스 연결 및 요청 처리"""
    
    def __init__(self, api_url: str, api_key: str, model_name: str = "gpt-4"):
        """
        LLM 커넥터 초기화
        
        Args:
            api_url: LLM API URL
            api_key: API 키
            model_name: 사용할 모델 이름
        """
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
        self.logger = logging.getLogger("llm_connector")
    
    async def generate_response(self, prompt: str, system_message: Optional[str] = None,
                              temperature: float = 0.7, max_tokens: int = 1000) -> Dict[str, Any]:
        """
        LLM을 사용하여 응답 생성
        
        Args:
            prompt: 사용자 프롬프트
            system_message: 시스템 메시지 (선택사항)
            temperature: 온도 파라미터
            max_tokens: 최대 토큰 수
            
        Returns:
            LLM 응답 결과
        """
        self.logger.info(f"LLM 응답 생성: 모델={self.model_name}, 프롬프트 길이={len(prompt)}")
        
        # 실제 구현에서는 LLM API에 요청합니다.
        # 여기서는 시뮬레이션만 수행합니다.
        
        # 모의 응답
        return {
            "response": f"[LLM 응답] 프롬프트 '{prompt[:30]}...'에 대한 응답입니다.",
            "model": self.model_name,
            "tokens_used": len(prompt) // 4,
            "timestamp": datetime.now().isoformat()
        }


# --------- 에이전트 기본 클래스 ---------

class AgentBase(ABC):
    """모든 Sub-Agent의 기본 클래스"""
    
    def __init__(self, 
                 agent_card: AgentCard,
                 mcp_client: Optional[MCPClient] = None,
                 a2a_protocol: Optional[A2AProtocol] = None,
                 llm_connector: Optional[LLMConnector] = None):
        """
        에이전트 기본 클래스 초기화
        
        Args:
            agent_card: 에이전트 카드
            mcp_client: MCP 클라이언트 (선택사항)
            a2a_protocol: A2A 프로토콜 (선택사항)
            llm_connector: LLM 커넥터 (선택사항)
        """
        self.agent_card = agent_card
        self.tasks: Dict[str, Task] = {}
        self.status = AgentStatus.IDLE
        
        # 클라이언트 초기화
        self.mcp_client = mcp_client or MCPClient("http://mcp-server:8000")
        self.a2a_protocol = a2a_protocol or A2AProtocol(agent_card.agent_id)
        self.llm_connector = llm_connector
        
        self.logger = logging.getLogger(f"agent.{agent_card.agent_id}")
        self.logger.info(f"에이전트 초기화: {agent_card.name} (ID: {agent_card.agent_id})")
    
    def get_agent_card(self) -> Dict[str, Any]:
        """에이전트 카드 반환"""
        return self.agent_card.dict()
    
    async def create_task(self, title: str, description: str, context: Dict[str, Any] = None) -> str:
        """
        새 작업 생성
        
        Args:
            title: 작업 제목
            description: 작업 설명
            context: 작업 컨텍스트 (선택사항)
            
        Returns:
            생성된 작업 ID
        """
        self.logger.info(f"작업 생성: {title}")
        
        task = Task(
            title=title,
            description=description,
            created_by=self.agent_card.agent_id,
            context=context or {}
        )
        
        # 작업 이력 추가
        task.history.append(
            TaskEvent(
                agent_id=self.agent_card.agent_id,
                event_type="task_created",
                message=f"작업이 생성되었습니다."
            )
        )
        
        # 작업 등록
        self.tasks[task.task_id] = task
        
        # A2A 시스템에 작업 등록
        await self.a2a_protocol.register_task(task)
        
        return task.task_id
    
    async def assign_task(self, task_id: str, agent_id: str) -> bool:
        """
        작업을 다른 에이전트에 할당
        
        Args:
            task_id: 작업 ID
            agent_id: 할당할 에이전트 ID
            
        Returns:
            할당 성공 여부
        """
        if task_id not in self.tasks:
            self.logger.warning(f"작업 할당 실패: 작업 {task_id}를 찾을 수 없습니다.")
            return False
        
        self.logger.info(f"작업 할당: {task_id} -> {agent_id}")
        
        # 작업 상태 업데이트
        self.tasks[task_id].assigned_to = agent_id
        self.tasks[task_id].status = TaskStatus.IN_PROGRESS
        self.tasks[task_id].updated_at = datetime.now()
        
        # 작업 이력 추가
        self.tasks[task_id].history.append(
            TaskEvent(
                agent_id=self.agent_card.agent_id,
                event_type="task_assigned",
                message=f"작업이 {agent_id}에게 할당되었습니다."
            )
        )
        
        # 해당 에이전트에게 알림
        await self.a2a_protocol.send_message(
            to_agent_id=agent_id,
            task_id=task_id,
            message=f"작업 {task_id}가 할당되었습니다."
        )
        
        return True
    
    async def update_task_status(self, task_id: str, status: TaskStatus, message: Optional[str] = None) -> bool:
        """
        작업 상태 업데이트
        
        Args:
            task_id: 작업 ID
            status: 새 상태
            message: 상태 변경 메시지 (선택사항)
            
        Returns:
            업데이트 성공 여부
        """
        if task_id not in self.tasks:
            self.logger.warning(f"작업 상태 업데이트 실패: 작업 {task_id}를 찾을 수 없습니다.")
            return False
        
        self.logger.info(f"작업 상태 업데이트: {task_id} -> {status}")
        
        # 작업 상태 업데이트
        self.tasks[task_id].status = status
        self.tasks[task_id].updated_at = datetime.now()
        
        # 작업 이력 추가
        event_message = message or f"작업 상태가 {status}로 변경되었습니다."
        self.tasks[task_id].history.append(
            TaskEvent(
                agent_id=self.agent_card.agent_id,
                event_type="status_updated",
                message=event_message
            )
        )
        
        return True
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        작업 정보 조회
        
        Args:
            task_id: 작업 ID
            
        Returns:
            작업 정보 (없으면 None)
        """
        if task_id in self.tasks:
            return self.tasks[task_id].dict()
        return None
    
    async def call_mcp_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        MCP 도구 호출
        
        Args:
            tool_name: 도구 이름
            kwargs: 도구 매개변수
            
        Returns:
            도구 실행 결과
        """
        self.logger.info(f"MCP 도구 호출: {tool_name}")
        return await self.mcp_client.execute_tool(tool_name, **kwargs)
    
    async def communicate(self, to_agent_id: str, task_id: str, message: str) -> Dict[str, Any]:
        """
        다른 에이전트와 통신
        
        Args:
            to_agent_id: 수신 에이전트 ID
            task_id: 작업 ID
            message: 메시지
            
        Returns:
            통신 결과
        """
        self.logger.info(f"에이전트 통신: -> {to_agent_id}, 작업: {task_id}")
        
        if task_id in self.tasks:
            # 작업 이력 추가
            self.tasks[task_id].history.append(
                TaskEvent(
                    agent_id=self.agent_card.agent_id,
                    event_type="message_sent",
                    message=f"{to_agent_id}에게 메시지 전송: {message}"
                )
            )
        
        # A2A 프로토콜을 통해 메시지 전송
        return await self.a2a_protocol.send_message(to_agent_id, task_id, message)
    
    @abstractmethod
    async def process_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        이벤트 처리 (하위 클래스에서 구현해야 함)
        
        Args:
            event: 처리할 이벤트
            
        Returns:
            처리 결과
        """
        pass
    
    @abstractmethod
    async def process_task(self, task_id: str) -> Dict[str, Any]:
        """
        작업 처리 (하위 클래스에서 구현해야 함)
        
        Args:
            task_id: 작업 ID
            
        Returns:
            처리 결과
        """
        pass
    
    def set_status(self, status: AgentStatus):
        """
        에이전트 상태 설정
        
        Args:
            status: 새 상태
        """
        self.logger.info(f"에이전트 상태 변경: {self.status} -> {status}")
        self.status = status 