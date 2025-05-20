#!/usr/bin/env python3
"""
Chat Gateway - 상태 메시지 핸들러 구현

이 모듈은 실행 중인 작업의 상태를 조회하고 스트리밍하는 핸들러를 구현합니다.
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("status_handler")

# 상태 저장소 (실제로는 Redis 등을 사용해야 함)
status_store: Dict[str, Dict[str, Any]] = {}

# SSE 연결 저장소 (실제로는 Redis PubSub 등을 사용해야 함)
status_connections: Dict[str, List[asyncio.Queue]] = {}


# ----- 데이터 모델 -----

class RunStatusResponse(BaseModel):
    """실행 상태 응답 모델"""
    run_id: str
    agent_id: str
    status: str = Field(regex="^(pending|running|completed|failed|cancelled)$")
    progress: Optional[float] = Field(None, ge=0, le=100)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    details: Dict[str, Any] = Field(default_factory=dict)


# ----- 라우터 생성 -----

router = APIRouter(
    prefix="/agent",
    tags=["status"]
)


# ----- API 엔드포인트 -----

@router.get("/{agent_id}/status", response_model=RunStatusResponse)
async def get_run_status(
    agent_id: str,
    run_id: str
):
    """
    작업 상태 조회 엔드포인트
    
    특정 Agent에서 실행 중인 작업의 상태를 조회합니다.
    """
    logger.info(f"상태 조회 요청 수신: Agent={agent_id}, Run={run_id}")
    
    try:
        # Agent 엔드포인트 조회
        endpoint = await get_agent_endpoint(agent_id)
        
        # 상태 조회 요청 전송
        result = await get_status_from_agent(endpoint, run_id)
        
        # 상태 저장
        status_key = f"{agent_id}:{run_id}"
        status_store[status_key] = {
            **result,
            "last_updated": datetime.now()
        }
        
        return RunStatusResponse(
            run_id=run_id,
            agent_id=agent_id,
            status=result["status"],
            progress=result.get("progress"),
            start_time=result.get("start_time"),
            end_time=result.get("end_time"),
            details=result.get("details", {})
        )
    
    except AgentNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "AGENT_NOT_FOUND",
                "message": str(e)
            }
        )
    
    except RunNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "RUN_NOT_FOUND",
                "message": str(e)
            }
        )
    
    except Exception as e:
        logger.error(f"상태 조회 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "STATUS_ERROR",
                "message": f"상태 조회 중 오류가 발생했습니다: {str(e)}"
            }
        )


@router.get("/{agent_id}/status/stream")
async def stream_run_status(
    agent_id: str,
    run_id: str
):
    """
    작업 상태 스트림 엔드포인트
    
    SSE(Server-Sent Events)를 통해 특정 Agent의 작업 상태를 실시간으로 스트리밍합니다.
    """
    logger.info(f"상태 스트림 요청 수신: Agent={agent_id}, Run={run_id}")
    
    try:
        # Agent 엔드포인트 조회
        endpoint = await get_agent_endpoint(agent_id)
        
        # 상태 키 생성
        status_key = f"{agent_id}:{run_id}"
        
        # 이 클라이언트를 위한 큐 생성
        queue = asyncio.Queue()
        
        # 연결 저장소에 큐 추가
        if status_key not in status_connections:
            status_connections[status_key] = []
        status_connections[status_key].append(queue)
        
        # 백그라운드에서 상태 폴링 시작
        asyncio.create_task(poll_status(endpoint, agent_id, run_id, status_key))
        
        try:
            # SSE 스트림 생성
            return StreamingResponse(
                status_stream_generator(queue, agent_id, run_id),
                media_type="text/event-stream"
            )
        finally:
            # 연결 종료 시 큐 제거
            if status_key in status_connections and queue in status_connections[status_key]:
                status_connections[status_key].remove(queue)
                if not status_connections[status_key]:
                    del status_connections[status_key]
    
    except AgentNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "AGENT_NOT_FOUND",
                "message": str(e)
            }
        )
    
    except Exception as e:
        logger.error(f"상태 스트림 설정 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "STREAM_ERROR",
                "message": f"상태 스트림 설정 중 오류가 발생했습니다: {str(e)}"
            }
        )


# ----- 유틸리티 함수 및 예외 클래스 -----

class AgentNotFoundException(Exception):
    """Agent를 찾을 수 없을 때 발생하는 예외"""
    pass


class RunNotFoundException(Exception):
    """실행을 찾을 수 없을 때 발생하는 예외"""
    pass


async def get_agent_endpoint(agent_id: str) -> str:
    """
    Agent ID에 해당하는 엔드포인트 조회
    
    실제로는 Redis 캐시나 서비스 디스커버리를 통해 조회해야 함
    """
    # 임시 매핑 (실제로는 동적으로 조회)
    agent_routes = {
        "supervisor_agent": "http://supervisor:8080",
        "mechanic_agent": "http://mechanic-agent:8080",
        "doctor_agent": "http://doctor-agent:8080",
        "general_agent": "http://general-agent:8080"
    }
    
    endpoint = agent_routes.get(agent_id)
    if not endpoint:
        raise AgentNotFoundException(f"Agent ID '{agent_id}'를 찾을 수 없습니다.")
    
    return endpoint


async def get_status_from_agent(endpoint: str, run_id: str) -> Dict[str, Any]:
    """
    Agent에서 상태 조회
    
    Args:
        endpoint: Agent 엔드포인트 URL
        run_id: 조회할 실행 ID
        
    Returns:
        Dict[str, Any]: 상태 데이터
        
    Raises:
        RunNotFoundException: 실행을 찾을 수 없음
        Exception: 기타 오류
    """
    try:
        async with httpx.AsyncClient() as client:
            # 상태 조회 요청 전송
            response = await client.get(
                f"{endpoint}/status/{run_id}",
                timeout=10.0
            )
            
            # 응답 처리
            if response.status_code == 404:
                raise RunNotFoundException(f"실행 ID '{run_id}'를 찾을 수 없습니다.")
            
            response.raise_for_status()
            return response.json()
    
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 오류 발생: {e.response.status_code} {e.response.text}")
        if e.response.status_code == 404:
            raise RunNotFoundException(f"실행 ID '{run_id}'를 찾을 수 없습니다.")
        raise Exception(f"상태 조회 중 HTTP 오류 발생: {e}")
    
    except httpx.RequestError as e:
        logger.error(f"요청 오류 발생: {str(e)}")
        raise Exception(f"상태 조회 중 네트워크 오류 발생: {e}")


async def poll_status(endpoint: str, agent_id: str, run_id: str, status_key: str):
    """
    Agent 상태 주기적 폴링
    
    Args:
        endpoint: Agent 엔드포인트 URL
        agent_id: Agent ID
        run_id: 실행 ID
        status_key: 상태 저장소 키
    """
    try:
        # 종료 상태 목록
        terminal_states = ["completed", "failed", "cancelled"]
        
        # 폴링 간격 (초)
        poll_interval = 1.0
        
        # 이전 상태
        previous_status = None
        
        while True:
            try:
                # 상태 조회
                status_data = await get_status_from_agent(endpoint, run_id)
                
                # 상태 저장
                status_store[status_key] = {
                    **status_data,
                    "last_updated": datetime.now()
                }
                
                # 상태가 변경되었거나 진행률이 변경된 경우에만 브로드캐스트
                current_status = status_data.get("status")
                if (previous_status != current_status or
                    "progress" in status_data or
                    current_status in terminal_states):
                    
                    # 상태 이벤트 브로드캐스트
                    await broadcast_status(status_key, {
                        "run_id": run_id,
                        "agent_id": agent_id,
                        **status_data
                    })
                    
                    previous_status = current_status
                
                # 종료 상태인 경우 폴링 종료
                if current_status in terminal_states:
                    logger.info(f"작업이 종료 상태에 도달했습니다: {current_status}")
                    break
                
                # 다음 폴링까지 대기
                await asyncio.sleep(poll_interval)
            
            except RunNotFoundException as e:
                logger.error(f"실행을 찾을 수 없음: {str(e)}")
                
                # 오류 이벤트 브로드캐스트
                await broadcast_status(status_key, {
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "status": "failed",
                    "error": str(e)
                })
                
                break
            
            except Exception as e:
                logger.error(f"상태 폴링 중 오류 발생: {str(e)}", exc_info=True)
                
                # 폴링은 계속하되 오류 로그만 기록
                await asyncio.sleep(poll_interval)
    
    except asyncio.CancelledError:
        logger.info(f"상태 폴링 작업 취소됨: {status_key}")
    
    except Exception as e:
        logger.error(f"상태 폴링 작업 중 예기치 않은 오류 발생: {str(e)}", exc_info=True)


async def broadcast_status(status_key: str, status_data: Dict[str, Any]):
    """
    모든 연결된 클라이언트에 상태 브로드캐스트
    """
    if status_key not in status_connections:
        return
    
    # 상태 데이터 직렬화
    event_data = json.dumps(status_data)
    
    # 모든 연결된 클라이언트에 전송
    for queue in status_connections[status_key]:
        await queue.put(event_data)


async def status_stream_generator(queue: asyncio.Queue, agent_id: str, run_id: str):
    """
    SSE 상태 스트림 생성기
    """
    try:
        # 연결 시작 메시지
        yield "event: connected\n"
        yield f"data: {json.dumps({'agent_id': agent_id, 'run_id': run_id})}\n\n"
        
        # 큐에서 메시지 수신 및 전송
        while True:
            try:
                # 큐에서 메시지 대기 (타임아웃 30초)
                data = await asyncio.wait_for(queue.get(), timeout=30)
                
                # SSE 형식으로 전송
                status_data = json.loads(data)
                status = status_data.get("status", "unknown")
                
                yield f"event: status\n"
                yield f"data: {data}\n\n"
                
                # 종료 상태인 경우 스트림 종료
                if status in ["completed", "failed", "cancelled"]:
                    yield f"event: end\n"
                    yield f"data: {json.dumps({'final_status': status})}\n\n"
                    break
                
            except asyncio.TimeoutError:
                # 30초 동안 메시지가 없으면 핑 전송
                yield "event: ping\n"
                yield "data: {}\n\n"
    
    except asyncio.CancelledError:
        # 클라이언트 연결 종료
        logger.info(f"클라이언트 연결 종료: {agent_id}:{run_id}")
    
    except Exception as e:
        # 오류 발생
        logger.error(f"스트림 생성 중 오류 발생: {str(e)}", exc_info=True)
        yield f"event: error\n"
        yield f"data: {json.dumps({'message': str(e)})}\n\n"


# ----- 시뮬레이션 함수 (테스트용) -----

async def simulate_status_update(agent_id: str, run_id: str) -> Dict[str, Any]:
    """
    상태 업데이트 시뮬레이션 (테스트용)
    
    실제로는 Agent에서 상태를 조회해야 함
    """
    # 시뮬레이션 상태 데이터
    status_data = {
        "run_id": run_id,
        "agent_id": agent_id,
        "status": "running",
        "progress": 0.0,
        "start_time": datetime.now().isoformat(),
        "details": {
            "current_step": "초기화 중",
            "steps_completed": 0,
            "total_steps": 5
        }
    }
    
    # 상태 키
    status_key = f"{agent_id}:{run_id}"
    
    # 상태 저장
    status_store[status_key] = {
        **status_data,
        "last_updated": datetime.now()
    }
    
    # 상태 브로드캐스트
    await broadcast_status(status_key, status_data)
    
    # 진행 상태 시뮬레이션
    for step in range(1, 6):
        await asyncio.sleep(2)  # 2초 간격으로 업데이트
        
        progress = step * 20.0  # 0%, 20%, 40%, 60%, 80%, 100%
        step_name = f"단계 {step} 실행 중"
        
        # 상태 업데이트
        status_data.update({
            "progress": progress,
            "details": {
                "current_step": step_name,
                "steps_completed": step,
                "total_steps": 5
            }
        })
        
        # 마지막 단계인 경우 완료 상태로 변경
        if step == 5:
            status_data["status"] = "completed"
            status_data["end_time"] = datetime.now().isoformat()
        
        # 상태 저장
        status_store[status_key] = {
            **status_data,
            "last_updated": datetime.now()
        }
        
        # 상태 브로드캐스트
        await broadcast_status(status_key, status_data)
    
    return status_data 