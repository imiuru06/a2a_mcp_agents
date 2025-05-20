#!/usr/bin/env python3
"""
Chat Gateway - 채팅 메시지 핸들러 구현

이 모듈은 사용자의 채팅 메시지를 수신하고 적절한 Agent로 라우팅하는 핸들러를 구현합니다.
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, HTTPException, Request, Response, Depends, BackgroundTasks, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("chat_gateway")

# 대화 저장소 (실제로는 Redis 등을 사용해야 함)
conversation_store: Dict[str, Dict[str, Any]] = {}

# SSE 연결 저장소 (실제로는 Redis PubSub 등을 사용해야 함)
sse_connections: Dict[str, List[asyncio.Queue]] = {}


# ----- 데이터 모델 -----

class ChatMetadata(BaseModel):
    """채팅 메타데이터 모델"""
    class Config:
        extra = "allow"  # 추가 필드 허용


class ChatMessage(BaseModel):
    """채팅 메시지 모델"""
    message: str
    message_type: str = Field(default="text", regex="^(text|command)$")
    conversation_id: Optional[str] = None
    metadata: Optional[ChatMetadata] = None


class ChatResponse(BaseModel):
    """채팅 응답 모델"""
    conversation_id: str
    status: str = Field(regex="^(received|processing)$")
    message: Optional[str] = None
    stream_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


# ----- FastAPI 앱 생성 -----

app = FastAPI(
    title="Chat Gateway API",
    description="사용자의 채팅 메시지를 적절한 Agent로 라우팅하는 API",
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

def get_agent_id(agent_id: str = Header(..., description="메시지를 전달할 Agent ID")) -> str:
    """Agent ID 헤더 검증"""
    if not agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "MISSING_AGENT_ID",
                "message": "Agent ID 헤더가 필요합니다."
            }
        )
    return agent_id


async def get_agent_endpoint(agent_id: str) -> str:
    """
    Agent ID에 해당하는 엔드포인트 조회
    
    실제로는 Redis 캐시나 서비스 디스커버리를 통해 조회해야 함
    """
    # 임시 매핑 (실제로는 동적으로 조회)
    agent_routes = {
        "supervisor_agent": "http://supervisor:8080/chat",
        "mechanic_agent": "http://mechanic-agent:8080/chat",
        "doctor_agent": "http://doctor-agent:8080/chat",
        "general_agent": "http://general-agent:8080/chat"
    }
    
    endpoint = agent_routes.get(agent_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "AGENT_NOT_FOUND",
                "message": f"Agent ID '{agent_id}'를 찾을 수 없습니다."
            }
        )
    
    return endpoint


# ----- API 엔드포인트 -----

@app.post("/chat", status_code=status.HTTP_202_ACCEPTED, response_model=ChatResponse)
async def send_chat_message(
    message: ChatMessage,
    background_tasks: BackgroundTasks,
    agent_id: str = Depends(get_agent_id)
):
    """
    채팅 메시지 전송 엔드포인트
    
    사용자의 채팅 메시지를 지정된 Agent로 전달합니다.
    """
    logger.info(f"채팅 메시지 수신: Agent={agent_id}")
    
    # 대화 ID 생성 또는 기존 ID 사용
    conversation_id = message.conversation_id or str(uuid.uuid4())
    
    # 대화 정보 저장
    conversation_store[conversation_id] = {
        "agent_id": agent_id,
        "last_message": message.dict(),
        "timestamp": datetime.now(),
        "status": "received"
    }
    
    # 백그라운드에서 메시지 처리
    background_tasks.add_task(process_message, conversation_id, message, agent_id)
    
    # 스트림 URL 생성
    stream_url = f"/chat/stream?conversation_id={conversation_id}"
    
    return ChatResponse(
        conversation_id=conversation_id,
        status="received",
        message="메시지가 성공적으로 전달되었습니다.",
        stream_url=stream_url
    )


@app.get("/chat/stream")
async def stream_chat_response(conversation_id: str):
    """
    채팅 응답 스트림 엔드포인트
    
    SSE(Server-Sent Events)를 통해 Agent의 응답을 실시간으로 스트리밍합니다.
    """
    if conversation_id not in conversation_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "CONVERSATION_NOT_FOUND",
                "message": f"대화 ID '{conversation_id}'를 찾을 수 없습니다."
            }
        )
    
    # 이 클라이언트를 위한 큐 생성
    queue = asyncio.Queue()
    
    # 연결 저장소에 큐 추가
    if conversation_id not in sse_connections:
        sse_connections[conversation_id] = []
    sse_connections[conversation_id].append(queue)
    
    try:
        # SSE 스트림 생성
        return StreamingResponse(
            stream_generator(queue, conversation_id),
            media_type="text/event-stream"
        )
    finally:
        # 연결 종료 시 큐 제거
        if conversation_id in sse_connections and queue in sse_connections[conversation_id]:
            sse_connections[conversation_id].remove(queue)
            if not sse_connections[conversation_id]:
                del sse_connections[conversation_id]


@app.get("/health")
async def health_check():
    """
    서비스 상태 확인 엔드포인트
    
    Chat Gateway 서비스의 상태를 확인합니다.
    """
    # 실제로는 의존성 서비스 상태도 확인해야 함
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime": 3600,  # 실제로는 서비스 시작 시간에서 계산
        "timestamp": datetime.now(),
        "dependencies": {
            "redis": "ok",
            "agent_directory": "ok"
        }
    }


# ----- 메시지 처리 함수 -----

async def process_message(conversation_id: str, message: ChatMessage, agent_id: str):
    """
    메시지 처리 함수
    
    메시지를 지정된 Agent로 전달하고 응답을 SSE로 스트리밍합니다.
    """
    if conversation_id not in conversation_store:
        logger.error(f"대화를 찾을 수 없음: {conversation_id}")
        return
    
    conversation = conversation_store[conversation_id]
    conversation["status"] = "processing"
    
    try:
        # Agent 엔드포인트 조회
        endpoint = await get_agent_endpoint(agent_id)
        
        logger.info(f"메시지 전달 중: {endpoint}")
        
        # 실제로는 HTTP 클라이언트로 Agent에 전달하고 응답을 스트리밍
        # 여기서는 시뮬레이션만 수행
        await simulate_agent_response(conversation_id, agent_id)
        
        # 처리 완료
        conversation["status"] = "completed"
        logger.info(f"메시지 처리 완료: {conversation_id}")
        
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: {str(e)}", exc_info=True)
        conversation["status"] = "failed"
        conversation["error"] = str(e)
        
        # 오류 메시지를 SSE로 전송
        if conversation_id in sse_connections:
            error_event = {
                "event": "error",
                "data": {
                    "message": f"메시지 처리 중 오류가 발생했습니다: {str(e)}"
                }
            }
            await broadcast_event(conversation_id, error_event)


async def simulate_agent_response(conversation_id: str, agent_id: str):
    """
    Agent 응답 시뮬레이션
    
    실제로는 HTTP 클라이언트를 사용하여 Agent에 요청을 보내고 응답을 스트리밍해야 함
    """
    # 시뮬레이션 응답 데이터
    responses = {
        "supervisor_agent": [
            "안녕하세요! 무엇을 도와드릴까요?",
            "현재 여러 전문 에이전트와 연결할 수 있습니다.",
            "자동차 관련 문제는 정비사 에이전트, 건강 관련 문제는 의사 에이전트를 추천합니다."
        ],
        "mechanic_agent": [
            "안녕하세요, 정비사 에이전트입니다.",
            "차량에 어떤 문제가 있으신가요?",
            "소음, 진동, 엔진 문제 등을 자세히 알려주시면 도움드리겠습니다."
        ],
        "doctor_agent": [
            "안녕하세요, 의사 에이전트입니다.",
            "어떤 증상이 있으신가요?",
            "증상을 자세히 설명해 주시면 도움을 드릴 수 있습니다."
        ],
        "general_agent": [
            "안녕하세요, 일반 에이전트입니다.",
            "어떤 질문이 있으신가요?",
            "다양한 주제에 대해 도움을 드릴 수 있습니다."
        ]
    }
    
    # 에이전트별 응답 선택
    agent_responses = responses.get(agent_id, responses["general_agent"])
    
    # 시작 이벤트 전송
    start_event = {
        "event": "start",
        "data": {
            "agent_id": agent_id,
            "conversation_id": conversation_id
        }
    }
    await broadcast_event(conversation_id, start_event)
    
    # 응답 스트리밍 시뮬레이션
    for i, text in enumerate(agent_responses):
        # 지연 시뮬레이션
        await asyncio.sleep(1)
        
        # 텍스트 이벤트 전송
        text_event = {
            "event": "text",
            "data": {
                "text": text,
                "sequence": i + 1
            }
        }
        await broadcast_event(conversation_id, text_event)
    
    # 종료 이벤트 전송
    end_event = {
        "event": "end",
        "data": {
            "conversation_id": conversation_id,
            "timestamp": datetime.now().isoformat()
        }
    }
    await broadcast_event(conversation_id, end_event)


async def broadcast_event(conversation_id: str, event: Dict[str, Any]):
    """
    모든 연결된 클라이언트에 이벤트 브로드캐스트
    """
    if conversation_id not in sse_connections:
        return
    
    # 이벤트를 JSON으로 직렬화
    event_data = json.dumps(event)
    
    # 모든 연결된 클라이언트에 전송
    for queue in sse_connections[conversation_id]:
        await queue.put(event_data)


async def stream_generator(queue: asyncio.Queue, conversation_id: str):
    """
    SSE 스트림 생성기
    """
    try:
        # 연결 시작 메시지
        yield "event: connected\n"
        yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"
        
        # 큐에서 메시지 수신 및 전송
        while True:
            try:
                # 큐에서 메시지 대기 (타임아웃 30초)
                data = await asyncio.wait_for(queue.get(), timeout=30)
                
                # SSE 형식으로 전송
                event_data = json.loads(data)
                event_type = event_data.get("event", "message")
                
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(event_data.get('data', {}))}\n\n"
                
                # 종료 이벤트인 경우 스트림 종료
                if event_type == "end":
                    break
                
            except asyncio.TimeoutError:
                # 30초 동안 메시지가 없으면 핑 전송
                yield "event: ping\n"
                yield "data: {}\n\n"
    
    except asyncio.CancelledError:
        # 클라이언트 연결 종료
        logger.info(f"클라이언트 연결 종료: {conversation_id}")
    
    except Exception as e:
        # 오류 발생
        logger.error(f"스트림 생성 중 오류 발생: {str(e)}", exc_info=True)
        yield f"event: error\n"
        yield f"data: {json.dumps({'message': str(e)})}\n\n"


# ----- 메인 함수 -----

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("chat_handler:app", host="0.0.0.0", port=8001, reload=True) 