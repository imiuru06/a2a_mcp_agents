#!/usr/bin/env python3
"""
Event Gateway - 이벤트 핸들러 구현

이 모듈은 모니터링 시스템에서 전송되는 이벤트를 수신하고 처리하는 핸들러를 구현합니다.
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException, Request, Response, Depends, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("event_gateway")

# 이벤트 저장소 (실제로는 데이터베이스를 사용해야 함)
event_store: Dict[str, Dict[str, Any]] = {}

# Sub-Agent 라우팅 테이블 (실제로는 서비스 디스커버리나 설정에서 가져와야 함)
SUB_AGENT_ROUTES = {
    "cpu_high_usage": "http://sub-agent-cpu:8080/events",
    "memory_high_usage": "http://sub-agent-memory:8080/events",
    "disk_space_low": "http://sub-agent-disk:8080/events",
    "network_issue": "http://sub-agent-network:8080/events",
    "default": "http://sub-agent-general:8080/events"
}


# ----- 데이터 모델 -----

class EventData(BaseModel):
    """이벤트 데이터 모델"""
    class Config:
        extra = "allow"  # 추가 필드 허용


class EventPayload(BaseModel):
    """이벤트 페이로드 모델"""
    event_type: str
    source: str
    timestamp: datetime
    severity: str = Field(default="info", regex="^(info|warning|error|critical)$")
    data: EventData
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator('timestamp')
    def check_timestamp(cls, v):
        """타임스탬프가 미래 시간이 아닌지 확인"""
        if v > datetime.now():
            raise ValueError("타임스탬프는 미래 시간일 수 없습니다")
        return v


class EventResponse(BaseModel):
    """이벤트 응답 모델"""
    event_id: str
    status: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)


class EventStatusResponse(BaseModel):
    """이벤트 상태 응답 모델"""
    event_id: str
    status: str
    timestamp: datetime
    destination: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """오류 응답 모델"""
    error_code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    request_id: str
    timestamp: datetime = Field(default_factory=datetime.now)


# ----- FastAPI 앱 생성 -----

app = FastAPI(
    title="Event Gateway API",
    description="모니터링 시스템의 이벤트를 수신하여 Sub-Agent로 전달하는 API",
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


# ----- 의존성 함수 -----

def get_request_id(request: Request) -> str:
    """요청 ID 생성 또는 헤더에서 가져오기"""
    if "X-Request-ID" in request.headers:
        return request.headers["X-Request-ID"]
    return str(uuid.uuid4())


# ----- API 엔드포인트 -----

@app.post("/events", status_code=status.HTTP_202_ACCEPTED, response_model=EventResponse)
async def receive_event(
    payload: EventPayload,
    background_tasks: BackgroundTasks,
    request: Request,
    request_id: str = Depends(get_request_id)
):
    """
    이벤트 수신 엔드포인트
    
    모니터링 시스템에서 전송된 이벤트를 수신하고 처리합니다.
    """
    logger.info(f"이벤트 수신: {payload.event_type} (요청 ID: {request_id})")
    
    # 이벤트 ID 생성
    event_id = str(uuid.uuid4())
    
    # 이벤트 저장
    event_store[event_id] = {
        "payload": payload.dict(),
        "status": "received",
        "timestamp": datetime.now(),
        "request_id": request_id,
        "retry_count": 0
    }
    
    # 백그라운드에서 이벤트 처리
    background_tasks.add_task(process_event, event_id, payload)
    
    return EventResponse(
        event_id=event_id,
        status="received",
        message="이벤트가 성공적으로 수신되었습니다."
    )


@app.get("/events/{event_id}", response_model=EventStatusResponse)
async def get_event_status(event_id: str):
    """
    이벤트 상태 조회 엔드포인트
    
    특정 이벤트의 처리 상태를 조회합니다.
    """
    if event_id not in event_store:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error_code="EVENT_NOT_FOUND",
                message="지정된 이벤트를 찾을 수 없습니다.",
                request_id=str(uuid.uuid4())
            ).dict()
        )
    
    event = event_store[event_id]
    
    return EventStatusResponse(
        event_id=event_id,
        status=event["status"],
        timestamp=event["timestamp"],
        destination=event.get("destination"),
        details={
            "retry_count": event.get("retry_count", 0),
            "processing_time_ms": event.get("processing_time_ms")
        }
    )


@app.get("/health")
async def health_check():
    """
    서비스 상태 확인 엔드포인트
    
    Event Gateway 서비스의 상태를 확인합니다.
    """
    # 실제로는 의존성 서비스 상태도 확인해야 함
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime": 3600,  # 실제로는 서비스 시작 시간에서 계산
        "timestamp": datetime.now(),
        "dependencies": {
            "database": "ok",
            "cache": "ok",
            "message_broker": "ok"
        }
    }


# ----- 예외 핸들러 -----

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 예외 핸들러"""
    if isinstance(exc.detail, dict) and "error_code" in exc.detail:
        # 이미 ErrorResponse 형식인 경우
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )
    
    # ErrorResponse 형식으로 변환
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_code="HTTP_ERROR",
            message=str(exc.detail),
            request_id=get_request_id(request),
            details={"status_code": exc.status_code}
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """일반 예외 핸들러"""
    logger.error(f"예외 발생: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="서버 내부 오류가 발생했습니다.",
            request_id=get_request_id(request),
            details={"error": str(exc)}
        ).dict()
    )


