#!/usr/bin/env python3
"""
수퍼바이저 서비스 - A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답
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
    title="수퍼바이저 서비스",
    description="A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답",
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
CHAT_GATEWAY_URL = "http://chat-gateway:8002/responses"

# 상태 저장소
reports_store: Dict[str, Dict[str, Any]] = {}
messages_store: Dict[str, Dict[str, Any]] = {}

# 데이터 모델
class Report(BaseModel):
    """A2A 보고 모델"""
    report_id: str
    event_id: str
    agent_id: str
    status: str
    result: Dict[str, Any]
    timestamp: str

class UserResponse(BaseModel):
    """사용자 응답 모델"""
    client_id: str
    message: str
    response_type: str = "text"  # text, status, error
    data: Optional[Dict[str, Any]] = None

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "수퍼바이저 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.post("/reports")
async def receive_report(report: Report, background_tasks: BackgroundTasks):
    """Sub-Agent로부터 보고 수신"""
    # 보고 저장
    reports_store[report.report_id] = report.dict()
    
    # 보고 처리
    client_id = "client_1"  # 실제 구현에서는 이벤트와 클라이언트 매핑 필요
    
    if report.status == "completed":
        await send_response_to_user(
            client_id, 
            "작업이 완료되었습니다.", 
            "text"
        )
    else:
        await send_response_to_user(
            client_id, 
            "작업 처리 중 오류가 발생했습니다.", 
            "error"
        )
    
    return {"status": "accepted"}

@app.post("/messages")
async def receive_message(message: Dict[str, Any], background_tasks: BackgroundTasks):
    """Chat Gateway로부터 메시지 수신"""
    client_id = message.get("client_id")
    user_message = message.get("message", "")
    message_id = message.get("message_id", f"msg_{uuid.uuid4().hex[:8]}")
    
    # 메시지 저장
    messages_store[client_id] = {
        "message_id": message_id,
        "client_id": client_id,
        "message": user_message,
        "timestamp": datetime.now().isoformat(),
        "status": "received"
    }
    
    # 간단한 응답 생성 (실제 구현에서는 더 복잡한 로직 필요)
    response = "안녕하세요! 자동차 정비 서비스입니다. 어떻게 도와드릴까요?"
    
    # 응답 저장
    messages_store[client_id] = {
        "message_id": f"resp_{uuid.uuid4().hex[:8]}",
        "client_id": client_id,
        "message": response,
        "timestamp": datetime.now().isoformat(),
        "status": "completed"
    }
    
    # 사용자에게 응답 전송
    await send_response_to_user(client_id, response, "text")
    
    return {"status": "accepted"}

async def send_response_to_user(client_id: str, message: str, response_type: str, data: Dict[str, Any] = None):
    """사용자에게 응답 전송"""
    try:
        response = UserResponse(
            client_id=client_id,
            message=message,
            response_type=response_type,
            data=data
        )
        
        async with httpx.AsyncClient() as client:
            api_response = await client.post(CHAT_GATEWAY_URL, json=response.dict())
            
            if api_response.status_code != 200:
                print(f"응답 전송 실패: {api_response.status_code} - {api_response.text}")
                
    except Exception as e:
        print(f"응답 전송 중 오류 발생: {str(e)}")

@app.get("/responses/{client_id}")
async def get_response_by_client_id(client_id: str):
    """특정 클라이언트의 최신 응답 조회"""
    # 해당 클라이언트의 응답 검색
    if client_id in messages_store:
        return messages_store[client_id]
    
    # 응답이 없는 경우
    raise HTTPException(status_code=404, detail="해당 클라이언트의 응답을 찾을 수 없습니다.")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8003, reload=True)
