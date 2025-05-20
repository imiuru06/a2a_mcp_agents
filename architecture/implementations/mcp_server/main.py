#!/usr/bin/env python3
"""
MCP Server - 메인 애플리케이션

이 모듈은 FastAPI를 사용하여 MCP 프로토콜 API를 제공하고,
도구 실행, 컨텍스트 저장소, 취소 토큰, 이벤트 스트리밍 모듈을 통합합니다.
"""

import os
import json
import uuid
import asyncio
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

# 내부 모듈 임포트
from .tool_executor import ToolExecutor, ToolExecutionError
from .context_store import ContextStore
from .cancellation_token import get_registry as get_token_registry
from .event_streamer import EventType, SSEResponse, get_streamer


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp_server")


# 환경 변수에서 설정 로드
DOCKER_HOST = os.environ.get("DOCKER_HOST", None)
TOOL_REGISTRY_URL = os.environ.get("TOOL_REGISTRY_URL", None)
CONTAINER_NETWORK = os.environ.get("CONTAINER_NETWORK", "mcp-tools")
EXECUTION_TIMEOUT = int(os.environ.get("EXECUTION_TIMEOUT", "300"))
CONTEXT_BACKEND = os.environ.get("CONTEXT_BACKEND", "memory")
REDIS_URL = os.environ.get("REDIS_URL", None)
MONGO_URL = os.environ.get("MONGO_URL", None)


# API 모델 정의
class ToolParameter(BaseModel):
    """도구 매개변수 정의"""
    name: str
    value: Any


class ExecuteRequest(BaseModel):
    """도구 실행 요청"""
    tool_name: str
    tool_version: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    context_id: Optional[str] = None
    timeout: Optional[int] = None


class ExecuteResponse(BaseModel):
    """도구 실행 응답"""
    run_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    """상태 조회 응답"""
    run_id: str
    tool_name: str
    tool_version: Optional[str]
    status: str
    progress: float = 0.0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class CancelRequest(BaseModel):
    """실행 취소 요청"""
    run_id: str


class CancelResponse(BaseModel):
    """실행 취소 응답"""
    run_id: str
    status: str
    message: str


# 애플리케이션 인스턴스 생성
app = FastAPI(
    title="MCP Server",
    description="Model Context Protocol 서버",
    version="1.0.0"
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 의존성 주입
def get_tool_executor() -> ToolExecutor:
    """도구 실행기 인스턴스 반환"""
    return app.state.tool_executor


def get_context_store() -> ContextStore:
    """컨텍스트 저장소 인스턴스 반환"""
    return app.state.context_store


# 애플리케이션 시작 이벤트
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 호출"""
    # 도구 실행기 초기화
    app.state.tool_executor = ToolExecutor(
        docker_client=None,  # 자동 생성
        tool_registry_url=TOOL_REGISTRY_URL,
        container_network=CONTAINER_NETWORK,
        execution_timeout=EXECUTION_TIMEOUT
    )
    
    # 컨텍스트 저장소 초기화
    app.state.context_store = ContextStore(
        backend=CONTEXT_BACKEND,
        redis_url=REDIS_URL,
        mongo_url=MONGO_URL
    )
    
    logger.info("MCP Server 시작됨")


# 애플리케이션 종료 이벤트
@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 호출"""
    logger.info("MCP Server 종료 중...")


# API 엔드포인트 정의
@app.post("/v1/execute", response_model=ExecuteResponse)
async def execute_tool(
    request: ExecuteRequest,
    background_tasks: BackgroundTasks,
    tool_executor: ToolExecutor = Depends(get_tool_executor),
    context_store: ContextStore = Depends(get_context_store)
):
    """
    도구 실행 API
    
    Args:
        request: 실행 요청
        background_tasks: 백그라운드 태스크
        tool_executor: 도구 실행기
        context_store: 컨텍스트 저장소
    """
    try:
        # 실행 ID 생성
        run_id = str(uuid.uuid4())
        
        # 취소 토큰 생성
        token = await get_token_registry().create_token(run_id)
        
        # 컨텍스트 초기화
        initial_context = {
            "tool_name": request.tool_name,
            "tool_version": request.tool_version,
            "parameters": request.parameters,
            "context_id": request.context_id,
            "status": "queued",
            "progress": 0.0,
            "start_time": None,
            "end_time": None,
            "created_at": datetime.now().isoformat()
        }
        await context_store.save_context(run_id, initial_context)
        
        # 상태 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.STATUS,
            {"status": "queued", "message": "도구 실행 대기 중"}
        )
        
        # 백그라운드에서 실행
        background_tasks.add_task(
            execute_tool_background,
            run_id=run_id,
            request=request,
            tool_executor=tool_executor,
            context_store=context_store
        )
        
        return ExecuteResponse(
            run_id=run_id,
            status="queued",
            message="도구 실행이 큐에 추가되었습니다."
        )
    
    except Exception as e:
        logger.error(f"도구 실행 요청 처리 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"도구 실행 요청 처리 중 오류 발생: {str(e)}"
        )


