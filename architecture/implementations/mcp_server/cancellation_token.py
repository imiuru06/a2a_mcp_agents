#!/usr/bin/env python3
"""
MCP Server - 취소 토큰 관리 모듈

이 모듈은 실행 중인 작업의 취소를 관리하는 기능을 제공합니다.
취소 토큰은 실행 ID로 식별되며, 작업 취소 시 설정됩니다.
"""

import asyncio
import logging
import weakref
from typing import Dict, Optional, Set, Callable, Any, Awaitable
from enum import Enum


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cancellation_token")


class CancellationState(str, Enum):
    """취소 상태 정의"""
    ACTIVE = "active"        # 활성 상태 (취소되지 않음)
    CANCELLING = "cancelling"  # 취소 중
    CANCELLED = "cancelled"  # 취소됨


class CancellationError(Exception):
    """취소 관련 예외"""
    pass


class CancellationToken:
    """취소 토큰 클래스"""
    
    def __init__(self, run_id: str):
        """
        Args:
            run_id: 실행 ID
        """
        self.run_id = run_id
        self._state = CancellationState.ACTIVE
        self._event = asyncio.Event()
        self._callbacks: Set[Callable[[], Awaitable[None]]] = set()
    
    @property
    def is_cancellation_requested(self) -> bool:
        """취소 요청 여부"""
        return self._state != CancellationState.ACTIVE
    
    @property
    def state(self) -> CancellationState:
        """현재 상태"""
        return self._state
    
    async def cancel(self) -> bool:
        """
        취소 요청
        
        Returns:
            bool: 취소 성공 여부
        """
        if self._state != CancellationState.ACTIVE:
            logger.warning(f"실행 {self.run_id}는 이미 취소 상태입니다: {self._state}")
            return False
        
        # 상태 변경
        self._state = CancellationState.CANCELLING
        
        # 이벤트 설정
        self._event.set()
        
        # 콜백 실행
        await self._invoke_callbacks()
        
        # 취소 완료
        self._state = CancellationState.CANCELLED
        
        logger.info(f"실행 {self.run_id} 취소 완료")
        return True
    
    async def _invoke_callbacks(self) -> None:
        """등록된 콜백 실행"""
        if not self._callbacks:
            return
        
        logger.debug(f"실행 {self.run_id}의 취소 콜백 {len(self._callbacks)}개 실행 중")
        
        # 각 콜백 실행
        for callback in list(self._callbacks):
            try:
                await callback()
            except Exception as e:
                logger.error(f"취소 콜백 실행 중 오류 발생: {str(e)}", exc_info=True)
    
    def register_callback(self, callback: Callable[[], Awaitable[None]]) -> Callable[[], None]:
        """
        취소 콜백 등록
        
        Args:
            callback: 취소 시 호출할 비동기 콜백 함수
            
        Returns:
            Callable[[], None]: 등록 해제 함수
        """
        if self.is_cancellation_requested:
            logger.warning(f"실행 {self.run_id}는 이미 취소 상태이므로 콜백을 등록하지 않습니다.")
            return lambda: None
        
        self._callbacks.add(callback)
        
        def unregister():
            if callback in self._callbacks:
                self._callbacks.remove(callback)
        
        return unregister
    
    async def wait_for_cancellation(self, timeout: Optional[float] = None) -> bool:
        """
        취소 대기
        
        Args:
            timeout: 제한 시간(초)
            
        Returns:
            bool: 취소 여부 (True: 취소됨, False: 제한 시간 초과)
        """
        if self.is_cancellation_requested:
            return True
        
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
    
    def throw_if_cancellation_requested(self) -> None:
        """취소 요청 시 예외 발생"""
        if self.is_cancellation_requested:
            raise CancellationError(f"실행 {self.run_id}가 취소되었습니다.")


class CancellationTokenSource:
    """취소 토큰 소스"""
    
    def __init__(self, run_id: str):
        """
        Args:
            run_id: 실행 ID
        """
        self.run_id = run_id
        self.token = CancellationToken(run_id)
    
    async def cancel(self) -> bool:
        """
        취소 요청
        
        Returns:
            bool: 취소 성공 여부
        """
        return await self.token.cancel()


