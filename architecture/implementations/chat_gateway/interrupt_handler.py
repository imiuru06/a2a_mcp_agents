#!/usr/bin/env python3
"""
Chat Gateway - 인터럽트 메시지 핸들러 구현

이 모듈은 실행 중인 작업을 중단하기 위한 인터럽트 요청을 처리하는 핸들러를 구현합니다.
"""

import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("interrupt_handler")

# 인터럽트 상태 저장소 (실제로는 Redis 등을 사용해야 함)
interrupt_store: Dict[str, Dict[str, Any]] = {}


# ----- 데이터 모델 -----

class InterruptResponse(BaseModel):
    """인터럽트 응답 모델"""
    status: str = Field(regex="^(accepted|rejected)$")
    message: Optional[str] = None
    agent_id: str
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.now)


# ----- 라우터 생성 -----

router = APIRouter(
    prefix="/agent",
    tags=["interrupt"]
)


# ----- API 엔드포인트 -----

@router.post("/{agent_id}/interrupt", response_model=InterruptResponse)
async def interrupt_run(
    agent_id: str,
    run_id: str
):
    """
    작업 인터럽트 요청 엔드포인트
    
    특정 Agent에서 실행 중인 작업을 중단하도록 요청합니다.
    """
    logger.info(f"인터럽트 요청 수신: Agent={agent_id}, Run={run_id}")
    
    try:
        # Agent 엔드포인트 조회
        endpoint = await get_agent_endpoint(agent_id)
        
        # 인터럽트 요청 전송
        result = await send_interrupt_request(endpoint, run_id)
        
        # 인터럽트 상태 저장
        interrupt_id = f"{agent_id}:{run_id}"
        interrupt_store[interrupt_id] = {
            "agent_id": agent_id,
            "run_id": run_id,
            "status": "accepted",
            "timestamp": datetime.now()
        }
        
        return InterruptResponse(
            status="accepted",
            message="인터럽트 요청이 성공적으로 전달되었습니다.",
            agent_id=agent_id,
            run_id=run_id
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
    
    except InterruptRejectedException as e:
        return InterruptResponse(
            status="rejected",
            message=str(e),
            agent_id=agent_id,
            run_id=run_id
        )
    
    except Exception as e:
        logger.error(f"인터럽트 요청 처리 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "INTERRUPT_ERROR",
                "message": f"인터럽트 요청 처리 중 오류가 발생했습니다: {str(e)}"
            }
        )


# ----- 유틸리티 함수 및 예외 클래스 -----

class AgentNotFoundException(Exception):
    """Agent를 찾을 수 없을 때 발생하는 예외"""
    pass


class RunNotFoundException(Exception):
    """실행을 찾을 수 없을 때 발생하는 예외"""
    pass


class InterruptRejectedException(Exception):
    """인터럽트 요청이 거부되었을 때 발생하는 예외"""
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


async def send_interrupt_request(endpoint: str, run_id: str) -> Dict[str, Any]:
    """
    Agent에 인터럽트 요청 전송
    
    Args:
        endpoint: Agent 엔드포인트 URL
        run_id: 중단할 실행 ID
        
    Returns:
        Dict[str, Any]: 응답 데이터
        
    Raises:
        RunNotFoundException: 실행을 찾을 수 없음
        InterruptRejectedException: 인터럽트 요청 거부
        Exception: 기타 오류
    """
    try:
        async with httpx.AsyncClient() as client:
            # 인터럽트 요청 전송
            response = await client.post(
                f"{endpoint}/interrupt",
                json={"run_id": run_id},
                timeout=10.0
            )
            
            # 응답 처리
            if response.status_code == 404:
                raise RunNotFoundException(f"실행 ID '{run_id}'를 찾을 수 없습니다.")
            
            elif response.status_code == 409:
                raise InterruptRejectedException("이미 완료되었거나 취소된 실행입니다.")
            
            response.raise_for_status()
            return response.json()
    
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 오류 발생: {e.response.status_code} {e.response.text}")
        if e.response.status_code == 404:
            raise RunNotFoundException(f"실행 ID '{run_id}'를 찾을 수 없습니다.")
        raise Exception(f"인터럽트 요청 중 HTTP 오류 발생: {e}")
    
    except httpx.RequestError as e:
        logger.error(f"요청 오류 발생: {str(e)}")
        raise Exception(f"인터럽트 요청 중 네트워크 오류 발생: {e}")


# ----- 시뮬레이션 함수 (테스트용) -----

async def simulate_interrupt_request(agent_id: str, run_id: str) -> Dict[str, Any]:
    """
    인터럽트 요청 시뮬레이션 (테스트용)
    
    실제로는 HTTP 클라이언트를 사용하여 Agent에 요청을 보내야 함
    """
    # 시뮬레이션 지연
    await asyncio.sleep(0.5)
    
    # 특정 조건에서 예외 발생 (테스트용)
    if agent_id == "unknown_agent":
        raise AgentNotFoundException(f"Agent ID '{agent_id}'를 찾을 수 없습니다.")
    
    if run_id == "unknown_run":
        raise RunNotFoundException(f"실행 ID '{run_id}'를 찾을 수 없습니다.")
    
    if run_id == "completed_run":
        raise InterruptRejectedException("이미 완료된 실행입니다.")
    
    # 성공 응답
    return {
        "status": "accepted",
        "agent_id": agent_id,
        "run_id": run_id,
        "timestamp": datetime.now().isoformat()
    } 