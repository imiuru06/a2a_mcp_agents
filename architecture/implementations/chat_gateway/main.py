#!/usr/bin/env python3
"""
Chat Gateway - 메인 애플리케이션

이 모듈은 Chat Gateway의 메인 애플리케이션을 정의하고 모든 핸들러를 통합합니다.
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 내부 모듈 임포트
from chat_handler import app as chat_app
from interrupt_handler import router as interrupt_router
from status_handler import router as status_router
from routing_cache import RoutingCache, initialize_cache
import auth

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("chat_gateway")

# 환경 변수
REDIS_URL = os.environ.get("REDIS_URL")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

# 애플리케이션 생성
app = FastAPI(
    title="Chat Gateway API",
    description="사용자의 채팅 메시지, 인터럽트 요청, 상태 조회 요청을 적절한 Agent로 라우팅하는 API",
    version="1.0.0",
    debug=DEBUG
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 운영에서는 특정 도메인으로 제한하는 것이 좋음
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- 데이터 모델 -----

class SessionRequest(BaseModel):
    """세션 요청 모델"""
    username: str
    password: str
    client_info: Dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """세션 응답 모델"""
    session_id: str
    token: str
    expires_at: str
    user: Dict[str, Any]


# ----- 라우터 통합 -----

# 채팅 핸들러의 라우터 통합
app.include_router(chat_app.router)

# 인터럽트 핸들러의 라우터 통합
app.include_router(interrupt_router)

# 상태 핸들러의 라우터 통합
app.include_router(status_router)


# ----- 세션 관리 API -----

@app.post("/session", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session(request: SessionRequest):
    """
    새 세션 생성 엔드포인트
    
    사용자 인증 후 새 세션을 생성합니다.
    """
    # 사용자 인증
    user = auth.authenticate_user(request.username, request.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "AUTHENTICATION_FAILED",
                "message": "사용자 이름 또는 비밀번호가 올바르지 않습니다."
            }
        )
    
    # JWT 토큰 생성
    token = auth.create_jwt_token(
        username=user["username"],
        user_id=user["user_id"],
        roles=user["roles"]
    )
    
    # 토큰 디코딩하여 만료 시간 확인
    payload = auth.decode_jwt_token(token)
    expires_at = datetime.fromtimestamp(payload["exp"]).isoformat()
    
    # 세션 생성
    session_id = auth.create_session(user["user_id"], token, user)
    
    # 클라이언트 정보 저장
    if request.client_info:
        auth.session_store[session_id]["client_info"] = request.client_info
    
    return SessionResponse(
        session_id=session_id,
        token=token,
        expires_at=expires_at,
        user=user
    )


@app.delete("/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(session_id: str):
    """
    세션 종료 엔드포인트
    
    특정 세션을 종료합니다.
    """
    # 세션 존재 여부 확인
    if not auth.get_session(session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "SESSION_NOT_FOUND",
                "message": f"세션 ID '{session_id}'를 찾을 수 없습니다."
            }
        )
    
    # 세션 삭제
    auth.delete_session(session_id)
    
    # 204 No Content 응답
    return None


# ----- 상태 확인 API -----

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
        "timestamp": datetime.now().isoformat(),
        "dependencies": {
            "redis": "ok" if REDIS_URL else "not_configured",
            "agent_directory": "ok"  # 실제로는 서비스 디스커버리 상태 확인
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
        content={
            "error_code": "HTTP_ERROR",
            "message": str(exc.detail),
            "request_id": request.headers.get("X-Request-ID", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """일반 예외 핸들러"""
    logger.error(f"예외 발생: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "서버 내부 오류가 발생했습니다.",
            "request_id": request.headers.get("X-Request-ID", "unknown"),
            "details": {"error": str(exc)},
            "timestamp": datetime.now().isoformat()
        }
    )


# ----- 시작 이벤트 핸들러 -----

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행되는 이벤트 핸들러"""
    # 라우팅 캐시 초기화
    app.state.routing_cache = RoutingCache(redis_url=REDIS_URL)
    await initialize_cache(app.state.routing_cache)
    
    logger.info("Chat Gateway 애플리케이션이 시작되었습니다.")


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행되는 이벤트 핸들러"""
    # 리소스 정리
    logger.info("Chat Gateway 애플리케이션이 종료되었습니다.")


# ----- 메인 함수 -----

if __name__ == "__main__":
    import uvicorn
    
    # 포트 설정
    port = int(os.environ.get("PORT", "8001"))
    
    # 서버 실행
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=DEBUG,
        log_level="info"
    ) 