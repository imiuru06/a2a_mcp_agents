#!/usr/bin/env python3
"""
Event Gateway - 속도 제한 미들웨어 구현

이 모듈은 Event Gateway에 대한 요청의 속도를 제한하는 미들웨어를 구현합니다.
토큰 버킷 알고리즘을 사용하여 IP 및 클라이언트 기반 속도 제한을 적용합니다.
"""

import time
import logging
from typing import Dict, Any, Callable, Optional, Tuple
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("rate_limiter")


@dataclass
class TokenBucket:
    """토큰 버킷 구현"""
    capacity: int
    refill_rate: float  # 초당 토큰 수
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    
    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.time()
    
    def consume(self, tokens: int = 1) -> bool:
        """
        토큰 소비 시도
        
        Args:
            tokens: 소비할 토큰 수
            
        Returns:
            bool: 토큰 소비 성공 여부
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def _refill(self):
        """경과 시간에 따라 토큰 보충"""
        now = time.time()
        elapsed = now - self.last_refill
        
        # 경과 시간에 따라 토큰 보충
        new_tokens = elapsed * self.refill_rate
        
        if new_tokens > 0:
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now


class InMemoryRateLimiter:
    """메모리 기반 속도 제한 구현"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: 버킷 용량 (최대 토큰 수)
            refill_rate: 초당 보충되는 토큰 수
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.buckets: Dict[str, TokenBucket] = {}
    
    def is_allowed(self, key: str, tokens: int = 1) -> bool:
        """
        요청 허용 여부 확인
        
        Args:
            key: 속도 제한 키 (예: IP 주소)
            tokens: 소비할 토큰 수
            
        Returns:
            bool: 요청 허용 여부
        """
        if key not in self.buckets:
            self.buckets[key] = TokenBucket(self.capacity, self.refill_rate)
        
        return self.buckets[key].consume(tokens)


class RedisRateLimiter:
    """Redis 기반 속도 제한 구현 (분산 환경에서 사용)"""
    
    def __init__(self, redis_client: redis.Redis, capacity: int, refill_rate: float):
        """
        Args:
            redis_client: Redis 클라이언트
            capacity: 버킷 용량 (최대 토큰 수)
            refill_rate: 초당 보충되는 토큰 수
        """
        self.redis = redis_client
        self.capacity = capacity
        self.refill_rate = refill_rate
    
    def is_allowed(self, key: str, tokens: int = 1) -> Tuple[bool, int]:
        """
        요청 허용 여부 확인
        
        Args:
            key: 속도 제한 키 (예: IP 주소)
            tokens: 소비할 토큰 수
            
        Returns:
            Tuple[bool, int]: (요청 허용 여부, 남은 토큰 수)
        """
        # Redis에서 토큰 버킷 정보 가져오기
        bucket_key = f"rate_limit:{key}"
        
        # Redis 파이프라인을 사용하여 원자적으로 처리
        pipe = self.redis.pipeline()
        
        # 현재 시간
        now = time.time()
        
        # 토큰 버킷 정보 가져오기 (없으면 생성)
        pipe.hmget(bucket_key, ["tokens", "last_refill"])
        result = pipe.execute()
        
        tokens_str, last_refill_str = result[0]
        
        if tokens_str is None or last_refill_str is None:
            # 새 버킷 생성
            tokens = self.capacity
            last_refill = now
        else:
            tokens = float(tokens_str)
            last_refill = float(last_refill_str)
            
            # 토큰 보충
            elapsed = now - last_refill
            new_tokens = elapsed * self.refill_rate
            
            if new_tokens > 0:
                tokens = min(self.capacity, tokens + new_tokens)
                last_refill = now
        
        # 토큰 소비 시도
        allowed = tokens >= tokens
        if allowed:
            tokens -= tokens
        
        # 버킷 정보 업데이트
        pipe.hmset(bucket_key, {
            "tokens": tokens,
            "last_refill": last_refill
        })
        
        # 만료 시간 설정 (1시간)
        pipe.expire(bucket_key, 3600)
        pipe.execute()
        
        return allowed, int(tokens)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """속도 제한 미들웨어"""
    
    def __init__(
        self,
        app: FastAPI,
        rate_limiter: Any,
        get_key: Callable[[Request], str],
        tokens_per_request: int = 1,
        status_code: int = status.HTTP_429_TOO_MANY_REQUESTS,
        error_message: str = "요청 빈도 제한을 초과했습니다."
    ):
        """
        Args:
            app: FastAPI 앱
            rate_limiter: 속도 제한 구현체
            get_key: 요청에서 속도 제한 키를 추출하는 함수
            tokens_per_request: 요청당 소비할 토큰 수
            status_code: 속도 제한 초과 시 반환할 상태 코드
            error_message: 속도 제한 초과 시 반환할 오류 메시지
        """
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.get_key = get_key
        self.tokens_per_request = tokens_per_request
        self.status_code = status_code
        self.error_message = error_message
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """요청 처리"""
        # 속도 제한 키 추출 (예: IP 주소)
        key = self.get_key(request)
        
        # Redis 기반 속도 제한인 경우
        if hasattr(self.rate_limiter, 'redis'):
            allowed, remaining = self.rate_limiter.is_allowed(key, self.tokens_per_request)
        else:
            # 메모리 기반 속도 제한인 경우
            allowed = self.rate_limiter.is_allowed(key, self.tokens_per_request)
            remaining = 0  # 메모리 기반에서는 남은 토큰 수를 추적하지 않음
        
        if not allowed:
            logger.warning(f"속도 제한 초과: {key}")
            
            # 재시도 가능한 시간 계산 (초)
            retry_after = max(1, int(self.tokens_per_request / self.rate_limiter.refill_rate))
            
            return JSONResponse(
                status_code=self.status_code,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": self.error_message,
                    "details": {
                        "retry_after": retry_after
                    }
                },
                headers={"Retry-After": str(retry_after)}
            )
        
        # 요청 처리 계속
        response = await call_next(request)
        
        # 응답 헤더에 속도 제한 정보 추가
        response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response