async def execute_tool_background(
    run_id: str,
    request: ExecuteRequest,
    tool_executor: ToolExecutor,
    context_store: ContextStore
):
    """
    백그라운드에서 도구 실행
    
    Args:
        run_id: 실행 ID
        request: 실행 요청
        tool_executor: 도구 실행기
        context_store: 컨텍스트 저장소
    """
    try:
        # 상태 업데이트 콜백
        async def status_callback(run_id: str, status: Dict[str, Any]):
            # 컨텍스트 업데이트
            await context_store.update_context(run_id, status)
            
            # 이벤트 발행
            if "status" in status:
                await get_streamer().publish_event(
                    run_id,
                    EventType.STATUS,
                    {"status": status["status"], "message": status.get("message", "")}
                )
            
            if "progress" in status:
                await get_streamer().publish_event(
                    run_id,
                    EventType.PROGRESS,
                    {"progress": status["progress"], "message": status.get("message", "")}
                )
            
            if "logs" in status and status["logs"]:
                # 마지막 로그만 발행
                log = status["logs"][-1]
                await get_streamer().publish_event(
                    run_id,
                    EventType.LOG,
                    {"level": "info", "message": log}
                )
            
            if "result" in status and status["result"]:
                await get_streamer().publish_event(
                    run_id,
                    EventType.RESULT,
                    {"result": status["result"]}
                )
            
            if "error" in status and status["error"]:
                await get_streamer().publish_event(
                    run_id,
                    EventType.ERROR,
                    {"error": status["error"]}
                )
        
        # 도구 실행
        result = await tool_executor.execute_tool(
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            parameters=request.parameters,
            run_id=run_id,
            context_id=request.context_id,
            timeout=request.timeout,
            callback=status_callback
        )
        
        # 컨텍스트 업데이트
        await context_store.update_context(run_id, {
            "status": "completed",
            "end_time": datetime.now().isoformat(),
            "result": result
        })
        
        # 완료 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.STATUS,
            {"status": "completed", "message": "도구 실행 완료"}
        )
        
        # 결과 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.RESULT,
            {"result": result}
        )
        
        # 토큰 정리
        await get_token_registry().remove_token(run_id)
    
    except ToolExecutionError as e:
        error_info = {"code": "TOOL_EXECUTION_ERROR", "message": str(e)}
        
        # 컨텍스트 업데이트
        await context_store.update_context(run_id, {
            "status": "failed",
            "end_time": datetime.now().isoformat(),
            "error": error_info
        })
        
        # 오류 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.STATUS,
            {"status": "failed", "message": str(e)}
        )
        
        await get_streamer().publish_event(
            run_id,
            EventType.ERROR,
            {"error": error_info}
        )
        
        # 토큰 정리
        await get_token_registry().remove_token(run_id)
    
    except asyncio.CancelledError:
        # 취소된 경우
        await context_store.update_context(run_id, {
            "status": "cancelled",
            "end_time": datetime.now().isoformat()
        })
        
        # 취소 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.STATUS,
            {"status": "cancelled", "message": "도구 실행이 취소되었습니다."}
        )
        
        # 토큰 정리
        await get_token_registry().remove_token(run_id)
    
    except Exception as e:
        logger.error(f"도구 실행 중 예기치 않은 오류 발생: {str(e)}", exc_info=True)
        error_info = {"code": "UNEXPECTED_ERROR", "message": str(e)}
        
        # 컨텍스트 업데이트
        await context_store.update_context(run_id, {
            "status": "failed",
            "end_time": datetime.now().isoformat(),
            "error": error_info
        })
        
        # 오류 이벤트 발행
        await get_streamer().publish_event(
            run_id,
            EventType.STATUS,
            {"status": "failed", "message": f"예기치 않은 오류: {str(e)}"}
        )
        
        await get_streamer().publish_event(
            run_id,
            EventType.ERROR,
            {"error": error_info}
        )
        
        # 토큰 정리
        await get_token_registry().remove_token(run_id)