class CancellationTokenRegistry:
    """취소 토큰 레지스트리"""
    
    def __init__(self):
        """초기화"""
        self._tokens: Dict[str, CancellationTokenSource] = {}
        self._lock = asyncio.Lock()
    
    async def create_token(self, run_id: str) -> CancellationToken:
        """
        토큰 생성
        
        Args:
            run_id: 실행 ID
            
        Returns:
            CancellationToken: 생성된 토큰
        """
        async with self._lock:
            if run_id in self._tokens:
                logger.warning(f"실행 {run_id}의 토큰이 이미 존재합니다. 기존 토큰을 반환합니다.")
                return self._tokens[run_id].token
            
            source = CancellationTokenSource(run_id)
            self._tokens[run_id] = source
            logger.debug(f"실행 {run_id}의 토큰 생성 완료")
            
            return source.token
    
    async def cancel_execution(self, run_id: str) -> bool:
        """
        실행 취소
        
        Args:
            run_id: 실행 ID
            
        Returns:
            bool: 취소 성공 여부
        """
        async with self._lock:
            if run_id not in self._tokens:
                logger.warning(f"실행 {run_id}의 토큰을 찾을 수 없습니다.")
                return False
            
            source = self._tokens[run_id]
        
        # 락 외부에서 취소 실행
        return await source.cancel()
    
    async def get_token(self, run_id: str) -> Optional[CancellationToken]:
        """
        토큰 조회
        
        Args:
            run_id: 실행 ID
            
        Returns:
            Optional[CancellationToken]: 토큰 또는 None
        """
        async with self._lock:
            if run_id not in self._tokens:
                return None
            
            return self._tokens[run_id].token
    
    async def remove_token(self, run_id: str) -> bool:
        """
        토큰 제거
        
        Args:
            run_id: 실행 ID
            
        Returns:
            bool: 제거 성공 여부
        """
        async with self._lock:
            if run_id not in self._tokens:
                return False
            
            del self._tokens[run_id]
            logger.debug(f"실행 {run_id}의 토큰 제거 완료")
            return True
    
    async def cleanup(self) -> None:
        """만료된 토큰 정리"""
        async with self._lock:
            # 취소된 토큰 목록
            to_remove = [
                run_id for run_id, source in self._tokens.items()
                if source.token.state == CancellationState.CANCELLED
            ]
            
            # 토큰 제거
            for run_id in to_remove:
                del self._tokens[run_id]
            
            if to_remove:
                logger.debug(f"만료된 토큰 {len(to_remove)}개 정리 완료")


# 싱글톤 인스턴스
_registry: Optional[CancellationTokenRegistry] = None


def get_registry() -> CancellationTokenRegistry:
    """레지스트리 싱글톤 인스턴스 반환"""
    global _registry
    if _registry is None:
        _registry = CancellationTokenRegistry()
    return _registry


async def create_token(run_id: str) -> CancellationToken:
    """
    토큰 생성
    
    Args:
        run_id: 실행 ID
        
    Returns:
        CancellationToken: 생성된 토큰
    """
    return await get_registry().create_token(run_id)


async def cancel_execution(run_id: str) -> bool:
    """
    실행 취소
    
    Args:
        run_id: 실행 ID
        
    Returns:
        bool: 취소 성공 여부
    """
    return await get_registry().cancel_execution(run_id)


async def get_token(run_id: str) -> Optional[CancellationToken]:
    """
    토큰 조회
    
    Args:
        run_id: 실행 ID
        
    Returns:
        Optional[CancellationToken]: 토큰 또는 None
    """
    return await get_registry().get_token(run_id)


async def example_usage():
    """사용 예시"""
    # 토큰 생성
    run_id = "test-run-456"
    token = await create_token(run_id)
    
    # 취소 콜백 등록
    async def on_cancel():
        print(f"실행 {run_id}이 취소되었습니다!")
    
    unregister = token.register_callback(on_cancel)
    
    # 비동기 작업 시뮬레이션
    async def long_running_task():
        for i in range(10):
            # 취소 확인
            if token.is_cancellation_requested:
                print(f"작업이 취소되어 중단합니다. (단계 {i}/10)")
                return
            
            print(f"작업 진행 중... (단계 {i}/10)")
            await asyncio.sleep(0.5)
        
        print("작업 완료!")
    
    # 작업 및 취소 태스크 생성
    task = asyncio.create_task(long_running_task())
    
    # 3초 후 취소
    await asyncio.sleep(3)
    print("작업 취소 요청...")
    await cancel_execution(run_id)
    
    # 작업 완료 대기
    await task
    
    # 토큰 상태 확인
    print(f"토큰 상태: {token.state}")
    
    # 콜백 등록 해제
    unregister()


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage()) 