#!/usr/bin/env python3
"""
이벤트 게이트웨이 서비스 - 모니터링 시스템의 이벤트를 수신하여 Sub-Agent로 전달
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# FastAPI 앱 생성
app = FastAPI(
    title="이벤트 게이트웨이 서비스",
    description="모니터링 시스템의 이벤트를 수신하여 Sub-Agent로 전달하는 서비스",
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

# 서비스 설정
SUB_AGENT_URL = "http://sub-agent:8000/events"

# 데이터 모델
class Event(BaseModel):
    """이벤트 모델"""
    event_type: str
    source: str
    data: Dict[str, Any]
    timestamp: Optional[str] = None

class EventResponse(BaseModel):
    """이벤트 응답 모델"""
    event_id: str
    status: str
    message: str

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "이벤트 게이트웨이 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.post("/events", response_model=EventResponse)
async def receive_event(event: Event, background_tasks: BackgroundTasks):
    """외부 시스템으로부터 이벤트 수신"""
    # 이벤트 ID 생성
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    
    # 타임스탬프 추가
    if not event.timestamp:
        event.timestamp = datetime.now().isoformat()
    
    # 이벤트 처리를 백그라운드 작업으로 등록
    background_tasks.add_task(forward_event_to_sub_agent, event_id, event)
    
    return {
        "event_id": event_id,
        "status": "accepted",
        "message": "이벤트가 수신되었으며 처리 중입니다."
    }

# 백그라운드 작업
async def forward_event_to_sub_agent(event_id: str, event: Event):
    """이벤트를 Sub-Agent로 전달"""
    try:
        # 이벤트 데이터 준비
        payload = {
            "event_id": event_id,
            **event.dict()
        }
        
        # Sub-Agent로 이벤트 전달
        async with httpx.AsyncClient() as client:
            response = await client.post(SUB_AGENT_URL, json=payload)
            
            # 응답 확인
            if response.status_code != 200:
                print(f"Sub-Agent 이벤트 전달 실패: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"이벤트 전달 중 오류 발생: {str(e)}")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True) 