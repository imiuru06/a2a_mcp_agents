#!/usr/bin/env python3
"""
채팅 게이트웨이 서비스 - 사용자 채팅/인터럽트/상태 메시지 처리 및 라우팅
"""

import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json
import asyncio
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat_gateway")

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
SUPERVISOR_URL = os.getenv("SUPERVISOR_URL", "http://supervisor:8003/messages")
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# 재시도 설정
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))
RESPONSE_TIMEOUT = float(os.getenv("RESPONSE_TIMEOUT", "10.0"))  # 응답 대기 타임아웃(초)

# 메시지 저장소 (간단한 인메모리 저장소)
message_store: Dict[str, Dict[str, Any]] = {}

# 웹소켓 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"웹소켓 연결 성공: client_id={client_id}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"웹소켓 연결 종료: client_id={client_id}")

    async def send_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)
            logger.debug(f"메시지 전송 성공: client_id={client_id}")
            return True
        else:
            logger.warning(f"메시지 전송 실패: client_id={client_id} - 연결 없음")
            return False

    async def broadcast(self, message: str):
        for client_id, connection in self.active_connections.items():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"브로드캐스트 중 오류 발생: client_id={client_id}, error={str(e)}")

manager = ConnectionManager()

# 데이터 모델
class ChatMessage(BaseModel):
    """채팅 메시지 모델"""
    client_id: str
    message: str
    timestamp: Optional[str] = None
    message_type: str = "chat"  # chat, interrupt, status
    context: Optional[Dict[str, Any]] = None

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
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/messages", response_model=ChatResponse)
async def send_message(chat: ChatMessage, background_tasks: BackgroundTasks):
    """사용자로부터 메시지 수신"""
    # 메시지 ID 생성
    message_id = f"msg_{uuid.uuid4().hex[:8]}"
    
    # 타임스탬프 추가
    if not chat.timestamp:
        chat.timestamp = datetime.now().isoformat()
    
    # 메시지 저장
    message_store[message_id] = {
        "client_id": chat.client_id,
        "message": chat.message,
        "timestamp": chat.timestamp,
        "status": "received"
    }
    
    logger.info(f"새 메시지 수신: message_id={message_id}, client_id={chat.client_id}")
    
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
        logger.info(f"슈퍼바이저로부터 응답 수신: client_id={client_id}")
        
        try:
            # 웹소켓으로 메시지 전송
            sent = await manager.send_message(json.dumps(response), client_id)
            
            if sent:
                return {"status": "delivered"}
            else:
                # 웹소켓 연결이 없는 경우 응답 저장
                response_id = f"resp_{uuid.uuid4().hex[:8]}"
                message_store[response_id] = {
                    "client_id": client_id,
                    "response": message,
                    "timestamp": datetime.now().isoformat()
                }
                logger.info(f"웹소켓 연결 없음, 응답 저장: response_id={response_id}")
                return {"status": "stored", "response_id": response_id}
        except Exception as e:
            logger.error(f"응답 처리 중 오류 발생: client_id={client_id}, error={str(e)}")
            return {"status": "error", "message": str(e)}
    else:
        logger.error("잘못된 응답 형식: client_id 또는 message 누락")
        raise HTTPException(status_code=400, detail="Invalid response format")

@app.get("/messages/{message_id}")
async def get_message(message_id: str):
    """특정 메시지 조회"""
    if message_id in message_store:
        return message_store[message_id]
    raise HTTPException(status_code=404, detail=f"메시지 ID {message_id}를 찾을 수 없습니다")

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
            
            logger.info(f"웹소켓을 통해 메시지 수신: client_id={client_id}")
            
            # 메시지를 Supervisor로 전달
            message_id = f"msg_{uuid.uuid4().hex[:8]}"
            await websocket.send_text(json.dumps({"status": "accepted", "message_id": message_id}))
            asyncio.create_task(forward_message_to_supervisor(message_id, ChatMessage(**message)))
            
    except WebSocketDisconnect:
        logger.info(f"웹소켓 연결 종료: client_id={client_id}")
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"웹소켓 처리 중 오류 발생: client_id={client_id}, error={str(e)}")
        manager.disconnect(client_id)

# 백그라운드 작업
async def forward_message_to_supervisor(message_id: str, chat: ChatMessage):
    """메시지를 Supervisor로 전달"""
    # 메시지 데이터 준비
    payload = {
        "message_id": message_id,
        **chat.dict(exclude_none=True)
    }
    
    # 메시지 상태 업데이트
    if message_id in message_store:
        message_store[message_id]["status"] = "processing"
    
    # 재시도 로직
    for retry in range(MAX_RETRIES):
        try:
            # Supervisor로 메시지 전달
            async with httpx.AsyncClient(timeout=RESPONSE_TIMEOUT) as client:
                logger.info(f"메시지를 슈퍼바이저로 전달 시도 ({retry+1}/{MAX_RETRIES}): message_id={message_id}")
                response = await client.post(SUPERVISOR_URL, json=payload)
                
                # 응답 확인
                if response.status_code == 200:
                    logger.info(f"메시지 전달 성공: message_id={message_id}")
                    # 메시지 상태 업데이트
                    if message_id in message_store:
                        message_store[message_id]["status"] = "forwarded"
                    return
                else:
                    logger.warning(f"슈퍼바이저 메시지 전달 실패: message_id={message_id}, status_code={response.status_code}")
                    # 마지막 시도가 아니면 재시도
                    if retry < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
                    else:
                        # 메시지 상태 업데이트
                        if message_id in message_store:
                            message_store[message_id]["status"] = "failed"
                            message_store[message_id]["error"] = f"Supervisor 메시지 전달 실패: {response.status_code}"
        except asyncio.TimeoutError:
            logger.error(f"메시지 전달 시간 초과: message_id={message_id}")
            if retry < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
            else:
                # 메시지 상태 업데이트
                if message_id in message_store:
                    message_store[message_id]["status"] = "failed"
                    message_store[message_id]["error"] = "메시지 전달 시간 초과"
        except Exception as e:
            logger.error(f"메시지 전달 중 오류 발생: message_id={message_id}, error={str(e)}")
            # 마지막 시도가 아니면 재시도
            if retry < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
            else:
                # 메시지 상태 업데이트
                if message_id in message_store:
                    message_store[message_id]["status"] = "failed"
                    message_store[message_id]["error"] = f"메시지 전달 중 오류 발생: {str(e)}"

async def register_service():
    """서비스 레지스트리에 등록"""
    service_data = {
        "name": "chat-gateway",
        "url": "http://chat-gateway:8002",
        "health_check_url": "http://chat-gateway:8002/health",
        "metadata": {
            "description": "채팅 게이트웨이 서비스",
            "version": "1.0.0"
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(SERVICE_REGISTRY_URL, json=service_data)
            if response.status_code == 200:
                logger.info("서비스 레지스트리 등록 성공")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 등록 중 오류 발생: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 이벤트"""
    # 서비스 레지스트리 등록
    try:
        await register_service()
    except Exception as e:
        logger.error(f"시작 이벤트 중 오류 발생: {str(e)}")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8002, reload=True) 