#!/usr/bin/env python3
"""
Event Gateway - 재시도 로직 미들웨어 구현

이 모듈은 Sub-Agent로의 요청 전송 실패 시 지수 백오프 방식으로 재시도하는 로직을 구현합니다.
"""

import time
import random
import logging
import asyncio
from typing import Dict, Any, Callable, Optional, List, Union
from functools import wraps

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
    before_sleep_log
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("retry_middleware")


class SubAgentClient:
    """Sub-Agent 클라이언트 (재시도 로직 포함)"""
    
    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        min_wait: float = 1.0,
        max_wait: float = 10.0,
        jitter: bool = True,
        headers: Optional[Dict[str, str]] = None
    ):
        """
        Args:
            base_url: Sub-Agent 기본 URL
            timeout: 요청 타임아웃 (초)
            max_retries: 최대 재시도 횟수
            min_wait: 최소 대기 시간 (초)
            max_wait: 최대 대기 시간 (초)
            jitter: 지터 적용 여부 (무작위성 추가)
            headers: 기본 헤더
        """
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_wait = min_wait
        self.max_wait = max_wait
        self.jitter = jitter
        self.headers = headers or {}
        
        # 비동기 HTTP 클라이언트 (필요할 때 생성)
        self._client = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """비동기 HTTP 클라이언트 가져오기 (필요시 생성)"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self.headers
            )
        return self._client
    
    async def close(self):
        """클라이언트 연결 종료"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    @retry(
        stop=stop_after_attempt(3),  # 최대 3회 재시도
        wait=wait_exponential(multiplier=1, min=1, max=10),  # 지수 백오프
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),  # 재시도할 예외 유형
        before_sleep=before_sleep_log(logger, logging.WARNING)  # 재시도 전 로깅
    )
    async def send_event(self, event_data: Dict[str, Any], path: str = "/events") -> Dict[str, Any]:
        """
        이벤트 전송 (재시도 로직 포함)
        
        Args:
            event_data: 이벤트 데이터
            path: 엔드포인트 경로
            
        Returns:
            Dict[str, Any]: 응답 데이터
            
        Raises:
            RetryError: 최대 재시도 횟수 초과
            httpx.HTTPError: HTTP 오류
        """
        client = await self.get_client()
        
        try:
            response = await client.post(path, json=event_data)
            response.raise_for_status()  # 4xx, 5xx 응답 시 예외 발생
            return response.json()
        except httpx.HTTPStatusError as e:
            # 특정 상태 코드에 대한 처리
            if e.response.status_code == 429:  # Too Many Requests
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    logger.warning(f"속도 제한 감지, {retry_after}초 후 재시도")
                    await asyncio.sleep(float(retry_after))
            
            # 5xx 서버 오류는 재시도, 4xx 클라이언트 오류는 재시도하지 않음
            if 500 <= e.response.status_code < 600:
                logger.warning(f"서버 오류 발생 ({e.response.status_code}), 재시도 중...")
                raise  # 재시도를 위해 예외 다시 발생
            else:
                logger.error(f"클라이언트 오류 발생 ({e.response.status_code}), 재시도하지 않음")
                raise RetryError(f"클라이언트 오류: {e}")