# ----- 이벤트 처리 함수 -----

async def process_event(event_id: str, payload: EventPayload):
    """
    이벤트 처리 함수
    
    이벤트를 적절한 Sub-Agent로 전달합니다.
    """
    if event_id not in event_store:
        logger.error(f"이벤트를 찾을 수 없음: {event_id}")
        return
    
    event = event_store[event_id]
    event["status"] = "processing"
    
    try:
        # 이벤트 유형에 따라 적절한 Sub-Agent 선택
        destination = SUB_AGENT_ROUTES.get(payload.event_type, SUB_AGENT_ROUTES["default"])
        event["destination"] = destination
        
        logger.info(f"이벤트 {event_id} 전달 중: {destination}")
        
        # 실제로는 HTTP 클라이언트로 Sub-Agent에 전달
        # 여기서는 시뮬레이션만 수행
        await simulate_subagent_call(event_id, destination, payload)
        
        # 성공적으로 처리됨
        event["status"] = "forwarded"
        logger.info(f"이벤트 {event_id} 전달 완료: {destination}")
        
    except Exception as e:
        logger.error(f"이벤트 {event_id} 처리 중 오류 발생: {str(e)}", exc_info=True)
        event["status"] = "failed"
        event["error"] = str(e)
        
        # 재시도 로직 (최대 3회)
        if event["retry_count"] < 3:
            event["retry_count"] += 1
            logger.info(f"이벤트 {event_id} 재시도 중 ({event['retry_count']}/3)")
            
            # 지수 백오프 재시도
            await asyncio.sleep(2 ** event["retry_count"])
            await process_event(event_id, payload)


async def simulate_subagent_call(event_id: str, destination: str, payload: EventPayload):
    """
    Sub-Agent 호출 시뮬레이션
    
    실제로는 HTTP 클라이언트를 사용하여 Sub-Agent에 요청을 보내야 함
    """
    # 처리 시간 시뮬레이션
    start_time = datetime.now()
    await asyncio.sleep(0.5)  # 0.5초 지연
    end_time = datetime.now()
    
    # 처리 시간 기록
    processing_time = (end_time - start_time).total_seconds() * 1000
    event_store[event_id]["processing_time_ms"] = processing_time
    
    # 임의로 5%의 확률로 오류 발생 (테스트용)
    import random
    if random.random() < 0.05:
        raise Exception("Sub-Agent 연결 오류 (시뮬레이션)")


# ----- 메인 함수 -----

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("event_handler:app", host="0.0.0.0", port=8000, reload=True) 