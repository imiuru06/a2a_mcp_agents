#!/usr/bin/env python3
"""
A2A와 MCP 프로토콜을 활용한 자동차 정비 서비스 구현
"""

import json
import uuid
import asyncio
from datetime import datetime
from fastapi import FastAPI, HTTPException, WebSocket, Depends, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union
import uvicorn
import logging

# main.py에서 구현한 에이전트 클래스 가져오기
from main import (
    A2AAgent, ShopManagerAgent, MechanicAgent, PartsSupplierAgent,
    TaskStatus, AgentCard, Task
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("agent_service")

# FastAPI 앱 생성
app = FastAPI(
    title="자동차 정비 에이전트 서비스",
    description="A2A와 MCP 프로토콜을 활용한 자동차 정비 에이전트 서비스 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 운영에서는 특정 도메인으로 제한하는 것이 좋음
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------ 서비스 상태 관리 ------
# 실제 서비스에서는 데이터베이스를 사용하는 것이 바람직함
agents: Dict[str, A2AAgent] = {}
active_tasks: Dict[str, Dict[str, Any]] = {}
websocket_connections: Dict[str, WebSocket] = {}


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
    logger.info("에이전트 서비스 시작 중...")
    
    # 에이전트 인스턴스 생성
    shop_manager = ShopManagerAgent()
    mechanic = MechanicAgent()
    parts_supplier = PartsSupplierAgent()
    
    # 에이전트 등록
    agents[shop_manager.agent_card.agent_id] = shop_manager
    agents[mechanic.agent_card.agent_id] = mechanic
    agents[parts_supplier.agent_card.agent_id] = parts_supplier
    
    logger.info(f"에이전트 등록 완료: {len(agents)} 에이전트 활성화")


# ------ API 엔드포인트 ------
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "자동차 정비 에이전트 서비스 API"}


@app.get("/agents", response_model=List[AgentCardResponse])
async def list_agents():
    """등록된 모든 에이전트 목록 조회"""
    return [agent.get_agent_card() for agent in agents.values()]


@app.get("/agents/{agent_id}", response_model=AgentCardResponse)
async def get_agent(agent_id: str):
    """특정 에이전트 정보 조회"""
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="에이전트를 찾을 수 없습니다")
    
    return agents[agent_id].get_agent_card()


@app.post("/tasks", response_model=TaskCreationResponse)
async def create_task(request: CustomerRequest, background_tasks: BackgroundTasks):
    """고객 요청으로 새 작업 생성"""
    # Shop Manager 에이전트 가져오기
    shop_manager = next((a for a in agents.values() if isinstance(a, ShopManagerAgent)), None)
    if not shop_manager:
        raise HTTPException(status_code=500, detail="Shop Manager 에이전트를 찾을 수 없습니다")
    
    # 작업 생성
    task_id = shop_manager.create_task(
        title=f"차량 문제: {request.symptoms[0] if request.symptoms else '미지정'}",
        description=request.description,
        context={
            "customer_id": request.customer_id,
            "vehicle_id": request.vehicle_id,
            "vehicle_info": request.vehicle_info,
            "symptoms": request.symptoms,
            "created_at": datetime.now().isoformat()
        }
    )
    
    # 작업 진단 및 처리를 백그라운드로 실행
    background_tasks.add_task(process_new_task, task_id, shop_manager, request.symptoms)
    
    return {
        "task_id": task_id,
        "status": "created",
        "message": "작업이 생성되었으며 진단 중입니다."
    }


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """작업 상태 조회"""
    # 모든 에이전트에서 작업 찾기
    for agent in agents.values():
        if task_id in agent.tasks:
            task = agent.get_task(task_id)
            if task:
                return {
                    "task_id": task["task_id"],
                    "title": task["title"],
                    "status": task["status"],
                    "assigned_to": task["assigned_to"],
                    "history": task["history"],
                    "created_at": task["context"].get("created_at", "unknown")
                }
    
    raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")


