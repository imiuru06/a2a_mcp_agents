from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Set, Any
import os
import json
import time
import httpx
from datetime import datetime
import logging
from sqlalchemy import create_engine, Column, String, Integer, JSON, DateTime, Boolean, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.sql import func
import uuid
from contextlib import contextmanager

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_card_registry")

# 데이터베이스 URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/agent_registry")

# 서비스 레지스트리 URL
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# 메시지 브로커 URL
MESSAGE_BROKER_URL = os.getenv("MESSAGE_BROKER_URL", "amqp://message-broker:5672")

# DB 엔진 생성
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 세션 컨텍스트 매니저
@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 에이전트 능력-태그 연결 테이블
agent_capability = Table(
    "agent_capability",
    Base.metadata,
    Column("agent_id", String, ForeignKey("agents.id"), primary_key=True),
    Column("capability_id", String, ForeignKey("capabilities.id"), primary_key=True)
)

# 데이터베이스 모델
class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    version = Column(String, nullable=False)
    url = Column(String, nullable=False)  # 에이전트 서비스 URL
    health_check_url = Column(String, nullable=True)
    status = Column(String, default="active")  # active, inactive, error
    metadata = Column(JSON, nullable=True, default={})
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # 관계 설정
    capabilities = relationship("Capability", secondary=agent_capability, back_populates="agents")

class Capability(Base):
    __tablename__ = "capabilities"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    category = Column(String, nullable=True)
    priority = Column(Integer, default=5)  # 1-10 우선순위 (10이 최고)
    metadata = Column(JSON, nullable=True, default={})
    created_at = Column(DateTime, server_default=func.now())
    
    # 관계 설정
    agents = relationship("Agent", secondary=agent_capability, back_populates="capabilities")

# Pydantic 모델
class AgentBase(BaseModel):
    name: str
    description: Optional[str] = None
    version: str
    url: str
    health_check_url: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)

class AgentCreate(AgentBase):
    capabilities: List[str] = []  # 능력 이름 목록

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    url: Optional[str] = None
    health_check_url: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict] = None
    capabilities: Optional[List[str]] = None

class AgentResponse(AgentBase):
    id: str
    status: str
    capabilities: List[str]
    created_at: datetime
    updated_at: Optional[datetime] = None

