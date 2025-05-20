from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import redis
import json
import os
import time
from datetime import datetime, timedelta
import uuid

# Redis 연결
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    decode_responses=True
)

# 서비스 TTL (초)
SERVICE_TTL = int(os.getenv("SERVICE_TTL", 60))

app = FastAPI(title="Service Registry API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터 모델
class ServiceRegistration(BaseModel):
    name: str
    url: str
    health_check_url: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)
    

class ServiceResponse(BaseModel):
    id: str
    name: str
    url: str
    health_check_url: Optional[str] = None
    metadata: Dict
    registered_at: str
    last_heartbeat: str


@app.get("/health")
async def health_check():
    """서비스 헬스 체크 엔드포인트"""
    # Redis 연결 확인
    try:
        redis_client.ping()
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
    except:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service registry database is not available"
        )


@app.post("/services", response_model=ServiceResponse)
async def register_service(service: ServiceRegistration):
    """새 서비스 등록"""
    service_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    service_data = {
        "id": service_id,
        "name": service.name,
        "url": service.url,
        "health_check_url": service.health_check_url,
        "metadata": service.metadata,
        "registered_at": timestamp,
        "last_heartbeat": timestamp
    }
    
    # Redis에 서비스 정보 저장
    key = f"service:{service_id}"
    redis_client.hset(key, mapping=service_data)
    redis_client.expire(key, SERVICE_TTL)
    
    # 서비스 이름으로 인덱스 생성
    redis_client.sadd(f"services:name:{service.name}", service_id)
    
    return ServiceResponse(**service_data)


@app.put("/services/{service_id}/heartbeat", response_model=ServiceResponse)
async def update_heartbeat(service_id: str):
    """서비스 하트비트 업데이트"""
    key = f"service:{service_id}"
    
    # 서비스 존재 확인
    if not redis_client.exists(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found"
        )
    
    # 하트비트 업데이트
    timestamp = datetime.utcnow().isoformat()
    redis_client.hset(key, "last_heartbeat", timestamp)
    redis_client.expire(key, SERVICE_TTL)
    
    # 업데이트된 데이터 반환
    service_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                    v.decode('utf-8') if isinstance(v, bytes) else v 
                    for k, v in redis_client.hgetall(key).items()}
    
    # JSON 문자열로 저장된 메타데이터 파싱
    if isinstance(service_data.get("metadata"), str):
        try:
            service_data["metadata"] = json.loads(service_data["metadata"])
        except:
            service_data["metadata"] = {}
    
    return ServiceResponse(**service_data)


@app.get("/services", response_model=List[ServiceResponse])
async def list_services(name: Optional[str] = None):
    """등록된 모든 서비스 목록 조회"""
    services = []
    
    # 특정 이름의 서비스만 조회
    if name:
        service_ids = redis_client.smembers(f"services:name:{name}")
    else:
        # 모든 서비스 ID 가져오기
        keys = redis_client.keys("service:*")
        service_ids = [key.decode('utf-8').split(':')[1] if isinstance(key, bytes) else key.split(':')[1] for key in keys]
    
    # 각 서비스의 상세 정보 가져오기
    for service_id in service_ids:
        key = f"service:{service_id}"
        if redis_client.exists(key):
            service_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                           v.decode('utf-8') if isinstance(v, bytes) else v 
                           for k, v in redis_client.hgetall(key).items()}
            
            # JSON 문자열로 저장된 메타데이터 파싱
            if isinstance(service_data.get("metadata"), str):
                try:
                    service_data["metadata"] = json.loads(service_data["metadata"])
                except:
                    service_data["metadata"] = {}
            
            services.append(ServiceResponse(**service_data))
    
    return services