@app.post("/parts/order", response_model=Dict[str, Any])
async def order_parts(request: PartOrderRequest):
    """부품 주문 API"""
    # Parts Supplier 에이전트 찾기
    parts_supplier = next((a for a in agents.values() if isinstance(a, PartsSupplierAgent)), None)
    if not parts_supplier:
        raise HTTPException(status_code=500, detail="Parts Supplier 에이전트를 찾을 수 없습니다")
    
    # 메카닉 에이전트 찾기
    mechanic = next((a for a in agents.values() if isinstance(a, MechanicAgent)), None)
    if not mechanic:
        raise HTTPException(status_code=500, detail="Mechanic 에이전트를 찾을 수 없습니다")
    
    # 작업이 존재하는지 확인
    task_exists = False
    for agent in agents.values():
        if request.task_id in agent.tasks:
            task_exists = True
            break
    
    if not task_exists:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    # 부품 주문을 위한 작업 생성 (실제 서비스에서는 A2A 서버로 요청할 것)
    parts_task_id = mechanic.create_task(
        title="부품 주문 요청",
        description=f"부품 #{request.part_number} {request.quantity}개 주문",
        context={"original_task_id": request.task_id}
    )
    
    # Parts Supplier에게 작업 전달 (실제로는 A2A 프로토콜을 통해)
    parts_supplier.tasks[parts_task_id] = mechanic.tasks[parts_task_id]
    
    # 메시지 전송
    mechanic.communicate(
        to_agent_id=parts_supplier.agent_card.agent_id,
        task_id=parts_task_id,
        message=f"부품 #{request.part_number} {request.quantity}개가 필요합니다."
    )
    
    # 부품 주문 처리
    order_result = parts_supplier.order_part(parts_task_id, request.part_number, request.quantity)
    
    return order_result


@app.websocket("/ws/task/{task_id}")
async def websocket_task_updates(websocket: WebSocket, task_id: str):
    """WebSocket을 통한 작업 업데이트 실시간 알림"""
    await websocket.accept()
    
    # 연결 저장
    client_id = str(uuid.uuid4())
    websocket_connections[client_id] = websocket
    
    try:
        # 현재 작업 상태 전송
        task_found = False
        for agent in agents.values():
            if task_id in agent.tasks:
                task = agent.get_task(task_id)
                if task:
                    task_found = True
                    await websocket.send_json({
                        "event": "initial_state",
                        "task": task
                    })
                    break
        
        if not task_found:
            await websocket.send_json({
                "event": "error",
                "message": "작업을 찾을 수 없습니다"
            })
            return
        
        # 클라이언트가 연결을 유지하는 동안 대기
        while True:
            # 클라이언트로부터 메시지를 받으면 처리
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            # 추가 메시지 처리 로직 구현 가능
            
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"WebSocket 오류: {str(e)}")
    finally:
        # 연결 종료 시 정리
        if client_id in websocket_connections:
            del websocket_connections[client_id]


# ------ 백그라운드 작업 처리 함수 ------
async def process_new_task(task_id: str, shop_manager: ShopManagerAgent, symptoms: List[str]):
    """새 작업 처리 백그라운드 함수"""
    logger.info(f"작업 {task_id} 진단 시작")
    
    try:
        # 진단 수행
        diagnosis_result = shop_manager.diagnose_issue(task_id, symptoms)
        
        # 진단 결과에 따라 메카닉에게 작업 할당
        mechanic = next((a for a in agents.values() if isinstance(a, MechanicAgent)), None)
        if not mechanic:
            logger.error("Mechanic 에이전트를 찾을 수 없습니다")
            return
        
        # 작업 할당
        assign_result = shop_manager.assign_to_mechanic(task_id, mechanic.agent_card.agent_id)
        logger.info(f"작업 할당 결과: {assign_result}")
        
        # 메카닉에게 작업 전달 (실제로는 A2A 프로토콜을 통해)
        mechanic.tasks[task_id] = shop_manager.tasks[task_id]
        
        # 수리 수행
        repair_result = mechanic.perform_repair(task_id)
        logger.info(f"수리 결과: {repair_result}")
        
        # 작업 상태 업데이트 알림
        await broadcast_task_update(task_id)
        
    except Exception as e:
        logger.error(f"작업 처리 중 오류 발생: {str(e)}")


async def broadcast_task_update(task_id: str):
    """작업 업데이트를 모든 관련 WebSocket 연결에 브로드캐스트"""
    # 작업 정보 찾기
    task_data = None
    for agent in agents.values():
        if task_id in agent.tasks:
            task_data = agent.get_task(task_id)
            break
    
    if not task_data:
        return
    
    # 모든 연결된 클라이언트에 업데이트 전송
    for client_id, websocket in list(websocket_connections.items()):
        try:
            await websocket.send_json({
                "event": "task_update",
                "task": task_data
            })
        except Exception as e:
            logger.error(f"업데이트 전송 중 오류: {str(e)}")
            # 끊어진 연결 정리
            if client_id in websocket_connections:
                del websocket_connections[client_id]


# ------ 서비스 실행 ------
if __name__ == "__main__":
    uvicorn.run("agent_service:app", host="0.0.0.0", port=8000, reload=True) 