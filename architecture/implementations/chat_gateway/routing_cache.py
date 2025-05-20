#!/usr/bin/env python3
"""
Chat Gateway - 라우팅 테이블 캐시 구현

이 모듈은 에이전트 ID와 엔드포인트 매핑을 관리하는 라우팅 테이블 캐시를 구현합니다.
"""

import json
import time
import logging
import asyncio
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta

# Redis 클라이언트 (선택적 의존성)
try:
    import redis
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("routing_cache")


class InMemoryRoutingCache:
    """메모리 기반 라우팅 테이블 캐시 구현"""
    
    def __init__(self, default_ttl: int = 3600):
        """
        Args:
            default_ttl: 기본 TTL(초)
        """
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._expiry: Dict[str, float] = {}
    
    async def get(self, agent_id: str) -> Optional[str]:
        """
        에이전트 엔드포인트 조회
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            Optional[str]: 엔드포인트 URL 또는 None
        """
        self._cleanup_expired()
        
        if agent_id not in self._cache:
            return None
        
        return self._cache[agent_id].get("endpoint")
    
    async def set(self, agent_id: str, endpoint: str, ttl: Optional[int] = None) -> None:
        """
        에이전트 엔드포인트 설정
        
        Args:
            agent_id: 에이전트 ID
            endpoint: 엔드포인트 URL
            ttl: TTL(초), None인 경우 기본값 사용
        """
        ttl = ttl or self.default_ttl
        expiry = time.time() + ttl
        
        self._cache[agent_id] = {
            "endpoint": endpoint,
            "updated_at": datetime.now().isoformat()
        }
        self._expiry[agent_id] = expiry
    
    async def delete(self, agent_id: str) -> bool:
        """
        에이전트 엔드포인트 삭제
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        if agent_id in self._cache:
            del self._cache[agent_id]
            del self._expiry[agent_id]
            return True
        return False
    
    async def get_all(self) -> Dict[str, Dict[str, Any]]:
        """
        모든 에이전트 엔드포인트 조회
        
        Returns:
            Dict[str, Dict[str, Any]]: 에이전트 ID를 키로 하는 엔드포인트 정보
        """
        self._cleanup_expired()
        return self._cache.copy()
    
    async def exists(self, agent_id: str) -> bool:
        """
        에이전트 존재 여부 확인
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            bool: 존재 여부
        """
        self._cleanup_expired()
        return agent_id in self._cache
    
    async def ttl(self, agent_id: str) -> Optional[int]:
        """
        에이전트 엔드포인트 TTL 조회
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            Optional[int]: TTL(초) 또는 None
        """
        if agent_id not in self._expiry:
            return None
        
        ttl = int(self._expiry[agent_id] - time.time())
        return max(0, ttl)
    
    async def refresh(self, agent_id: str, ttl: Optional[int] = None) -> bool:
        """
        에이전트 엔드포인트 TTL 갱신
        
        Args:
            agent_id: 에이전트 ID
            ttl: 새 TTL(초), None인 경우 기본값 사용
            
        Returns:
            bool: 갱신 성공 여부
        """
        if agent_id not in self._cache:
            return False
        
        ttl = ttl or self.default_ttl
        self._expiry[agent_id] = time.time() + ttl
        return True
    
    def _cleanup_expired(self) -> None:
        """만료된 항목 정리"""
        now = time.time()
        expired = [k for k, v in self._expiry.items() if v <= now]
        
        for key in expired:
            if key in self._cache:
                del self._cache[key]
            if key in self._expiry:
                del self._expiry[key]


class RedisRoutingCache:
    """Redis 기반 라우팅 테이블 캐시 구현"""
    
    def __init__(self, redis_client, prefix: str = "agent:", default_ttl: int = 3600):
        """
        Args:
            redis_client: Redis 클라이언트
            prefix: 키 접두사
            default_ttl: 기본 TTL(초)
        """
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = default_ttl
    
    def _key(self, agent_id: str) -> str:
        """Redis 키 생성"""
        return f"{self.prefix}{agent_id}"
    
    async def get(self, agent_id: str) -> Optional[str]:
        """
        에이전트 엔드포인트 조회
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            Optional[str]: 엔드포인트 URL 또는 None
        """
        key = self._key(agent_id)
        data = await self.redis.get(key)
        
        if not data:
            return None
        
        try:
            agent_data = json.loads(data)
            return agent_data.get("endpoint")
        except json.JSONDecodeError:
            logger.error(f"잘못된 JSON 형식: {data}")
            return None
    
    async def set(self, agent_id: str, endpoint: str, ttl: Optional[int] = None) -> None:
        """
        에이전트 엔드포인트 설정
        
        Args:
            agent_id: 에이전트 ID
            endpoint: 엔드포인트 URL
            ttl: TTL(초), None인 경우 기본값 사용
        """
        key = self._key(agent_id)
        ttl = ttl or self.default_ttl
        
        agent_data = {
            "endpoint": endpoint,
            "updated_at": datetime.now().isoformat()
        }
        
        await self.redis.setex(key, ttl, json.dumps(agent_data))
    
    async def delete(self, agent_id: str) -> bool:
        """
        에이전트 엔드포인트 삭제
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        key = self._key(agent_id)
        result = await self.redis.delete(key)
        return result > 0
    
    async def get_all(self) -> Dict[str, Dict[str, Any]]:
        """
        모든 에이전트 엔드포인트 조회
        
        Returns:
            Dict[str, Dict[str, Any]]: 에이전트 ID를 키로 하는 엔드포인트 정보
        """
        # 모든 키 조회
        keys = await self.redis.keys(f"{self.prefix}*")
        result = {}
        
        # 키가 없는 경우
        if not keys:
            return result
        
        # 파이프라인으로 한 번에 조회
        pipeline = self.redis.pipeline()
        for key in keys:
            pipeline.get(key)
        
        values = await pipeline.execute()
        
        # 결과 처리
        for key, value in zip(keys, values):
            if value:
                try:
                    agent_id = key.decode('utf-8').replace(self.prefix, '')
                    result[agent_id] = json.loads(value)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    logger.error(f"데이터 처리 중 오류 발생: {e}")
        
        return result
    
    async def exists(self, agent_id: str) -> bool:
        """
        에이전트 존재 여부 확인
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            bool: 존재 여부
        """
        key = self._key(agent_id)
        return await self.redis.exists(key) > 0
    
    async def ttl(self, agent_id: str) -> Optional[int]:
        """
        에이전트 엔드포인트 TTL 조회
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            Optional[int]: TTL(초) 또는 None
        """
        key = self._key(agent_id)
        ttl = await self.redis.ttl(key)
        
        if ttl < 0:  # 키가 없거나 만료 시간이 없는 경우
            return None
        
        return ttl
    
    async def refresh(self, agent_id: str, ttl: Optional[int] = None) -> bool:
        """
        에이전트 엔드포인트 TTL 갱신
        
        Args:
            agent_id: 에이전트 ID
            ttl: 새 TTL(초), None인 경우 기본값 사용
            
        Returns:
            bool: 갱신 성공 여부
        """
        key = self._key(agent_id)
        ttl = ttl or self.default_ttl
        
        # 키가 있는지 확인
        if not await self.redis.exists(key):
            return False
        
        # TTL 갱신
        return await self.redis.expire(key, ttl)


