#!/usr/bin/env python3
"""
A2A MCP 자동차 정비 서비스를 위한 간단한 API 서버
"""

import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# FastAPI 앱 생성
app = FastAPI(
    title="자동차 정비 에이전트 서비스 API",
    description="A2A와 MCP 프로토콜을 활용한 자동차 정비 에이전트 서비스 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터 저장소 (실제로는 데이터베이스를 사용해야 함)
agents = {}
tasks = {}

# ------ 데이터 모델 ------
class CustomerRequest(BaseModel):
    """고객 요청 모델"""
    customer_id: str
    vehicle_id: str
    vehicle_info: Dict[str, Any]
    description: str
    symptoms: List[str]


class TaskCreationResponse(BaseModel):
    """작업 생성 응답 모델"""
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """작업 상태 응답 모델"""
    task_id: str
    title: str
    status: str
    assigned_to: Optional[str] = None
    history: List[Dict[str, Any]]
    created_at: str


class PartOrderRequest(BaseModel):
    """부품 주문 요청 모델"""
    task_id: str
    part_number: str
    quantity: int = 1


class AgentCardResponse(BaseModel):
    """에이전트 카드 응답 모델"""
    agent_id: str
    name: str
    description: str
    skills: List[str]
    supported_modalities: List[str]


# ------ 서비스 초기화 ------
@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 에이전트 초기화"""
    print("에이전트 서비스 시작 중...")
    
    # 샘플 에이전트 생성
    agents["shop_manager"] = {
        "agent_id": "shop_manager",
        "name": "정비소 매니저",
        "description": "차량 정비 작업을 관리하고 작업을 할당하는 에이전트",
        "skills": ["작업 관리", "작업 할당", "고객 응대"],
        "supported_modalities": ["text"]
    }
    
    agents["mechanic"] = {
        "agent_id": "mechanic",
        "name": "정비사",
        "description": "차량 진단 및 수리를 수행하는 에이전트",
        "skills": ["엔진 수리", "전기 시스템", "브레이크 시스템", "진단"],
        "supported_modalities": ["text", "image"]
    }
    
    agents["parts_supplier"] = {
        "agent_id": "parts_supplier",
        "name": "부품 공급자",
        "description": "필요한 부품을 주문하고 재고를 관리하는 에이전트",
        "skills": ["부품 주문", "재고 관리", "가격 견적"],
        "supported_modalities": ["text"]
    }
    
    print(f"에이전트 등록 완료: {len(agents)} 에이전트 활성화")


# ------ API 엔드포인트 ------
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "자동차 정비 에이전트 서비스 API"}


@app.get("/agents", response_model=List[AgentCardResponse])
async def list_agents():
    """등록된 모든 에이전트 목록 조회"""
    return list(agents.values())


@app.get("/agents/{agent_id}", response_model=AgentCardResponse)
async def get_agent(agent_id: str):
    """특정 에이전트 정보 조회"""
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="에이전트를 찾을 수 없습니다")
    
    return agents[agent_id]


@app.post("/tasks", response_model=TaskCreationResponse)
async def create_task(request: CustomerRequest):
    """고객 요청으로 새 작업 생성"""
    # 작업 ID 생성
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    
    # 작업 생성
    tasks[task_id] = {
        "task_id": task_id,
        "title": f"차량 문제: {request.symptoms[0] if request.symptoms else '미지정'}",
        "description": request.description,
        "status": "pending",
        "assigned_to": None,
        "history": [
            {
                "timestamp": datetime.now().isoformat(),
                "agent_id": "system",
                "message": "작업이 생성되었습니다."
            }
        ],
        "context": {
            "customer_id": request.customer_id,
            "vehicle_id": request.vehicle_id,
            "vehicle_info": request.vehicle_info,
            "symptoms": request.symptoms,
            "created_at": datetime.now().isoformat()
        }
    }
    
    # 작업 할당 (백그라운드 작업 대신 즉시 처리)
    tasks[task_id]["status"] = "in_progress"
    tasks[task_id]["assigned_to"] = "mechanic"
    tasks[task_id]["history"].append({
        "timestamp": datetime.now().isoformat(),
        "agent_id": "shop_manager",
        "message": "작업이 정비사에게 할당되었습니다."
    })
    
    return {
        "task_id": task_id,
        "status": "created",
        "message": "작업이 생성되었으며 진단 중입니다."
    }


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """작업 상태 조회"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    task = tasks[task_id]
    return {
        "task_id": task["task_id"],
        "title": task["title"],
        "status": task["status"],
        "assigned_to": task["assigned_to"],
        "history": task["history"],
        "created_at": task["context"].get("created_at", "unknown")
    }


@app.post("/parts/order")
async def order_parts(request: PartOrderRequest):
    """부품 주문 API"""
    if request.task_id not in tasks:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    # 부품 주문 처리
    order_id = f"order_{uuid.uuid4().hex[:8]}"
    
    # 작업 기록 업데이트
    tasks[request.task_id]["history"].append({
        "timestamp": datetime.now().isoformat(),
        "agent_id": "parts_supplier",
        "message": f"부품 #{request.part_number} {request.quantity}개가 주문되었습니다. 주문 ID: {order_id}"
    })
    
    return {
        "order_id": order_id,
        "task_id": request.task_id,
        "part_number": request.part_number,
        "quantity": request.quantity,
        "status": "ordered",
        "estimated_arrival": (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                             .timestamp() + 86400).strftime("%Y-%m-%d")
    }


# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("simple_api:app", host="0.0.0.0", port=8000, reload=True) 