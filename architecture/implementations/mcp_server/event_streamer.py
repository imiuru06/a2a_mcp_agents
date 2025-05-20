#!/usr/bin/env python3
"""
MCP Server - 이벤트 스트리밍 모듈

이 모듈은 SSE(Server-Sent Events)를 통해 도구 실행 상태를 실시간으로 스트리밍하는 기능을 제공합니다.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, AsyncGenerator, Set, Callable
from datetime import datetime
from enum import Enum


# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("event_streamer")


class EventType(str, Enum):
    """이벤트 유형 정의"""
    STATUS = "status"      # 상태 변경 이벤트
    PROGRESS = "progress"  # 진행률 이벤트
    LOG = "log"            # 로그 이벤트
    RESULT = "result"      # 결과 이벤트
    ERROR = "error"        # 오류 이벤트


class EventStreamer:
    """이벤트 스트리밍 관리자"""
    
    def __init__(self):
        """초기화"""
        # 실행 ID별 이벤트 큐
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        
        # 실행 ID별 마지막 이벤트
        self._last_events: Dict[str, Dict[EventType, Dict[str, Any]]] = {}
        
        # 큐 관리를 위한 락
        self._lock = asyncio.Lock()
        
        # 실행 ID별 구독자 수
        self._subscribers: Dict[str, int] = {}
    
    async def publish_event(
        self,
        run_id: str,
        event_type: EventType,
        data: Dict[str, Any]
    ) -> None:
        """
        이벤트 발행
        
        Args:
            run_id: 실행 ID
            event_type: 이벤트 유형
            data: 이벤트 데이터
        """
        # 이벤트 생성
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        # 마지막 이벤트 업데이트
        if run_id not in self._last_events:
            self._last_events[run_id] = {}
        
        self._last_events[run_id][event_type] = event
        
        # 구독자가 없는 경우 로그만 남김
        if run_id not in self._queues or not self._queues[run_id]:
            logger.debug(f"실행 {run_id}의 구독자가 없습니다. 이벤트: {event_type}")
            return
        
        # 모든 큐에 이벤트 전송
        for queue in self._queues[run_id]:
            await queue.put(event)
        
        logger.debug(f"실행 {run_id}의 {len(self._queues[run_id])}개 구독자에게 {event_type} 이벤트 발행")
    
    async def subscribe(self, run_id: str, history: bool = True) -> AsyncGenerator[Dict[str, Any], None]:
        """
        이벤트 구독
        
        Args:
            run_id: 실행 ID
            history: 이전 이벤트 포함 여부
            
        Yields:
            Dict[str, Any]: 이벤트
        """
        # 큐 생성
        queue = asyncio.Queue()
        
        # 큐 등록
        async with self._lock:
            if run_id not in self._queues:
                self._queues[run_id] = []
            
            self._queues[run_id].append(queue)
            
            # 구독자 수 증가
            self._subscribers[run_id] = self._subscribers.get(run_id, 0) + 1
            
            logger.debug(f"실행 {run_id}에 새 구독자 추가 (총 {self._subscribers[run_id]}명)")
        
        try:
            # 이전 이벤트 전송
            if history and run_id in self._last_events:
                for event_type, event in self._last_events[run_id].items():
                    yield event
            
            # 새 이벤트 스트리밍
            while True:
                event = await queue.get()
                yield event
                queue.task_done()
        
        finally:
            # 구독 해제
            async with self._lock:
                if run_id in self._queues and queue in self._queues[run_id]:
                    self._queues[run_id].remove(queue)
                    
                    # 구독자 수 감소
                    self._subscribers[run_id] = self._subscribers.get(run_id, 1) - 1
                    
                    logger.debug(f"실행 {run_id}의 구독자 제거 (남은 구독자: {self._subscribers[run_id]})")
                    
                    # 구독자가 없는 경우 큐 목록 제거
                    if not self._queues[run_id]:
                        del self._queues[run_id]
                        if run_id in self._subscribers:
                            del self._subscribers[run_id]
    
    async def get_last_event(self, run_id: str, event_type: EventType) -> Optional[Dict[str, Any]]:
        """
        마지막 이벤트 조회
        
        Args:
            run_id: 실행 ID
            event_type: 이벤트 유형
            
        Returns:
            Optional[Dict[str, Any]]: 마지막 이벤트 또는 None
        """
        if run_id not in self._last_events:
            return None
        
        return self._last_events[run_id].get(event_type)
    
    async def get_subscriber_count(self, run_id: str) -> int:
        """
        구독자 수 조회
        
        Args:
            run_id: 실행 ID
            
        Returns:
            int: 구독자 수
        """
        return self._subscribers.get(run_id, 0)
    
    async def clear_events(self, run_id: str) -> None:
        """
        이벤트 정리
        
        Args:
            run_id: 실행 ID
        """
        async with self._lock:
            if run_id in self._last_events:
                del self._last_events[run_id]
                logger.debug(f"실행 {run_id}의 이벤트 정리 완료")


class SSEResponse:
    """SSE 응답 생성기"""
    
    @staticmethod
    def format_sse(event: Optional[str], data: Any) -> str:
        """
        SSE 형식 문자열 생성
        
        Args:
            event: 이벤트 이름 (None인 경우 생략)
            data: 이벤트 데이터
            
        Returns:
            str: SSE 형식 문자열
        """
        message = ""
        
        # 이벤트 이름이 있는 경우 추가
        if event:
            message += f"event: {event}\n"
        
        # 데이터가 딕셔너리인 경우 JSON으로 직렬화
        if isinstance(data, dict):
            data = json.dumps(data)
        
        # 데이터 추가 (여러 줄인 경우 각 줄마다 data: 접두사 추가)
        for line in str(data).split("\n"):
            message += f"data: {line}\n"
        
        # 메시지 종료
        message += "\n"
        
        return message
    
    @staticmethod
    async def stream_sse(
        events: AsyncGenerator[Dict[str, Any], None]
    ) -> AsyncGenerator[str, None]:
        """
        SSE 스트림 생성
        
        Args:
            events: 이벤트 생성기
            
        Yields:
            str: SSE 형식 문자열
        """
        # 연결 유지를 위한 주기적인 빈 메시지
        keep_alive_task = None
        
        try:
            # 연결 시작 메시지
            yield SSEResponse.format_sse(None, {"status": "connected"})
            
            # 연결 유지 태스크 생성
            keep_alive_event = asyncio.Event()
            keep_alive_task = asyncio.create_task(
                SSEResponse._keep_alive(keep_alive_event)
            )
            
            # 이벤트 스트리밍
            async for event in events:
                # 이벤트 유형 추출
                event_type = event.get("type", "message")
                
                # SSE 형식으로 변환하여 전송
                yield SSEResponse.format_sse(event_type, event)
        
        finally:
            # 연결 유지 태스크 종료
            if keep_alive_task:
                keep_alive_event.set()
                try:
                    await keep_alive_task
                except asyncio.CancelledError:
                    pass
    
    @staticmethod
    async def _keep_alive(stop_event: asyncio.Event) -> AsyncGenerator[str, None]:
        """
        연결 유지를 위한 주기적인 빈 메시지 전송
        
        Args:
            stop_event: 중지 이벤트
            
        Yields:
            str: 빈 SSE 메시지
        """
        while not stop_event.is_set():
            try:
                # 30초마다 빈 주석 전송
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"


# 싱글톤 인스턴스
_streamer: Optional[EventStreamer] = None


def get_streamer() -> EventStreamer:
    """스트리머 싱글톤 인스턴스 반환"""
    global _streamer
    if _streamer is None:
        _streamer = EventStreamer()
    return _streamer


async def publish_event(
    run_id: str,
    event_type: EventType,
    data: Dict[str, Any]
) -> None:
    """
    이벤트 발행
    
    Args:
        run_id: 실행 ID
        event_type: 이벤트 유형
        data: 이벤트 데이터
    """
    await get_streamer().publish_event(run_id, event_type, data)


async def subscribe(
    run_id: str,
    history: bool = True
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    이벤트 구독
    
    Args:
        run_id: 실행 ID
        history: 이전 이벤트 포함 여부
        
    Yields:
        Dict[str, Any]: 이벤트
    """
    async for event in get_streamer().subscribe(run_id, history):
        yield event


