#!/usr/bin/env python3
"""
채팅 게이트웨이 서비스 - 사용자 채팅/인터럽트/상태 메시지 처리 및 라우팅
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import asyncio

# FastAPI 앱 생성
app = FastAPI(
    title="채팅 게이트웨이 서비스",
    description="사용자 채팅/인터럽트/상태 메시지 처리 및 라우팅",
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
SUPERVISOR_URL = "http://supervisor:8003/messages"

# 웹소켓 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]

    async def send_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)

manager = ConnectionManager()

# 데이터 모델
class ChatMessage(BaseModel):
    """채팅 메시지 모델"""
    client_id: str
    message: str
    timestamp: Optional[str] = None
    message_type: str = "chat"  # chat, interrupt, status

class ChatResponse(BaseModel):
    """채팅 응답 모델"""
    message_id: str
    status: str

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "채팅 게이트웨이 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.post("/messages", response_model=ChatResponse)
async def send_message(chat: ChatMessage, background_tasks: BackgroundTasks):
    """사용자로부터 메시지 수신"""
    # 메시지 ID 생성
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    
    # 타임스탬프 추가
    if not chat.timestamp:
        chat.timestamp = datetime.now().isoformat()
    
    # 메시지 처리를 백그라운드 작업으로 등록
    background_tasks.add_task(forward_message_to_supervisor, message_id, chat)
    
    return {
        "message_id": message_id,
        "status": "accepted"
    }

@app.post("/responses")
async def receive_response(response: Dict[str, Any]):
    """Supervisor로부터 응답 수신"""
    client_id = response.get("client_id")
    message = response.get("message")
    
    if client_id and message:
        await manager.send_message(json.dumps(response), client_id)
        return {"status": "delivered"}
    else:
        raise HTTPException(status_code=400, detail="Invalid response format")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """웹소켓 연결 처리"""
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            message["client_id"] = client_id
            message["timestamp"] = datetime.now().isoformat()
            
            # 메시지를 Supervisor로 전달
            message_id = f"msg_{uuid.uuid4().hex[:8]}"
            asyncio.create_task(forward_message_to_supervisor(message_id, ChatMessage(**message)))
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        print(f"웹소켓 처리 중 오류 발생: {str(e)}")
        manager.disconnect(client_id)

# 백그라운드 작업
async def forward_message_to_supervisor(message_id: str, chat: ChatMessage):
    """메시지를 Supervisor로 전달"""
    try:
        # 메시지 데이터 준비
        payload = {
            "message_id": message_id,
            **chat.dict()
        }
        
        # Supervisor로 메시지 전달
        async with httpx.AsyncClient() as client:
            response = await client.post(SUPERVISOR_URL, json=payload)
            
            # 응답 확인
            if response.status_code != 200:
                print(f"Supervisor 메시지 전달 실패: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"메시지 전달 중 오류 발생: {str(e)}")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8002, reload=True) 