class RoutingCache:
    """라우팅 테이블 캐시 인터페이스"""
    
    def __init__(self, redis_url: Optional[str] = None, default_ttl: int = 3600):
        """
        Args:
            redis_url: Redis URL (없으면 메모리 기반 사용)
            default_ttl: 기본 TTL(초)
        """
        self.default_ttl = default_ttl
        
        # Redis 사용 가능 여부 확인
        if redis_url and REDIS_AVAILABLE:
            try:
                # Redis 클라이언트 생성
                self.redis = aioredis.from_url(redis_url)
                self.cache = RedisRoutingCache(self.redis, default_ttl=default_ttl)
                logger.info("Redis 기반 라우팅 캐시 초기화")
            except Exception as e:
                logger.error(f"Redis 연결 실패, 메모리 기반으로 대체: {str(e)}")
                self.cache = InMemoryRoutingCache(default_ttl=default_ttl)
        else:
            # 메모리 기반 캐시 사용
            self.cache = InMemoryRoutingCache(default_ttl=default_ttl)
            logger.info("메모리 기반 라우팅 캐시 초기화")
    
    async def get(self, agent_id: str) -> Optional[str]:
        """에이전트 엔드포인트 조회"""
        return await self.cache.get(agent_id)
    
    async def set(self, agent_id: str, endpoint: str, ttl: Optional[int] = None) -> None:
        """에이전트 엔드포인트 설정"""
        await self.cache.set(agent_id, endpoint, ttl)
    
    async def delete(self, agent_id: str) -> bool:
        """에이전트 엔드포인트 삭제"""
        return await self.cache.delete(agent_id)
    
    async def get_all(self) -> Dict[str, Dict[str, Any]]:
        """모든 에이전트 엔드포인트 조회"""
        return await self.cache.get_all()
    
    async def exists(self, agent_id: str) -> bool:
        """에이전트 존재 여부 확인"""
        return await self.cache.exists(agent_id)
    
    async def ttl(self, agent_id: str) -> Optional[int]:
        """에이전트 엔드포인트 TTL 조회"""
        return await self.cache.ttl(agent_id)
    
    async def refresh(self, agent_id: str, ttl: Optional[int] = None) -> bool:
        """에이전트 엔드포인트 TTL 갱신"""
        return await self.cache.refresh(agent_id, ttl)


# ----- 기본 라우팅 테이블 -----

DEFAULT_ROUTES = {
    "supervisor_agent": "http://supervisor:8080",
    "mechanic_agent": "http://mechanic-agent:8080",
    "doctor_agent": "http://doctor-agent:8080",
    "general_agent": "http://general-agent:8080"
}


async def initialize_cache(cache: RoutingCache, routes: Dict[str, str] = None) -> None:
    """
    캐시 초기화
    
    Args:
        cache: 라우팅 캐시
        routes: 초기 라우팅 테이블 (None인 경우 기본값 사용)
    """
    routes = routes or DEFAULT_ROUTES
    
    for agent_id, endpoint in routes.items():
        await cache.set(agent_id, endpoint)
    
    logger.info(f"{len(routes)}개의 라우팅 항목으로 캐시 초기화")


# ----- 사용 예시 -----

async def example_usage():
    """사용 예시"""
    # 메모리 기반 캐시 생성
    cache = RoutingCache()
    
    # 캐시 초기화
    await initialize_cache(cache)
    
    # 엔드포인트 조회
    endpoint = await cache.get("supervisor_agent")
    print(f"Supervisor 엔드포인트: {endpoint}")
    
    # 새 에이전트 추가
    await cache.set("new_agent", "http://new-agent:8080", ttl=60)
    
    # 모든 에이전트 조회
    all_agents = await cache.get_all()
    print(f"모든 에이전트: {all_agents}")
    
    # TTL 조회
    ttl = await cache.ttl("new_agent")
    print(f"new_agent TTL: {ttl}초")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage()) 