async def get_last_event(
    run_id: str,
    event_type: EventType
) -> Optional[Dict[str, Any]]:
    """
    마지막 이벤트 조회
    
    Args:
        run_id: 실행 ID
        event_type: 이벤트 유형
        
    Returns:
        Optional[Dict[str, Any]]: 마지막 이벤트 또는 None
    """
    return await get_streamer().get_last_event(run_id, event_type)


async def example_usage():
    """사용 예시"""
    run_id = "test-run-789"
    
    # 구독 태스크 생성
    async def subscriber():
        print("구독 시작...")
        async for event in subscribe(run_id):
            print(f"이벤트 수신: {event}")
    
    # 발행 태스크 생성
    async def publisher():
        # 초기 상태 이벤트
        await publish_event(
            run_id,
            EventType.STATUS,
            {"status": "running", "message": "도구 실행 시작"}
        )
        
        # 진행률 이벤트
        for i in range(1, 11):
            await asyncio.sleep(0.5)
            
            # 진행률 이벤트
            await publish_event(
                run_id,
                EventType.PROGRESS,
                {"progress": i * 10, "message": f"단계 {i}/10 완료"}
            )
            
            # 로그 이벤트
            await publish_event(
                run_id,
                EventType.LOG,
                {"level": "info", "message": f"작업 진행 중... {i * 10}% 완료"}
            )
        
        # 결과 이벤트
        await publish_event(
            run_id,
            EventType.RESULT,
            {"result": {"output": "작업 결과"}}
        )
        
        # 완료 상태 이벤트
        await publish_event(
            run_id,
            EventType.STATUS,
            {"status": "completed", "message": "도구 실행 완료"}
        )
    
    # 태스크 실행
    sub_task = asyncio.create_task(subscriber())
    pub_task = asyncio.create_task(publisher())
    
    # 발행 태스크 완료 대기
    await pub_task
    
    # 추가 이벤트 대기
    await asyncio.sleep(1)
    
    # 구독 태스크 취소
    sub_task.cancel()
    try:
        await sub_task
    except asyncio.CancelledError:
        pass
    
    # 마지막 상태 이벤트 조회
    last_status = await get_last_event(run_id, EventType.STATUS)
    print(f"마지막 상태: {last_status}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage()) 