# ----- 유틸리티 함수 -----

def get_client_ip(request: Request) -> str:
    """클라이언트 IP 주소 추출"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def get_client_id(request: Request) -> str:
    """클라이언트 ID 추출 (API 키 또는 인증 토큰)"""
    # API 키 확인
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api:{api_key}"
    
    # 인증 토큰 확인
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return f"token:{auth[7:]}"
    
    # 기본값: IP 주소
    return f"ip:{get_client_ip(request)}"


# ----- 미들웨어 설정 함수 -----

def setup_rate_limit_middleware(
    app: FastAPI,
    redis_url: Optional[str] = None,
    capacity: int = 60,
    refill_rate: float = 1.0,
    tokens_per_request: int = 1
):
    """
    속도 제한 미들웨어 설정
    
    Args:
        app: FastAPI 앱
        redis_url: Redis URL (없으면 메모리 기반 사용)
        capacity: 버킷 용량 (최대 토큰 수)
        refill_rate: 초당 보충되는 토큰 수
        tokens_per_request: 요청당 소비할 토큰 수
    """
    if redis_url:
        # Redis 기반 속도 제한
        try:
            redis_client = redis.from_url(redis_url)
            rate_limiter = RedisRateLimiter(redis_client, capacity, refill_rate)
            logger.info("Redis 기반 속도 제한 미들웨어 설정")
        except Exception as e:
            logger.error(f"Redis 연결 실패, 메모리 기반으로 대체: {str(e)}")
            rate_limiter = InMemoryRateLimiter(capacity, refill_rate)
    else:
        # 메모리 기반 속도 제한
        rate_limiter = InMemoryRateLimiter(capacity, refill_rate)
        logger.info("메모리 기반 속도 제한 미들웨어 설정")
    
    # 미들웨어 추가
    app.add_middleware(
        RateLimitMiddleware,
        rate_limiter=rate_limiter,
        get_key=get_client_id,
        tokens_per_request=tokens_per_request
    )


# ----- 사용 예시 -----

if __name__ == "__main__":
    from fastapi import FastAPI
    
    app = FastAPI()
    
    # 메모리 기반 속도 제한 설정 (분당 60 요청, 요청당 1 토큰)
    setup_rate_limit_middleware(app, capacity=60, refill_rate=1.0)
    
    @app.get("/")
    def read_root():
        return {"message": "Hello World"}
    
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 