@app.get("/services/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: str):
    """특정 서비스 정보 조회"""
    key = f"service:{service_id}"
    
    # 서비스 존재 확인
    if not redis_client.exists(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found"
        )
    
    # 서비스 데이터 가져오기
    service_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                   v.decode('utf-8') if isinstance(v, bytes) else v 
                   for k, v in redis_client.hgetall(key).items()}
    
    # JSON 문자열로 저장된 메타데이터 파싱
    if isinstance(service_data.get("metadata"), str):
        try:
            service_data["metadata"] = json.loads(service_data["metadata"])
        except:
            service_data["metadata"] = {}
    
    return ServiceResponse(**service_data)


@app.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_service(service_id: str):
    """서비스 등록 해제"""
    key = f"service:{service_id}"
    
    # 서비스 존재 확인
    if not redis_client.exists(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found"
        )
    
    # 서비스 이름 인덱스에서 제거
    service_name = redis_client.hget(key, "name")
    if service_name:
        if isinstance(service_name, bytes):
            service_name = service_name.decode('utf-8')
        redis_client.srem(f"services:name:{service_name}", service_id)
    
    # Redis에서 서비스 정보 삭제
    redis_client.delete(key)


@app.put("/services/{service_id}", response_model=ServiceResponse)
async def update_service(service_id: str, service: ServiceRegistration):
    """서비스 정보 업데이트"""
    key = f"service:{service_id}"
    
    # 서비스 존재 확인
    if not redis_client.exists(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service with ID {service_id} not found"
        )
    
    # 기존 데이터 가져오기
    existing_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                    v.decode('utf-8') if isinstance(v, bytes) else v 
                    for k, v in redis_client.hgetall(key).items()}
    
    # 서비스 이름이 변경되었으면 인덱스 업데이트
    old_name = existing_data.get("name")
    if old_name and old_name != service.name:
        redis_client.srem(f"services:name:{old_name}", service_id)
        redis_client.sadd(f"services:name:{service.name}", service_id)
    
    # 업데이트할 필드
    update_data = {
        "name": service.name,
        "url": service.url,
        "health_check_url": service.health_check_url,
        "metadata": json.dumps(service.metadata) if service.metadata else "{}",
        "last_heartbeat": datetime.utcnow().isoformat()
    }
    
    # Redis 업데이트
    redis_client.hset(key, mapping=update_data)
    redis_client.expire(key, SERVICE_TTL)
    
    # 업데이트된 전체 데이터 반환
    updated_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                   v.decode('utf-8') if isinstance(v, bytes) else v 
                   for k, v in redis_client.hgetall(key).items()}
    
    # JSON 문자열로 저장된 메타데이터 파싱
    if isinstance(updated_data.get("metadata"), str):
        try:
            updated_data["metadata"] = json.loads(updated_data["metadata"])
        except:
            updated_data["metadata"] = {}
    
    return ServiceResponse(**updated_data)


@app.get("/services/discovery/{service_name}", response_model=List[ServiceResponse])
async def discover_service(service_name: str):
    """서비스 디스커버리 엔드포인트"""
    service_ids = redis_client.smembers(f"services:name:{service_name}")
    
    if not service_ids:
        return []
    
    services = []
    for service_id in service_ids:
        if isinstance(service_id, bytes):
            service_id = service_id.decode('utf-8')
        
        key = f"service:{service_id}"
        if redis_client.exists(key):
            service_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                           v.decode('utf-8') if isinstance(v, bytes) else v 
                           for k, v in redis_client.hgetall(key).items()}
            
            # JSON 문자열로 저장된 메타데이터 파싱
            if isinstance(service_data.get("metadata"), str):
                try:
                    service_data["metadata"] = json.loads(service_data["metadata"])
                except:
                    service_data["metadata"] = {}
            
            services.append(ServiceResponse(**service_data))
    
    return services


# 만료된 서비스 정리 작업을 위한 백그라운드 태스크
@app.on_event("startup")
async def startup_db_client():
    pass  # Redis 연결은 이미 설정됨


@app.on_event("shutdown")
async def shutdown_db_client():
    # Redis 연결 종료
    redis_client.close() 