class CapabilityBase(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = 5
    metadata: Dict = Field(default_factory=dict)

class CapabilityCreate(CapabilityBase):
    pass

class CapabilityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
    metadata: Optional[Dict] = None

class CapabilityResponse(CapabilityBase):
    id: str
    created_at: datetime
    agents: Optional[List[str]] = []

class FindAgentRequest(BaseModel):
    required_capabilities: List[str]
    preferred_capabilities: Optional[List[str]] = []
    metadata_filters: Optional[Dict[str, Any]] = None

# FastAPI 애플리케이션
app = FastAPI(title="Agent Card Registry API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP 클라이언트
http_client = httpx.AsyncClient(timeout=30.0)

# 테이블 생성
@app.on_event("startup")
async def startup_db_client():
    Base.metadata.create_all(bind=engine)
    
    # 서비스 등록
    try:
        service_data = {
            "name": "agent-card-registry",
            "url": "http://agent-card-registry:8006",
            "health_check_url": "http://agent-card-registry:8006/health",
            "metadata": {
                "version": "1.0",
                "description": "Agent capabilities and card management"
            }
        }
        
        async with http_client as client:
            response = await client.post(
                f"{SERVICE_REGISTRY_URL}",
                json=service_data
            )
            
            if response.status_code == 200:
                logger.info("Agent Card Registry가 서비스 레지스트리에 등록되었습니다.")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

@app.get("/health")
async def health_check():
    """서비스 헬스 체크 엔드포인트"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

# 에이전트 관련 엔드포인트
@app.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(agent: AgentCreate):
    """새 에이전트 등록"""
    with get_db() as db:
        # 이름 중복 확인
        existing = db.query(Agent).filter(Agent.name == agent.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent with name '{agent.name}' already exists"
            )
        
        # 새 에이전트 생성
        new_agent = Agent(
            name=agent.name,
            description=agent.description,
            version=agent.version,
            url=agent.url,
            health_check_url=agent.health_check_url,
            metadata=agent.metadata
        )
        
        # 능력 연결
        for capability_name in agent.capabilities:
            capability = db.query(Capability).filter(Capability.name == capability_name).first()
            if not capability:
                # 자동으로 새 능력 생성
                capability = Capability(name=capability_name)
                db.add(capability)
                db.flush()
            new_agent.capabilities.append(capability)
        
        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)
        
        # 응답 포맷팅
        return AgentResponse(
            id=new_agent.id,
            name=new_agent.name,
            description=new_agent.description,
            version=new_agent.version,
            url=new_agent.url,
            health_check_url=new_agent.health_check_url,
            status=new_agent.status,
            metadata=new_agent.metadata,
            capabilities=[c.name for c in new_agent.capabilities],
            created_at=new_agent.created_at,
            updated_at=new_agent.updated_at
        )

@app.get("/agents", response_model=List[AgentResponse])
async def list_agents(
    status: Optional[str] = None,
    capability: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """에이전트 목록 조회"""
    with get_db() as db:
        query = db.query(Agent)
        
        # 필터링
        if status:
            query = query.filter(Agent.status == status)
        
        if capability:
            query = query.join(Agent.capabilities).filter(Capability.name == capability)
        
        agents = query.offset(skip).limit(limit).all()
        
        return [
            AgentResponse(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                version=agent.version,
                url=agent.url,
                health_check_url=agent.health_check_url,
                status=agent.status,
                metadata=agent.metadata,
                capabilities=[c.name for c in agent.capabilities],
                created_at=agent.created_at,
                updated_at=agent.updated_at
            )
            for agent in agents
        ]

@app.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """특정 에이전트 정보 조회"""
    with get_db() as db:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found"
            )
        
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            url=agent.url,
            health_check_url=agent.health_check_url,
            status=agent.status,
            metadata=agent.metadata,
            capabilities=[c.name for c in agent.capabilities],
            created_at=agent.created_at,
            updated_at=agent.updated_at
        )

@app.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, agent_update: AgentUpdate):
    """에이전트 정보 업데이트"""
    with get_db() as db:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found"
            )
        
        # 필드 업데이트
        if agent_update.name is not None:
            # 이름 중복 확인
            if agent_update.name != agent.name:
                existing = db.query(Agent).filter(Agent.name == agent_update.name).first()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Agent with name '{agent_update.name}' already exists"
                    )
            agent.name = agent_update.name
        
        if agent_update.description is not None:
            agent.description = agent_update.description
        
        if agent_update.version is not None:
            agent.version = agent_update.version
        
        if agent_update.url is not None:
            agent.url = agent_update.url
        
        if agent_update.health_check_url is not None:
            agent.health_check_url = agent_update.health_check_url
        
        if agent_update.status is not None:
            agent.status = agent_update.status
        
        if agent_update.metadata is not None:
            agent.metadata = agent_update.metadata
        
        if agent_update.capabilities is not None:
            # 기존 능력 연결 제거
            agent.capabilities = []
            
            # 새 능력 연결
            for capability_name in agent_update.capabilities:
                capability = db.query(Capability).filter(Capability.name == capability_name).first()
                if not capability:
                    # 자동으로 새 능력 생성
                    capability = Capability(name=capability_name)
                    db.add(capability)
                    db.flush()
                agent.capabilities.append(capability)
        
        db.commit()
        db.refresh(agent)
        
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            url=agent.url,
            health_check_url=agent.health_check_url,
            status=agent.status,
            metadata=agent.metadata,
            capabilities=[c.name for c in agent.capabilities],
            created_at=agent.created_at,
            updated_at=agent.updated_at
        )

@app.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str):
    """에이전트 삭제"""
    with get_db() as db:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent with ID {agent_id} not found"
            )
        
        db.delete(agent)
        db.commit()

# 능력 관련 엔드포인트
@app.post("/capabilities", response_model=CapabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_capability(capability: CapabilityCreate):
    """새 능력 등록"""
    with get_db() as db:
        # 이름 중복 확인
        existing = db.query(Capability).filter(Capability.name == capability.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Capability with name '{capability.name}' already exists"
            )
        
        # 새 능력 생성
        new_capability = Capability(
            name=capability.name,
            description=capability.description,
            category=capability.category,
            priority=capability.priority,
            metadata=capability.metadata
        )
        
        db.add(new_capability)
        db.commit()
        db.refresh(new_capability)
        
        return CapabilityResponse(
            id=new_capability.id,
            name=new_capability.name,
            description=new_capability.description,
            category=new_capability.category,
            priority=new_capability.priority,
            metadata=new_capability.metadata,
            created_at=new_capability.created_at,
            agents=[]
        )

@app.get("/capabilities", response_model=List[CapabilityResponse])
async def list_capabilities(
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100
):
    """능력 목록 조회"""
    with get_db() as db:
        query = db.query(Capability)
        
        # 필터링
        if category:
            query = query.filter(Capability.category == category)
        
        capabilities = query.offset(skip).limit(limit).all()
        
        return [
            CapabilityResponse(
                id=capability.id,
                name=capability.name,
                description=capability.description,
                category=capability.category,
                priority=capability.priority,
                metadata=capability.metadata,
                created_at=capability.created_at,
                agents=[a.name for a in capability.agents]
            )
            for capability in capabilities
        ]

@app.get("/capabilities/{capability_id}", response_model=CapabilityResponse)
async def get_capability(capability_id: str):
    """특정 능력 정보 조회"""
    with get_db() as db:
        capability = db.query(Capability).filter(Capability.id == capability_id).first()
        if not capability:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capability with ID {capability_id} not found"
            )
        
        return CapabilityResponse(
            id=capability.id,
            name=capability.name,
            description=capability.description,
            category=capability.category,
            priority=capability.priority,
            metadata=capability.metadata,
            created_at=capability.created_at,
            agents=[a.name for a in capability.agents]
        )

@app.put("/capabilities/{capability_id}", response_model=CapabilityResponse)
async def update_capability(capability_id: str, capability_update: CapabilityUpdate):
    """능력 정보 업데이트"""
    with get_db() as db:
        capability = db.query(Capability).filter(Capability.id == capability_id).first()
        if not capability:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capability with ID {capability_id} not found"
            )
        
        # 필드 업데이트
        if capability_update.name is not None:
            # 이름 중복 확인
            if capability_update.name != capability.name:
                existing = db.query(Capability).filter(Capability.name == capability_update.name).first()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Capability with name '{capability_update.name}' already exists"
                    )
            capability.name = capability_update.name
        
        if capability_update.description is not None:
            capability.description = capability_update.description
        
        if capability_update.category is not None:
            capability.category = capability_update.category
        
        if capability_update.priority is not None:
            capability.priority = capability_update.priority
        
        if capability_update.metadata is not None:
            capability.metadata = capability_update.metadata
        
        db.commit()
        db.refresh(capability)
        
        return CapabilityResponse(
            id=capability.id,
            name=capability.name,
            description=capability.description,
            category=capability.category,
            priority=capability.priority,
            metadata=capability.metadata,
            created_at=capability.created_at,
            agents=[a.name for a in capability.agents]
        )

@app.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(capability_id: str):
    """능력 삭제"""
    with get_db() as db:
        capability = db.query(Capability).filter(Capability.id == capability_id).first()
        if not capability:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capability with ID {capability_id} not found"
            )
        
        db.delete(capability)
        db.commit()

# 에이전트 찾기 엔드포인트
@app.post("/agents/find", response_model=List[AgentResponse])
async def find_agents(request: FindAgentRequest):
    """필요한 능력을 가진 에이전트 찾기"""
    with get_db() as db:
        # 활성 상태의 에이전트 기본 쿼리
        query = db.query(Agent).filter(Agent.status == "active")
        
        # 필수 능력을 가진 에이전트 필터링
        for capability_name in request.required_capabilities:
            query = query.join(Agent.capabilities).filter(Capability.name == capability_name)
        
        # 메타데이터 필터링
        if request.metadata_filters:
            for key, value in request.metadata_filters.items():
                # JSON 필드 필터링은 DB에 따라 다를 수 있음
                # PostgreSQL의 경우 -> 표기법 사용
                query = query.filter(Agent.metadata[key].astext == str(value))
        
        # 결과 추출 - 잠재적으로 많은 에이전트가 나올 수 있으므로 제한
        potential_agents = query.all()
        
        # 선호 능력에 따른 점수 계산 및 정렬
        scored_agents = []
        for agent in potential_agents:
            score = 0
            agent_capabilities = {c.name: c for c in agent.capabilities}
            
            # 선호 능력에 따른 점수 부여
            for pref_cap in request.preferred_capabilities or []:
                if pref_cap in agent_capabilities:
                    # 능력의 우선순위를 점수에 반영
                    score += agent_capabilities[pref_cap].priority
            
            scored_agents.append((agent, score))
        
        # 점수에 따라 정렬 (높은 순)
        scored_agents.sort(key=lambda x: x[1], reverse=True)
        
        # 응답 변환
        return [
            AgentResponse(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                version=agent.version,
                url=agent.url,
                health_check_url=agent.health_check_url,
                status=agent.status,
                metadata=agent.metadata,
                capabilities=[c.name for c in agent.capabilities],
                created_at=agent.created_at,
                updated_at=agent.updated_at
            )
            for agent, _ in scored_agents
        ] 