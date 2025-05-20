#!/usr/bin/env python3
"""
MCP Server - 컨텍스트 저장소 모듈

이 모듈은 도구 실행 컨텍스트를 저장하고 관리하는 기능을 제공합니다.
컨텍스트는 실행 ID로 식별되며, 실행 상태, 매개변수, 결과 등을 포함합니다.
"""

import json
import time
import asyncio
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("context_store")


class ContextStoreError(Exception):
    """컨텍스트 저장소 관련 예외"""
    pass


class ContextStore:
    """도구 실행 컨텍스트 저장소"""
    
    def __init__(
        self,
        backend: str = "memory",
        redis_url: Optional[str] = None,
        mongo_url: Optional[str] = None,
        ttl_seconds: int = 86400  # 기본 TTL: 24시간
    ):
        """
        Args:
            backend: 저장소 백엔드 유형 ("memory", "redis", "mongo")
            redis_url: Redis 연결 URL
            mongo_url: MongoDB 연결 URL
            ttl_seconds: 컨텍스트 TTL(초)
        """
        self.backend = backend
        self.redis_url = redis_url
        self.mongo_url = mongo_url
        self.ttl_seconds = ttl_seconds
        
        # 인메모리 저장소
        self.memory_store: Dict[str, Dict[str, Any]] = {}
        
        # 백엔드별 클라이언트
        self.redis_client = None
        self.mongo_client = None
        self.mongo_db = None
        self.mongo_collection = None
        
        # 백엔드 초기화
        self._initialize_backend()
    
    def _initialize_backend(self):
        """백엔드 초기화"""
        if self.backend == "redis":
            try:
                import redis
                self.redis_client = redis.Redis.from_url(
                    self.redis_url or "redis://localhost:6379/0"
                )
                logger.info("Redis 백엔드 초기화 완료")
            except ImportError:
                logger.warning("redis 패키지가 설치되지 않았습니다. 인메모리 백엔드로 대체합니다.")
                self.backend = "memory"
            except Exception as e:
                logger.error(f"Redis 연결 실패: {str(e)}")
                logger.warning("인메모리 백엔드로 대체합니다.")
                self.backend = "memory"
        
        elif self.backend == "mongo":
            try:
                import pymongo
                self.mongo_client = pymongo.MongoClient(
                    self.mongo_url or "mongodb://localhost:27017/"
                )
                self.mongo_db = self.mongo_client["mcp_server"]
                self.mongo_collection = self.mongo_db["execution_contexts"]
                
                # TTL 인덱스 생성
                self.mongo_collection.create_index(
                    "created_at", 
                    expireAfterSeconds=self.ttl_seconds
                )
                
                logger.info("MongoDB 백엔드 초기화 완료")
            except ImportError:
                logger.warning("pymongo 패키지가 설치되지 않았습니다. 인메모리 백엔드로 대체합니다.")
                self.backend = "memory"
            except Exception as e:
                logger.error(f"MongoDB 연결 실패: {str(e)}")
                logger.warning("인메모리 백엔드로 대체합니다.")
                self.backend = "memory"
        
        logger.info(f"컨텍스트 저장소 백엔드: {self.backend}")
    
    async def save_context(self, run_id: str, context: Dict[str, Any]) -> bool:
        """
        컨텍스트 저장
        
        Args:
            run_id: 실행 ID
            context: 컨텍스트 데이터
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            # 타임스탬프 추가
            context["updated_at"] = datetime.now().isoformat()
            
            if "created_at" not in context:
                context["created_at"] = context["updated_at"]
            
            if self.backend == "memory":
                self.memory_store[run_id] = context
            
            elif self.backend == "redis":
                # Redis에 JSON으로 저장
                serialized = json.dumps(context)
                await asyncio.to_thread(
                    self.redis_client.setex,
                    f"context:{run_id}",
                    self.ttl_seconds,
                    serialized
                )
            
            elif self.backend == "mongo":
                # MongoDB에 저장
                document = {
                    "run_id": run_id,
                    **context
                }
                await asyncio.to_thread(
                    self.mongo_collection.update_one,
                    {"run_id": run_id},
                    {"$set": document},
                    upsert=True
                )
            
            logger.debug(f"컨텍스트 저장 성공: {run_id}")
            return True
        
        except Exception as e:
            logger.error(f"컨텍스트 저장 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 저장 실패: {str(e)}")
    
    async def get_context(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        컨텍스트 조회
        
        Args:
            run_id: 실행 ID
            
        Returns:
            Optional[Dict[str, Any]]: 컨텍스트 데이터 또는 None
        """
        try:
            if self.backend == "memory":
                return self.memory_store.get(run_id)
            
            elif self.backend == "redis":
                # Redis에서 조회
                serialized = await asyncio.to_thread(
                    self.redis_client.get,
                    f"context:{run_id}"
                )
                
                if serialized:
                    return json.loads(serialized)
                return None
            
            elif self.backend == "mongo":
                # MongoDB에서 조회
                document = await asyncio.to_thread(
                    self.mongo_collection.find_one,
                    {"run_id": run_id}
                )
                
                if document:
                    # ObjectId 제거
                    if "_id" in document:
                        del document["_id"]
                    return document
                return None
            
            return None
        
        except Exception as e:
            logger.error(f"컨텍스트 조회 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 조회 실패: {str(e)}")
    
    async def update_context(self, run_id: str, updates: Dict[str, Any]) -> bool:
        """
        컨텍스트 업데이트
        
        Args:
            run_id: 실행 ID
            updates: 업데이트할 필드
            
        Returns:
            bool: 업데이트 성공 여부
        """
        try:
            # 현재 컨텍스트 조회
            context = await self.get_context(run_id)
            
            if not context:
                logger.warning(f"업데이트할 컨텍스트를 찾을 수 없음: {run_id}")
                return False
            
            # 컨텍스트 업데이트
            context.update(updates)
            context["updated_at"] = datetime.now().isoformat()
            
            # 업데이트된 컨텍스트 저장
            return await self.save_context(run_id, context)
        
        except Exception as e:
            logger.error(f"컨텍스트 업데이트 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 업데이트 실패: {str(e)}")
    
    async def delete_context(self, run_id: str) -> bool:
        """
        컨텍스트 삭제
        
        Args:
            run_id: 실행 ID
            
        Returns:
            bool: 삭제 성공 여부
        """
        try:
            if self.backend == "memory":
                if run_id in self.memory_store:
                    del self.memory_store[run_id]
                    return True
                return False
            
            elif self.backend == "redis":
                # Redis에서 삭제
                deleted = await asyncio.to_thread(
                    self.redis_client.delete,
                    f"context:{run_id}"
                )
                return deleted > 0
            
            elif self.backend == "mongo":
                # MongoDB에서 삭제
                result = await asyncio.to_thread(
                    self.mongo_collection.delete_one,
                    {"run_id": run_id}
                )
                return result.deleted_count > 0
            
            return False
        
        except Exception as e:
            logger.error(f"컨텍스트 삭제 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 삭제 실패: {str(e)}")
    
    async def list_contexts(
        self,
        filter_criteria: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        컨텍스트 목록 조회
        
        Args:
            filter_criteria: 필터링 기준
            limit: 최대 결과 수
            offset: 결과 오프셋
            
        Returns:
            List[Dict[str, Any]]: 컨텍스트 목록
        """
        filter_criteria = filter_criteria or {}
        
        try:
            if self.backend == "memory":
                # 인메모리 필터링
                results = []
                for run_id, context in self.memory_store.items():
                    match = True
                    for key, value in filter_criteria.items():
                        if key not in context or context[key] != value:
                            match = False
                            break
                    
                    if match:
                        results.append({"run_id": run_id, **context})
                
                # 정렬 및 페이징
                results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                return results[offset:offset+limit]
            
            elif self.backend == "redis":
                # Redis는 필터링이 제한적이므로 모든 키를 가져와서 필터링
                keys = await asyncio.to_thread(
                    self.redis_client.keys,
                    "context:*"
                )
                
                results = []
                for key in keys:
                    run_id = key.decode().split(":", 1)[1]
                    context = await self.get_context(run_id)
                    
                    if context:
                        # 필터링
                        match = True
                        for key, value in filter_criteria.items():
                            if key not in context or context[key] != value:
                                match = False
                                break
                        
                        if match:
                            results.append({"run_id": run_id, **context})
                
                # 정렬 및 페이징
                results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                return results[offset:offset+limit]
            
            elif self.backend == "mongo":
                # MongoDB 쿼리
                cursor = self.mongo_collection.find(
                    filter_criteria,
                    {"_id": 0}  # _id 필드 제외
                ).sort("created_at", -1).skip(offset).limit(limit)
                
                return await asyncio.to_thread(list, cursor)
            
            return []
        
        except Exception as e:
            logger.error(f"컨텍스트 목록 조회 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 목록 조회 실패: {str(e)}")
    
    async def count_contexts(
        self,
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        컨텍스트 수 조회
        
        Args:
            filter_criteria: 필터링 기준
            
        Returns:
            int: 컨텍스트 수
        """
        filter_criteria = filter_criteria or {}
        
        try:
            if self.backend == "memory":
                # 인메모리 필터링 및 카운트
                count = 0
                for context in self.memory_store.values():
                    match = True
                    for key, value in filter_criteria.items():
                        if key not in context or context[key] != value:
                            match = False
                            break
                    
                    if match:
                        count += 1
                
                return count
            
            elif self.backend == "redis":
                # Redis는 필터링이 제한적이므로 모든 키를 가져와서 필터링
                if not filter_criteria:
                    # 필터가 없는 경우 키 수만 반환
                    return await asyncio.to_thread(
                        self.redis_client.keys,
                        "context:*"
                    ).__len__()
                
                # 필터가 있는 경우 각 항목 확인
                keys = await asyncio.to_thread(
                    self.redis_client.keys,
                    "context:*"
                )
                
                count = 0
                for key in keys:
                    run_id = key.decode().split(":", 1)[1]
                    context = await self.get_context(run_id)
                    
                    if context:
                        # 필터링
                        match = True
                        for key, value in filter_criteria.items():
                            if key not in context or context[key] != value:
                                match = False
                                break
                        
                        if match:
                            count += 1
                
                return count
            
            elif self.backend == "mongo":
                # MongoDB 카운트
                return await asyncio.to_thread(
                    self.mongo_collection.count_documents,
                    filter_criteria
                )
            
            return 0
        
        except Exception as e:
            logger.error(f"컨텍스트 수 조회 실패: {str(e)}", exc_info=True)
            raise ContextStoreError(f"컨텍스트 수 조회 실패: {str(e)}")


async def example_usage():
    """사용 예시"""
    # 인메모리 컨텍스트 저장소 생성
    context_store = ContextStore(backend="memory")
    
    # 컨텍스트 저장
    run_id = "test-run-123"
    await context_store.save_context(run_id, {
        "tool_name": "example-tool",
        "parameters": {"param1": "value1"},
        "status": "running"
    })
    
    # 컨텍스트 조회
    context = await context_store.get_context(run_id)
    print(f"조회된 컨텍스트: {context}")
    
    # 컨텍스트 업데이트
    await context_store.update_context(run_id, {
        "status": "completed",
        "result": {"output": "success"}
    })
    
    # 업데이트된 컨텍스트 조회
    updated_context = await context_store.get_context(run_id)
    print(f"업데이트된 컨텍스트: {updated_context}")
    
    # 컨텍스트 목록 조회
    contexts = await context_store.list_contexts(
        filter_criteria={"status": "completed"}
    )
    print(f"완료된 컨텍스트 수: {len(contexts)}")
    
    # 컨텍스트 삭제
    await context_store.delete_context(run_id)
    
    # 삭제 확인
    deleted_context = await context_store.get_context(run_id)
    print(f"삭제 후 컨텍스트: {deleted_context}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage()) 