class RetryMiddleware:
    """재시도 로직 미들웨어"""
    
    def __init__(
        self,
        sub_agent_routes: Dict[str, str],
        timeout: float = 10.0,
        max_retries: int = 3,
        min_wait: float = 1.0,
        max_wait: float = 10.0
    ):
        """
        Args:
            sub_agent_routes: 이벤트 유형별 Sub-Agent 라우팅 테이블
            timeout: 요청 타임아웃 (초)
            max_retries: 최대 재시도 횟수
            min_wait: 최소 대기 시간 (초)
            max_wait: 최대 대기 시간 (초)
        """
        self.sub_agent_routes = sub_agent_routes
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_wait = min_wait
        self.max_wait = max_wait
        
        # Sub-Agent 클라이언트 캐시
        self.clients: Dict[str, SubAgentClient] = {}
    
    def get_client(self, destination: str) -> SubAgentClient:
        """
        Sub-Agent 클라이언트 가져오기
        
        Args:
            destination: Sub-Agent URL
            
        Returns:
            SubAgentClient: Sub-Agent 클라이언트
        """
        if destination not in self.clients:
            self.clients[destination] = SubAgentClient(
                base_url=destination,
                timeout=self.timeout,
                max_retries=self.max_retries,
                min_wait=self.min_wait,
                max_wait=self.max_wait
            )
        
        return self.clients[destination]
    
    async def forward_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        custom_destination: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        이벤트 전달 (재시도 로직 포함)
        
        Args:
            event_type: 이벤트 유형
            event_data: 이벤트 데이터
            custom_destination: 사용자 지정 대상 URL (없으면 라우팅 테이블 사용)
            
        Returns:
            Dict[str, Any]: 응답 데이터
            
        Raises:
            ValueError: 대상을 찾을 수 없음
            RetryError: 최대 재시도 횟수 초과
        """
        # 대상 URL 결정
        if custom_destination:
            destination = custom_destination
        else:
            destination = self.sub_agent_routes.get(event_type)
            if not destination:
                destination = self.sub_agent_routes.get("default")
                if not destination:
                    raise ValueError(f"이벤트 유형 '{event_type}'에 대한 대상을 찾을 수 없습니다")
        
        # 클라이언트 가져오기
        client = self.get_client(destination)
        
        try:
            # 이벤트 전송 (재시도 로직 포함)
            result = await client.send_event(event_data)
            return result
        except RetryError as e:
            logger.error(f"최대 재시도 횟수 초과: {str(e)}")
            raise
    
    async def close_all(self):
        """모든 클라이언트 연결 종료"""
        for client in self.clients.values():
            await client.close()


# ----- 재시도 데코레이터 -----

def async_retry(
    max_tries: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
    jitter: bool = True,
    exceptions: Union[List[Exception], Exception] = (Exception,)
):
    """
    비동기 함수에 대한 재시도 데코레이터
    
    Args:
        max_tries: 최대 시도 횟수
        min_wait: 최소 대기 시간 (초)
        max_wait: 최대 대기 시간 (초)
        jitter: 지터 적용 여부 (무작위성 추가)
        exceptions: 재시도할 예외 유형
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tries = 0
            while True:
                tries += 1
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if tries >= max_tries:
                        logger.error(f"최대 재시도 횟수 초과 ({tries}/{max_tries}): {str(e)}")
                        raise
                    
                    # 지수 백오프 대기 시간 계산
                    wait_time = min(max_wait, min_wait * (2 ** (tries - 1)))
                    
                    # 지터 적용
                    if jitter:
                        wait_time = wait_time * (0.5 + random.random())
                    
                    logger.warning(f"시도 {tries}/{max_tries} 실패, {wait_time:.2f}초 후 재시도: {str(e)}")
                    await asyncio.sleep(wait_time)
        
        return wrapper
    
    return decorator


# ----- 사용 예시 -----

async def example_usage():
    """사용 예시"""
    # Sub-Agent 라우팅 테이블
    routes = {
        "cpu_high_usage": "http://sub-agent-cpu:8080",
        "memory_high_usage": "http://sub-agent-memory:8080",
        "default": "http://sub-agent-general:8080"
    }
    
    # 재시도 미들웨어 생성
    middleware = RetryMiddleware(routes)
    
    try:
        # 이벤트 전달 (재시도 로직 포함)
        result = await middleware.forward_event(
            event_type="cpu_high_usage",
            event_data={
                "event_type": "cpu_high_usage",
                "source": "monitoring_system",
                "timestamp": "2023-05-01T12:34:56Z",
                "severity": "warning",
                "data": {
                    "host_id": "server-123",
                    "cpu_usage": 95.2
                }
            }
        )
        
        logger.info(f"전송 성공: {result}")
    
    except Exception as e:
        logger.error(f"전송 실패: {str(e)}")
    
    finally:
        # 모든 클라이언트 연결 종료
        await middleware.close_all()


if __name__ == "__main__":
    asyncio.run(example_usage()) 