@app.get("/v1/status/{run_id}", response_model=StatusResponse)
async def get_status(
    run_id: str,
    context_store: ContextStore = Depends(get_context_store)
):
    """
    실행 상태 조회 API
    
    Args:
        run_id: 실행 ID
        context_store: 컨텍스트 저장소
    """
    try:
        # 컨텍스트 조회
        context = await context_store.get_context(run_id)
        
        if not context:
            raise HTTPException(
                status_code=404,
                detail=f"실행 ID {run_id}를 찾을 수 없습니다."
            )
        
        # 응답 생성
        return StatusResponse(
            run_id=run_id,
            tool_name=context.get("tool_name", ""),
            tool_version=context.get("tool_version"),
            status=context.get("status", "unknown"),
            progress=context.get("progress", 0.0),
            start_time=context.get("start_time"),
            end_time=context.get("end_time"),
            result=context.get("result"),
            error=context.get("error")
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"상태 조회 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"상태 조회 중 오류 발생: {str(e)}"
        )


@app.get("/v1/stream/{run_id}")
async def stream_events(
    run_id: str,
    request: Request,
    history: bool = True
):
    """
    이벤트 스트리밍 API
    
    Args:
        run_id: 실행 ID
        request: HTTP 요청
        history: 이전 이벤트 포함 여부
    """
    try:
        # 컨텍스트 확인
        context = await get_context_store().get_context(run_id)
        
        if not context:
            raise HTTPException(
                status_code=404,
                detail=f"실행 ID {run_id}를 찾을 수 없습니다."
            )
        
        # 이벤트 구독
        events = get_streamer().subscribe(run_id, history)
        
        # SSE 스트림 생성
        stream = SSEResponse.stream_sse(events)
        
        # 스트리밍 응답 반환
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"이벤트 스트리밍 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"이벤트 스트리밍 중 오류 발생: {str(e)}"
        )


@app.post("/v1/cancel", response_model=CancelResponse)
async def cancel_execution(
    request: CancelRequest,
    tool_executor: ToolExecutor = Depends(get_tool_executor),
    context_store: ContextStore = Depends(get_context_store)
):
    """
    실행 취소 API
    
    Args:
        request: 취소 요청
        tool_executor: 도구 실행기
        context_store: 컨텍스트 저장소
    """
    try:
        run_id = request.run_id
        
        # 컨텍스트 확인
        context = await context_store.get_context(run_id)
        
        if not context:
            raise HTTPException(
                status_code=404,
                detail=f"실행 ID {run_id}를 찾을 수 없습니다."
            )
        
        # 이미 종료된 작업인 경우
        status = context.get("status", "")
        if status in ["completed", "failed", "cancelled"]:
            return CancelResponse(
                run_id=run_id,
                status=status,
                message=f"이미 {status} 상태인 작업입니다."
            )
        
        # 취소 요청
        cancelled = await tool_executor.cancel_execution(run_id)
        
        if cancelled:
            # 취소 이벤트 발행
            await get_streamer().publish_event(
                run_id,
                EventType.STATUS,
                {"status": "cancelled", "message": "도구 실행이 취소되었습니다."}
            )
            
            return CancelResponse(
                run_id=run_id,
                status="cancelled",
                message="도구 실행이 취소되었습니다."
            )
        else:
            return CancelResponse(
                run_id=run_id,
                status=context.get("status", "unknown"),
                message="도구 실행을 취소할 수 없습니다."
            )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"실행 취소 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"실행 취소 중 오류 발생: {str(e)}"
        )


# 헬스 체크 엔드포인트
@app.get("/health")
async def health_check():
    """헬스 체크 API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# 메인 함수
def main():
    """애플리케이션 시작"""
    # 환경 변수에서 포트 로드
    port = int(os.environ.get("PORT", "8000"))
    
    # 서버 실행
    uvicorn.run(
        "architecture.implementations.mcp_server.main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )


if __name__ == "__main__":
    main() 