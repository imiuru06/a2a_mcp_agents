#!/usr/bin/env python3
"""
서비스 레지스트리 - 마이크로서비스 디스커버리, 상태 관리
"""

import os
import json
import logging
import uuid
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("service_registry")

# FastAPI 앱 생성
app = FastAPI(
    title="서비스 레지스트리",
    description="마이크로서비스 디스커버리, 상태 관리",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 변수
SERVICE_TTL = int(os.getenv("SERVICE_TTL", "60"))  # 서비스 TTL(초)
DATA_FILE = os.getenv("DATA_FILE", "/data/services.json")
HEALTHCHECK_INTERVAL = int(os.getenv("HEALTHCHECK_INTERVAL", "30"))  # 헬스체크 간격(초)

# 인메모리 서비스 저장소
services: Dict[str, Dict[str, Any]] = {}

# 데이터 모델
class ServiceRegistration(BaseModel):
    """서비스 등록 모델"""
    name: str
    url: str
    health_check_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ServiceStatus(BaseModel):
    """서비스 상태 모델"""
    name: str
    status: str
    last_check: str
    message: Optional[str] = None

# 데이터 파일 로드
def load_services():
    """서비스 데이터 파일 로드"""
    try:
        # 데이터 디렉토리 생성
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                for service_id, service_data in data.items():
                    services[service_id] = service_data
            logger.info(f"{len(services)} 개의 서비스 로드 완료")
    except Exception as e:
        logger.error(f"서비스 데이터 로드 중 오류 발생: {str(e)}")

# 데이터 파일 저장
def save_services():
    """서비스 데이터 파일 저장"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(services, f, indent=2)
        logger.info(f"{len(services)} 개의 서비스 저장 완료")
    except Exception as e:
        logger.error(f"서비스 데이터 저장 중 오류 발생: {str(e)}")

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "서비스 레지스트리 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "registered_services": len(services)
    }

@app.post("/services")
async def register_service(service: ServiceRegistration):
    """서비스 등록"""
    try:
        service_dict = service.dict(exclude_none=True)
        
        # 이미 등록된 서비스인지 확인
        existing_service_id = None
        for sid, sdata in services.items():
            if sdata.get("name") == service.name and sdata.get("url") == service.url:
                existing_service_id = sid
                break
        
        # 새 서비스 ID 생성 또는 기존 ID 사용
        service_id = existing_service_id or f"svc_{uuid.uuid4().hex[:8]}"
        
        # 서비스 정보 업데이트
        service_dict["last_updated"] = datetime.now().isoformat()
        service_dict["status"] = "registered"
        
        # 저장
        services[service_id] = service_dict
        logger.info(f"서비스 등록됨: id={service_id}, name={service.name}, url={service.url}")
        
        # 파일에 저장
        save_services()
        
        return {"service_id": service_id, "status": "registered"}
    except Exception as e:
        logger.error(f"서비스 등록 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서비스 등록 중 오류 발생: {str(e)}")

@app.get("/services")
async def list_services():
    """모든 등록된 서비스 목록 조회"""
    try:
        # 활성 서비스만 필터링
        active_services = []
        for service_id, service_data in services.items():
            # 생성 또는 마지막 업데이트가 TTL 내에 있는지 확인
            if "last_updated" in service_data:
                last_updated = datetime.fromisoformat(service_data["last_updated"])
                ttl_expired = datetime.now() > last_updated + timedelta(seconds=SERVICE_TTL)
                
                if not ttl_expired:
                    service_data["service_id"] = service_id
                    active_services.append(service_data)
        
        return active_services
    except Exception as e:
        logger.error(f"서비스 목록 조회 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서비스 목록 조회 중 오류 발생: {str(e)}")

@app.get("/services/discovery/{service_name}")
async def discover_service(service_name: str):
    """특정 서비스 이름으로 디스커버리"""
    try:
        # 해당 이름의 활성 서비스 찾기
        discovered_services = []
        
        for service_id, service_data in services.items():
            if service_data.get("name") == service_name:
                # TTL 확인
                if "last_updated" in service_data:
                    last_updated = datetime.fromisoformat(service_data["last_updated"])
                    ttl_expired = datetime.now() > last_updated + timedelta(seconds=SERVICE_TTL)
                    
                    if not ttl_expired:
                        service_data["service_id"] = service_id
                        discovered_services.append(service_data)
        
        return discovered_services
    except Exception as e:
        logger.error(f"서비스 디스커버리 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서비스 디스커버리 중 오류 발생: {str(e)}")

@app.get("/services/{service_id}")
async def get_service(service_id: str):
    """특정 서비스 ID로 조회"""
    if service_id in services:
        return services[service_id]
    
    raise HTTPException(status_code=404, detail=f"서비스 ID {service_id}를 찾을 수 없습니다.")

@app.delete("/services/{service_id}")
async def deregister_service(service_id: str):
    """서비스 등록 해제"""
    if service_id in services:
        del services[service_id]
        logger.info(f"서비스 등록 해제: id={service_id}")
        save_services()
        return {"status": "deregistered"}
    
    raise HTTPException(status_code=404, detail=f"서비스 ID {service_id}를 찾을 수 없습니다.")

@app.get("/status")
async def get_services_status():
    """모든 서비스의 상태 조회"""
    try:
        service_statuses = []
        
        for service_id, service_data in services.items():
            service_name = service_data.get("name", "unknown")
            health_check_url = service_data.get("health_check_url")
            
            if health_check_url:
                # 헬스 체크 수행
                status = await check_service_health(service_id, health_check_url)
                service_statuses.append(status)
            else:
                # 헬스 체크 URL이 없는 경우
                service_statuses.append({
                    "name": service_name,
                    "status": "unknown",
                    "last_check": datetime.now().isoformat(),
                    "message": "No health check URL provided"
                })
        
        return service_statuses
    except Exception as e:
        logger.error(f"서비스 상태 조회 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서비스 상태 조회 중 오류 발생: {str(e)}")

@app.get("/status/{service_id}")
async def get_service_status(service_id: str):
    """특정 서비스의 상태 조회"""
    if service_id not in services:
        raise HTTPException(status_code=404, detail=f"서비스 ID {service_id}를 찾을 수 없습니다.")
    
    service_data = services[service_id]
    service_name = service_data.get("name", "unknown")
    health_check_url = service_data.get("health_check_url")
    
    if health_check_url:
        # 헬스 체크 수행
        return await check_service_health(service_id, health_check_url)
    else:
        # 헬스 체크 URL이 없는 경우
        return {
            "name": service_name,
            "status": "unknown",
            "last_check": datetime.now().isoformat(),
            "message": "No health check URL provided"
        }

async def check_service_health(service_id: str, health_check_url: str) -> Dict[str, Any]:
    """서비스 헬스 체크 수행"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_check_url)
            
            service_name = services[service_id].get("name", "unknown")
            if response.status_code == 200:
                status = {
                    "name": service_name,
                    "status": "healthy",
                    "last_check": datetime.now().isoformat(),
                    "message": "Service is healthy"
                }
                
                # 서비스 데이터 업데이트
                services[service_id]["status"] = "healthy"
                services[service_id]["last_updated"] = datetime.now().isoformat()
                services[service_id]["last_health_check"] = datetime.now().isoformat()
                
                return status
            else:
                status = {
                    "name": service_name,
                    "status": "unhealthy",
                    "last_check": datetime.now().isoformat(),
                    "message": f"Service returned status code {response.status_code}"
                }
                
                # 서비스 데이터 업데이트
                services[service_id]["status"] = "unhealthy"
                services[service_id]["last_health_check"] = datetime.now().isoformat()
                
                return status
                
    except Exception as e:
        service_name = services[service_id].get("name", "unknown")
        status = {
            "name": service_name,
            "status": "unreachable",
            "last_check": datetime.now().isoformat(),
            "message": f"Error checking service health: {str(e)}"
        }
        
        # 서비스 데이터 업데이트
        services[service_id]["status"] = "unreachable"
        services[service_id]["last_health_check"] = datetime.now().isoformat()
        
        return status

async def periodic_health_check():
    """주기적으로 모든 서비스의 헬스 체크 수행"""
    while True:
        try:
            logger.info("모든 서비스 헬스 체크 시작")
            
            for service_id, service_data in list(services.items()):
                # 최근 업데이트 시간 확인
                if "last_updated" in service_data:
                    last_updated = datetime.fromisoformat(service_data["last_updated"])
                    ttl_expired = datetime.now() > last_updated + timedelta(seconds=SERVICE_TTL)
                    
                    if ttl_expired:
                        # TTL이 만료된 서비스 제거
                        logger.info(f"서비스 TTL 만료: id={service_id}, name={service_data.get('name')}")
                        services.pop(service_id, None)
                        continue
                
                # 헬스 체크 URL이 있는 경우 체크 수행
                health_check_url = service_data.get("health_check_url")
                if health_check_url:
                    try:
                        await check_service_health(service_id, health_check_url)
                    except Exception as e:
                        logger.error(f"서비스 헬스 체크 중 오류 발생: id={service_id}, error={str(e)}")
            
            # 변경사항 저장
            save_services()
            
            logger.info("모든 서비스 헬스 체크 완료")
            
        except Exception as e:
            logger.error(f"주기적 헬스 체크 중 오류 발생: {str(e)}")
        
        # 다음 체크까지 대기
        await asyncio.sleep(HEALTHCHECK_INTERVAL)

# 서버 시작 이벤트
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 이벤트"""
    try:
        # 서비스 데이터 로드
        load_services()
        
        # 주기적 헬스 체크 시작
        asyncio.create_task(periodic_health_check())
        
        logger.info("서비스 레지스트리 시작 완료")
    except Exception as e:
        logger.error(f"시작 이벤트 중 오류 발생: {str(e)}")

# 서버 종료 이벤트
@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 이벤트"""
    try:
        # 서비스 데이터 저장
        save_services()
        
        logger.info("서비스 레지스트리 종료")
    except Exception as e:
        logger.error(f"종료 이벤트 중 오류 발생: {str(e)}")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8007, reload=True) 