#!/usr/bin/env python3
"""
MSA 구조의 Event Gateway 서비스 구현

Event Gateway는 다음 기능을 제공합니다:
- 외부 모니터링 시스템의 이벤트 수신
- 이벤트 필터링 및 변환
- 적절한 Sub-Agent로 이벤트 라우팅
- 이벤트 처리 상태 추적
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Set
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import httpx

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("event_gateway")

# ----- 데이터 모델 -----

class EventStatus(str, Enum):
    """이벤트 처리 상태"""
    RECEIVED = "received"
    PROCESSING = "processing"
    ROUTED = "routed"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"


class EventType(str, Enum):
    """이벤트 유형"""
    MONITORING_ALERT = "monitoring_alert"
    SYSTEM_STATUS = "system_status"
    VEHICLE_DIAGNOSTIC = "vehicle_diagnostic"
    CUSTOMER_REQUEST = "customer_request"
    MAINTENANCE_REMINDER = "maintenance_reminder"
    PART_INVENTORY = "part_inventory"
    CUSTOM = "custom"


class EventSeverity(str, Enum):
    """이벤트 심각도"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Event(BaseModel):
    """이벤트 모델"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    source: str
    severity: EventSeverity = EventSeverity.INFO
    timestamp: datetime = Field(default_factory=datetime.now)
    data: Dict[str, Any]
    status: EventStatus = EventStatus.RECEIVED
    received_at: datetime = Field(default_factory=datetime.now)
    processed_at: Optional[datetime] = None
    routing_info: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class EventRequest(BaseModel):
    """이벤트 요청"""
    event_type: EventType
    source: str
    severity: EventSeverity = EventSeverity.INFO
    data: Dict[str, Any]
    tags: List[str] = Field(default_factory=list)


class EventResponse(BaseModel):
    """이벤트 응답"""
    event_id: str
    status: EventStatus
    message: str
    timestamp: datetime


class AgentInfo(BaseModel):
    """에이전트 정보"""
    agent_id: str
    name: str
    endpoint: str
    capabilities: List[str] = Field(default_factory=list)
    status: str = "active"


# ----- 인메모리 저장소 (실제 구현에서는 데이터베이스 사용) -----

events: Dict[str, Event] = {}
agents: Dict[str, AgentInfo] = {}
event_rules: List[Dict[str, Any]] = []

# ----- FastAPI 앱 생성 -----

app = FastAPI(
    title="Event Gateway",
    description="모니터링 시스템의 이벤트를 수신하여 Sub-Agent로 전달하는 서비스",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 보안을 위해 실제 환경에서는 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- 유틸리티 함수 -----

def match_event_to_rules(event: Event) -> List[AgentInfo]:
    """
    이벤트를 라우팅 규칙과 매칭하여 대상 에이전트 결정
    
    Args:
        event: 처리할 이벤트
        
    Returns:
        매칭된 에이전트 목록
    """
    matched_agents: List[AgentInfo] = []
    
    for rule in event_rules:
        match = True
        
        # 이벤트 유형 확인
        if "event_types" in rule and event.event_type not in rule["event_types"]:
            match = False
            continue
        
        # 소스 확인
        if "sources" in rule and event.source not in rule["sources"]:
            match = False
            continue
        
        # 심각도 확인
        if "min_severity" in rule:
            severity_levels = {
                EventSeverity.INFO: 0,
                EventSeverity.WARNING: 1,
                EventSeverity.ERROR: 2,
                EventSeverity.CRITICAL: 3
            }
            
            if severity_levels[event.severity] < severity_levels[rule["min_severity"]]:
                match = False
                continue
        
        # 태그 확인
        if "required_tags" in rule:
            required_tags = set(rule["required_tags"])
            event_tags = set(event.tags)
            if not required_tags.issubset(event_tags):
                match = False
                continue
        
        # 매칭되면 에이전트 추가
        if match and "agent_id" in rule and rule["agent_id"] in agents:
            matched_agents.append(agents[rule["agent_id"]])
    
    return matched_agents


async def route_event(event_id: str):
    """
    이벤트를 적절한 에이전트로 라우팅
    
    Args:
        event_id: 이벤트 ID
    """
    if event_id not in events:
        logger.error(f"이벤트 ID를 찾을 수 없음: {event_id}")
        return
    
    event = events[event_id]
    event.status = EventStatus.PROCESSING
    
    try:
        # 대상 에이전트 결정
        target_agents = match_event_to_rules(event)
        
        if not target_agents:
            logger.warning(f"이벤트 {event_id}에 대한 대상 에이전트가 없습니다.")
            event.status = EventStatus.IGNORED
            event.processed_at = datetime.now()
            event.routing_info["message"] = "매칭되는 규칙이 없습니다."
            return
        
        logger.info(f"이벤트 {event_id}를 {len(target_agents)}개 에이전트로 라우팅합니다.")
        
        # 각 에이전트로 이벤트 전송
        routed_agents = []
        for agent in target_agents:
            try:
                # 실제 구현에서는 비동기 HTTP 요청이나 메시지 큐 사용
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{agent.endpoint}/events",
                        json={
                            "event_id": event.event_id,
                            "event_type": event.event_type,
                            "source": event.source,
                            "severity": event.severity,
                            "timestamp": event.timestamp.isoformat(),
                            "data": event.data,
                            "tags": event.tags
                        },
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        routed_agents.append(agent.agent_id)
                        logger.info(f"이벤트 {event_id}가 에이전트 {agent.agent_id}로 성공적으로 라우팅되었습니다.")
                    else:
                        logger.warning(f"에이전트 {agent.agent_id}로 이벤트 라우팅 실패: {response.text}")
            except Exception as e:
                logger.error(f"에이전트 {agent.agent_id}로 이벤트 전송 중 오류: {str(e)}")
        
        # 라우팅 결과 업데이트
        if routed_agents:
            event.status = EventStatus.ROUTED
            event.routing_info["routed_to"] = routed_agents
            event.routing_info["routed_at"] = datetime.now().isoformat()
        else:
            event.status = EventStatus.FAILED
            event.routing_info["message"] = "모든 에이전트로의 라우팅이 실패했습니다."
        
        event.processed_at = datetime.now()
        
    except Exception as e:
        logger.error(f"이벤트 라우팅 중 오류: {str(e)}")
        event.status = EventStatus.FAILED
        event.processed_at = datetime.now()
        event.routing_info["error"] = str(e)


async def retry_failed_events():
    """실패한 이벤트를 재시도"""
    while True:
        try:
            retry_candidates = []
            now = datetime.now()
            
            for event_id, event in events.items():
                # 실패했고 5분 이내인 이벤트만 재시도
                if (event.status == EventStatus.FAILED and 
                    event.processed_at and 
                    (now - event.processed_at).total_seconds() < 300):
                    retry_candidates.append(event_id)
            
            for event_id in retry_candidates:
                logger.info(f"실패한 이벤트 재시도: {event_id}")
                await route_event(event_id)
            
            # 5분마다 재시도
            await asyncio.sleep(300)
        except Exception as e:
            logger.error(f"실패한 이벤트 재시도 중 오류: {str(e)}")
            await asyncio.sleep(60)  # 오류 발생 시 1분 후 재시도


# ----- API 엔드포인트 -----

@app.get("/")
async def root():
    """서버 상태 확인"""
    return {"status": "active", "version": "1.0.0"}


@app.post("/api/v1/events", response_model=EventResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_event(request: EventRequest, background_tasks: BackgroundTasks):
    """외부 시스템에서 이벤트 수신"""
    event_id = str(uuid.uuid4())
    
    # 이벤트 생성
    event = Event(
        event_id=event_id,
        event_type=request.event_type,
        source=request.source,
        severity=request.severity,
        data=request.data,
        tags=request.tags
    )
    
    # 이벤트 저장
    events[event_id] = event
    logger.info(f"이벤트 수신: {event_id}, 유형: {request.event_type}, 소스: {request.source}")
    
    # 백그라운드에서 이벤트 라우팅
    background_tasks.add_task(route_event, event_id)
    
    return EventResponse(
        event_id=event_id,
        status=EventStatus.RECEIVED,
        message="이벤트가 수신되었으며 처리 중입니다.",
        timestamp=datetime.now()
    )


@app.get("/api/v1/events/{event_id}")
async def get_event(event_id: str):
    """이벤트 상태 조회"""
    if event_id not in events:
        raise HTTPException(status_code=404, detail="이벤트 ID를 찾을 수 없습니다.")
    
    return events[event_id].dict()


@app.post("/api/v1/events/{event_id}/retry")
async def retry_event(event_id: str, background_tasks: BackgroundTasks):
    """이벤트 재처리 요청"""
    if event_id not in events:
        raise HTTPException(status_code=404, detail="이벤트 ID를 찾을 수 없습니다.")
    
    # 이벤트 상태 초기화
    event = events[event_id]
    event.status = EventStatus.RECEIVED
    event.routing_info = {}
    
    # 백그라운드에서 이벤트 라우팅 재시도
    background_tasks.add_task(route_event, event_id)
    
    return {
        "event_id": event_id,
        "message": "이벤트 재처리가 시작되었습니다.",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/v1/agents")
async def list_agents():
    """등록된 에이전트 목록"""
    return list(agents.values())


@app.post("/api/v1/agents")
async def register_agent(agent: AgentInfo):
    """새 에이전트 등록"""
    agents[agent.agent_id] = agent
    logger.info(f"에이전트 등록: {agent.name} (ID: {agent.agent_id})")
    
    return {
        "agent_id": agent.agent_id,
        "message": "에이전트가 성공적으로 등록되었습니다."
    }


@app.get("/api/v1/rules")
async def list_rules():
    """라우팅 규칙 목록"""
    return event_rules


@app.post("/api/v1/rules")
async def add_rule(rule: Dict[str, Any]):
    """새 라우팅 규칙 추가"""
    rule_id = len(event_rules)
    rule["rule_id"] = rule_id
    
    event_rules.append(rule)
    logger.info(f"라우팅 규칙 추가: {rule_id}")
    
    return {
        "rule_id": rule_id,
        "message": "라우팅 규칙이 추가되었습니다."
    }


@app.get("/api/v1/metrics")
async def get_metrics():
    """이벤트 처리 메트릭 조회"""
    metrics = {
        "total_events": len(events),
        "events_by_status": {
            status.value: sum(1 for e in events.values() if e.status == status)
            for status in EventStatus
        },
        "events_by_type": {
            event_type.value: sum(1 for e in events.values() if e.event_type == event_type)
            for event_type in EventType
        },
        "events_by_severity": {
            severity.value: sum(1 for e in events.values() if e.severity == severity)
            for severity in EventSeverity
        }
    }
    
    return metrics


# ----- 서버 시작 시 실행 -----

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 초기화"""
    logger.info("Event Gateway 시작 중...")
    
    # 샘플 에이전트 등록
    shop_manager = AgentInfo(
        agent_id="shop_manager_001",
        name="Shop Manager",
        endpoint="http://shop-manager-service:8001/api/v1",
        capabilities=["customer_service", "task_delegation", "problem_diagnosis"]
    )
    
    mechanic = AgentInfo(
        agent_id="mechanic_001",
        name="Auto Mechanic",
        endpoint="http://mechanic-service:8002/api/v1",
        capabilities=["car_diagnosis", "car_repair", "parts_replacement"]
    )
    
    parts_supplier = AgentInfo(
        agent_id="parts_supplier_001",
        name="Parts Supplier",
        endpoint="http://parts-supplier-service:8003/api/v1",
        capabilities=["parts_inventory", "pricing", "ordering"]
    )
    
    agents[shop_manager.agent_id] = shop_manager
    agents[mechanic.agent_id] = mechanic
    agents[parts_supplier.agent_id] = parts_supplier
    
    logger.info(f"샘플 에이전트 등록 완료: {len(agents)}개 에이전트")
    
    # 샘플 라우팅 규칙 등록
    event_rules.extend([
        {
            "rule_id": 0,
            "event_types": [EventType.CUSTOMER_REQUEST],
            "agent_id": "shop_manager_001",
            "description": "모든 고객 요청은 매장 관리자에게 라우팅"
        },
        {
            "rule_id": 1,
            "event_types": [EventType.VEHICLE_DIAGNOSTIC],
            "agent_id": "mechanic_001",
            "description": "모든 차량 진단 이벤트는 정비사에게 라우팅"
        },
        {
            "rule_id": 2,
            "event_types": [EventType.PART_INVENTORY],
            "agent_id": "parts_supplier_001",
            "description": "모든 부품 재고 이벤트는 부품 공급자에게 라우팅"
        },
        {
            "rule_id": 3,
            "event_types": [EventType.MONITORING_ALERT],
            "min_severity": EventSeverity.ERROR,
            "agent_id": "mechanic_001",
            "description": "심각한 모니터링 경고는 정비사에게 라우팅"
        },
        {
            "rule_id": 4,
            "event_types": [EventType.MAINTENANCE_REMINDER],
            "sources": ["system_scheduler"],
            "agent_id": "shop_manager_001",
            "description": "시스템 스케줄러에서 발생한 유지보수 알림은 매장 관리자에게 라우팅"
        }
    ])
    
    logger.info(f"샘플 라우팅 규칙 등록 완료: {len(event_rules)}개 규칙")
    
    # 실패한 이벤트 재시도 백그라운드 작업 시작
    asyncio.create_task(retry_failed_events())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8010, reload=True) 